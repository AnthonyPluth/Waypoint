"""Trips and their segments: a trip is a journey, a segment one flight leg, hotel stay, car rental or train in it.

A segment's start and end are the wall-clock times where they happen, as typed (2026-03-01T22:15), stored with the IANA
zone of the place (Pacific/Auckland): nothing here converts one to the server's zone or to UTC, and the zone is never
dropped. Times are turned into instants only to compare them (an arrival that isn't before its departure, the order of a
trip's segments), never to store or show.

Every read and every change of a trip or segment starts from the visibility helper (waypoint/domain/visibility.py), so
what the viewer can't see is None, as if it weren't there (the API answers 404). Segments are grouped into trips by
date gaps and by getting back home (`choose_trip`), and a person can rename, merge and split trips. A person's edit to a
segment locks the fields they changed (`locked_fields`), so a later email never overwrites them (`unlocked`)."""
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select, update

from ..storage import db
from ..storage.models import Segment, SegmentTraveler, Trip
from . import airports, links, people, visibility
from .visibility import Viewer

Kind = Literal["flight", "hotel", "car", "train"]
Status = Literal["confirmed", "changed", "cancelled"]
KINDS: tuple[Kind, ...] = ("flight", "hotel", "car", "train")
STATUSES: tuple[Status, ...] = ("confirmed", "changed", "cancelled")
TIME_UNKNOWN = "time_unknown"
# What a segment's details may hold (the rest of a booking has a field of its own), each a text. `time_unknown` ("yes") marks an
# imported flight whose file gave no times: it starts and ends at midnight of its day and counts in distance, not time.
DETAIL_KEYS = ("flight_number", "terminal", "seat", "cabin", "room", "car_class", "address", "phone", TIME_UNKNOWN)


def untimed(details: Mapping[str, str]) -> bool:
    """Whether a segment's times are unknown (an imported flight whose file gave none): its start and end are only a
    placeholder at midnight of its day, so nothing may show them as real times or schedule anything from them."""
    return details.get(TIME_UNKNOWN) == "yes"


# A person's edit locks the fields it changes; these are the names a lock can have.
FIELDS = ("kind", "status", "confirmation", "provider", "start_local", "start_zone", "end_local", "end_zone", "origin",
          "destination", "details", "manage_url", "travelers")
TIME_FIELDS = ("start_local", "start_zone", "end_local", "end_zone")   # (a person who looks at these has settled them)
GAP_DAYS = 2    # a segment this many days or fewer from a trip (before or after it) can belong to it
AWAY_DAYS = 60  # and one that carries on from where an unfinished trip's last leg landed (the way back), this many
FLIGHT_NUMBER = re.compile(r"([A-Z0-9]{2,3}?)0*(\d{1,4}[A-Z]?)")   # carrier code, then the number without its leading zeros
COMPANY_SUFFIXES = frozenset({"inc", "incorporated", "ltd", "limited", "llc", "plc", "corp", "corporation", "co", "company",
                              "gmbh", "ag", "sa", "bv"})
LOCAL_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?")
IATA = re.compile(r"[A-Za-z]{3}")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Invalid(ValueError):
    """Something a person sent can't be saved; the message says what to fix (the API's 400)."""


class TravelerIn(TypedDict):
    """Someone on a segment: a person (`person_id`), and/or a name as printed on the booking."""
    person_id: int | None
    name: str | None


class SegmentIn(TypedDict, total=False):
    """A segment's fields, as far as they are given: all of them for a new one except the status (confirmed unless said)
    and the zones of a flight's known airports (taken from them); only what changes for an edit. Already checked for
    type and length (waypoint/server/api/trips.py); `check` does the rest."""
    kind: str
    status: str
    confirmation: str | None
    provider: str | None
    start_local: str
    start_zone: str | None
    end_local: str
    end_zone: str | None
    origin: str | None
    destination: str | None
    details: dict[str, str]
    manage_url: str | None
    travelers: list[TravelerIn]
    check_times: bool          # from an email: its times couldn't be settled (not for a person to send)


class TripIn(TypedDict, total=False):
    name: str
    destination: str | None
    notes: str | None
    start_date: str | None
    end_date: str | None


class TravelerOut(TypedDict):
    id: int
    person_id: int | None
    name: str                  # the person's display name, or the name as printed


class SegmentOut(TypedDict):
    id: int
    trip_id: int
    kind: Kind
    status: Status
    confirmation: str | None
    provider: str | None
    start_local: str
    start_zone: str
    end_local: str
    end_zone: str
    origin: str | None
    destination: str | None
    details: dict[str, str]
    manage_url: str | None
    source: Literal["manual", "email", "import"]
    booked_by: int | None
    locked_fields: list[str]
    check_times: bool
    travelers: list[TravelerOut]
    links: links.Links


class TripOut(TypedDict):
    id: int
    name: str
    start_date: str | None
    end_date: str | None
    destination: str | None
    notes: str | None
    auto: bool
    booked_by: int | None
    segments: list[SegmentOut]


