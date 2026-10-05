"""A booking read from an email, put among the mailbox owner's trips: its times at their places' zones, its passengers
matched to people (by loyalty number, then by legal name or alias; a name nobody matches stays "Who is this?"), and its
segment merged with the one it updates, never overwriting a field a person edited."""
from __future__ import annotations

from typing import Literal

from ...storage import db
from .. import airports, loyalty, people, trips
from ..visibility import Viewer
from . import extract


def _zone(conn: db.Connection, b: extract.Booking, code: str | None, place: extract.Place) -> str | None:
    """The zone where a booking starts or ends: a flight's airport's, else where the stay, the rental or the station is."""
    if b.kind == "flight":
        known = airports.lookup(conn, code) if code else None
        return known["zone"] if known else None
    return airports.zone_for_place(conn, place.city, place.country)


def travelers(conn: db.Connection, passengers: tuple[extract.Passenger, ...]) -> list[trips.TravelerIn]:
    """Who a booking is for: each passenger's person, by the loyalty number printed on the booking and then by name, or the
    name as printed when nobody matches."""
    found: list[trips.TravelerIn] = []
    for p in passengers:
        pid = loyalty.person_for_number(conn, p.member_number) if p.member_number else None
        if pid is None:
            pid = people.match_name(conn, p.name)
        found.append({"person_id": pid, "name": None if pid is not None else p.name})
    return found


def _plausible(minutes: float, km: float) -> bool:
    """Whether a flight of this length is believable over this distance (not faster than a jet, not slower than a long day)."""
    return km / 950 * 60 + 15 <= minutes <= km / 300 * 60 + 300


def _times(conn: db.Connection, b: extract.Booking, start_zone: str, end_zone: str) -> tuple[str, str] | None:
    """A booking's start and end as wall-clock times at their places, or None when they aren't dates and times. Markup writes
    a time with an offset, which is the place's own when the sender is careful; but many senders print the local clock with a
    UTC mark ("19:00Z" for 19:00 at the airport). So when the offsets aren't the places' own, the clock is taken as written,
    except for a flight where only the conversion from UTC gives a believable flight time for the distance between its
    airports (a departure that would arrive in two hours across an ocean was in UTC)."""
    start, end = extract.written_clock(b.start), extract.written_clock(b.end)
    if start is None or end is None:
        return None
    moved = extract.wall_clock(b.start, start_zone), extract.wall_clock(b.end, end_zone)
    if b.kind != "flight" or None in moved or moved == (start, end) or not (extract.has_offset(b.start) and extract.has_offset(b.end)):
        return start, end
    origin, destination = airports.coords(conn, b.origin or ""), airports.coords(conn, b.destination or "")
    if origin is None or destination is None:
        return start, end
    km = airports.distance_km(origin, destination)

    def minutes(first: str, last: str) -> float:
        return (trips.instant(last, end_zone) - trips.instant(first, start_zone)).total_seconds() / 60
    if _plausible(minutes(start, end), km) or not _plausible(minutes(moved[0] or "", moved[1] or ""), km):
        return start, end
    return moved[0] or "", moved[1] or ""


def fields(conn: db.Connection, b: extract.Booking) -> trips.SegmentIn | None:
    """The segment a booking describes, or None when its times or places can't be settled (no known airport, a place whose
    zone isn't clear, a time that isn't a date and time)."""
    start_zone, end_zone = _zone(conn, b, b.origin, b.start_place), _zone(conn, b, b.destination, b.end_place)
    if not start_zone or not end_zone:
        return None
    times = _times(conn, b, start_zone, end_zone)
    if times is None:
        return None
    start, end = times
    out: trips.SegmentIn = {"kind": b.kind, "status": b.status, "confirmation": b.confirmation, "provider": b.provider,
                            "start_local": start, "start_zone": start_zone, "end_local": end, "end_zone": end_zone,
                            "origin": b.origin, "destination": b.destination,
                            "details": {k: v for k, v in b.details if k in trips.DETAIL_KEYS}, "manage_url": b.manage_url}
    if b.passengers:
        out["travelers"] = travelers(conn, b.passengers)
    return out


def explain(conn: db.Connection, b: extract.Booking) -> str:
    """Why `file_booking` couldn't make this booking a segment, from a fixed list (nothing from the message)."""
    if not _zone(conn, b, b.origin, b.start_place) or not _zone(conn, b, b.destination, b.end_place):
        return "unknown airport" if b.kind == "flight" else "place's time zone unknown"
    if fields(conn, b) is None:
        return "time isn't a date and time"
    return "rejected as a segment"


def file_booking(conn: db.Connection, viewer: Viewer, b: extract.Booking) -> Literal["added", "updated", "unchanged"] | None:
    """Put one booking among `viewer`'s segments. None: it can't be made into a segment (it goes to the review queue)."""
    found = fields(conn, b)
    if found is None:
        return None
    try:
        return trips.merge_email_segment(conn, viewer, found)   # (it checks everything before it writes anything)
    except trips.Invalid:
        return None
