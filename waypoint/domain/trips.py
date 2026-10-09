from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, NotRequired, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select, update

from ..storage import db, stored_mail
from ..storage.models import Segment, SegmentPort, SegmentTraveler, Trip
from . import airports, links, logos, people, place_zones, visibility
from .visibility import Viewer

Kind = Literal["flight", "hotel", "car", "train", "cruise"]
Status = Literal["confirmed", "changed", "cancelled"]
KINDS: tuple[Kind, ...] = ("flight", "hotel", "car", "train", "cruise")
STATUSES: tuple[Status, ...] = ("confirmed", "changed", "cancelled")
TIME_UNKNOWN = "time_unknown"
ADDRESS_LIMIT = 300
MAX_PORTS = 40
SEAT_LIMIT = 10
DETAIL_KEYS = ("flight_number", "terminal", "seat", "seat_position", "aircraft", "cabin", "room", "car_class", "address", "phone", "ship", "deck", TIME_UNKNOWN)


def untimed(details: Mapping[str, str]) -> bool:
    return details.get(TIME_UNKNOWN) == "yes"


FIELDS = ("kind", "status", "confirmation", "provider", "start_local", "start_zone", "end_local", "end_zone", "origin",
          "destination", "details", "manage_url", "travelers", "itinerary")
TIME_FIELDS = ("start_local", "start_zone", "end_local", "end_zone")
GAP_DAYS = 2
AWAY_DAYS = 60
FLIGHT_NUMBER = re.compile(r"([A-Z0-9]{2,3}?)0*(\d{1,4}[A-Z]?)")
COMPANY_SUFFIXES = frozenset({"inc", "incorporated", "ltd", "limited", "llc", "plc", "corp", "corporation", "co", "company",
                              "gmbh", "ag", "sa", "bv"})
LOCAL_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?")
IATA = re.compile(r"[A-Za-z]{3}")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Invalid(ValueError):
    pass


class TravelerIn(TypedDict):
    person_id: int | None
    name: str | None
    seat: NotRequired[str | None]


class PortIn(TypedDict):
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None


class SegmentIn(TypedDict, total=False):
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
    itinerary: list[PortIn]
    check_times: bool


class TripIn(TypedDict, total=False):
    name: str
    destination: str | None
    notes: str | None
    start_date: str | None
    end_date: str | None


class TravelerOut(TypedDict):
    id: int
    person_id: int | None
    name: str
    seat: str | None


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
    itinerary: list[PortIn]
    logo: str | None
    logo_label: str | None
    has_email: bool
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


def flight_key(number: str | None) -> str | None:
    n = re.sub(r"[\s-]", "", number or "").upper()
    found = FLIGHT_NUMBER.fullmatch(n)
    return f"{found.group(1)}{found.group(2)}" if found else None


def provider_key(name: str | None) -> str:
    words = re.sub(r"[^\w\s]", " ", (name or "").casefold()).split()
    while len(words) > 1 and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    return " ".join(words)