# ------------------------------------------------------------------------------------------------ the same booking, written another way

def flight_key(number: str | None) -> str | None:
    """A flight number as one flight has it however it's written (carrier code and number, no spaces, no leading zeros,
    upper case): "AA 4001", "aa4001" and "AA04001" are all AA4001. None for text that isn't one."""
    n = re.sub(r"[\s-]", "", number or "").upper()
    found = FLIGHT_NUMBER.fullmatch(n)
    return f"{found.group(1)}{found.group(2)}" if found else None


def provider_key(name: str | None) -> str:
    """A company's name without case, punctuation, spacing or a trailing "Inc." or "Ltd": "American Airlines, Inc." and
    "AMERICAN AIRLINES" are the same."""
    words = re.sub(r"[^\w\s]", " ", (name or "").casefold()).split()
    while len(words) > 1 and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def _text_key(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _code_key(code: str | None) -> str:
    return re.sub(r"\s+", "", code or "").casefold()


def flight_group_key(seg: SegmentOut) -> tuple[str, str, str, str] | None:
    """What makes bookings the same flight: its flight number (`flight_key`), local departure date and airports. None for
    anything but a flight that has a number: hotels and cars are never grouped."""
    number = flight_key(seg["details"].get("flight_number")) if seg["kind"] == "flight" else None
    if number is None:
        return None
    return number, seg["start_local"][:10], (seg["origin"] or "").upper(), (seg["destination"] or "").upper()


def flight_groups(segs: Sequence[SegmentOut]) -> list[list[SegmentOut]]:
    """These segments with the bookings of one flight together (each booking keeps its own segment; this is how the calendar
    feed, the reminders and the screens count a flight once), in the order each group first appears. Everything that isn't a
    numbered flight is a group of its own."""
    groups: list[list[SegmentOut]] = []
    by_key: dict[tuple[str, str, str, str], list[SegmentOut]] = {}
    for seg in segs:
        key = flight_group_key(seg)
        if key is not None and key in by_key:
            by_key[key].append(seg)
            continue
        group = [seg]
        groups.append(group)
        if key is not None:
            by_key[key] = group
    return groups


# ------------------------------------------------------------------------------------------------ times and fields

def instant(local: str, zone: str) -> datetime:
    """The moment a wall-clock time at a place is, for comparing (never for storing or showing)."""
    return datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(zone))


def _zone(value: str | None, label: str) -> str:
    if not value:
        raise Invalid(f"Enter the {label} time zone (for example America/New_York)")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise Invalid(f"The {label} time zone “{value[:40]}” isn’t one Waypoint knows (use a name like America/New_York)") from None
    return value


def _local(value: str | None, label: str) -> str:
    """A wall-clock time: date, T, hour and minute (seconds optional), and no offset, because it's the time where it happens."""
    if not value or not LOCAL_TIME.fullmatch(value):
        raise Invalid(f"The {label} time must be the local time at the place, like 2026-03-01T22:15 (no time zone offset)")
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        raise Invalid(f"The {label} time isn’t a real date and time") from None
    return t.isoformat(timespec="minutes" if t.second == 0 else "seconds")


def decode_details(raw: str | None) -> dict[str, str]:
    try:
        found = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return {k: v for k, v in found.items() if isinstance(v, str)} if isinstance(found, dict) else {}


def decode_locked(raw: str | None) -> list[str]:
    try:
        found = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [f for f in found if isinstance(f, str)] if isinstance(found, list) else []


def _place_zone(conn: db.Connection, kind: str, code: str | None, given: str | None, label: str) -> str:
    """The zone of a segment's start or end: the one given, else a flight's airport's."""
    if given:
        return _zone(given, label)
    known = airports.lookup(conn, code) if kind == "flight" and code else None
    return _zone(known["zone"] if known else None, label)


def check(conn: db.Connection, fields: SegmentIn) -> dict[str, str | None]:
    """A segment's columns from all of its fields (not travelers: see `_travelers`), checked: its kind and status are known,
    a flight's places are airport codes, its times are local times with a known zone each (a flight's from its airports
    unless given), and it doesn't end before it starts (compared as moments: crossing the date line, an arrival's local
    time is earlier than its departure's). Raises Invalid."""
    kind = fields.get("kind")
    if kind not in KINDS:
        raise Invalid(f"Choose what this is: {', '.join(KINDS)}")
    status = fields.get("status") or "confirmed"
    if status not in STATUSES:
        raise Invalid(f"The status must be one of {', '.join(STATUSES)}")
    origin, destination = fields.get("origin"), fields.get("destination")
    if kind == "flight":
        for label, code in (("origin", origin), ("destination", destination)):
            if not code or not IATA.fullmatch(code):
                raise Invalid(f"A flight’s {label} is an airport code like JFK")
        origin, destination = (origin or "").upper(), (destination or "").upper()
    start_zone = _place_zone(conn, kind, origin, fields.get("start_zone"), "start")
    end_zone = _place_zone(conn, kind, destination, fields.get("end_zone"), "end")
    start, end = _local(fields.get("start_local"), "start"), _local(fields.get("end_local"), "end")
    if instant(end, end_zone) < instant(start, start_zone):
        raise Invalid("This ends before it starts (times are compared at their own places’ zones)")
    details = fields.get("details") or {}
    if any(k not in DETAIL_KEYS for k in details):
        raise Invalid(f"Details can hold only: {', '.join(DETAIL_KEYS)}")
    return {"kind": kind, "status": status, "confirmation": fields.get("confirmation"),
            "provider": fields.get("provider"), "start_local": start, "start_zone": start_zone, "end_local": end,
            "end_zone": end_zone, "origin": origin, "destination": destination,
            "details": json.dumps(details, ensure_ascii=False) if details else None,
            "manage_url": fields.get("manage_url")}


