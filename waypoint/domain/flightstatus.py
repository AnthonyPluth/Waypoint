"""Live flight status within the RapidAPI plan's budget (400 calls a month for the whole household, by default).

The booking stays the record: a status is shown beside a segment's booked times and never written over its fields. The
answers are cached by (flight number, local departure date) in `flight_status`, which holds nothing personal, so one call
answers for everyone on a flight, and for every segment that names it.

When a flight is checked (`due`), a pure rule on the booked times, so it can be tested without a clock or a service:
  * at fixed points before the booked departure (CHECKS: 24 h, 3 h, 1 h and 20 min) and once at the booked arrival, at most
    five calls a flight; nothing for a flight more than 24 h out, one that has landed, was cancelled or diverted, or one
    that arrived LATE ago. If Waypoint was off, it makes up only the latest check it missed. A call that fails still
    uses up its check (it's recorded as attempted, in the database), so an outage costs at most one call per check,
    never a retry every few minutes.
  * from 90% of the monthly limit, only the 1 h check; at the limit, none; a "Refresh" press (`refresh`) is the viewer's
    to make and costs a call too, unless the answer is under REFRESH_AFTER old. A 429, or a key RapidAPI refuses, pauses
    fetching for an hour. The month is the machine's local month (TZ).

Times stay where they happen: the cache holds the airports' wall-clock times with their zones, and nothing here converts
one (`trips.instant` only compares)."""
from __future__ import annotations

import json
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Literal, TypedDict, cast

from sqlalchemy import delete, select

from .. import dates, monitoring
from ..providers import flightstatus as service
from ..storage import db
from ..storage import settings_keys as sk
from ..storage.models import FlightStatus, Segment
from . import trips, visibility
from .visibility import Viewer

DEFAULT_LIMIT = 400
REDUCED_FROM = 0.9                              # of the limit
CHECKS = (("24h", timedelta(hours=24)), ("3h", timedelta(hours=3)), ("1h", timedelta(hours=1)),
          ("20m", timedelta(minutes=20)))       # before the booked departure
ONE_HOUR = "1h"                                 # the check that survives the 90% mark
REFRESH_AFTER = timedelta(minutes=15)           # a cached answer this young is what Refresh shows
LATE = timedelta(hours=6)                       # checks stop this long after the booked arrival
PAUSE = timedelta(hours=1)                      # after a 429, or a key RapidAPI refuses
KEEP_DAYS = 7                                   # cached answers go this long after the flight
OVER = (service.LANDED, service.CANCELLED, service.DIVERTED)   # states with nothing more to learn

Reason = Literal["limit", "rate", "key"]
Shown = Literal["scheduled", "delayed", "departed", "landed", "cancelled", "diverted"]   # (an unknown flight shows nothing)

_lock = threading.Lock()


class NotAFlight(ValueError):
    """The segment isn't a flight with a flight number, so there's no status to fetch (the API's 400)."""


@dataclass(frozen=True)
class Flight:
    """One flight to watch: what a call is for. `departs` and `arrives` are the booked times, as instants (for comparing)."""
    number: str            # normalized: EX101
    day: str               # its local departure date
    origin: str | None
    departs: datetime
    arrives: datetime


@dataclass(frozen=True)
class Pause:
    until: datetime
    reason: Reason


@dataclass(frozen=True)
class Usage:
    month: str             # "2026-10"
    used: int
    limit: int
    paused: Pause | None   # why nothing is fetched now, if so

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
    delay_minutes: int | None   # how much later than booked it leaves (or left)
    fetched_at: str             # when the answer came, with its UTC offset


class PauseOut(TypedDict):
    until: str                  # with its UTC offset
    reason: Reason


class Overview(TypedDict):
    enabled: bool               # RAPIDAPI_KEY is set
    month: str
    used: int
    limit: int
    paused: PauseOut | None
    statuses: list[StatusOut]


# ------------------------------------------------------------------------------------------------ the schedule

def checkpoints(flight: Flight) -> list[tuple[datetime, str]]:
    """When the flight is checked: (the moment, its name) in order."""
    return [(flight.departs - before, name) for name, before in CHECKS] + [(flight.arrives, "arrival")]


def due(flight: Flight, now: datetime, last: datetime | None, state: str | None, reduced: bool = False) -> bool:
    """Whether a check is due: the latest checkpoint that has passed (only the 1 h one when `reduced`) is after the last
    answer (`last`, when it came; `state`, what it said). Early on, nothing has passed, so nothing is fetched."""
    if state in OVER or now > flight.arrives + LATE:
        return False
    passed = [at for at, name in checkpoints(flight) if at <= now and (name == ONE_HOUR or not reduced)]
    return bool(passed) and (last is None or last < passed[-1])


# ------------------------------------------------------------------------------------------------ the budget

def limit() -> int:
    """WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT, or 400 when it isn't set to a positive whole number."""
    try:
        n = int((os.environ.get("WAYPOINT_FLIGHT_STATUS_MONTHLY_LIMIT") or "").strip() or DEFAULT_LIMIT)
    except ValueError:
        return DEFAULT_LIMIT
    return n if n > 0 else DEFAULT_LIMIT