def _text_key(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _code_key(code: str | None) -> str:
    return re.sub(r"\s+", "", code or "").casefold()


def flight_group_key(seg: SegmentOut) -> tuple[str, str, str, str] | None:
    number = flight_key(seg["details"].get("flight_number")) if seg["kind"] == "flight" else None
    if number is None:
        return None
    return number, seg["start_local"][:10], (seg["origin"] or "").upper(), (seg["destination"] or "").upper()


def flight_groups(segs: Sequence[SegmentOut]) -> list[list[SegmentOut]]:
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


def instant(local: str, zone: str) -> datetime:
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
    if not value or not LOCAL_TIME.fullmatch(value):
        raise Invalid(f"The {label} time must be the local time at the place, like 2026-03-01T22:15 (no time zone offset)")
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        raise Invalid(f"The {label} time isn’t a real date and time") from None
    return t.isoformat(timespec="minutes" if t.second == 0 else "seconds")


def check_itinerary(kind: str, given: Sequence[PortIn], start: tuple[str, str], end: tuple[str, str]) -> list[PortIn]:
    if not given:
        return []
    if kind != "cruise":
        raise Invalid("Only a cruise has ports of call")
    if len(given) > MAX_PORTS:
        raise Invalid(f"Add at most {MAX_PORTS} ports of call")
    kept: list[PortIn] = []
    last = instant(*start)
    for n, port in enumerate(given, 1):
        name = (port.get("name") or "").strip()
        if not name:
            raise Invalid(f"Name port {n}")
        zone = _zone(port.get("zone"), f"port {n}’s")
        arrive = _local(port["arrive_local"], f"port {n}’s arrival") if port.get("arrive_local") else None
        depart = _local(port["depart_local"], f"port {n}’s departure") if port.get("depart_local") else None
        if arrive and depart and instant(depart, zone) < instant(arrive, zone):
            raise Invalid(f"{name}: the ship can’t leave before it arrives")
        for at in (arrive, depart):
            if at is None:
                continue
            moment = instant(at, zone)
            if moment < last:
                raise Invalid(f"{name}: list the ports in the order the ship calls at them, after it sets sail")
            last = moment
        kept.append({"name": name, "zone": zone, "arrive_local": arrive, "depart_local": depart})
    if last > instant(*end):
        raise Invalid("A port of call is after the cruise ends")
    return kept


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
    if given:
        return _zone(given, label)
    known = airports.lookup(conn, code) if kind == "flight" and code else None
    return _zone(known["zone"] if known else None, label)


def _stay_zone(conn: db.Connection, fields: SegmentIn) -> str:
    if fields.get("start_zone"):
        return _zone(fields.get("start_zone"), "stay’s")
    found = place_zones.zone_for_address(conn, (fields.get("details") or {}).get("address"))
    if found is None:
        raise Invalid("Enter the time zone of the stay (Waypoint couldn’t tell it from the address, for example America/New_York)")
    return _zone(found, "stay’s")


def check(conn: db.Connection, fields: SegmentIn) -> dict[str, str | None]:
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
    if kind == "hotel":
        start_zone = end_zone = _stay_zone(conn, fields)
    else:
        start_zone = _place_zone(conn, kind, origin, fields.get("start_zone"), "start")
        end_zone = _place_zone(conn, kind, destination, fields.get("end_zone"), "end")
    start, end = _local(fields.get("start_local"), "start"), _local(fields.get("end_local"), "end")
    if instant(end, end_zone) < instant(start, start_zone):
        raise Invalid("This ends before it starts (times are compared at their own places’ zones)")
    details = fields.get("details") or {}
    if any(k not in DETAIL_KEYS for k in details):
        raise Invalid(f"Details can hold only: {', '.join(DETAIL_KEYS)}")
    if len(details.get("address", "")) > ADDRESS_LIMIT:
        details = {**details, "address": details["address"][:ADDRESS_LIMIT].rstrip()}
    return {"kind": kind, "status": status, "confirmation": fields.get("confirmation"),
            "provider": fields.get("provider"), "start_local": start, "start_zone": start_zone, "end_local": end,
            "end_zone": end_zone, "origin": origin, "destination": destination,
            "details": json.dumps(details, ensure_ascii=False) if details else None,
            "manage_url": fields.get("manage_url")}


def _span(values: Mapping[str, str | None], end: Literal["start", "end"]) -> tuple[str, str]:
    return (values[f"{end}_local"] or "", values[f"{end}_zone"] or "")


def _current(seg: Segment, travelers: list[TravelerIn], ports: list[PortIn] | None = None) -> SegmentIn:
    return {**({"itinerary": ports} if ports is not None else {}), "kind": seg.kind, "status": seg.status, "confirmation": seg.confirmation, "provider": seg.provider,
            "start_local": seg.start_local, "start_zone": seg.start_zone, "end_local": seg.end_local,
            "end_zone": seg.end_zone, "origin": seg.origin, "destination": seg.destination,
            "details": decode_details(seg.details), "manage_url": seg.manage_url, "travelers": travelers}


def unlocked(incoming: SegmentIn, locked: Iterable[str]) -> SegmentIn:
    skip = set(locked)
    return {k: v for k, v in incoming.items() if k not in skip}  # type: ignore[return-value]


def _port_in(p: SegmentPort) -> PortIn:
    return {"name": p.name, "zone": p.zone, "arrive_local": p.arrive_local, "depart_local": p.depart_local}


def ports_of(conn: db.Connection, segment_ids: Sequence[int]) -> dict[int, list[PortIn]]:
    found: dict[int, list[PortIn]] = {}
    if segment_ids:
        for p in conn.orm.scalars(select(SegmentPort).where(SegmentPort.segment_id.in_(list(segment_ids)))
                                  .order_by(SegmentPort.segment_id, SegmentPort.position)).all():
            found.setdefault(p.segment_id, []).append(_port_in(p))
    return found


def _set_ports(conn: db.Connection, segment_id: int, ports: Sequence[PortIn]) -> None:
    conn.execute(delete(SegmentPort).where(SegmentPort.segment_id == segment_id))
    for i, p in enumerate(ports):
        conn.orm.add(SegmentPort(segment_id=segment_id, position=i, name=p["name"], zone=p["zone"],
                                 arrive_local=p["arrive_local"], depart_local=p["depart_local"]))
    conn.orm.flush()


def _travelers(conn: db.Connection, given: Sequence[TravelerIn]) -> list[TravelerIn]:
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
            one: TravelerIn = {"person_id": pid, "name": name}
            if "seat" in t:
                seat = (t["seat"] or "").strip()
                if len(seat) > SEAT_LIMIT:
                    raise Invalid(f"A seat is at most {SEAT_LIMIT} characters")
                one["seat"] = seat or None
            kept.append(one)
    return kept


def _stored(rows: Sequence[SegmentTraveler]) -> list[TravelerIn]:
    return [{"person_id": t.person_id, "name": t.name, "seat": t.seat} for t in rows]


def _keep_seats(given: list[TravelerIn], old: Sequence[TravelerIn]) -> list[TravelerIn]:
    seats = {_who(t): t.get("seat") for t in old}
    return [t if "seat" in t else {**t, "seat": seats.get(_who(t))} for t in given]


def _segment_outs(conn: db.Connection, segs: Sequence[Segment], travs: Sequence[SegmentTraveler]) -> list[SegmentOut]:
    ports = ports_of(conn, [s.id for s in segs if s.kind == "cruise"])
    ids = [t.person_id for t in travs if t.person_id is not None]
    names = people.existing(conn, ids)
    by_segment: dict[int, list[TravelerOut]] = {}
    for t in travs:
        shown = names.get(t.person_id, "") if t.person_id is not None else ""
        by_segment.setdefault(t.segment_id, []).append({"id": t.id, "person_id": t.person_id, "name": shown or t.name or "", "seat": t.seat})
    def last_name(s: Segment) -> str | None:
        who = by_segment.get(s.id, [])
        return who[0]["name"].split()[-1] if who and who[0]["name"] else None

    decoded = [decode_details(s.details) for s in segs]
    brands = logos.brand_names(conn, segs, decoded)
    with_logo = logos.have(conn, brands)
    with_mail = stored_mail.with_messages(conn, [s.id for s in segs])
    out: list[SegmentOut] = [
        {"id": s.id, "trip_id": s.trip_id, "kind": cast(Kind, s.kind), "status": cast(Status, s.status), "confirmation": s.confirmation,
         "provider": s.provider, "start_local": s.start_local, "start_zone": s.start_zone, "end_local": s.end_local,
         "end_zone": s.end_zone, "origin": s.origin, "destination": s.destination, "details": details,
         "manage_url": s.manage_url, "source": cast(Literal["manual", "email", "import"], s.source), "booked_by": s.booked_by,
         "locked_fields": decode_locked(s.locked_fields), "check_times": bool(s.check_times), "travelers": by_segment.get(s.id, []),
         "itinerary": ports.get(s.id, []), "logo": f"/api/segments/{s.id}/logo" if brand and logos.key(brand) in with_logo else None,
         "logo_label": logos.chip(s.kind, s.origin, brand) if brand and logos.key(brand) in with_logo else None,
         "has_email": s.id in with_mail,
         "links": links.segment_links(s.kind, s.provider, s.confirmation, last_name(s), s.manage_url, details, s.origin)}
        for s, details, brand in zip(segs, decoded, brands, strict=True)]
    return sorted(out, key=lambda s: (instant(s["start_local"], s["start_zone"]), s["id"]))


def _trip_outs(conn: db.Connection, viewer: Viewer, trips: Sequence[Trip]) -> list[TripOut]:
    segs = visibility.visible_segments(conn, viewer, [t.id for t in trips])
    travs = visibility.visible_travelers(conn, viewer, [s.id for s in segs])
    outs = _segment_outs(conn, segs, travs)
    return [{"id": t.id, "name": t.name, "start_date": t.start_date, "end_date": t.end_date,
             "destination": t.destination, "notes": t.notes, "auto": t.auto, "booked_by": t.booked_by,
             "segments": [s for s in outs if s["trip_id"] == t.id]} for t in trips]


def listing(conn: db.Connection, viewer: Viewer) -> list[TripOut]:
    return _trip_outs(conn, viewer, visibility.visible_trips(conn, viewer))


def get(conn: db.Connection, viewer: Viewer, trip_id: int) -> TripOut | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    return _trip_outs(conn, viewer, [trip])[0] if trip else None


def get_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> SegmentOut | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    return _segment_outs(conn, [seg], visibility.visible_travelers(conn, viewer, [seg.id]))[0] if seg else None


def _after_change(conn: db.Connection, seg: Segment) -> SegmentOut:
    travs = list(conn.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id)
                                  .order_by(SegmentTraveler.id)).all())
    return _segment_outs(conn, [seg], travs)[0]