def _current(seg: Segment, travelers: list[TravelerIn]) -> SegmentIn:
    """A stored segment's fields, as `check` takes them."""
    return {"kind": seg.kind, "status": seg.status, "confirmation": seg.confirmation, "provider": seg.provider,
            "start_local": seg.start_local, "start_zone": seg.start_zone, "end_local": seg.end_local,
            "end_zone": seg.end_zone, "origin": seg.origin, "destination": seg.destination,
            "details": decode_details(seg.details), "manage_url": seg.manage_url, "travelers": travelers}


def unlocked(incoming: SegmentIn, locked: Iterable[str]) -> SegmentIn:
    """What a later email may change: its fields without the ones a person edited."""
    skip = set(locked)
    return {k: v for k, v in incoming.items() if k not in skip}  # type: ignore[return-value]


def _travelers(conn: db.Connection, given: Sequence[TravelerIn]) -> list[TravelerIn]:
    """Who is on a segment, checked: each a person who exists, or a name as printed, each once."""
    ids = [t["person_id"] for t in given if t.get("person_id") is not None]
    known = people.existing(conn, [i for i in ids if i is not None])
    kept: list[TravelerIn] = []
    seen: set[object] = set()
    for t in given:
        pid, name = t.get("person_id"), t.get("name")
        if pid is not None and pid not in known:
            raise Invalid("Someone on this isn’t in People")
        if pid is None and not name:
            raise Invalid("Name each traveller, or choose them from People")
        key: object = pid if pid is not None else (name or "").casefold()
        if key not in seen:
            seen.add(key)
            kept.append({"person_id": pid, "name": name})
    return kept


# ------------------------------------------------------------------------------------------------ reading

def _segment_outs(conn: db.Connection, segs: Sequence[Segment], travs: Sequence[SegmentTraveler]) -> list[SegmentOut]:
    ids = [t.person_id for t in travs if t.person_id is not None]
    names = people.existing(conn, ids)
    by_segment: dict[int, list[TravelerOut]] = {}
    for t in travs:
        shown = names.get(t.person_id, "") if t.person_id is not None else ""
        by_segment.setdefault(t.segment_id, []).append({"id": t.id, "person_id": t.person_id, "name": shown or t.name or ""})
    def last_name(s: Segment) -> str | None:
        who = by_segment.get(s.id, [])
        return who[0]["name"].split()[-1] if who and who[0]["name"] else None

    out: list[SegmentOut] = [
        {"id": s.id, "trip_id": s.trip_id, "kind": cast(Kind, s.kind), "status": cast(Status, s.status), "confirmation": s.confirmation,
         "provider": s.provider, "start_local": s.start_local, "start_zone": s.start_zone, "end_local": s.end_local,
         "end_zone": s.end_zone, "origin": s.origin, "destination": s.destination, "details": decode_details(s.details),
         "manage_url": s.manage_url, "source": cast(Literal["manual", "email", "import"], s.source), "booked_by": s.booked_by,
         "locked_fields": decode_locked(s.locked_fields), "check_times": bool(s.check_times), "travelers": by_segment.get(s.id, []),
         "links": links.segment_links(s.kind, s.provider, s.confirmation, last_name(s), s.manage_url, decode_details(s.details), s.origin)}
        for s in segs]
    return sorted(out, key=lambda s: (instant(s["start_local"], s["start_zone"]), s["id"]))


def _trip_outs(conn: db.Connection, viewer: Viewer, trips: Sequence[Trip]) -> list[TripOut]:
    segs = visibility.visible_segments(conn, viewer, [t.id for t in trips])
    travs = visibility.visible_travelers(conn, viewer, [s.id for s in segs])
    outs = _segment_outs(conn, segs, travs)
    return [{"id": t.id, "name": t.name, "start_date": t.start_date, "end_date": t.end_date,
             "destination": t.destination, "notes": t.notes, "auto": t.auto, "booked_by": t.booked_by,
             "segments": [s for s in outs if s["trip_id"] == t.id]} for t in trips]


