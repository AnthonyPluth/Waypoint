from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ...storage import db
from ...storage.models import Segment
from .. import trips, visibility
from ..visibility import Viewer
from . import ai, ingest, newer
from .booking import Passenger

Reason = Literal["already_known", "older_copy"]
REASONS: tuple[Reason, ...] = ("already_known", "older_copy")
CHANGE = re.compile(
    r"(?i)\b(?:cancel\w*|refund\w*|delay\w*|reschedul\w*|re-?book\w*|re-?issu\w*|chang(?:e|es|ed|ing)|modif\w*|amend\w*|revis\w*|updated|"
    r"diverted|missed|waitlist\w*|upgrad\w*|downgrad\w*|no longer|name correction|new (?:departure|arrival|time|flight|seat|gate)|"
    r"gate|terminal|seat|seats|boarding|added (?:a )?(?:passenger|traveller|traveler|guest))\b")
TRAVEL_WORDS = re.compile(
    r"(?i)\b\d{1,2}:\d{2}\b|\b\d{1,2}\s?[ap]\.?m\b|\bconfirmation\b|\breservation (?:number|code|no\b|#)|record locator|\bpnr\b|e-?ticket|ticket number|"
    r"\bitinerary\b|check-?in\b|check-?out\b|\bdepart\w*|\barriv\w*|pick-?up|drop-?off|\bpassengers?\b|\bflight\s*(?:no\.?|number|#)")
TRAVEL_CODES = re.compile(r"\([A-Z]{3}\)|\b[A-Z][A-Z0-9] ?\d{2,4}\b")


PASSENGER = re.compile(r"(?i)\b(?:passengers?|travell?ers?|guests?)\b[ \t]*[:#-]?[ \t]*([^\W\d_][^\d\n,;:()]{0,59})")
JOINED = re.compile(r"(?i)\s+(?:and|&)\s+")


@dataclass(frozen=True)
class Signals:
    change: bool
    travel: bool
    passengers: tuple[str, ...] = ()


def signals(text: str, subject: str = "", revises: bool = False) -> Signals:
    whole = f"{subject}\n{text}"
    named = tuple(dict.fromkeys(n for m in PASSENGER.finditer(whole) for part in JOINED.split(m[1]) if (n := " ".join(part.split()))))
    return Signals(change=revises or bool(CHANGE.search(whole)), travel=bool(TRAVEL_WORDS.search(whole) or TRAVEL_CODES.search(whole)), passengers=named)


def _day(local: str | None) -> str:
    return (local or "")[:10]


def _minute(local: str | None) -> str:
    return (local or "")[:16]


def _airport(code: str | None) -> str:
    return (code or "").strip().upper()


def _flight_matches(seg: Segment, said: ai.Suggestion) -> bool:
    number = trips.flight_key(said.get("flight_number"))
    if seg.kind != "flight" or number is None or not _day(said.get("start_local")):
        return False
    stored = trips.flight_key(trips.decode_details(seg.details).get("flight_number"))
    same_airport = (_airport(said.get("origin")) == _airport(seg.origin) and bool(_airport(seg.origin))) or \
                   (_airport(said.get("destination")) == _airport(seg.destination) and bool(_airport(seg.destination)))
    return stored == number and _day(seg.start_local) == _day(said.get("start_local")) and same_airport


def _same_reservations(conn: db.Connection, viewer: Viewer, fields: trips.SegmentIn) -> list[Segment]:
    try:
        values = trips.check(conn, fields)
    except trips.Invalid:
        return []
    details = fields.get("details") or {}
    return [s for s in visibility.visible_segments(conn, viewer) if s.status != "cancelled" and trips.reservation(s, values, details) == "same"]


def _matches(conn: db.Connection, viewer: Viewer, said: ai.Suggestion, fields: trips.SegmentIn | None) -> list[Segment]:
    if said.get("kind") == "flight":
        return [s for s in visibility.visible_segments(conn, viewer) if _flight_matches(s, said)]
    if fields is None:
        return []
    return [s for s in _same_reservations(conn, viewer, fields) if _day(s.start_local) == _day(fields.get("start_local"))]


def _held_by(conn: db.Connection, seg: Segment, said: ai.Suggestion, stored: dict[str, str]) -> bool:
    held = trips.effective_travelers(conn, seg)
    wanted = said.get("travelers") or []
    named = ingest.travelers(conn, tuple(Passenger(t["name"]) for t in wanted))
    for want, listed in zip(named, wanted, strict=True):
        mine = next((h for h in held if trips._who(h) == trips._who(want)), None)
        seat = (mine.get("seat") if mine is not None else None) or (stored.get("seat") if len(held) == 1 else None)
        if mine is None or (listed["seat"] and (seat or "").upper() != listed["seat"].upper()):
            return False
    return True


def adds_nothing(conn: db.Connection, seg: Segment, said: ai.Suggestion) -> bool:
    stored = trips.decode_details(seg.details)
    times = ((said.get("start_local"), seg.start_local), (said.get("end_local"), seg.end_local))
    zones = ((said.get("start_zone"), seg.start_zone), (said.get("end_zone"), seg.end_zone))
    places = ((said.get("origin"), seg.origin), (said.get("destination"), seg.destination))
    if any(told and _minute(told) != _minute(held) for told, held in times):
        return False
    if any(told and told != held for told, held in zones):
        return False
    if any(told and trips._text_key(told) != trips._text_key(held) for told, held in places):
        return False
    if said.get("confirmation") and not (seg.confirmation and trips._code_key(said["confirmation"]) == trips._code_key(seg.confirmation)):
        return False
    number = trips.flight_key(stored.get("flight_number"))
    if said.get("provider") and not (seg.provider and trips._providers_agree(seg.provider, said["provider"], number)):
        return False
    if said.get("flight_number") and number != trips.flight_key(said["flight_number"]):
        return False
    if said.get("cabin") and trips._text_key(stored.get("cabin")) != trips._text_key(said["cabin"]):
        return False
    extras = (said.get("address"), "address"), (said.get("phone"), "phone"), (said.get("room"), "room"), (said.get("ship"), "ship"), (said.get("deck"), "deck")
    if any(told and trips._text_key(stored.get(key)) != trips._text_key(told) for told, key in extras):
        return False
    if said.get("price_minor") is not None and (seg.price_minor != said["price_minor"] or seg.price_currency != said.get("price_currency")):
        return False
    return _held_by(conn, seg, said, stored)


def _names_held(conn: db.Connection, seg: Segment, passengers: tuple[str, ...]) -> bool:
    if not passengers:
        return True
    held = {trips._who(h) for h in trips.effective_travelers(conn, seg)}
    return all(trips._who(t) in held for t in ingest.travelers(conn, tuple(Passenger(n) for n in passengers)))


def assess(conn: db.Connection, viewer: Viewer, said: ai.Suggestion, fields: trips.SegmentIn | None, received: str | None,
           passengers: tuple[str, ...] = ()) -> Reason | None:
    if fields is not None:
        decision = newer.decide(conn, viewer, fields, received, False)
        if decision is not None and decision.action == "older":
            same = _same_reservations(conn, viewer, fields)
            if [s.id for s in same] == [decision.segment_id] and _names_held(conn, same[0], passengers):
                return "older_copy"
    found = _matches(conn, viewer, said, fields)
    if len(found) == 1 and found[0].status == "confirmed" and adds_nothing(conn, found[0], said) and _names_held(conn, found[0], passengers):
        return "already_known"
    return None