@dataclass(frozen=True)
class Facts:
    start: date
    end: date
    people: frozenset[int]
    leg: tuple[str | None, str | None] | None = None


@dataclass(frozen=True)
class Candidate:
    trip_id: int
    facts: Facts
    legs: tuple[tuple[str | None, str | None], ...]


def returned_home(legs: Sequence[tuple[str | None, str | None]]) -> bool:
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
    landed = (trip.legs[-1][1] or "").upper() if trip.legs else ""
    return after and gap <= AWAY_DAYS and new.leg is not None and bool(landed) and (new.leg[0] or "").upper() == landed


def choose_trip(candidates: Sequence[Candidate], new: Facts) -> int | None:
    fits = [(_gap(c.facts, new), c.trip_id) for c in candidates if _joins(c, new)]
    return min(fits)[1] if fits else None


def _dates(start_local: str, end_local: str) -> tuple[date, date]:
    return date.fromisoformat(start_local[:10]), date.fromisoformat(end_local[:10])


def _involved(conn: db.Connection, trip_ids: Sequence[int]) -> tuple[list[Segment], dict[int, set[int]]]:
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
    if values["kind"] == "flight" and values["destination"]:
        known = airports.lookup(conn, values["destination"])
        return known["city"] if known else values["destination"]
    return values["destination"] or values["origin"]


