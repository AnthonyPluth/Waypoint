from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from ... import monitoring, validate
from ...domain import airports, loyalty, money, people, tripmap, trips
from ...domain.mail import ai
from ...domain.visibility import Viewer
from ...storage import db
from ..common import NO_IMAGE, ApiError, Response, _current, image_response, own_session, position, row_id
from ..contract import (Airport, DestinationSuggestion, EmailsCleared, MergeBody, MoveBody, Ok, Segment, SegmentBody, SegmentEdit, SegmentEmails, SplitBody, StoredEmail, Trip, TripBody,
                        TripList, TripPlaces)

NAME_LIMIT = 100
NOTES_LIMIT = 4000
ADDRESS_LIMIT = trips.ADDRESS_LIMIT
MAX_TRAVELERS = 20
MAX_SEGMENTS_MOVED = 200
_v = validate.Validator(ApiError, too_long="The {label} is too long (at most {limit} characters)")

NO_TRIP = "No such trip"
NO_SEGMENT = "No such segment"
NO_AI = "Suggestions need the AI fallback, which is off. Turn it on under Settings, in Mail and AI."
NO_PLACES = "Add a booking to this trip first, so there are places to describe."
TEXTS = {"confirmation": ("confirmation code", 50), "provider": ("provider", 100), "origin": ("origin", 100),
         "destination": ("destination", 100), "start_zone": ("start time zone", 64), "end_zone": ("end time zone", 64)}


def viewer(conn) -> Viewer:
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
    limits = {"address": ADDRESS_LIMIT}
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


def _price(raw: Any) -> trips.PriceIn | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ApiError('Send "price" as an amount and a currency, or null to clear it')
    amount, currency = raw.get("amount_minor"), raw.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, int) or not isinstance(currency, str):
        raise ApiError('Send the cost as {"amount_minor": a whole number of cents, "currency": "USD"}')
    if not money.valid(amount, currency):
        raise ApiError("The cost needs an amount between 0 and 1,000,000,000 in the currency’s smallest unit and a three-letter currency code like USD")
    return {"amount_minor": amount, "currency": currency}