def listing(conn: db.Connection, viewer: Viewer) -> list[TripOut]:
    """The viewer's trips with their segments, by start date."""
    return _trip_outs(conn, viewer, visibility.visible_trips(conn, viewer))


def get(conn: db.Connection, viewer: Viewer, trip_id: int) -> TripOut | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    return _trip_outs(conn, viewer, [trip])[0] if trip else None


def get_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> SegmentOut | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    return _segment_outs(conn, [seg], visibility.visible_travelers(conn, viewer, [seg.id]))[0] if seg else None


def _after_change(conn: db.Connection, seg: Segment) -> SegmentOut:
    """A segment just saved (so the viewer was allowed to), as the API shows it, even if what they changed means they no
    longer see its trip."""
    travs = list(conn.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id)
                                  .order_by(SegmentTraveler.id)).all())
    return _segment_outs(conn, [seg], travs)[0]


# ------------------------------------------------------------------------------------------------ grouping

@dataclass(frozen=True)
class Facts:
    """What grouping needs to know of a trip or a new segment: its local dates and the people it involves (travellers
    and bookers)."""
    start: date
    end: date
    people: frozenset[int]
    leg: tuple[str | None, str | None] | None = None   # a new flight's or train's (origin, destination)


@dataclass(frozen=True)
class Candidate:
    trip_id: int
    facts: Facts
    legs: tuple[tuple[str | None, str | None], ...]   # (origin, destination) of its flights and trains, in order


def returned_home(legs: Sequence[tuple[str | None, str | None]]) -> bool:
    """A round trip is done once a leg gets back to where the first one left: A to B, B to A."""
    return len(legs) >= 2 and bool(legs[0][0]) and (legs[-1][1] or "").upper() == (legs[0][0] or "").upper()


def _gap(a: Facts, b: Facts) -> int:
    if a.end < b.start:
        return (b.start - a.end).days
    if b.end < a.start:
        return (a.start - b.end).days
    return 0


def _joins(trip: Candidate, new: Facts) -> bool:
    if not new.people <= trip.facts.people:
        return False
    after = new.start > trip.facts.end
    done = returned_home(trip.legs)
    if after and done:
        return False
    gap = _gap(trip.facts, new)
    if gap <= GAP_DAYS:
        return True
    # A trip that hasn't got back yet takes the leg that carries on from where its last one landed, however long the stay.
    landed = (trip.legs[-1][1] or "").upper() if trip.legs else ""
    return after and gap <= AWAY_DAYS and new.leg is not None and bool(landed) and (new.leg[0] or "").upper() == landed


def choose_trip(candidates: Sequence[Candidate], new: Facts) -> int | None:
    """The trip a new segment belongs to, or None for a trip of its own. It joins a trip when everyone it involves is
    already on the trip (so someone's solo trip never takes in another person's booking, and shows them nothing of it),
    and it is within GAP_DAYS of the trip, or carries on from where the trip's last leg landed (the way back from a
    stay); not once the trip has already got back home before the segment starts. The nearest such trip wins, then the
    earliest."""
    fits = [(_gap(c.facts, new), c.trip_id) for c in candidates if _joins(c, new)]
    return min(fits)[1] if fits else None


def _dates(start_local: str, end_local: str) -> tuple[date, date]:
    return date.fromisoformat(start_local[:10]), date.fromisoformat(end_local[:10])


def _involved(conn: db.Connection, trip_ids: Sequence[int]) -> tuple[list[Segment], dict[int, set[int]]]:
    """A trip's segments and, for each trip, the people on them or who booked them (called only for trips the viewer sees)."""
    segs = list(conn.orm.scalars(select(Segment).where(Segment.trip_id.in_(list(trip_ids))).order_by(Segment.id)).all())
    who: dict[int, set[int]] = {i: set() for i in trip_ids}
    by_id = {s.id: s for s in segs}
    for s in segs:
        if s.booked_by is not None:
            who[s.trip_id].add(s.booked_by)
    for t in conn.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id.in_(list(by_id)),
                                                            SegmentTraveler.person_id.is_not(None))).all():
        if t.person_id is not None:
            who[by_id[t.segment_id].trip_id].add(t.person_id)
    return segs, who


def _candidates(conn: db.Connection, viewer: Viewer) -> list[Candidate]:
    """The viewer's grouped (auto) trips that have segments, as grouping reads them."""
    trips = [t for t in visibility.visible_trips(conn, viewer) if t.auto and t.start_date and t.end_date]
    segs, who = _involved(conn, [t.id for t in trips])
    found = []
    for t in trips:
        legs = sorted((s for s in segs if s.trip_id == t.id and s.kind in ("flight", "train") and s.status != "cancelled"),
                      key=lambda s: instant(s.start_local, s.start_zone))
        people_on = set(who[t.id]) | ({t.booked_by} if t.booked_by is not None else set())
        found.append(Candidate(t.id, Facts(date.fromisoformat(t.start_date or ""), date.fromisoformat(t.end_date or ""),
                                           frozenset(people_on)), tuple((s.origin, s.destination) for s in legs)))
    return found