def _name_for(place: str | None, start: str) -> str:
    when = f"{MONTHS[int(start[5:7]) - 1]} {start[:4]}"
    return f"Trip to {place} ({when})" if place else f"Trip ({when})"


def refresh(conn: db.Connection, trip: Trip) -> None:
    segs = list(conn.orm.scalars(select(Segment).where(Segment.trip_id == trip.id)).all())
    live = [s for s in segs if s.status != "cancelled"] or segs
    if live:
        trip.start_date = min(s.start_local[:10] for s in live)
        trip.end_date = max(s.end_local[:10] for s in live)
        conn.orm.flush()


def _set_travelers(conn: db.Connection, segment_id: int, travelers: Sequence[TravelerIn]) -> None:
    conn.execute(delete(SegmentTraveler).where(SegmentTraveler.segment_id == segment_id))
    for t in travelers:
        conn.orm.add(SegmentTraveler(segment_id=segment_id, person_id=t["person_id"], name=t["name"], seat=t.get("seat")))
    conn.orm.flush()


def _who(t: TravelerIn) -> tuple[int, str]:
    if t["person_id"] is not None:
        return (t["person_id"], "")
    return (-1, (t["name"] or "").strip().casefold())


def _key(t: TravelerIn) -> tuple[int, str, str]:
    return (*_who(t), t.get("seat") or "")


def _involves(travelers: Sequence[TravelerIn], booker: int | None) -> frozenset[int]:
    return frozenset({t["person_id"] for t in travelers if t["person_id"] is not None} | ({booker} if booker is not None else set()))