def _month(now: datetime) -> str:
    return dates.month_key(now.astimezone().date())


def _calls(conn: db.Connection, month: str) -> int:
    """The calls made in `month`; a counter from an earlier month is a new month's zero."""
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
    if used >= cap:   # until the 1st, local time
        first = datetime.combine(dates.key_start(dates.next_month_key(month)), time.min).astimezone()
        return Usage(month, used, cap, Pause(first, "limit"))
    return Usage(month, used, cap, _stored_pause(conn, now))


def _spend(conn: db.Connection, now: datetime) -> None:
    """Count a call, and keep the count: a request that goes on to fail still used up its call."""
    with _lock:
        month = _month(now)
        db.set_setting(conn, sk.FLIGHT_STATUS_CALLS, str(_calls(conn, month) + 1))
        db.set_setting(conn, sk.FLIGHT_STATUS_MONTH, month)
        conn.commit()


def forget_key_pause(conn: db.Connection) -> None:
    """At startup: a pause for a refused key ends, so fixing RAPIDAPI_KEY and restarting takes effect at once."""
    try:
        refused = json.loads(db.get_setting(conn, sk.FLIGHT_STATUS_PAUSED) or "null")["reason"] == "key"
    except (ValueError, TypeError, KeyError):
        refused = False
    if refused:
        db.set_setting(conn, sk.FLIGHT_STATUS_PAUSED, None)


def _pause(conn: db.Connection, now: datetime, reason: Reason) -> None:
    db.set_setting(conn, sk.FLIGHT_STATUS_PAUSED, json.dumps({"until": (now + PAUSE).timestamp(), "reason": reason}))
    conn.commit()


# ------------------------------------------------------------------------------------------------ flights and the cache

def _flight(seg: Segment) -> Flight | None:
    """The flight a segment is, when it's one that can be asked about."""
    if seg.kind != "flight" or seg.status == "cancelled":
        return None
    details = trips.decode_details(seg.details)
    if trips.untimed(details):   # its times are a placeholder: there's no departure to ask about
        return None
    raw = details.get("flight_number")
    number = service.normalize(trips.flight_key(raw) or raw)   # (AA04001 and AA 4001 are one flight: one call)
    if not number:
        return None
    return Flight(number, seg.start_local[:10], seg.origin, trips.instant(seg.start_local, seg.start_zone),
                  trips.instant(seg.end_local, seg.end_zone))


def watching(conn: db.Connection, now: datetime) -> list[Flight]:
    """The flights near enough to matter (a day or two either side of today), once each however many segments or
    travellers they have, the soonest first."""
    today = now.astimezone().date()
    near = conn.orm.scalars(select(Segment).where(
        Segment.kind == "flight", Segment.start_local >= (today - timedelta(days=2)).isoformat(),
        Segment.start_local < (today + timedelta(days=3)).isoformat()).order_by(Segment.id)).all()
    found: dict[tuple[str, str], Flight] = {}
    for seg in near:
        if (f := _flight(seg)) and (f.number, f.day) not in found:
            found[f.number, f.day] = f
    return sorted(found.values(), key=lambda f: f.departs)


def _cached(conn: db.Connection, number: str, day: str) -> FlightStatus | None:
    return conn.orm.get(FlightStatus, (number, day))


def _fetched(row: FlightStatus) -> datetime:
    return datetime.fromtimestamp(row.fetched_at, UTC)


def _last_call(row: FlightStatus | None) -> datetime | None:
    """When the flight's last call was made, whether it worked or not: what a check is measured against."""
    if row is None:
        return None
    return datetime.fromtimestamp(max(row.fetched_at, row.attempted_at or 0.0), UTC)


def _store(conn: db.Connection, flight: Flight, found: service.Status | None, now: datetime) -> None:
    """Keep the answer (an unknown flight is kept as one, so it isn't asked about again until the next check)."""
    values = {"flight_number": flight.number, "date": flight.day, "fetched_at": now.timestamp(), "attempted_at": now.timestamp(),
              **{k: getattr(found or service.Status(service.UNKNOWN), k) for k in service.Status.__dataclass_fields__}}
    db.upsert(conn, FlightStatus, values, key=["flight_number", "date"])


def purge(conn: db.Connection, now: datetime) -> None:
    """Remove the answers for flights more than KEEP_DAYS gone."""
    conn.execute(delete(FlightStatus).where(FlightStatus.date <= (now.astimezone().date() - timedelta(days=KEEP_DAYS)).isoformat()))


def _note_failure(conn: db.Connection, flight: Flight, now: datetime) -> None:
    """Record that a call was made and failed, so this check isn't made again (the answer held, if any, stays)."""
    if (row := _cached(conn, flight.number, flight.day)) is not None:
        row.attempted_at = now.timestamp()
    else:   # (nothing to show: an unknown flight, as far as anyone can tell)
        db.upsert(conn, FlightStatus, {"flight_number": flight.number, "date": flight.day, "state": service.UNKNOWN,
                                       "fetched_at": 0.0, "attempted_at": now.timestamp()}, key=["flight_number", "date"])
    conn.commit()