def _headline(conn: db.Connection, values: Mapping[str, str | None]) -> str | None:
    """Where a segment goes, for naming and describing a trip it starts: a flight's destination city, a stay's place."""
    if values["kind"] == "flight" and values["destination"]:
        known = airports.lookup(conn, values["destination"])
        return known["city"] if known else values["destination"]
    return values["destination"] or values["origin"]


def _name_for(place: str | None, start: str) -> str:
    when = f"{MONTHS[int(start[5:7]) - 1]} {start[:4]}"
    return f"Trip to {place} ({when})" if place else f"Trip ({when})"


def refresh(conn: db.Connection, trip: Trip) -> None:
    """A trip's dates are its segments' local dates (the first start's, the last end's); a trip with none keeps its own.
    Cancelled segments count only when nothing else is left."""
    segs = list(conn.orm.scalars(select(Segment).where(Segment.trip_id == trip.id)).all())
    live = [s for s in segs if s.status != "cancelled"] or segs
    if live:
        trip.start_date = min(s.start_local[:10] for s in live)
        trip.end_date = max(s.end_local[:10] for s in live)
        conn.orm.flush()


# ------------------------------------------------------------------------------------------------ changing segments

def _set_travelers(conn: db.Connection, segment_id: int, travelers: Sequence[TravelerIn]) -> None:
    conn.execute(delete(SegmentTraveler).where(SegmentTraveler.segment_id == segment_id))
    for t in travelers:
        conn.orm.add(SegmentTraveler(segment_id=segment_id, person_id=t["person_id"], name=t["name"]))
    conn.orm.flush()


def _key(t: TravelerIn) -> tuple[int, str]:
    return (t["person_id"] if t["person_id"] is not None else -1, t["name"] or "")


def _involves(travelers: Sequence[TravelerIn], booker: int | None) -> frozenset[int]:
    return frozenset({t["person_id"] for t in travelers if t["person_id"] is not None} | ({booker} if booker is not None else set()))


def _needs_person(viewer: Viewer) -> None:
    """What someone adds is theirs (they booked it), so they need a person; one without would add what no one can see."""
    if viewer.person_id is None and not viewer.household:
        raise Invalid("Your sign-in has no person in People yet, so what you add couldn’t be shown to you. Sign in again.")


def add_segment(conn: db.Connection, viewer: Viewer, fields: SegmentIn, trip_id: int | None = None,
                source: Literal["manual", "email", "import"] = "manual") -> SegmentOut | None:
    """Add a segment the viewer booked, to this trip, or (without one) to the trip it belongs to or a new one. Travellers
    default to the viewer. `source`: where it came from (a scanned email, or the person). None: no such trip (for the
    viewer). Raises Invalid."""
    _needs_person(viewer)
    values = check(conn, fields)
    given = fields.get("travelers")
    travelers = _travelers(conn, given if given is not None else
                           ([{"person_id": viewer.person_id, "name": None}] if viewer.person_id is not None else []))
    trip: Trip | None
    if trip_id is not None:
        trip = visibility.visible_trip(conn, viewer, trip_id)
        if trip is None:
            return None
    else:
        first, last = _dates(values["start_local"] or "", values["end_local"] or "")
        leg = (values["origin"], values["destination"]) if values["kind"] in ("flight", "train") else None
        found = choose_trip(_candidates(conn, viewer), Facts(first, last, _involves(travelers, viewer.person_id), leg))
        trip = visibility.visible_trip(conn, viewer, found) if found is not None else None
        if trip is None:
            place = _headline(conn, values)
            trip = Trip(name=_name_for(place, values["start_local"] or ""), destination=place, auto=True,
                        booked_by=viewer.person_id)
            conn.orm.add(trip)
            conn.orm.flush()
    seg = Segment(**values, trip_id=trip.id, source=source, booked_by=viewer.person_id, locked_fields=None,
                  check_times=bool(fields.get("check_times")))
    conn.orm.add(seg)
    conn.orm.flush()
    _set_travelers(conn, seg.id, travelers)
    refresh(conn, trip)
    return _after_change(conn, seg)


