from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ...storage import db
from ...storage.models import Segment
from .. import trips, visibility
from ..visibility import Viewer
from . import ai, ingest, newer, price, references, when, words
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
LABELS = re.compile(r"(?i)" + "|".join(re.escape(w) for w in sorted(words.CONFIRMATION, key=len, reverse=True)))
TRAVEL_CODES = re.compile(r"\([A-Z]{3}\)|\b[A-Z][A-Z0-9] ?\d{2,4}\b")


UNCOMPARED = re.compile(
    r"(?i)\bticket\b|\bfrequent flyer\b|\bloyalty\b|\bmember(?:ship)?\b|\bmiles\b|\bknown traveler\b|\bktn\b|\bbag\w*|\bluggage\b|\bmeals?\b|\blounge\b|"
    r"\bitinerary\b|\bport of call\b|\blayover\b|\bstopover\b|\bconnection\b|\bmanage\b|https?://|\bwww\.|\btotal\b|\bamount\b|\bpaid\b|\bcharged?\b|\bfare\b|\bprice\b|"
    r"[$€£]\s?\d|\b(?:USD|EUR|GBP|CAD|AUD)\s?\d|\d\s?(?:USD|EUR|GBP|CAD|AUD)\b|\bnotes?\b|\binstructions?\b|"
    r"\b(?:state)?rooms?\b|\bsuites?\b|\bbeds?\b|\bbreakfast\b|\brates?\b|\bnightly\b|\bvehicle\b|\bcar class\b")
FLIGHT_TOKEN = re.compile(rf"(?i)(?<![A-Za-z0-9])({ai.FLIGHT_CODE}){ai.FLIGHT_GAP}(\d{{1,4}})(?![A-Za-z0-9])")
PLAIN_WORDS = frozenset({"am", "an", "as", "at", "be", "by", "do", "go", "he", "if", "in", "is", "it", "me", "my", "no", "of", "on", "or",
                         "pm", "so", "to", "up", "us", "we"})
PASSENGER = re.compile(r"(?i)\b(?:(?:lead\s+)?(?:passengers?|travell?ers?|guests?)(?:\s+names?)?|passagers?|passagiere?|reisende[rn]?|pasajeros?|"
                       r"viajeros?|huéspedes|huésped|搭乗者|旅行者)\b[ \t]*[:#-]?[ \t]*([^\W\d_][^\d\n,;:()]{0,59})")
JOINED = re.compile(r"(?i)\s+(?:and|&)\s+")
DAY_MONTH = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+(?:de\s+)?({when.WORD})")
MONTH_DAY = re.compile(rf"(?<![^\W\d_])({when.WORD})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!\d)")
ISO_DAY = re.compile(r"(?<!\d)\d{4}-(\d\d)-(\d\d)(?!\d)")
NUMERIC_DAY = re.compile(r"(?<![\d/.])(\d{1,2})[/.](\d{1,2})(?:[/.]\d{2,4})?(?![\d/]|\.\d)")
JP_DAY = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日")
SEAT_TOKEN = re.compile(r"(?i)(?<![A-Za-z0-9])(\d{1,2}[A-K])(?![A-Za-z0-9])")
Day = tuple[int, int]
Clock = tuple[int, int]


@dataclass(frozen=True)
class Signals:
    change: bool
    travel: bool
    passengers: tuple[str, ...] = ()
    uncompared: bool = False
    flights: frozenset[str] = frozenset()
    codes: frozenset[str] = frozenset()
    days: frozenset[frozenset[Day]] = frozenset()
    seats: frozenset[str] = frozenset()
    clocks: frozenset[Clock] = frozenset()


def _clocks(whole: str) -> frozenset[Clock]:
    found: set[Clock] = set()
    for m in when.CLOCK.finditer(whole):
        hour, minute, half = int(m[1]), int(m[2]), (m[3] or "").lower()
        if half == "p" and hour < 12:
            hour += 12
        elif half == "a" and hour == 12:
            hour = 0
        found.add((hour, minute))
    found.update((int(m[1]), int(m[2])) for m in when.FRENCH_CLOCK.finditer(whole))
    found.update((int(m[1]), int(m[2] or 0)) for m in when.JP_CLOCK.finditer(whole))
    return frozenset(found)


