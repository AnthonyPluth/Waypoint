"""From what a file proposes to what Waypoint keeps: each flight marked as new, already in Waypoint or unreadable (`preview`),
and the confirmed ones added as segments (`save`).

Times are wall-clock times at the airports (AGENTS.md, "Times are where they happen"): a time a file gives with an offset
(or in UTC) is put at its airport's zone, one without is taken to be the airport's already, and nothing is converted to
the server's zone. An arrival that gives only a time of day is on the day it first can be after the departure. A flight
the file gives no (or no usable) times for keeps none: it counts in distance but not in time in the air (its segment
says `time_unknown` and starts and ends at the same moment, on its day at both airports, so it has no duration)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal, NotRequired, TypedDict
from zoneinfo import ZoneInfo

from ...storage import db
from .. import airports, trips, visibility
from ..visibility import Viewer
from .formats import Clock, Proposed, Skipped

Status = Literal["new", "exists", "unreadable"]
MAX_DAYS_AHEAD = 2   # an arrival time with no day is put up to this many days after the departure's


class FlightIn(TypedDict):
    """A flight to add, as a preview showed it (the segment's own fields are worked out from it)."""
    day: str                       # the local departure day, YYYY-MM-DD
    origin: str                    # IATA codes
    destination: str
    flight_number: NotRequired[str | None]
    airline: NotRequired[str | None]
    start_local: NotRequired[str | None]   # wall-clock times at the airports; both or neither
    end_local: NotRequired[str | None]
    seat: NotRequired[str | None]
    cabin: NotRequired[str | None]


class PreviewRow(TypedDict):
    line: int                      # the row's line in the file (the header is line 1)
    status: Status
    reason: str | None             # why it's already here or can't be read
    day: str | None
    origin: str | None
    destination: str | None
    flight_number: str | None
    airline: str | None
    start_local: str | None
    end_local: str | None
    seat: str | None
    cabin: str | None


@dataclass(frozen=True)
class Saved:
    added: int
    existing: int                  # already in Waypoint (or repeated in what was sent), so left alone


def _at(clock: Clock, fallback_day: str, zone: str) -> datetime:
    """A time a file gives, as a naive wall-clock time at `zone`."""
    hours, minutes = clock.time.split(":")
    local = datetime.fromisoformat(clock.day or fallback_day).replace(hour=int(hours), minute=int(minutes))
    if clock.offset is None:
        return local
    return local.replace(tzinfo=timezone(timedelta(minutes=clock.offset))).astimezone(ZoneInfo(zone)).replace(tzinfo=None)


def _times(flight: Proposed, origin_zone: str, destination_zone: str) -> tuple[str, str, str] | None:
    """(local departure day, departure, arrival) as wall-clock texts, or None when the file doesn't give both."""
    if flight.dep is None or flight.arr is None:
        return None
    dep = _at(flight.dep, flight.day, origin_zone)
    arr = _at(flight.arr, dep.date().isoformat(), destination_zone)
    start = dep.replace(tzinfo=ZoneInfo(origin_zone))
    for _ in range(MAX_DAYS_AHEAD + 1):
        if arr.replace(tzinfo=ZoneInfo(destination_zone)) >= start:
            return dep.date().isoformat(), dep.strftime("%Y-%m-%dT%H:%M"), arr.strftime("%Y-%m-%dT%H:%M")
        if flight.arr.day or flight.arr.offset is not None:
            return None   # it says when, and that's before it left: the times can't be right
        arr += timedelta(days=1)
    return None


def _keys(day: str, number: str | None, origin: str | None, destination: str | None) -> list[tuple[str, ...]]:
    """What makes two flights the same: the flight number and day, or the route and day."""
    keys: list[tuple[str, ...]] = [("route", day, (origin or "").upper(), (destination or "").upper())]
    if number:
        keys.append(("number", day, number.replace(" ", "").upper()))
    return keys


def _known(conn: db.Connection, viewer: Viewer) -> set[tuple[str, ...]]:
    """The flights the viewer already has, by `_keys`."""
    found: set[tuple[str, ...]] = set()
    for s in visibility.visible_segments(conn, viewer):
        if s.kind == "flight" and s.status != "cancelled":
            found.update(_keys(s.start_local[:10], trips.decode_details(s.details).get("flight_number"), s.origin, s.destination))
    return found


def _row(line: int, status: Status, reason: str | None, **fields: str | None) -> PreviewRow:
    shown: PreviewRow = {"line": line, "status": status, "reason": reason, "day": None, "origin": None, "destination": None,
                         "flight_number": None, "airline": None, "start_local": None, "end_local": None, "seat": None,
                         "cabin": None}
    shown.update(fields)   # type: ignore[typeddict-item]
    return shown


def preview(conn: db.Connection, viewer: Viewer, parsed: Iterable[Proposed | Skipped]) -> list[PreviewRow]:
    """Each row as the person will see it: new, already in Waypoint (the same flight number and day, or the same route and
    day, among the viewer's flights or earlier in the file), or unreadable, with why."""
    rows = list(parsed)
    zones = airports.zones(conn, [c for r in rows if isinstance(r, Proposed) for c in (r.origin, r.destination)])
    have = _known(conn, viewer)
    out: list[PreviewRow] = []
    for r in rows:
        if isinstance(r, Skipped):
            out.append(_row(r.line, "unreadable", r.reason))
            continue
        unknown = [c for c in (r.origin, r.destination) if c not in zones]
        if unknown:
            out.append(_row(r.line, "unreadable", f"Waypoint doesn’t know the airport {unknown[0]}", day=r.day,
                            origin=r.origin, destination=r.destination))
            continue
        times = _times(r, zones[r.origin], zones[r.destination])
        day = times[0] if times else r.day
        fields = {"day": day, "origin": r.origin, "destination": r.destination, "flight_number": r.flight_number,
                  "airline": r.airline, "start_local": times[1] if times else None, "end_local": times[2] if times else None,
                  "seat": r.seat, "cabin": r.cabin}
        keys = _keys(day, r.flight_number, r.origin, r.destination)
        if any(k in have for k in keys):
            out.append(_row(r.line, "exists", "Already in Waypoint", **fields))
            continue
        have.update(keys)
        out.append(_row(r.line, "new", None, **fields))
    return out


def _day(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError:
        raise trips.Invalid("its day isn’t a date like 2026-03-01") from None


def _segment(flight: FlightIn, zones: Mapping[str, str]) -> trips.SegmentIn:
    start, end = flight.get("start_local"), flight.get("end_local")
    details = {k: v for k, v in (("flight_number", flight.get("flight_number")), ("seat", flight.get("seat")),
                                 ("cabin", flight.get("cabin"))) if v}
    if not (start and end):
        # No times: one moment on its day (the later of the day's two midnights, so it's still that day at both airports),
        # written at each airport's clock. It has no duration, and both ends are on the same date whichever way it flies.
        day = datetime.fromisoformat(f"{flight['day']}T00:00")
        start = end = f"{flight['day']}T00:00"
        origin, destination = zones.get(flight["origin"].upper()), zones.get(flight["destination"].upper())
        if origin and destination:
            moment = max(day.replace(tzinfo=ZoneInfo(origin)), day.replace(tzinfo=ZoneInfo(destination)))
            start = moment.astimezone(ZoneInfo(origin)).strftime("%Y-%m-%dT%H:%M")
            end = moment.astimezone(ZoneInfo(destination)).strftime("%Y-%m-%dT%H:%M")
        details[trips.TIME_UNKNOWN] = "yes"
    return {"kind": "flight", "origin": flight["origin"], "destination": flight["destination"], "start_local": start,
            "end_local": end, "provider": flight.get("airline"), "details": details}


def save(conn: db.Connection, viewer: Viewer, flights: Sequence[FlightIn],
         travelers: Sequence[trips.TravelerIn]) -> Saved:
    """Add the flights that aren't here yet as segments from an import, booked by the viewer, with these travellers, in
    date order so grouping sees them as they happened. One that is already here (or repeated in `flights`) is left alone,
    so saving the same file again adds nothing. Raises trips.Invalid for a flight that can't be a segment, and then
    none are added (the caller's transaction rolls back)."""
    have = _known(conn, viewer)
    zones = airports.zones(conn, [c for f in flights for c in (f["origin"], f["destination"])])
    added = existing = 0
    for n, flight in sorted(enumerate(flights, start=1), key=lambda p: (p[1]["day"], p[1].get("start_local") or "", p[0])):
        keys = _keys(flight["day"], flight.get("flight_number"), flight["origin"], flight["destination"])
        if any(k in have for k in keys):
            existing += 1
            continue
        try:
            _day(flight["day"])
            trips.add_segment(conn, viewer, {**_segment(flight, zones), "travelers": list(travelers)}, source="import")
        except trips.Invalid as e:
            raise trips.Invalid(f"Flight {n} of those you chose can’t be added: {e}") from None
        have.update(keys)
        added += 1
    return Saved(added, existing)