def edit_segment(conn: db.Connection, viewer: Viewer, segment_id: int, changes: SegmentIn) -> SegmentOut | None:
    """Change some of a segment's fields; the ones that end up different are locked, so an email never puts them back. A
    flight whose airport changes takes its new zone from it unless a zone is given. None: no such segment (for the viewer).
    Raises Invalid."""
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    old: list[TravelerIn] = [{"person_id": t.person_id, "name": t.name} for t in conn.orm.scalars(
        select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id).order_by(SegmentTraveler.id)).all()]
    before = _current(seg, old)
    merged: SegmentIn = {**before, **changes}
    if untimed(before.get("details") or {}):
        # The marker is the server's: it stays until a person gives the segment real times, whatever "details" a client sends.
        retimed = any(k in changes and changes[k] != before.get(k) for k in ("start_local", "end_local"))
        kept = {k: v for k, v in (merged.get("details") or {}).items() if k != TIME_UNKNOWN}
        merged["details"] = kept if retimed else {**kept, TIME_UNKNOWN: "yes"}
    for place, zone in (("origin", "start_zone"), ("destination", "end_zone")):
        # (only an airport gives a zone; a stay's or a rental's is the person's)
        if place in changes and zone not in changes and changes.get(place) != before.get(place) and merged.get("kind") == "flight":
            merged[zone] = None   # type: ignore[literal-required]   # the old place's zone isn't the new one's
    values = check(conn, merged)
    travelers = _travelers(conn, merged.get("travelers") or [])
    changed = [f for f in FIELDS if f in values and (decode_details(values[f]) != decode_details(seg.details) if f == "details"
                                                    else values[f] != getattr(seg, f))]
    if sorted(map(_key, travelers)) != sorted(map(_key, old)):
        changed.append("travelers")
    for k, v in values.items():
        setattr(seg, k, v)
    if "travelers" in changed:
        _set_travelers(conn, seg.id, travelers)
    if any(f in changes for f in TIME_FIELDS):
        if seg.check_times:   # (saving the times, even as they were, says they are right: a later email won't ask again)
            changed += [f for f in ("start_local", "end_local") if f not in changed]
        seg.check_times = False
    if changed:
        seg.locked_fields = json.dumps(sorted(set(decode_locked(seg.locked_fields)) | set(changed)))
    conn.orm.flush()
    trip = conn.orm.get(Trip, seg.trip_id)
    if trip:
        refresh(conn, trip)
    return _after_change(conn, seg)


EMAIL_MERGE_DAYS = 3   # an email updates a segment whose start is this many days or fewer from its own (a schedule change)


def _same_leg(seg: Segment, values: Mapping[str, str | None], details: Mapping[str, str]) -> bool:
    """Whether a stored segment is the booking's leg: the same kind and a confirmation code that both have, the same places (a
    flight's airports, a stay's hotel), a start within EMAIL_MERGE_DAYS of its own, and the same flight number when both
    have one (written any way: `flight_key`). Providers are compared after `provider_key` when both have one, except that
    two flight numbers already name the carrier. A booking with no code is never taken for another segment."""
    mine, theirs = flight_key(decode_details(seg.details).get("flight_number")), flight_key(details.get("flight_number"))
    near = abs((date.fromisoformat(seg.start_local[:10]) - date.fromisoformat((values["start_local"] or "")[:10])).days) <= EMAIL_MERGE_DAYS
    providers = bool(mine and theirs) or not seg.provider or not values["provider"] or provider_key(seg.provider) == provider_key(values["provider"])
    return (bool(values["confirmation"]) and near and seg.kind == values["kind"]
            and _code_key(seg.confirmation) == _code_key(values["confirmation"])
            and (not mine or not theirs or mine == theirs) and providers
            and _text_key(seg.origin) == _text_key(values["origin"]) and _text_key(seg.destination) == _text_key(values["destination"]))