def _check(conn: db.Connection, flight: Flight, now: datetime) -> None:
    """One call for the flight, kept. Raises what the provider raises; a rate limit or a refused key pauses fetching first."""
    _spend(conn, now)
    try:
        found = service.fetch(flight.number, flight.day, flight.origin)
    except service.FlightStatusError as e:
        _note_failure(conn, flight, now)
        if isinstance(e, service.RateLimited):
            _pause(conn, now, "rate")
        elif isinstance(e, service.Refused):
            _pause(conn, now, "key")
        raise
    _store(conn, flight, found, now)
    conn.commit()


def run_due(conn: db.Connection, now: datetime) -> int:
    """The scheduler's round (every few minutes): make the checks that are due, within the budget. Returns how many calls
    it made. A failure is logged as its fixed message (never the flight), and the next round tries again."""
    if not service.configured():
        return 0
    purge(conn, now)
    made = 0
    for flight in watching(conn, now):
        spent = usage(conn, now)
        if spent.paused:
            break
        row = _cached(conn, flight.number, flight.day)
        if not due(flight, now, _last_call(row), row.state if row else None, spent.reduced):
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


# ------------------------------------------------------------------------------------------------ what the viewer sees

def _delay(row: FlightStatus) -> int | None:
    expected = row.dep_actual or row.dep_estimated
    if not (expected and row.dep_scheduled):
        return None
    late = service.minutes_later(expected, row.dep_scheduled)
    return late if late > 0 else None


def _out(seg: Segment, row: FlightStatus) -> StatusOut:
    return {"segment_id": seg.id, "state": cast(Shown, row.state), "origin": row.origin, "destination": row.destination,
            "dep_scheduled": row.dep_scheduled, "dep_estimated": row.dep_estimated, "dep_actual": row.dep_actual,
            "dep_zone": row.dep_zone or seg.start_zone, "dep_terminal": row.dep_terminal, "dep_gate": row.dep_gate,
            "arr_scheduled": row.arr_scheduled, "arr_estimated": row.arr_estimated, "arr_actual": row.arr_actual,
            "arr_zone": row.arr_zone or seg.end_zone, "arr_terminal": row.arr_terminal, "arr_gate": row.arr_gate,
            "delay_minutes": _delay(row), "fetched_at": _fetched(row).isoformat(timespec="seconds")}


def _statuses(conn: db.Connection, segs: Sequence[Segment]) -> list[StatusOut]:
    """The cached status for each of these segments that has one that's about the same leg (a flight number that flies several
    legs a day has a status for one of them; the others show none). Nothing for an unknown flight."""
    flights = {s.id: f for s in segs if (f := _flight(s))}
    if not flights:
        return []
    days = {f.day for f in flights.values()}
    rows = {(r.flight_number, r.date): r for r in conn.orm.scalars(select(FlightStatus).where(FlightStatus.date.in_(days))).all()}
    found: list[StatusOut] = []
    for seg in segs:
        f = flights.get(seg.id)
        row = rows.get((f.number, f.day)) if f else None
        if row and f and row.state != service.UNKNOWN and (not (row.origin and f.origin) or row.origin.upper() == f.origin.upper()):
            found.append(_out(seg, row))
    return found


def _overview(conn: db.Connection, now: datetime, statuses: list[StatusOut]) -> Overview:
    spent = usage(conn, now)
    paused: PauseOut | None = {"until": spent.paused.until.isoformat(timespec="seconds"), "reason": spent.paused.reason} \
        if spent.paused else None
    return {"enabled": service.configured(), "month": spent.month, "used": spent.used, "limit": spent.limit,
            "paused": paused, "statuses": statuses if service.configured() else []}


def overview(conn: db.Connection, viewer: Viewer, now: datetime) -> Overview:
    """The budget, and the status of each of the viewer's flights that has one."""
    return _overview(conn, now, _statuses(conn, visibility.visible_segments(conn, viewer)))


def refresh(conn: db.Connection, viewer: Viewer, segment_id: int, now: datetime) -> Overview | None:
    """The "Refresh" button: fetch this flight's status now, unless the answer held is under REFRESH_AFTER old or the flight
    is over, or fetching is paused (then what's held, with why). None when the segment isn't the viewer's. Raises NotAFlight,
    and the provider's errors (their messages are fixed texts)."""
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    flight = _flight(seg)
    if flight is None:
        raise NotAFlight("Live status is for flights that have a flight number.")
    if not service.configured():
        raise service.NotConfigured("Flight status isn’t set up: RAPIDAPI_KEY isn’t set.")
    row = _cached(conn, flight.number, flight.day)
    held = row is not None and (row.state in OVER or now - _fetched(row) < REFRESH_AFTER)
    if not held and not usage(conn, now).paused:
        _check(conn, flight, now)
    return _overview(conn, now, _statuses(conn, [seg]))
