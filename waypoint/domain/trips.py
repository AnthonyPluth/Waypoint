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
from . import airports, people, visibility
from .visibility import Viewer

Kind = Literal["flight", "hotel", "car", "train"]
Status = Literal["confirmed", "changed", "cancelled"]
KINDS: tuple[Kind, ...] = ("flight", "hotel", "car", "train")
STATUSES: tuple[Status, ...] = ("confirmed", "changed", "cancelled")
# What a segment's details may hold (the rest of a booking has a field of its own), each a text.
DETAIL_KEYS = ("flight_number", "terminal", "seat", "cabin", "room", "car_class", "address", "phone")
# A person's edit locks the fields it changes; these are the names a lock can have.
FIELDS = ("kind", "status", "confirmation", "provider", "start_local", "start_zone", "end_local", "end_zone", "origin",
          "destination", "details", "manage_url", "travelers")
GAP_DAYS = 2    # a segment this many days or fewer from a trip (before or after it) can belong to it
AWAY_DAYS = 60  # and one that carries on from where an unfinished trip's last leg landed (the way back), this many
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
    source: Literal["manual", "email"]
    booked_by: int | None
    locked_fields: list[str]
    travelers: list[TravelerOut]


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
    out: list[SegmentOut] = [
        {"id": s.id, "trip_id": s.trip_id, "kind": cast(Kind, s.kind), "status": cast(Status, s.status), "confirmation": s.confirmation,
         "provider": s.provider, "start_local": s.start_local, "start_zone": s.start_zone, "end_local": s.end_local,
         "end_zone": s.end_zone, "origin": s.origin, "destination": s.destination, "details": decode_details(s.details),
         "manage_url": s.manage_url, "source": cast(Literal["manual", "email"], s.source), "booked_by": s.booked_by,
         "locked_fields": decode_locked(s.locked_fields), "travelers": by_segment.get(s.id, [])} for s in segs]
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


def add_segment(conn: db.Connection, viewer: Viewer, fields: SegmentIn, trip_id: int | None = None) -> SegmentOut | None:
    """Add a segment the viewer booked, to this trip, or (without one) to the trip it belongs to or a new one. Travellers
    default to the viewer. None: no such trip (for the viewer). Raises Invalid."""
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
    seg = Segment(**values, trip_id=trip.id, source="manual", booked_by=viewer.person_id, locked_fields=None)
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
    for place, zone in (("origin", "start_zone"), ("destination", "end_zone")):
        if place in changes and zone not in changes and changes.get(place) != before.get(place):
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
    if changed:
        seg.locked_fields = json.dumps(sorted(set(decode_locked(seg.locked_fields)) | set(changed)))
    conn.orm.flush()
    trip = conn.orm.get(Trip, seg.trip_id)
    if trip:
        refresh(conn, trip)
    return _after_change(conn, seg)


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
    hand (grouping leaves it alone). Everyone on either trip now sees both's segments, as they're one trip. None: either
    trip isn't there (for the viewer). Raises Invalid for a trip with itself."""
    if trip_id == other_id:
        raise Invalid("Choose another trip to merge into this one")
    trip, other = visibility.visible_trip(conn, viewer, trip_id), visibility.visible_trip(conn, viewer, other_id)
    if trip is None or other is None:
        return None
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