def merge_email_segment(conn: db.Connection, viewer: Viewer, fields: SegmentIn,
                        again: bool = False) -> Literal["added", "updated", "unchanged"]:
    """Put a booking read from the viewer's mail among the household's segments: the segment of the same (kind, provider,
    confirmation, leg) takes what the email says, except the fields a person edited (`locked_fields`), whoever booked it. When
    the viewer can't see that segment's trip they are noted as having received its confirmation (`visibility.note_recipient`).
    With no such segment, a new one is added as the viewer's, grouped into a trip as `add_segment` does. A booking whose
    times moved is marked changed, one the email cancels cancelled; the people on it are added, never removed. `again`: the
    message was read again (Read bookings again), so a time that differs is the reading corrected, not the airline's change. A
    booking whose times couldn't be settled (`check_times`) is flagged, until a person edits or confirms them. Raises Invalid
    when the booking can't be a segment."""
    values = check(conn, fields)
    day = (values["start_local"] or "")[:10]
    found = [s for s in visibility.household_segments(conn, values["kind"] or "") if _same_leg(s, values, fields.get("details") or {})]
    if len(found) > 1:   # (the nearest in time, then one the viewer already sees, then the oldest)
        seen = {s.id for s in visibility.visible_segments(conn, viewer)}
        found.sort(key=lambda s: (abs((date.fromisoformat(s.start_local[:10]) - date.fromisoformat(day)).days), s.id not in seen, s.id))
    if not found:
        added = add_segment(conn, viewer, fields, source="email")
        if added is None:   # (no trip was named, so one is always found or made)
            raise Invalid("The booking couldn’t be added")
        return "added"
    seg = found[0]
    old: list[TravelerIn] = [{"person_id": t.person_id, "name": t.name} for t in conn.orm.scalars(
        select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id).order_by(SegmentTraveler.id)).all()]
    locked = decode_locked(seg.locked_fields)
    # (an email that doesn't say who runs the booking or where to manage it doesn't take what the segment has away)
    given: SegmentIn = {**fields}
    if given.get("provider") is None:
        given.pop("provider", None)
    if given.get("manage_url") is None:
        given.pop("manage_url", None)
    stored = decode_details(seg.details)
    said = {**stored, **(fields.get("details") or {})}
    if flight_key(stored.get("flight_number")) is not None and flight_key(stored.get("flight_number")) == flight_key(said.get("flight_number")):
        said["flight_number"] = stored["flight_number"]   # (the same number written another way isn't a change)
    named = given.get("provider")
    if seg.provider and named:
        code = named.strip().upper()   # (an airline given as its code, "AA", is the one the number names)
        if provider_key(seg.provider) == provider_key(named) or (len(code) <= 3 and (flight_key(said.get("flight_number")) or "").startswith(code)):
            given["provider"] = seg.provider
    incoming = unlocked({**given, "details": said}, locked)
    if "status" not in locked and incoming.get("status") != "cancelled":
        moved = any(values[f] != getattr(seg, f) for f in ("start_local", "start_zone", "end_local", "end_zone", "origin", "destination"))
        if moved and not again and "start_local" not in locked and "end_local" not in locked:
            incoming["status"] = "changed"
        else:
            incoming["status"] = cast(Status, seg.status)   # (a confirmation again changes nothing)
    merged: SegmentIn = {**_current(seg, old), **incoming}
    changed_values = check(conn, merged)
    changed = [f for f in FIELDS if f in changed_values and (decode_details(changed_values[f]) != decode_details(seg.details)
                                                            if f == "details" else changed_values[f] != getattr(seg, f))]
    for f in changed:
        setattr(seg, f, changed_values[f])
    if not set(TIME_FIELDS) & set(locked) and bool(fields.get("check_times")) != bool(seg.check_times):
        seg.check_times = bool(fields.get("check_times"))   # (times a person edited or confirmed stand as they are)
        changed.append("check_times")
    if "travelers" not in locked:
        have = {_key(t) for t in old}
        extra = [t for t in _travelers(conn, fields.get("travelers") or []) if _key(t) not in have
                 and not (t["person_id"] is None and any(o["person_id"] is None and (o["name"] or "").casefold() == (t["name"] or "").casefold()
                                                         for o in old))]
        if extra:
            _set_travelers(conn, seg.id, [*old, *extra])
            changed.append("travelers")
    conn.orm.flush()
    visibility.note_recipient(conn, viewer, seg)
    trip = conn.orm.get(Trip, seg.trip_id)
    if trip:
        refresh(conn, trip)
    return "updated" if changed else "unchanged"


def delete_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> bool:
    """Remove a segment. A grouped trip left with none goes too. False: no such segment (for the viewer)."""
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return False
    trip_id = seg.trip_id
    conn.execute(delete(Segment).where(Segment.id == seg.id))
    trip = conn.orm.get(Trip, trip_id)
    if trip:
        left = conn.orm.scalars(select(Segment.id).where(Segment.trip_id == trip_id)).first()
        if left is None and trip.auto:
            conn.execute(delete(Trip).where(Trip.id == trip_id))
        else:
            refresh(conn, trip)
    return True


# ------------------------------------------------------------------------------------------------ changing trips

def create_trip(conn: db.Connection, viewer: Viewer, fields: TripIn) -> TripOut:
    """A trip made by hand, booked by the viewer, with no segments yet."""
    _needs_person(viewer)
    start, end = fields.get("start_date"), fields.get("end_date")
    if (start is None) != (end is None):
        raise Invalid("Give both dates of a trip, or neither")
    if start and end and end < start:
        raise Invalid("A trip can’t end before it starts")
    trip = Trip(name=fields.get("name") or "", destination=fields.get("destination"), notes=fields.get("notes"),
                start_date=start, end_date=end, auto=False, booked_by=viewer.person_id)
    conn.orm.add(trip)
    conn.orm.flush()
    return _trip_outs(conn, viewer, [trip])[0]


def edit_trip(conn: db.Connection, viewer: Viewer, trip_id: int, fields: TripIn) -> TripOut | None:
    """Rename a trip, or change where it goes and its notes (its dates are its segments'). None: no such trip."""
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    if "start_date" in fields or "end_date" in fields:
        raise Invalid("A trip’s dates come from its segments")
    if "name" in fields:
        trip.name = fields["name"]
    if "destination" in fields:
        trip.destination = fields["destination"]
    if "notes" in fields:
        trip.notes = fields["notes"]
    conn.orm.flush()
    return _trip_outs(conn, viewer, [trip])[0]


def delete_trip(conn: db.Connection, viewer: Viewer, trip_id: int) -> bool:
    """Remove a trip with its segments. False: no such trip (for the viewer)."""
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return False
    conn.execute(delete(Trip).where(Trip.id == trip.id))
    return True