def _needs_person(viewer: Viewer) -> None:
    if viewer.person_id is None and not viewer.household:
        raise Invalid("Your sign-in has no person in People yet, so what you add couldn’t be shown to you. Sign in again.")


def add_segment(conn: db.Connection, viewer: Viewer, fields: SegmentIn, trip_id: int | None = None,
                source: Literal["manual", "email", "import"] = "manual") -> SegmentOut | None:
    _needs_person(viewer)
    values = check(conn, fields)
    ports = check_itinerary(fields.get("kind") or "", fields.get("itinerary") or [], _span(values, "start"), _span(values, "end"))
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
    if ports:
        _set_ports(conn, seg.id, ports)
    refresh(conn, trip)
    return _after_change(conn, seg)


def _seats(travelers: Sequence[TravelerIn], details: Mapping[str, str]) -> set[str]:
    return {s for s in (*(t.get("seat") for t in travelers), details.get("seat")) if s}


def _stale_position(old: Mapping[str, str], new: dict[str, str], seats_changed: bool) -> dict[str, str]:
    if seats_changed and "seat_position" in new and new["seat_position"] == old.get("seat_position"):
        return {k: v for k, v in new.items() if k != "seat_position"}
    return new


def edit_segment(conn: db.Connection, viewer: Viewer, segment_id: int, changes: SegmentIn) -> SegmentOut | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    old: list[TravelerIn] = _stored(conn.orm.scalars(
        select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id).order_by(SegmentTraveler.id)).all())
    ports_before = ports_of(conn, [seg.id]).get(seg.id, [])
    before = _current(seg, old, ports_before)
    merged: SegmentIn = {**before, **changes}
    if untimed(before.get("details") or {}):
        retimed = any(k in changes and changes[k] != before.get(k) for k in ("start_local", "end_local"))
        kept = {k: v for k, v in (merged.get("details") or {}).items() if k != TIME_UNKNOWN}
        merged["details"] = kept if retimed else {**kept, TIME_UNKNOWN: "yes"}
    if merged.get("kind") != "cruise" and "itinerary" not in changes:
        merged["itinerary"] = []
    for place, zone in (("origin", "start_zone"), ("destination", "end_zone")):
        if place in changes and zone not in changes and changes.get(place) != before.get(place) and merged.get("kind") == "flight":
            merged[zone] = None   # type: ignore[literal-required]
    values = check(conn, merged)
    ports = check_itinerary(merged.get("kind") or "", merged.get("itinerary") or [], _span(values, "start"), _span(values, "end"))
    travelers = _keep_seats(_travelers(conn, merged.get("travelers") or []), old)
    new_details = decode_details(values["details"])
    kept_details = _stale_position(decode_details(seg.details), new_details,
                                   _seats(old, decode_details(seg.details)) != _seats(travelers, new_details))
    if kept_details != new_details:
        values["details"] = json.dumps(kept_details, ensure_ascii=False) if kept_details else None
    changed = [f for f in FIELDS if f in values and (decode_details(values[f]) != decode_details(seg.details) if f == "details"
                                                    else values[f] != getattr(seg, f))]
    if sorted(map(_key, travelers)) != sorted(map(_key, old)):
        changed.append("travelers")
    if ports != ports_before:
        changed.append("itinerary")
    for k, v in values.items():
        setattr(seg, k, v)
    if "itinerary" in changed:
        _set_ports(conn, seg.id, ports)
    if "travelers" in changed:
        _set_travelers(conn, seg.id, travelers)
    if any(f in changes for f in TIME_FIELDS):
        if seg.check_times:
            changed += [f for f in ("start_local", "end_local") if f not in changed]
        seg.check_times = False
    if changed:
        seg.locked_fields = json.dumps(sorted(set(decode_locked(seg.locked_fields)) | set(changed)))
    conn.orm.flush()
    trip = conn.orm.get(Trip, seg.trip_id)
    if trip:
        refresh(conn, trip)
    return _after_change(conn, seg)


EMAIL_MERGE_DAYS = 3


PLACE_FILLER = frozenset({"the", "a", "hotel", "hotels", "inn", "resort", "suites", "and"})