def _real(month: int, day: int) -> bool:
    return 1 <= month <= 12 and 1 <= day <= 31


def _days(whole: str) -> frozenset[frozenset[Day]]:
    found: set[frozenset[Day]] = set()
    for m in DAY_MONTH.finditer(whole):
        if (month := when.month_number(m[2])) is not None and _real(month, int(m[1])):
            found.add(frozenset({(month, int(m[1]))}))
    for m in MONTH_DAY.finditer(whole):
        if (month := when.month_number(m[1])) is not None and _real(month, int(m[2])):
            found.add(frozenset({(month, int(m[2]))}))
    for pattern in (ISO_DAY, JP_DAY):
        found.update(frozenset({(int(m[1]), int(m[2]))}) for m in pattern.finditer(whole) if _real(int(m[1]), int(m[2])))
    for m in NUMERIC_DAY.finditer(whole):
        readings = frozenset((a, b) for a, b in ((int(m[1]), int(m[2])), (int(m[2]), int(m[1]))) if _real(a, b))
        if readings:
            found.add(readings)
    return frozenset(found)


def signals(text: str, subject: str = "", revises: bool = False) -> Signals:
    whole = f"{subject}\n{text}"
    named = tuple(dict.fromkeys(n for m in PASSENGER.finditer(whole) for part in JOINED.split(m[1]) if (n := " ".join(part.split()))))
    flights = frozenset({*(f"{m[1]}{m[2]}".upper() for m in FLIGHT_TOKEN.finditer(whole) if m[1].isupper() or m[1].lower() not in PLAIN_WORDS),
                         *(f"{a}{n}".upper() for a, n in ai.LISTED_FLIGHT.findall(whole))})
    timed = any(c.search(whole) for c in (when.CLOCK, when.FRENCH_CLOCK, when.JP_CLOCK))
    return Signals(change=revises or bool(CHANGE.search(whole)), travel=bool(timed or LABELS.search(whole) or TRAVEL_WORDS.search(whole) or TRAVEL_CODES.search(whole)),
                   passengers=named, uncompared=bool(UNCOMPARED.search(whole) or price.MONEY.search(whole)), flights=flights,
                   codes=references.labelled(whole), days=_days(whole),
                   seats=frozenset(m[1].upper() for m in SEAT_TOKEN.finditer(whole)), clocks=_clocks(whole))


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


def _flights_like(conn: db.Connection, viewer: Viewer, said: ai.Suggestion) -> list[Segment]:
    if said.get("kind") != "flight":
        return []
    fits = [s for s in visibility.household_segments(conn, "flight") if _flight_matches(s, said)]
    seen = {s.id for s in visibility.visible_segments(conn, viewer)}
    return fits if all(s.id in seen for s in fits) else []


def _held_by(conn: db.Connection, seg: Segment, said: ai.Suggestion, stored: dict[str, str], seats: bool = True) -> bool:
    held = trips.effective_travelers(conn, seg)
    wanted = said.get("travelers") or []
    named = ingest.travelers(conn, tuple(Passenger(t["name"]) for t in wanted))
    for want, listed in zip(named, wanted, strict=True):
        mine = next((h for h in held if trips._who(h) == trips._who(want)), None)
        seat = (mine.get("seat") if mine is not None else None) or (stored.get("seat") if len(held) == 1 else None)
        if mine is None or (seats and listed["seat"] and (seat or "").upper() != listed["seat"].upper()):
            return False
    return True


