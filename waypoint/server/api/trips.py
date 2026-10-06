"""Trips and segments: the viewer's own (the trips they travel on or booked), made by hand, changed, merged and split, and
the airports that fill in a flight's time zones. Every read and change goes through the domain's visibility helper
(waypoint/domain/visibility.py); a trip or segment that isn't the viewer's is a 404, the same as one that doesn't exist."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from ... import validate
from ...domain import airports, people, trips
from ...domain.visibility import Viewer
from ..common import ApiError, _current, row_id
from ..contract import (Airport, MergeBody, Ok, Segment, SegmentBody, SegmentEdit, SegmentEmails, SplitBody, StoredEmail, Trip, TripBody,
                        TripList)

NAME_LIMIT = 100
NOTES_LIMIT = 4000
ADDRESS_LIMIT = trips.ADDRESS_LIMIT
MAX_TRAVELERS = 20
MAX_SEGMENTS_MOVED = 200
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")

NO_TRIP = "No such trip"
NO_SEGMENT = "No such segment"
TEXTS = {"confirmation": ("confirmation code", 50), "provider": ("provider", 100), "origin": ("origin", 100),
         "destination": ("destination", 100), "start_zone": ("start time zone", 64), "end_zone": ("end time zone", 64)}


def viewer(conn) -> Viewer:
    """Who is asking: the person the sign-in belongs to; without sign-in (your own machine), the local household, which
    sees every trip."""
    user = getattr(_current, "user", None) or {}
    if user.get("local"):
        return Viewer(None, household=True)
    sub = user.get("sub")
    return Viewer(people.person_for_sub(conn, str(sub)) if sub else None)


def _text(body: Mapping[str, Any], key: str, label: str, limit: int, required: bool = False) -> str | None:
    if key in body and body[key] is not None and not isinstance(body[key], str):
        raise ApiError(f'Send "{key}" as text')
    return _v.text(body.get(key), label, limit, required)


def _id(value: Any, missing: str) -> int:
    return row_id(value, missing, 400)


def _link(value: str | None) -> str | None:
    if value and urlsplit(value).scheme not in ("http", "https"):
        raise ApiError("The manage link must start with https:// or http://")
    return value


def _details(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        raise ApiError('Send "details" as an object of texts')
    limits = {"address": ADDRESS_LIMIT}   # (an address is as written, over several lines)
    return {k: kept for k, v in raw.items() if (kept := _v.text(v.replace("\r\n", "\n").replace("\r", "\n"), f"detail “{k[:30]}”", limits.get(k, 200)))}


def _itinerary(raw: Any) -> list[trips.PortIn]:
    if not isinstance(raw, list) or not all(isinstance(p, dict) for p in raw):
        raise ApiError('Send "itinerary" as a list of ports')
    if len(raw) > trips.MAX_PORTS:
        raise ApiError(f"Add at most {trips.MAX_PORTS} ports of call")
    return [{"name": _text(p, "name", "port’s name", NAME_LIMIT, required=True) or "", "zone": _text(p, "zone", "port’s time zone", 60) or "",
             "arrive_local": _text(p, "arrive_local", "arrival", 30), "depart_local": _text(p, "depart_local", "departure", 30)}
            for p in raw]


def _travelers(raw: Any) -> list[trips.TravelerIn]:
    if not isinstance(raw, list) or not all(isinstance(t, dict) for t in raw):
        raise ApiError('Send "travelers" as a list of people')
    if len(raw) > MAX_TRAVELERS:
        raise ApiError(f"Add at most {MAX_TRAVELERS} travellers")
    found: list[trips.TravelerIn] = []
    for t in raw:
        pid = t.get("person_id")
        one: trips.TravelerIn = {"person_id": None if pid is None else _id(pid, "Choose travellers from People"),
                                 "name": _text(t, "name", "traveller’s name", NAME_LIMIT)}
        if "seat" in t:
            one["seat"] = _text(t, "seat", "seat", trips.SEAT_LIMIT)
        found.append(one)
    return found


def segment_fields(body: Mapping[str, Any]) -> trips.SegmentIn:
    """The segment fields a request sends, checked for type and length (what's left out stays out, so an edit changes only
    what it names); the domain checks what they mean together."""
    out: trips.SegmentIn = {}
    for key in ("kind", "status", "start_local", "end_local"):
        if key in body:
            if not isinstance(body[key], str):
                raise ApiError(f'Send "{key}" as text')
            out[key] = body[key]
    for key, (label, limit) in TEXTS.items():
        if key in body:
            out[key] = _text(body, key, label, limit)   # type: ignore[literal-required]
    if "manage_url" in body:
        out["manage_url"] = _link(_text(body, "manage_url", "manage link", 500))
    if "details" in body:
        out["details"] = _details(body["details"])
    if "travelers" in body:
        out["travelers"] = _travelers(body["travelers"])
    if "itinerary" in body:
        out["itinerary"] = _itinerary(body["itinerary"])
    return out


def trip_fields(body: Mapping[str, Any], creating: bool) -> trips.TripIn:
    out: trips.TripIn = {}
    if "name" in body or creating:
        out["name"] = _text(body, "name", "name", NAME_LIMIT, required=True) or ""
    for key, label, limit in (("destination", "destination", NAME_LIMIT), ("notes", "notes", NOTES_LIMIT)):
        if key in body:
            out[key] = _text(body, key, label, limit)   # type: ignore[literal-required]
    for key in ("start_date", "end_date"):
        if key in body:
            out[key] = _v.day(body[key], key.replace("_", " "))   # type: ignore[literal-required]
    return out


def _trip(t: trips.TripOut) -> Trip:
    return {**t, "segments": [Segment(**s) for s in t["segments"]]}


def _run[T](make: Callable[[], T | None], missing: str) -> T:
    """What a domain call gives, or the 400 it explains (Invalid), or the 404 for something the viewer can't see."""
    try:
        found = make()
    except trips.Invalid as e:
        raise ApiError(str(e)) from None
    if found is None:
        raise ApiError(missing, 404)
    return found