def merge(conn: db.Connection, viewer: Viewer, trip_id: int, other_id: int) -> TripOut | None:
    """Fold the other trip's segments into this one and remove the other: both are the viewer's, the result is a trip made by
    hand (grouping leaves it alone). Trips are visible whole, so it is refused unless the same people (travellers and
    bookers) are on both: nobody is shown a segment of a trip they aren't on. None: either trip isn't there (for the
    viewer). Raises Invalid for a trip with itself or one with different people."""
    if trip_id == other_id:
        raise Invalid("Choose another trip to merge into this one")
    trip, other = visibility.visible_trip(conn, viewer, trip_id), visibility.visible_trip(conn, viewer, other_id)
    if trip is None or other is None:
        return None
    if not viewer.household:
        _, who = _involved(conn, [trip.id, other.id])
        mine = who[trip.id] | ({trip.booked_by} if trip.booked_by is not None else set())
        theirs = who[other.id] | ({other.booked_by} if other.booked_by is not None else set())
        if mine != theirs:
            raise Invalid("These trips involve different people, and merging would show each one’s segments to people who "
                          "aren’t on it. Move a segment into the other trip by adding the missing travellers first.")
    conn.execute(update(Segment).where(Segment.trip_id == other.id).values(trip_id=trip.id))
    trip.auto = False
    trip.destination = trip.destination or other.destination
    trip.notes = trip.notes or other.notes
    trip.booked_by = trip.booked_by if trip.booked_by is not None else other.booked_by
    conn.orm.flush()
    conn.execute(delete(Trip).where(Trip.id == other.id))
    conn.orm.expire(trip)
    refresh(conn, trip)
    return _trip_outs(conn, viewer, [trip])[0]


def split(conn: db.Connection, viewer: Viewer, trip_id: int, segment_ids: Sequence[int]) -> TripOut | None:
    """Move some of a trip's segments to a new trip, booked by the viewer; both are now made by hand. None: no such trip.
    Raises Invalid unless it names some, but not all, of the trip's segments."""
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    mine = {s.id for s in visibility.visible_segments(conn, viewer, [trip.id])}
    moving = set(segment_ids)
    if not moving or not moving <= mine:
        raise Invalid("Choose segments of this trip to move to a new trip")
    if moving == mine:
        raise Invalid("Leave at least one segment in this trip")
    new = Trip(name=f"{trip.name} (split)", destination=None, auto=False, booked_by=viewer.person_id)
    conn.orm.add(new)
    conn.orm.flush()
    conn.execute(update(Segment).where(Segment.id.in_(list(moving))).values(trip_id=new.id))
    trip.auto = False
    conn.orm.flush()
    conn.orm.expire_all()
    refresh(conn, trip)
    refresh(conn, new)
    return _trip_outs(conn, viewer, [new])[0]




# ------------------------------------------------------------------------------------------------ who is this?

def unmatched(conn: db.Connection, viewer: Viewer) -> list[tuple[SegmentTraveler, SegmentOut]]:
    """The names on the viewer's segments that no person has been chosen for ("Who is this?"), each with its segment."""
    found = visibility.visible_unmatched(conn, viewer)
    segs = {s.id: s for s in visibility.visible_segments(conn, viewer, None) if s.id in {t.segment_id for t in found}}
    outs = {s["id"]: s for s in _segment_outs(conn, list(segs.values()), [])}
    return [(t, outs[t.segment_id]) for t in found if t.segment_id in outs]


def unmatched_count(conn: db.Connection, viewer: Viewer) -> int:
    """How many names on the viewer's segments wait for a person (what `unmatched` lists), without building the list."""
    return len(visibility.visible_unmatched(conn, viewer))


def name_traveler(conn: db.Connection, viewer: Viewer, traveler_id: int, person_id: int) -> int | None:
    """Say who a name on a booking is: this traveller, and every other unmatched traveller the viewer sees with the same
    printed name, become the person (a person already on the segment isn't added twice), and the printed name is kept
    as one of their aliases so later bookings match. Returns how many were set; None: there's no such traveller (for the
    viewer). Raises Invalid when the person isn't in People."""
    row = visibility.visible_traveler(conn, viewer, traveler_id)
    if row is None or row.person_id is not None:
        return None
    if person_id not in people.existing(conn, [person_id]):
        raise Invalid("Choose someone from People")
    printed = (row.name or "").strip()
    same = [t for t in visibility.visible_unmatched(conn, viewer) if people.normalize(t.name or "") == people.normalize(printed)] or [row]
    done = 0
    for t in same:
        already = conn.orm.scalars(select(SegmentTraveler.id).where(SegmentTraveler.segment_id == t.segment_id,
                                                                    SegmentTraveler.person_id == person_id)).first()
        if already is not None:
            conn.execute(delete(SegmentTraveler).where(SegmentTraveler.id == t.id))
        else:
            t.person_id = person_id
        done += 1
    conn.orm.flush()
    if printed:
        people.add_alias(conn, person_id, printed)
    return done