def _place_words(text: str | None) -> frozenset[str]:
    return frozenset(w for w in re.sub(r"[^\w\s]", " ", (text or "").casefold()).split() if w not in PLACE_FILLER)


def _same_place(mine: str | None, theirs: str | None) -> bool:
    words = _place_words(mine)
    return bool(words) and words == _place_words(theirs)


def _same_uncoded(seg: Segment, values: Mapping[str, str | None], details: Mapping[str, str]) -> bool:
    if seg.kind != values["kind"] or not values["confirmation"] or seg.start_local[:10] != (values["start_local"] or "")[:10]:
        return False
    if seg.kind == "flight":
        mine, theirs = flight_key(decode_details(seg.details).get("flight_number")), flight_key(details.get("flight_number"))
        return (mine is not None and mine == theirs and _text_key(seg.origin) == _text_key(values["origin"])
                and _text_key(seg.destination) == _text_key(values["destination"]))
    return (seg.end_local[:10] == (values["end_local"] or "")[:10] and seg.start_zone == values["start_zone"]
            and _same_place(seg.origin, values["origin"]))


def _same_leg(seg: Segment, values: Mapping[str, str | None], details: Mapping[str, str]) -> bool:
    if not seg.confirmation:
        return _same_uncoded(seg, values, details)
    mine, theirs = flight_key(decode_details(seg.details).get("flight_number")), flight_key(details.get("flight_number"))
    near = abs((date.fromisoformat(seg.start_local[:10]) - date.fromisoformat((values["start_local"] or "")[:10])).days) <= EMAIL_MERGE_DAYS
    providers = bool(mine and theirs) or not seg.provider or not values["provider"] or provider_key(seg.provider) == provider_key(values["provider"])
    return (bool(values["confirmation"]) and near and seg.kind == values["kind"]
            and _code_key(seg.confirmation) == _code_key(values["confirmation"])
            and (not mine or not theirs or mine == theirs) and providers
            and _text_key(seg.origin) == _text_key(values["origin"]) and _text_key(seg.destination) == _text_key(values["destination"]))