def api_trips(conn, _q, _b) -> TripList:
    """The viewer's trips (the ones they're travelling on, or booked), with their segments."""
    return {"trips": [_trip(t) for t in trips.listing(conn, viewer(conn))]}


def api_trip_add(conn, _q, body: TripBody) -> Trip:
    """Make a trip by hand, booked by the viewer."""
    try:
        return _trip(trips.create_trip(conn, viewer(conn), trip_fields(body, creating=True)))
    except trips.Invalid as e:
        raise ApiError(str(e)) from None


def api_trip(conn, _q, _b, trip_id) -> Trip:
    """One trip with its segments, or 404 (also for one that isn't the viewer's)."""
    who = viewer(conn)
    return _trip(_run(lambda: trips.get(conn, who, row_id(trip_id, NO_TRIP)), NO_TRIP))


def api_trip_edit(conn, _q, body: TripBody, trip_id) -> Trip:
    """Rename a trip, or change its destination or notes."""
    who, fields = viewer(conn), trip_fields(body, creating=False)
    return _trip(_run(lambda: trips.edit_trip(conn, who, row_id(trip_id, NO_TRIP), fields), NO_TRIP))


def api_trip_remove(conn, _q, _b, trip_id) -> Ok:
    """Remove a trip with its segments."""
    who = viewer(conn)
    if not trips.delete_trip(conn, who, row_id(trip_id, NO_TRIP)):
        raise ApiError(NO_TRIP, 404)
    return {"ok": True}


def api_trip_merge(conn, _q, body: MergeBody, trip_id) -> Trip:
    """Fold another of the viewer's trips into this one."""
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    other = _id(body.get("merge"), "Choose the trip to merge into this one")
    return _trip(_run(lambda: trips.merge(conn, who, this, other), NO_TRIP))


def api_trip_split(conn, _q, body: SplitBody, trip_id) -> Trip:
    """Move some of a trip's segments to a new trip, which is what comes back."""
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    raw = body.get("segment_ids")
    if not isinstance(raw, list) or len(raw) > MAX_SEGMENTS_MOVED:
        raise ApiError('Send "segment_ids" as a list of segments')
    ids = [_id(i, "Choose segments of this trip to move to a new trip") for i in raw]
    return _trip(_run(lambda: trips.split(conn, who, this, ids), NO_TRIP))


def api_segment_add(conn, _q, body: SegmentBody) -> Segment:
    """Add a flight, stay, rental or train by hand, to a trip of the viewer's, or (without `trip_id`) to the trip it falls
    into, which is made if none does."""
    who = viewer(conn)
    trip_id = body.get("trip_id")
    into = None if trip_id is None else row_id(trip_id, NO_TRIP)
    fields = segment_fields(body)
    return Segment(**_run(lambda: trips.add_segment(conn, who, fields, into), NO_TRIP))


def api_segment(conn, _q, _b, segment_id) -> Segment:
    """One segment, or 404 (also for one whose trip isn't the viewer's)."""
    who = viewer(conn)
    return Segment(**_run(lambda: trips.get_segment(conn, who, row_id(segment_id, NO_SEGMENT)), NO_SEGMENT))


def api_segment_emails(conn, _q, _b, segment_id) -> SegmentEmails:
    """The messages this segment was made from or updated by, as kept (a viewer of the segment may read them), newest first. 404
    for a segment that isn't the viewer's, as for one that isn't there."""
    found = trips.emails_of(conn, viewer(conn), row_id(segment_id, NO_SEGMENT))
    if found is None:
        raise ApiError(NO_SEGMENT, 404)
    return {"emails": [StoredEmail(**e) for e in found]}


def api_segment_edit(conn, _q, body: SegmentEdit, segment_id) -> Segment:
    """Change what's sent of a segment; what ends up different is locked, so a later email won't put it back."""
    who, fields = viewer(conn), segment_fields(body)
    return Segment(**_run(lambda: trips.edit_segment(conn, who, row_id(segment_id, NO_SEGMENT), fields), NO_SEGMENT))


def api_segment_remove(conn, _q, _b, segment_id) -> Ok:
    """Remove a segment (a grouped trip left with none goes too)."""
    who = viewer(conn)
    if not trips.delete_segment(conn, who, row_id(segment_id, NO_SEGMENT)):
        raise ApiError(NO_SEGMENT, 404)
    return {"ok": True}


def api_airport(conn, _q, _b, code) -> Airport:
    """An airport by its IATA code, with its time zone."""
    found = airports.lookup(conn, code) if len(code) == 3 and code.isascii() and code.isalpha() else None
    if found is None:
        raise ApiError("No such airport", 404)
    return Airport(**found)
