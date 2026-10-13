from __future__ import annotations

import json
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, time, timedelta
from typing import Literal, TypedDict, cast

from sqlalchemy import delete, select

from .. import dates, monitoring
from ..providers import flightstatus as service
from ..storage import db
from ..storage import settings_keys as sk
from ..storage.models import FlightCheck, FlightStatus, Segment
from . import seatmaps, trips, visibility
from .visibility import Viewer

DEFAULT_LIMIT = 400
REDUCED_FROM = 0.9
CHECKS = (("24h", timedelta(hours=24)), ("3h", timedelta(hours=3)), ("1h", timedelta(hours=1)),
          ("20m", timedelta(minutes=20)))
ONE_HOUR = "1h"
REFRESH_AFTER = timedelta(minutes=15)
LATE = timedelta(hours=6)
PAUSE = timedelta(hours=1)
CHECK_KEEP_DAYS = 7
OVER = (service.LANDED, service.CANCELLED, service.DIVERTED)

Reason = Literal["limit", "rate", "key"]
Shown = Literal["scheduled", "delayed", "departed", "landed", "cancelled", "diverted"]

_lock = threading.Lock()
_held_lock = threading.Lock()
_held: dict[tuple[str, str], tuple[service.Status, datetime, datetime]] = {}


class NotAFlight(ValueError):
    pass


@dataclass(frozen=True)
class Flight:
    number: str
    day: str
    origin: str | None
    departs: datetime
    arrives: datetime


@dataclass(frozen=True)
class Pause:
    until: datetime
    reason: Reason


@dataclass(frozen=True)
class Usage:
    month: str
    used: int
    limit: int
    paused: Pause | None

    @property
    def reduced(self) -> bool:
        return self.used >= self.limit * REDUCED_FROM


class StatusOut(TypedDict):
    segment_id: int
    state: Shown
    origin: str | None
    destination: str | None
    dep_scheduled: str | None
    dep_estimated: str | None
    dep_actual: str | None
    dep_zone: str
    dep_terminal: str | None
    dep_gate: str | None
    arr_scheduled: str | None
    arr_estimated: str | None
    arr_actual: str | None
    arr_zone: str
    arr_terminal: str | None
    arr_gate: str | None
    delay_minutes: int | None
    fetched_at: str


class PauseOut(TypedDict):
    until: str
    reason: Reason


class Overview(TypedDict):
    enabled: bool
    month: str
    used: int
    limit: int
    paused: PauseOut | None
    statuses: list[StatusOut]


def checkpoints(flight: Flight) -> list[tuple[datetime, str]]:
    return [(flight.departs - before, name) for name, before in CHECKS] + [(flight.arrives, "arrival")]


def due(flight: Flight, now: datetime, last: datetime | None, state: str | None, reduced: bool = False) -> bool:
    if state in OVER or now > flight.arrives + LATE:
        return False
    passed = [at for at, name in checkpoints(flight) if at <= now and (name == ONE_HOUR or not reduced)]
    return bool(passed) and (last is None or last < passed[-1])


