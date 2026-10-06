from __future__ import annotations

from typing import Literal

from ...storage import db
from .. import airports, loyalty, people, place_zones, trips
from ..visibility import Viewer
from . import extract


def _zone(conn: db.Connection, b: extract.Booking, code: str | None, place: extract.Place) -> str | None:
    if b.kind == "flight":
        known = airports.lookup(conn, code) if code else None
        return known["zone"] if known else None
    return (airports.zone_for_place(conn, place.city, place.country)
            or (place_zones.zone_for_address(conn, dict(b.details).get("address")) if b.kind == "hotel" else None))


def travelers(conn: db.Connection, passengers: tuple[extract.Passenger, ...]) -> list[trips.TravelerIn]:
    found: list[trips.TravelerIn] = []
    for p in passengers:
        pid = loyalty.person_for_number(conn, p.member_number) if p.member_number else None
        if pid is None:
            pid = people.match_name(conn, p.name)
        found.append({"person_id": pid, "name": None if pid is not None else p.name})
    return found


class Ambiguous(Exception):
    pass


def _plausible(minutes: float, km: float) -> bool:
    return km / 950 * 60 + 20 <= minutes <= km / 600 * 60 + 75


def _times(conn: db.Connection, b: extract.Booking, start_zone: str, end_zone: str) -> tuple[str, str, bool] | None:
    start, end = extract.written_clock(b.start), extract.written_clock(b.end)
    if start is None or end is None:
        return None
    moved = extract.wall_clock(b.start, start_zone), extract.wall_clock(b.end, end_zone)
    if moved == (start, end) or not (extract.has_offset(b.start) or extract.has_offset(b.end)):
        return start, end, False
    if None not in moved and any(extract.real_offset(t) and m == w for t, m, w in ((b.start, moved[0], start), (b.end, moved[1], end))):
        return moved[0] or "", moved[1] or "", False
    seen = extract.reading(b, start_zone, end_zone)
    if seen == "written":
        return start, end, False
    if seen == "moved" and moved[0] and moved[1]:
        return moved[0], moved[1], False
    if b.kind != "flight" or None in moved or not (extract.has_offset(b.start) and extract.has_offset(b.end)):
        raise Ambiguous()
    origin, destination = airports.coords(conn, b.origin or ""), airports.coords(conn, b.destination or "")
    if origin is None or destination is None:
        raise Ambiguous()
    km = airports.distance_km(origin, destination)

    def minutes(first: str, last: str) -> float:
        return (trips.instant(last, end_zone) - trips.instant(first, start_zone)).total_seconds() / 60
    as_written, as_moved = _plausible(minutes(start, end), km), _plausible(minutes(moved[0] or "", moved[1] or ""), km)
    if as_written == as_moved:
        raise Ambiguous()
    guessed = extract.utc_marked(b.start) or extract.utc_marked(b.end)
    return (start, end, guessed) if as_written else (moved[0] or "", moved[1] or "", guessed)


def fields(conn: db.Connection, b: extract.Booking) -> trips.SegmentIn | None:
    start_zone, end_zone = _zone(conn, b, b.origin, b.start_place), _zone(conn, b, b.destination, b.end_place)
    if not start_zone or not end_zone:
        return None
    try:
        times = _times(conn, b, start_zone, end_zone)
    except Ambiguous:
        return None
    if times is None:
        return None
    start, end, guessed = times
    out: trips.SegmentIn = {"kind": b.kind, "status": b.status, "confirmation": b.confirmation, "provider": b.provider,
                            "start_local": start, "start_zone": start_zone, "end_local": end, "end_zone": end_zone,
                            "origin": b.origin, "destination": b.destination,
                            "details": {k: v for k, v in b.details if k in trips.DETAIL_KEYS}, "manage_url": b.manage_url,
                            "check_times": guessed}
    if b.passengers:
        out["travelers"] = travelers(conn, b.passengers)
    return out


def explain(conn: db.Connection, b: extract.Booking) -> str:
    if not _zone(conn, b, b.origin, b.start_place) or not _zone(conn, b, b.destination, b.end_place):
        return "unknown airport" if b.kind == "flight" else "place's time zone unknown"
    try:
        if _times(conn, b, _zone(conn, b, b.origin, b.start_place) or "", _zone(conn, b, b.destination, b.end_place) or "") is None:
            return "time isn't a date and time"
    except Ambiguous:
        return "time offset doesn't match its place"
    return "rejected as a segment"


def file_booking(conn: db.Connection, viewer: Viewer, b: extract.Booking, again: bool = False,
                 touched: list[int] | None = None) -> Literal["added", "updated", "unchanged"] | None:
    found = fields(conn, b)
    if found is None:
        return None
    try:
        return trips.merge_email_segment(conn, viewer, found, again, touched)
    except trips.Invalid:
        return None
