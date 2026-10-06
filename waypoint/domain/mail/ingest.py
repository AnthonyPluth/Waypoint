"""A booking read from an email, put among the mailbox owner's trips: its times at their places' zones, its passengers
matched to people (by loyalty number, then by legal name or alias; a name nobody matches stays "Who is this?"), and its
segment merged with the one it updates, never overwriting a field a person edited."""
from __future__ import annotations

from typing import Literal

from ...storage import db
from .. import airports, loyalty, people, place_zones, trips
from ..visibility import Viewer
from . import extract


def _zone(conn: db.Connection, b: extract.Booking, code: str | None, place: extract.Place) -> str | None:
    """The zone where a booking starts or ends: a flight's airport's, else where the stay, the rental or the station is."""
    if b.kind == "flight":
        known = airports.lookup(conn, code) if code else None
        return known["zone"] if known else None
    return (airports.zone_for_place(conn, place.city, place.country)
            or (place_zones.zone_for_address(conn, dict(b.details).get("address")) if b.kind == "hotel" else None))


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


class Ambiguous(Exception):
    """A booking's times carry offsets that aren't its places' own, and nothing says which reading is right."""


def _plausible(minutes: float, km: float) -> bool:
    """Whether a flight of this length is believable over this distance: no faster than a jet plus taxiing, no slower than
    a slow cruise plus a long delay."""
    return km / 950 * 60 + 20 <= minutes <= km / 600 * 60 + 75


def _times(conn: db.Connection, b: extract.Booking, start_zone: str, end_zone: str) -> tuple[str, str, bool] | None:
    """A booking's start and end as wall-clock times at their places, or None when they aren't dates and times. Raises
    Ambiguous when they can't be told.

    Markup writes a time with an offset. When it is the place's own (or there is none), the clock is what's written. When
    it isn't, the sender either printed the local clock with a UTC mark ("19:00Z" for 19:00 at the airport) or really gave
    UTC. A flight is decided when exactly one of the two readings gives a believable flight time for the distance between
    its airports; before that, the message's own text can settle it (`extract.reading`). A guess made on distance alone for
    times marked UTC is flagged (the third value) so the segment's card asks for a look. Everything else (a stay, a rental, a
    train, a short hop where both fit) is Ambiguous and goes to the review queue, rather than being filed with a time that
    may be hours off. A sender who gives one time with a non-zero offset that is its place's own is giving real instants, so
    the other time (a "Z" into London in summer) is converted."""
    start, end = extract.written_clock(b.start), extract.written_clock(b.end)
    if start is None or end is None:
        return None
    moved = extract.wall_clock(b.start, start_zone), extract.wall_clock(b.end, end_zone)
    if moved == (start, end) or not (extract.has_offset(b.start) or extract.has_offset(b.end)):
        return start, end, False
    if None not in moved and any(extract.real_offset(t) and m == w for t, m, w in ((b.start, moved[0], start), (b.end, moved[1], end))):
        return moved[0] or "", moved[1] or "", False   # (an offset that is its own place's says the sender gives real instants)
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
    """The segment a booking describes, or None when its times or places can't be settled (no known airport, a place whose
    zone isn't clear, a time that isn't a date and time)."""
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
    """Why `file_booking` couldn't make this booking a segment, from a fixed list (nothing from the message)."""
    if not _zone(conn, b, b.origin, b.start_place) or not _zone(conn, b, b.destination, b.end_place):
        return "unknown airport" if b.kind == "flight" else "place's time zone unknown"
    try:
        if _times(conn, b, _zone(conn, b, b.origin, b.start_place) or "", _zone(conn, b, b.destination, b.end_place) or "") is None:
            return "time isn't a date and time"
    except Ambiguous:
        return "time offset doesn't match its place"
    return "rejected as a segment"


def file_booking(conn: db.Connection, viewer: Viewer, b: extract.Booking,
                 again: bool = False) -> Literal["added", "updated", "unchanged"] | None:
    """Put one booking among `viewer`'s segments (`again`: from a message read again). None: it can't be made into a segment
    (it goes to the review queue)."""
    found = fields(conn, b)
    if found is None:
        return None
    try:
        return trips.merge_email_segment(conn, viewer, found, again)   # (it checks everything before it writes anything)
    except trips.Invalid:
        return None