def adds_nothing(conn: db.Connection, seg: Segment, said: ai.Suggestion, superseded: bool = False) -> bool:
    stored = trips.decode_details(seg.details)
    times = ((said.get("start_local"), seg.start_local), (said.get("end_local"), seg.end_local))
    zones = ((said.get("start_zone"), seg.start_zone), (said.get("end_zone"), seg.end_zone))
    places = ((said.get("origin"), seg.origin), (said.get("destination"), seg.destination))
    if not superseded and any(told and _minute(told) != _minute(held) for told, held in times):
        return False
    if not superseded and any(told and told != held for told, held in zones):
        return False
    if not superseded and any(told and trips._text_key(told) != trips._text_key(held) for told, held in places):
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
    return _held_by(conn, seg, said, stored, not superseded)


def _names_held(conn: db.Connection, seg: Segment, passengers: tuple[str, ...]) -> bool:
    if not passengers:
        return True
    held = {trips._who(h) for h in trips.effective_travelers(conn, seg)}
    return all(trips._who(t) in held for t in ingest.travelers(conn, tuple(Passenger(n) for n in passengers)))


def _told_days(suggestions: list[ai.Suggestion]) -> set[Day]:
    told: set[Day] = set()
    for s in suggestions:
        for local in (s.get("start_local"), s.get("end_local")):
            if found := ISO_DAY.match(local or ""):
                told.add((int(found[1]), int(found[2])))
    return told


def covers(sign: Signals, suggestions: list[ai.Suggestion]) -> bool:
    told = {k for s in suggestions if (k := trips.flight_key(s.get("flight_number"))) is not None}
    days = _told_days(suggestions)
    return {k for f in sign.flights if (k := trips.flight_key(f)) is not None} <= told and all(readings & days for readings in sign.days)


def names_nothing(sign: Signals) -> bool:
    return not sign.codes and not sign.flights


def assess(conn: db.Connection, viewer: Viewer, said: ai.Suggestion, fields: trips.SegmentIn | None, received: str | None,
           sign: Signals) -> Reason | None:
    if fields is not None:
        decision = newer.decide(conn, viewer, fields, received, False)
        if decision is None or decision.action != "older":
            return None
        same = _same_reservations(conn, viewer, fields)
        if [s.id for s in same] == [decision.segment_id] and same[0].status == "confirmed" and _fully_held(conn, same[0], said, sign, True):
            return "older_copy"
        return None
    found = _flights_like(conn, viewer, said)
    if len(found) == 1 and found[0].status == "confirmed" and _fully_held(conn, found[0], said, sign, False):
        return "already_known"
    return None


def _seats_held(conn: db.Connection, seg: Segment, said: ai.Suggestion, sign: Signals, superseded: bool) -> bool:
    held = {(t.get("seat") or "").upper() for t in trips.effective_travelers(conn, seg)} | {(trips.decode_details(seg.details).get("seat") or "").upper()}
    if superseded:
        held |= {(t.get("seat") or "").upper() for t in said.get("travelers") or []}
    return sign.seats <= held - {""}


def _clock_of(local: str | None) -> Clock | None:
    found = re.fullmatch(r"\d{4}-\d\d-\d\dT(\d\d):(\d\d)", (local or "")[:16])
    return (int(found[1]), int(found[2])) if found else None


def _clocks_held(seg: Segment, said: ai.Suggestion, sign: Signals, superseded: bool) -> bool:
    held = {_clock_of(seg.start_local), _clock_of(seg.end_local)}
    if superseded:
        held |= {_clock_of(said.get("start_local")), _clock_of(said.get("end_local"))}
    return sign.clocks <= {c for c in held if c is not None}


def _fully_held(conn: db.Connection, seg: Segment, said: ai.Suggestion, sign: Signals, superseded: bool) -> bool:
    mine = {references.normal(c) for c in (said.get("confirmation"), seg.confirmation) if c}
    return (not sign.uncompared and {references.normal(c) for c in sign.codes} <= mine and adds_nothing(conn, seg, said, superseded)
            and _names_held(conn, seg, sign.passengers) and _seats_held(conn, seg, said, sign, superseded) and _clocks_held(seg, said, sign, superseded))