def limit() -> int:
    try:
        n = int((os.environ.get("WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT") or "").strip() or DEFAULT_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT
    return n if n > 0 else DEFAULT_LIMIT


def _month(now: datetime) -> str:
    return dates.month_key(now.astimezone().date())


def _calls(conn: db.Connection, month: str) -> int:
    if db.get_setting(conn, sk.FLIGHT_STATUS_MONTH) != month:
        return 0
    stored = db.get_setting(conn, sk.FLIGHT_STATUS_CALLS) or ""
    return int(stored) if stored.isdigit() else 0


def _stored_pause(conn: db.Connection, now: datetime) -> Pause | None:
    try:
        saved = json.loads(db.get_setting(conn, sk.FLIGHT_STATUS_PAUSED) or "null")
        until, reason = datetime.fromtimestamp(float(saved["until"]), UTC), saved["reason"]
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        return None
    return Pause(until, reason) if until > now and reason in ("rate", "key") else None


def usage(conn: db.Connection, now: datetime) -> Usage:
    month, cap = _month(now), limit()
    used = _calls(conn, month)
    if used >= cap:
        first = datetime.combine(dates.key_start(dates.next_month_key(month)), time.min).astimezone()
        return Usage(month, used, cap, Pause(first, "limit"))
    return Usage(month, used, cap, _stored_pause(conn, now))


def _spend(conn: db.Connection, now: datetime) -> None:
    with _lock:
        month = _month(now)
        db.set_setting(conn, sk.FLIGHT_STATUS_CALLS, str(_calls(conn, month) + 1))
        db.set_setting(conn, sk.FLIGHT_STATUS_MONTH, month)
        conn.commit()


def forget_key_pause(conn: db.Connection) -> None:
    try:
        refused = json.loads(db.get_setting(conn, sk.FLIGHT_STATUS_PAUSED) or "null")["reason"] == "key"
    except (ValueError, TypeError, KeyError):
        refused = False
    if refused:
        db.set_setting(conn, sk.FLIGHT_STATUS_PAUSED, None)


def _pause(conn: db.Connection, now: datetime, reason: Reason) -> None:
    db.set_setting(conn, sk.FLIGHT_STATUS_PAUSED, json.dumps({"until": (now + PAUSE).timestamp(), "reason": reason}))
    conn.commit()


def _flight(seg: Segment) -> Flight | None:
    if seg.kind != "flight" or seg.status == "cancelled":
        return None
    details = trips.decode_details(seg.details)
    if trips.untimed(details):
        return None
    raw = details.get("flight_number")
    number = service.normalize(trips.flight_key(raw) or raw)
    if not number:
        return None
    return Flight(number, seg.start_local[:10], seg.origin, trips.instant(seg.start_local, seg.start_zone),
                  trips.instant(seg.end_local, seg.end_zone))


def watching(conn: db.Connection, now: datetime) -> list[Flight]:
    today = now.astimezone().date()
    near = conn.orm.scalars(select(Segment).where(
        Segment.kind == "flight", Segment.start_local >= (today - timedelta(days=2)).isoformat(),
        Segment.start_local < (today + timedelta(days=3)).isoformat()).order_by(Segment.id)).all()
    found: dict[tuple[str, str], Flight] = {}
    for seg in near:
        if (f := _flight(seg)) and (f.number, f.day) not in found:
            found[f.number, f.day] = f
    return sorted(found.values(), key=lambda f: f.departs)


def _final(conn: db.Connection, number: str, day: str) -> FlightStatus | None:
    return conn.orm.get(FlightStatus, (number, day))


def _known(row: FlightStatus) -> service.Status:
    return service.Status(state=row.state, **{f.name: getattr(row, f.name, None) for f in fields(service.Status) if f.name != "state"})


def _fetched(row: FlightStatus) -> datetime:
    return datetime.fromtimestamp(row.fetched_at, UTC)


def hold(number: str, day: str, found: service.Status, fetched: datetime, until: datetime) -> None:
    with _held_lock:
        for key in [k for k, (_, _, end) in _held.items() if end <= fetched]:
            del _held[key]
        _held[number, day] = (found, fetched, until)


def drop_held(number: str | None = None, day: str | None = None) -> None:
    with _held_lock:
        if number is None or day is None:
            _held.clear()
        else:
            _held.pop((number, day), None)


def _fresh(number: str, day: str, now: datetime) -> tuple[service.Status, datetime] | None:
    with _held_lock:
        entry = _held.get((number, day))
    return (entry[0], entry[1]) if entry and entry[1] <= now < entry[2] else None


def _answer(conn: db.Connection, number: str, day: str, now: datetime) -> tuple[service.Status, datetime] | None:
    if (row := _final(conn, number, day)) is not None:
        return _known(row), _fetched(row)
    return _fresh(number, day, now)


def _last_call(conn: db.Connection, flight: Flight) -> datetime | None:
    checked = conn.orm.get(FlightCheck, (flight.number, flight.day))
    row = _final(conn, flight.number, flight.day)
    stamps = [t for t in (checked.checked_at if checked else None, row.fetched_at if row else None) if t]
    return datetime.fromtimestamp(max(stamps), UTC) if stamps else None


def _touch(conn: db.Connection, flight: Flight, now: datetime) -> None:
    db.upsert(conn, FlightCheck, {"flight_number": flight.number, "date": flight.day, "checked_at": now.timestamp()},
              key=["flight_number", "date"])


def _store(conn: db.Connection, flight: Flight, found: service.Status | None, now: datetime) -> None:
    _touch(conn, flight, now)
    if found is not None and found.state in OVER:
        values = {"flight_number": flight.number, "date": flight.day, "fetched_at": now.timestamp(),
                  **{f.name: getattr(found, f.name) for f in fields(service.Status) if f.name != "aircraft"}}
        db.upsert(conn, FlightStatus, values, key=["flight_number", "date"])
        drop_held(flight.number, flight.day)
    elif found is not None and found.state != service.UNKNOWN:
        hold(flight.number, flight.day, found, now, now + REFRESH_AFTER)
    else:
        drop_held(flight.number, flight.day)


def _note_aircraft(conn: db.Connection, flight: Flight, found: service.Status | None) -> None:
    family = seatmaps.family(found.aircraft) if found else None
    if not family:
        return
    for seg in conn.orm.scalars(select(Segment).where(Segment.kind == "flight", Segment.start_local.like(f"{flight.day}%"))).all():
        mine = _flight(seg)
        if mine is None or mine.number != flight.number or (flight.origin and (seg.origin or "").upper() != flight.origin.upper()):
            continue
        details = trips.decode_details(seg.details)
        if details.get("aircraft") or "details" in trips.decode_locked(seg.locked_fields):
            continue
        seg.details = json.dumps({**details, "aircraft": family}, ensure_ascii=False)


def purge(conn: db.Connection, now: datetime) -> None:
    conn.execute(delete(FlightCheck).where(FlightCheck.date <= (now.astimezone().date() - timedelta(days=CHECK_KEEP_DAYS)).isoformat()))


def _check(conn: db.Connection, flight: Flight, now: datetime) -> None:
    _spend(conn, now)
    try:
        found = service.fetch(flight.number, flight.day, flight.origin)
    except service.FlightStatusError as e:
        _touch(conn, flight, now)
        conn.commit()
        if isinstance(e, service.RateLimited):
            _pause(conn, now, "rate")
        elif isinstance(e, service.Refused):
            _pause(conn, now, "key")
        raise
    _store(conn, flight, found, now)
    _note_aircraft(conn, flight, found)
    conn.commit()


def run_due(conn: db.Connection, now: datetime) -> int:
    if not service.configured():
        return 0
    purge(conn, now)
    made = 0
    for flight in watching(conn, now):
        spent = usage(conn, now)
        if spent.paused:
            break
        row = _final(conn, flight.number, flight.day)
        if not due(flight, now, _last_call(conn, flight), row.state if row else None, spent.reduced):
            continue
        try:
            _check(conn, flight, now)
            made += 1
        except service.FlightStatusError as e:
            made += 1
            monitoring.log(f"Flight status: {e}", "warning")
            if isinstance(e, service.RateLimited | service.Refused):
                break
    return made


def _delay(found: service.Status) -> int | None:
    expected = found.dep_actual or found.dep_estimated
    if not (expected and found.dep_scheduled):
        return None
    late = service.minutes_later(expected, found.dep_scheduled)
    return late if late > 0 else None


def _out(seg: Segment, found: service.Status, fetched: datetime) -> StatusOut:
    return {"segment_id": seg.id, "state": cast(Shown, found.state), "origin": found.origin, "destination": found.destination,
            "dep_scheduled": found.dep_scheduled, "dep_estimated": found.dep_estimated, "dep_actual": found.dep_actual,
            "dep_zone": found.dep_zone or seg.start_zone, "dep_terminal": found.dep_terminal, "dep_gate": found.dep_gate,
            "arr_scheduled": found.arr_scheduled, "arr_estimated": found.arr_estimated, "arr_actual": found.arr_actual,
            "arr_zone": found.arr_zone or seg.end_zone, "arr_terminal": found.arr_terminal, "arr_gate": found.arr_gate,
            "delay_minutes": _delay(found), "fetched_at": fetched.isoformat(timespec="seconds")}


def _statuses(conn: db.Connection, segs: Sequence[Segment], now: datetime) -> list[StatusOut]:
    flights = {s.id: f for s in segs if (f := _flight(s))}
    if not flights:
        return []
    days = {f.day for f in flights.values()}
    finals = {(r.flight_number, r.date): r for r in conn.orm.scalars(select(FlightStatus).where(FlightStatus.date.in_(days))).all()}
    found: list[StatusOut] = []
    for seg in segs:
        f = flights.get(seg.id)
        if f is None:
            continue
        row = finals.get((f.number, f.day))
        answer = (_known(row), _fetched(row)) if row else _fresh(f.number, f.day, now)
        if answer and answer[0].state != service.UNKNOWN and (not (answer[0].origin and f.origin) or (answer[0].origin or "").upper() == f.origin.upper()):
            found.append(_out(seg, *answer))
    return found


def _overview(conn: db.Connection, now: datetime, statuses: list[StatusOut]) -> Overview:
    spent = usage(conn, now)
    paused: PauseOut | None = {"until": spent.paused.until.isoformat(timespec="seconds"), "reason": spent.paused.reason} \
        if spent.paused else None
    return {"enabled": service.configured(), "month": spent.month, "used": spent.used, "limit": spent.limit,
            "paused": paused, "statuses": statuses if service.configured() else []}


def overview(conn: db.Connection, viewer: Viewer, now: datetime) -> Overview:
    return _overview(conn, now, _statuses(conn, visibility.visible_segments(conn, viewer), now))


def refresh(conn: db.Connection, viewer: Viewer, segment_id: int, now: datetime) -> Overview | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    flight = _flight(seg)
    if flight is None:
        raise NotAFlight("Live status is for flights that have a flight number.")
    if not service.configured():
        raise service.NotConfigured("Flight status isn’t set up: RAPIDAPI_KEY isn’t set.")
    if _answer(conn, flight.number, flight.day, now) is None and not usage(conn, now).paused:
        _check(conn, flight, now)
    return _overview(conn, now, _statuses(conn, [seg], now))
