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


def fields(conn: db.Connection, b: extract.Booking) -> trips.SegmentIn | None:
    """The segment a booking describes, or None when its times or places can't be settled (no known airport, a place whose
    zone isn't clear, a time that isn't a date and time)."""
    start_zone, end_zone = _zone(conn, b, b.origin, b.start_place), _zone(conn, b, b.destination, b.end_place)
    if not start_zone or not end_zone:
        return None
    when = extract.times(b, start_zone, end_zone)
    start, end = when.start, when.end
    if not start or not end:
        return None
    out: trips.SegmentIn = {"kind": b.kind, "status": b.status, "confirmation": b.confirmation, "provider": b.provider,
                            "start_local": start, "start_zone": start_zone, "end_local": end, "end_zone": end_zone,
                            "origin": b.origin, "destination": b.destination,
                            "details": {k: v for k, v in b.details if k in trips.DETAIL_KEYS}, "manage_url": b.manage_url,
                            "check_times": when.check}
    if b.passengers:
        out["travelers"] = travelers(conn, b.passengers)
    return out


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