def merge_email_segment(conn: db.Connection, viewer: Viewer, fields: SegmentIn, again: bool = False,
                        touched: list[int] | None = None, fill_only: bool = False, candidates: list[int] | None = None,
                        into: int | None = None) -> Literal["added", "updated", "unchanged", "ambiguous"]:
    values = check(conn, fields)
    day = (values["start_local"] or "")[:10]
    if into is not None:
        target = visibility.visible_segment(conn, viewer, into)
        if target is None:
            raise Invalid("No such booking")
        found, seen = [target], {target.id}
    else:
        found = [s for s in visibility.household_segments(conn, values["kind"] or "") if _same_leg(s, values, fields.get("details") or {})]
        coded = [s for s in found if s.confirmation]
        uncoded = [s for s in found if not s.confirmation]
        seen = {s.id for s in visibility.visible_segments(conn, viewer)} if found else set()
        uncoded = [s for s in uncoded if s.id in seen]
        if candidates is not None and not coded and len(uncoded) > 1:
            candidates.extend(s.id for s in uncoded)
            return "ambiguous"
        found = coded or (uncoded if len(uncoded) == 1 else [])
    if len(found) > 1:
        found.sort(key=lambda s: (abs((date.fromisoformat(s.start_local[:10]) - date.fromisoformat(day)).days), s.id not in seen, s.id))
    if not found:
        added = add_segment(conn, viewer, fields, source="email")
        if added is None:
            raise Invalid("The booking couldn’t be added")
        if touched is not None:
            touched.append(added["id"])
        return "added"
    seg = found[0]
    if touched is not None:
        touched.append(seg.id)
    old: list[TravelerIn] = _stored(conn.orm.scalars(
        select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id).order_by(SegmentTraveler.id)).all())
    locked = decode_locked(seg.locked_fields)
    given: SegmentIn = {**fields}
    if given.get("provider") is None:
        given.pop("provider", None)
    if given.get("manage_url") is None:
        given.pop("manage_url", None)
    stored = decode_details(seg.details)
    said = {**(fields.get("details") or {}), **stored} if fill_only else {**stored, **(fields.get("details") or {})}
    if flight_key(stored.get("flight_number")) is not None and flight_key(stored.get("flight_number")) == flight_key(said.get("flight_number")):
        said["flight_number"] = stored["flight_number"]
    named = given.get("provider")
    if seg.provider and named:
        code = named.strip().upper()
        if provider_key(seg.provider) == provider_key(named) or (len(code) <= 3 and (flight_key(said.get("flight_number")) or "").startswith(code)):
            given["provider"] = seg.provider
    if "seat_position" not in (fields.get("details") or {}):
        said = _stale_position(stored, said, bool(stored.get("seat")) and said.get("seat") != stored.get("seat"))
    incoming = unlocked({**given, "details": said}, locked)
    if fill_only:
        incoming = cast(SegmentIn, {k: v for k, v in incoming.items() if k == "details" or (k in ("provider", "confirmation", "manage_url") and not getattr(seg, k))})
    if not fill_only and "status" not in locked and incoming.get("status") != "cancelled":
        moved = any(values[f] != getattr(seg, f) for f in ("start_local", "start_zone", "end_local", "end_zone", "origin", "destination"))
        if moved and not again and "start_local" not in locked and "end_local" not in locked:
            incoming["status"] = "changed"
        else:
            incoming["status"] = cast(Status, seg.status)
    merged: SegmentIn = {**_current(seg, old), **incoming}
    changed_values = check(conn, merged)
    changed = [f for f in FIELDS if f in changed_values and (decode_details(changed_values[f]) != decode_details(seg.details)
                                                            if f == "details" else changed_values[f] != getattr(seg, f))]
    new_ports: list[PortIn] | None = None
    if fields.get("itinerary") and "itinerary" not in locked and not ports_of(conn, [seg.id]).get(seg.id):
        try:
            new_ports = check_itinerary(values["kind"] or "", fields["itinerary"], _span(changed_values, "start"), _span(changed_values, "end"))
        except Invalid:
            new_ports = None
    for f in changed:
        setattr(seg, f, changed_values[f])
    if new_ports:
        _set_ports(conn, seg.id, new_ports)
        changed.append("itinerary")
    if not fill_only and not set(TIME_FIELDS) & set(locked) and bool(fields.get("check_times")) != bool(seg.check_times):
        seg.check_times = bool(fields.get("check_times"))
        changed.append("check_times")
    if "travelers" not in locked:
        have = {_who(t) for t in old}
        extra = [t for t in _travelers(conn, fields.get("travelers") or []) if _who(t) not in have
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


def emails_of(conn: db.Connection, viewer: Viewer, segment_id: int) -> list[stored_mail.Content] | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    return None if seg is None else stored_mail.for_segment(conn, seg.id)


def delete_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> bool:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return False
    trip_id = seg.trip_id
    conn.execute(delete(Segment).where(Segment.id == seg.id))
    stored_mail.prune(conn)
    trip = conn.orm.get(Trip, trip_id)
    if trip:
        left = conn.orm.scalars(select(Segment.id).where(Segment.trip_id == trip_id)).first()
        if left is None and trip.auto:
            conn.execute(delete(Trip).where(Trip.id == trip_id))
        else:
            refresh(conn, trip)
    return True


def create_trip(conn: db.Connection, viewer: Viewer, fields: TripIn) -> TripOut:
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
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return False
    conn.execute(delete(Trip).where(Trip.id == trip.id))
    stored_mail.prune(conn)
    return True


def merge(conn: db.Connection, viewer: Viewer, trip_id: int, other_id: int) -> TripOut | None:
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


def unmatched(conn: db.Connection, viewer: Viewer) -> list[tuple[SegmentTraveler, SegmentOut]]:
    found = visibility.visible_unmatched(conn, viewer)
    segs = {s.id: s for s in visibility.visible_segments(conn, viewer, None) if s.id in {t.segment_id for t in found}}
    outs = {s["id"]: s for s in _segment_outs(conn, list(segs.values()), [])}
    return [(t, outs[t.segment_id]) for t in found if t.segment_id in outs]


def unmatched_count(conn: db.Connection, viewer: Viewer) -> int:
    return len(visibility.visible_unmatched(conn, viewer))


def name_traveler(conn: db.Connection, viewer: Viewer, traveler_id: int, person_id: int) -> int | None:
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