def _people(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        raise ApiError('Send "people" as a list of people')
    if len(raw) > MAX_TRAVELERS:
        raise ApiError(f"Add at most {MAX_TRAVELERS} people")
    return [_id(p, "Choose people from People") for p in raw]


def segment_fields(body: Mapping[str, Any]) -> trips.SegmentIn:
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
    if "price" in body:
        out["price"] = _price(body["price"])
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
    if "people" in body:
        out["people"] = _people(body["people"])
    return out


def _trip(t: trips.TripOut) -> Trip:
    return {**t, "segments": [Segment(**s) for s in t["segments"]]}


def _run[T](make: Callable[[], T | None], missing: str) -> T:
    try:
        found = make()
    except trips.NeedsConfirmation:
        raise
    except trips.Invalid as e:
        raise ApiError(str(e)) from None
    if found is None:
        raise ApiError(missing, 404)
    return found


def api_trips(conn, _q, _b) -> TripList:
    return {"trips": [_trip(t) for t in trips.listing(conn, viewer(conn))]}


def _needs_the_person(e: trips.NeedsConfirmation, assistant: bool) -> ApiError:
    if assistant:
        return ApiError("This needs the person to do it in the app: adding someone to a trip changes who sees what, and only they can "
                        "confirm it.", 403)
    return ApiError(str(e), 409, {"see_booking": e.see_booking, "see_trip": e.see_trip})


def _assistant() -> bool:
    return bool(getattr(_current, "assistant", True))


def api_trip_add(conn, _q, body: TripBody) -> Trip:
    assistant = _assistant()
    try:
        return _trip(trips.create_trip(conn, viewer(conn), trip_fields(body, creating=True), validate.on(body.get("confirm")) and not assistant))
    except trips.NeedsConfirmation as e:
        raise _needs_the_person(e, assistant) from None
    except trips.Invalid as e:
        raise ApiError(str(e)) from None


def api_trip(conn, _q, _b, trip_id) -> Trip:
    who = viewer(conn)
    return _trip(_run(lambda: trips.get(conn, who, row_id(trip_id, NO_TRIP)), NO_TRIP))


def api_trip_places(conn, _q, _b, trip_id) -> TripPlaces:
    who = viewer(conn)
    return _run(lambda: tripmap.places(conn, who, row_id(trip_id, NO_TRIP)), NO_TRIP)


def api_trip_edit(conn, _q, body: TripBody, trip_id) -> Trip:
    who, fields, assistant = viewer(conn), trip_fields(body, creating=False), _assistant()
    confirmed = validate.on(body.get("confirm")) and not assistant
    try:
        return _trip(_run(lambda: trips.edit_trip(conn, who, row_id(trip_id, NO_TRIP), fields, confirmed), NO_TRIP))
    except trips.NeedsConfirmation as e:
        raise _needs_the_person(e, assistant) from None


def api_trip_remove(conn, _q, _b, trip_id) -> Ok:
    who = viewer(conn)
    if not trips.delete_trip(conn, who, row_id(trip_id, NO_TRIP)):
        raise ApiError(NO_TRIP, 404)
    return {"ok": True}


def api_trip_emails_clear(conn, _q, _b, trip_id) -> EmailsCleared:
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    removed = _run(lambda: trips.clear_emails(conn, who, this, date.today(), time.time()), NO_TRIP)
    monitoring.log(f"Removed {removed} saved emails of a trip")
    return {"removed": removed}


def api_trip_merge(conn, _q, body: MergeBody, trip_id) -> Trip:
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    other = _id(body.get("merge"), "Choose the trip to merge into this one")
    return _trip(_run(lambda: trips.merge(conn, who, this, other), NO_TRIP))


def api_trip_split(conn, _q, body: SplitBody, trip_id) -> Trip:
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    raw = body.get("segment_ids")
    if not isinstance(raw, list) or len(raw) > MAX_SEGMENTS_MOVED:
        raise ApiError('Send "segment_ids" as a list of segments')
    ids = [_id(i, "Choose segments of this trip to move to a new trip") for i in raw]
    return _trip(_run(lambda: trips.split(conn, who, this, ids), NO_TRIP))


@own_session
def api_trip_destination_suggest(_conn, _q, _b, trip_id) -> DestinationSuggestion:
    this = row_id(trip_id, NO_TRIP)
    with db.session() as conn:
        facts = trips.destination_facts(conn, viewer(conn), this)
        cfg = ai.config(conn)
        known = tuple(loyalty.known_numbers(conn)) if cfg else ()
    if facts is None:
        raise ApiError(NO_TRIP, 404)
    if cfg is None:
        raise ApiError(NO_AI)
    if not facts["stops"]:
        raise ApiError(NO_PLACES)
    try:
        return {"suggestion": ai.destination(cfg, facts, known)}
    except ai.AiError as e:
        raise ApiError(str(e), 502) from e


def api_segment_add(conn, _q, body: SegmentBody) -> Segment:
    who = viewer(conn)
    trip_id = body.get("trip_id")
    into = None if trip_id is None else row_id(trip_id, NO_TRIP)
    fields = segment_fields(body)
    return Segment(**_run(lambda: trips.add_segment(conn, who, fields, into), NO_TRIP))


def api_segment(conn, _q, _b, segment_id) -> Segment:
    who = viewer(conn)
    return Segment(**_run(lambda: trips.get_segment(conn, who, row_id(segment_id, NO_SEGMENT)), NO_SEGMENT))


def api_segment_emails(conn, _q, _b, segment_id) -> SegmentEmails:
    found = trips.emails_of(conn, viewer(conn), row_id(segment_id, NO_SEGMENT))
    if found is None:
        raise ApiError(NO_SEGMENT, 404)
    return {"emails": [StoredEmail(**e) for e in found]}


def api_segment_email_image(conn, _q, _b, segment_id, email, index) -> Response:
    found = trips.email_image_of(conn, viewer(conn), row_id(segment_id, NO_IMAGE), position(email), position(index))
    if found is None:
        raise ApiError(NO_IMAGE, 404)
    return image_response(found)


def api_segment_edit(conn, _q, body: SegmentEdit, segment_id) -> Segment:
    who, fields = viewer(conn), segment_fields(body)
    return Segment(**_run(lambda: trips.edit_segment(conn, who, row_id(segment_id, NO_SEGMENT), fields), NO_SEGMENT))


def api_segment_remove(conn, _q, _b, segment_id) -> Ok:
    who = viewer(conn)
    if not trips.delete_segment(conn, who, row_id(segment_id, NO_SEGMENT)):
        raise ApiError(NO_SEGMENT, 404)
    return {"ok": True}


def api_segment_move(conn, _q, body: MoveBody, segment_id) -> Trip:
    who, this = viewer(conn), row_id(segment_id, NO_SEGMENT)
    target = body.get("trip_id")
    into = None if target is None else _id(target, "Choose the trip to move this into")
    assistant = _assistant()
    confirmed = validate.on(body.get("confirm")) and not assistant
    try:
        return _trip(_run(lambda: trips.move_segment(conn, who, this, into, confirmed), NO_SEGMENT))
    except trips.NeedsConfirmation as e:
        if assistant:
            raise ApiError("This needs the person to do it in the app: moving a booking into a trip with different people changes who "
                           "sees what, and only they can confirm it.", 403) from None
        raise ApiError(str(e), 409, {"see_booking": e.see_booking, "see_trip": e.see_trip}) from None


def api_airport(conn, _q, _b, code) -> Airport:
    found = airports.lookup(conn, code) if len(code) == 3 and code.isascii() and code.isalpha() else None
    if found is None:
        raise ApiError("No such airport", 404)
    return Airport(**found)
