from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, NotRequired, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select, update

from .. import dates
from ..storage import db, geocode, stored_mail
from ..storage.models import Segment, SegmentPort, SegmentRecipient, SegmentTraveler, Trip
from . import airports, links, logos, money, people, place_zones, regions, trippeople, visibility
from .visibility import Viewer

Kind = Literal["flight", "hotel", "car", "train", "cruise", "parking"]
Status = Literal["confirmed", "changed", "cancelled"]
SHARED_KINDS = frozenset({"hotel", "car", "parking"})
KINDS: tuple[Kind, ...] = ("flight", "hotel", "car", "train", "cruise", "parking")
STATUSES: tuple[Status, ...] = ("confirmed", "changed", "cancelled")
TIME_UNKNOWN = "time_unknown"
ADDRESS_LIMIT = 300
EMAILS_CLEARABLE_AFTER_DAYS = 7
MAX_PORTS = 40
SEAT_LIMIT = 10
DETAIL_KEYS = ("flight_number", "terminal", "seat", "seat_position", "aircraft", "cabin", "room", "car_class", "address", "phone", "ship", "deck", "space_type", "vehicle", "notes", TIME_UNKNOWN)


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


class NamedPerson(TypedDict):
    id: int
    name: str


class NeedsConfirmation(Invalid):
    def __init__(self, message: str, see_booking: list[NamedPerson], see_trip: list[NamedPerson]):
        super().__init__(message)
        self.see_booking = see_booking
        self.see_trip = see_trip


class TravelerIn(TypedDict):
    person_id: int | None
    name: str | None
    seat: NotRequired[str | None]


class PortIn(TypedDict):
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None


class PriceIn(TypedDict):
    amount_minor: int
    currency: str


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
    price: PriceIn | None


class TripIn(TypedDict, total=False):
    name: str
    destination: str | None
    notes: str | None
    start_date: str | None
    end_date: str | None
    people: list[int]


class TravelerOut(TypedDict):
    id: int
    person_id: int | None
    name: str
    seat: str | None


class CruiseStop(TypedDict):
    name: str
    zone: str
    arrive_local: str | None
    depart_local: str | None
    recorded: bool


class CruiseDay(TypedDict):
    day: int
    date: str
    sea: bool
    stops: list[CruiseStop]


class PriceOut(TypedDict):
    amount_minor: int
    currency: str
    source: Literal["email", "manual"]


class CostTotal(TypedDict):
    currency: str
    amount_minor: int


class CostsOut(TypedDict):
    totals: list[CostTotal]
    priced: int
    bookings: int


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
    days: list[CruiseDay]
    logo: str | None
    logo_label: str | None
    hotel_brand: str | None
    has_email: bool
    price: PriceOut | None
    links: links.Links


class TripOut(TypedDict):
    id: int
    name: str
    start_date: str | None
    end_date: str | None
    destination: str | None
    destination_manual: bool
    notes: str | None
    auto: bool
    booked_by: int | None
    emails: int
    can_clear_emails: bool
    people: list[int]
    costs: CostsOut
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


def port_days(port: PortIn) -> set[date]:
    days = [date.fromisoformat(t[:10]) for t in (port["arrive_local"], port["depart_local"]) if t]
    return {days[0] + timedelta(days=i) for i in range((max(days) - min(days)).days + 1)} if days else set()


def _stop(port: PortIn, day: date) -> CruiseStop:
    on = {k: v if v and date.fromisoformat(v[:10]) == day else None for k, v in (("arrive_local", port["arrive_local"]), ("depart_local", port["depart_local"]))}
    return {"name": port["name"], "zone": port["zone"], "arrive_local": on["arrive_local"], "depart_local": on["depart_local"],
            "recorded": bool(port["arrive_local"] or port["depart_local"])}


def cruise_days(start_local: str, start_zone: str, end_local: str, end_zone: str, origin: str | None, destination: str | None,
                ports: Sequence[PortIn]) -> list[CruiseDay]:
    if not ports:
        return []
    first, last = date.fromisoformat(start_local[:10]), date.fromisoformat(end_local[:10])
    stops: dict[date, list[CruiseStop]] = {first + timedelta(days=i): [] for i in range((last - first).days + 1)}
    stops[first].append({"name": origin or "Embarkation", "zone": start_zone, "arrive_local": None, "depart_local": start_local, "recorded": True})
    anchor = first
    for port in ports:
        days = sorted(d for d in port_days(port) if d in stops)
        for d in days or [anchor]:
            stops[d].append(_stop(port, d))
        anchor = days[-1] if days else anchor
    if last != first:
        stops[last].append({"name": destination or "Disembarkation", "zone": end_zone, "arrive_local": end_local, "depart_local": None, "recorded": True})
    return [{"day": n, "date": d.isoformat(), "sea": not stops[d], "stops": stops[d]} for n, d in enumerate(sorted(stops), 1)]


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


AIRPORT_KINDS = ("flight", "car", "train")


def _airport(conn: db.Connection, code: str | None) -> airports.Found | None:
    return airports.lookup(conn, code) if code and IATA.fullmatch(code.strip()) else None


def _place_zone(conn: db.Connection, kind: str, code: str | None, given: str | None, label: str, address: str | None = None) -> str:
    if given:
        return _zone(given, label)
    known = _airport(conn, code) if kind in AIRPORT_KINDS else None
    if known:
        return _zone(known["zone"], label)
    return _zone(place_zones.zone_for_address(conn, address) if kind == "car" else None, label)


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
    if kind in ("hotel", "parking"):
        start_zone = end_zone = _stay_zone(conn, fields)
        if kind == "parking" and fields.get("end_zone"):
            end_zone = _zone(fields["end_zone"], "exit")
    else:
        address = (fields.get("details") or {}).get("address")
        start_zone = _place_zone(conn, kind, origin, fields.get("start_zone"), "start", address)
        end_zone = _place_zone(conn, kind, destination, fields.get("end_zone") or (start_zone if kind in ("car", "train") and not _airport(conn, destination) else None), "end")
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


def located(values: Mapping[str, str | None]) -> dict[str, float | str | None]:
    point = geocode.locate(values["kind"] or "", values["origin"], values["destination"], decode_details(values["details"]).get("address"))
    return {"latitude": point.latitude if point else None, "longitude": point.longitude if point else None,
            "geo_precision": point.precision if point else None}


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


def priced(seg: Segment) -> PriceOut | None:
    if seg.price_minor is None or seg.price_currency is None or seg.price_source not in ("email", "manual"):
        return None
    return {"amount_minor": seg.price_minor, "currency": seg.price_currency, "source": cast(Literal["email", "manual"], seg.price_source)}


def costs_of(segs: Sequence[SegmentOut]) -> CostsOut:
    live = [s for s in segs if s["status"] != "cancelled"]
    units: dict[str, bool] = {}
    sums: dict[str, int] = {}
    counts: dict[str, int] = {}
    for s in live:
        unit = f"{provider_key(s['provider'])}|{_code_key(s['confirmation'])}" if s["confirmation"] else f"#{s['id']}"
        units[unit] = units.get(unit, False) or s["price"] is not None
        if s["price"] is not None:
            code = s["price"]["currency"]
            sums[code] = sums.get(code, 0) + s["price"]["amount_minor"]
            counts[code] = counts.get(code, 0) + 1
    totals: list[CostTotal] = [{"currency": c, "amount_minor": sums[c]} for c in sorted(sums, key=lambda c: (-counts[c], c))]
    return {"totals": totals, "priced": sum(units.values()), "bookings": len(units)}


def check_price(given: PriceIn | None) -> PriceIn | None:
    if given is None:
        return None
    if not money.valid(given.get("amount_minor"), given.get("currency")):
        raise Invalid("The cost needs an amount and a three-letter currency code like USD")
    return {"amount_minor": given["amount_minor"], "currency": given["currency"]}


def email_price(given: PriceIn | None) -> PriceIn | None:
    return given if given is not None and money.valid(given.get("amount_minor"), given.get("currency")) else None


def set_price(seg: Segment, given: PriceIn | None, source: Literal["email", "manual"]) -> bool:
    now = None if seg.price_minor is None else (seg.price_minor, seg.price_currency)
    if given is None:
        seg.price_minor = seg.price_currency = seg.price_source = None
        return now is not None
    if now == (given["amount_minor"], given["currency"]):
        return False
    seg.price_minor, seg.price_currency, seg.price_source = given["amount_minor"], given["currency"], source
    return True


def fill_price(seg: Segment, given: PriceIn | None) -> bool:
    found = email_price(given)
    return found is not None and seg.price_minor is None and set_price(seg, found, "email")


def _segment_outs(conn: db.Connection, segs: Sequence[Segment], travs: Sequence[SegmentTraveler],
                  viewer: Viewer | None = None) -> list[SegmentOut]:
    ports = ports_of(conn, [s.id for s in segs if s.kind == "cruise"])
    shared = trippeople.of(conn, {s.trip_id for s in segs if s.travelers_from_trip})
    own = {s.id for s in segs if not s.travelers_from_trip}
    ids = [t.person_id for t in travs if t.person_id is not None and t.segment_id in own] + [p for ps in shared.values() for p in ps]
    names = people.existing(conn, ids)
    by_segment: dict[int, list[TravelerOut]] = {}
    for t in travs:
        if t.segment_id in own:
            shown = names.get(t.person_id, "") if t.person_id is not None else ""
            by_segment.setdefault(t.segment_id, []).append({"id": t.id, "person_id": t.person_id, "name": shown or t.name or "", "seat": t.seat})
    for s in segs:
        if s.travelers_from_trip:
            by_segment[s.id] = [{"id": 0, "person_id": p, "name": names.get(p, ""), "seat": None} for p in shared[s.trip_id]]
    def last_name(s: Segment) -> str | None:
        who = [(t["person_id"], t["name"]) for t in by_segment.get(s.id, [])]
        return links.last_name(who, viewer.person_id if viewer else None)

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
         "itinerary": ports.get(s.id, []),
         "days": cruise_days(s.start_local, s.start_zone, s.end_local, s.end_zone, s.origin, s.destination, ports.get(s.id, [])),
         "logo": f"/api/segments/{s.id}/logo" if brand and logos.key(brand) in with_logo else None,
         "logo_label": logos.chip(s.kind, s.origin, brand) if brand and logos.key(brand) in with_logo else None,
         "hotel_brand": logos.sub_brand(s.origin) if s.kind == "hotel" else None,
         "has_email": s.id in with_mail,
         "price": priced(s),
         "links": links.segment_links(s.kind, s.provider, s.confirmation, last_name(s), s.manage_url, details, s.origin)}
        for s, details, brand in zip(segs, decoded, brands, strict=True)]
    return sorted(out, key=lambda s: (instant(s["start_local"], s["start_zone"]), s["id"]))


def _trip_outs(conn: db.Connection, viewer: Viewer, trips: Sequence[Trip], today: date | None = None) -> list[TripOut]:
    segs = visibility.visible_segments(conn, viewer, [t.id for t in trips])
    travs = visibility.visible_travelers(conn, viewer, [s.id for s in segs])
    outs = _segment_outs(conn, segs, travs, viewer)
    aboard = trippeople.of(conn, [t.id for t in trips])
    day = today or date.today()
    by_trip: dict[int, list[int]] = {t.id: [] for t in trips}
    for s in segs:
        by_trip[s.trip_id].append(s.id)
    removable = stored_mail.deletable_by_group(conn, by_trip)
    def emails_of_trip(trip: Trip) -> int:
        return len(removable[trip.id])
    return [{"id": t.id, "name": t.name, "start_date": t.start_date, "end_date": t.end_date,
             "destination": t.destination, "destination_manual": t.destination_manual, "notes": t.notes, "auto": t.auto, "booked_by": t.booked_by,
             "emails": (n := emails_of_trip(t)), "can_clear_emails": n > 0 and emails_clearable(t, day),
             "people": aboard[t.id], "costs": costs_of(mine := [s for s in outs if s["trip_id"] == t.id]), "segments": mine} for t in trips]


def emails_clearable(trip: Trip, today: date) -> bool:
    return trip.end_date is not None and (today - dates.parse_day(trip.end_date)).days >= EMAILS_CLEARABLE_AFTER_DAYS


def listing(conn: db.Connection, viewer: Viewer) -> list[TripOut]:
    return _trip_outs(conn, viewer, visibility.visible_trips(conn, viewer))


def get(conn: db.Connection, viewer: Viewer, trip_id: int) -> TripOut | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    return _trip_outs(conn, viewer, [trip])[0] if trip else None


def get_segment(conn: db.Connection, viewer: Viewer, segment_id: int) -> SegmentOut | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    return _segment_outs(conn, [seg], visibility.visible_travelers(conn, viewer, [seg.id]), viewer)[0] if seg else None


def _after_change(conn: db.Connection, seg: Segment, viewer: Viewer) -> SegmentOut:
    travs = list(conn.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id)
                                  .order_by(SegmentTraveler.id)).all())
    return _segment_outs(conn, [seg], travs, viewer)[0]


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
    for trip_id, aboard in trippeople.of(conn, trip_ids).items():
        who[trip_id].update(aboard)
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


def _region(conn: db.Connection, seg: Segment) -> str | None:
    address = decode_details(seg.details).get("address")
    if seg.kind in ("flight", "train"):
        return regions.of_place(conn, seg.destination)
    if seg.kind in ("hotel", "parking"):
        return regions.of_address(conn, address) or regions.of_place(conn, seg.destination)
    if seg.kind == "car":
        return regions.of_address(conn, address) or regions.of_place(conn, seg.origin, fallback=False)
    return regions.of_place(conn, seg.origin)


def _in_order(segs: Sequence[Segment]) -> list[Segment]:
    live = [s for s in segs if s.status != "cancelled"] or list(segs)
    return sorted(live, key=lambda s: (instant(s.start_local, s.start_zone), s.id))


def auto_destination(conn: db.Connection, segs: Sequence[Segment]) -> str | None:
    ordered = _in_order(segs)
    if not ordered:
        return None
    leaving = next((s for s in ordered if s.kind in ("flight", "train") and s.origin), None)
    home = regions.of_place(conn, leaving.origin) if leaving else None
    named = regions.phrase([r for s in ordered if (r := _region(conn, s))], home)
    first = ordered[0]
    return named or _headline(conn, {"kind": first.kind, "origin": first.origin, "destination": first.destination})


def destination_facts(conn: db.Connection, viewer: Viewer, trip_id: int) -> regions.Facts | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    stops: list[regions.Stop] = []
    for seg in _in_order(visibility.visible_segments(conn, viewer, [trip.id])):
        region = _region(conn, seg)
        if not region:
            continue
        city = airports.lookup(conn, seg.destination or "") if seg.kind == "flight" else None
        place = f"{city['city']}, {region}" if city and city["city"] != region else region
        if {"kind": seg.kind, "place": place} not in stops:
            stops.append({"kind": seg.kind, "place": place})
    return {"name": trip.name, "stops": stops}


def refresh(conn: db.Connection, trip: Trip) -> None:
    segs = list(conn.orm.scalars(select(Segment).where(Segment.trip_id == trip.id)).all())
    live = [s for s in segs if s.status != "cancelled"] or segs
    if live:
        trip.start_date = min(s.start_local[:10] for s in live)
        trip.end_date = max(s.end_local[:10] for s in live)
    if not trip.destination_manual:
        trip.destination = auto_destination(conn, segs)
    conn.orm.flush()


def _set_travelers(conn: db.Connection, segment_id: int, travelers: Sequence[TravelerIn]) -> None:
    conn.execute(delete(SegmentTraveler).where(SegmentTraveler.segment_id == segment_id))
    for t in travelers:
        conn.orm.add(SegmentTraveler(segment_id=segment_id, person_id=t["person_id"], name=t["name"], seat=t.get("seat")))
    seg = conn.orm.get(Segment, segment_id)
    if seg is not None:
        seg.travelers_from_trip = False
    conn.orm.flush()


def effective_travelers(conn: db.Connection, seg: Segment) -> list[TravelerIn]:
    if seg.travelers_from_trip:
        return [{"person_id": p, "name": None, "seat": None} for p in trippeople.of(conn, [seg.trip_id])[seg.trip_id]]
    return _stored(conn.orm.scalars(select(SegmentTraveler).where(SegmentTraveler.segment_id == seg.id).order_by(SegmentTraveler.id)).all())


def _freeze(conn: db.Connection, seg: Segment, person_ids: Sequence[int]) -> None:
    _set_travelers(conn, seg.id, [{"person_id": p, "name": None, "seat": None} for p in person_ids])


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
    cost = email_price(fields.get("price")) if source == "email" else check_price(fields.get("price"))
    ports = check_itinerary(fields.get("kind") or "", fields.get("itinerary") or [], _span(values, "start"), _span(values, "end"))
    given = None if source != "email" and values["kind"] in SHARED_KINDS else fields.get("travelers")
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
    named = [t["person_id"] for t in travelers if t["person_id"] is not None]
    for_everyone = (values["kind"] in SHARED_KINDS
                    and set(named) <= _seen_by_bookings(conn, trip) | {viewer.person_id})
    seg = Segment(**values, **located(values), trip_id=trip.id, source=source, booked_by=viewer.person_id, locked_fields=None,
                  check_times=bool(fields.get("check_times")))
    set_price(seg, cost, "email" if source == "email" else "manual")
    conn.orm.add(seg)
    conn.orm.flush()
    if for_everyone:
        seg.travelers_from_trip = True
        trippeople.add(conn, trip.id, named)
    else:
        _set_travelers(conn, seg.id, travelers)
    trippeople.keep_lists_inside(conn, trip.id)
    if ports:
        _set_ports(conn, seg.id, ports)
    refresh(conn, trip)
    return _after_change(conn, seg, viewer)


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
    old = effective_travelers(conn, seg)
    ports_before = ports_of(conn, [seg.id]).get(seg.id, [])
    before = _current(seg, old, ports_before)
    merged: SegmentIn = {**before, **changes}
    if untimed(before.get("details") or {}):
        retimed = any(k in changes and changes[k] != before.get(k) for k in ("start_local", "end_local"))
        kept = {k: v for k, v in (merged.get("details") or {}).items() if k != TIME_UNKNOWN}
        merged["details"] = kept if retimed else {**kept, TIME_UNKNOWN: "yes"}
    if seg.travelers_from_trip and merged.get("kind") in SHARED_KINDS:
        merged["travelers"] = before.get("travelers") or []
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
    owner = conn.orm.get(Trip, seg.trip_id)
    becomes_shared = (owner is not None and not seg.travelers_from_trip and seg.kind not in SHARED_KINDS and values["kind"] in SHARED_KINDS
                      and {t["person_id"] for t in old if t["person_id"] is not None} <= _seen_by_bookings(conn, owner, seg.id))
    if sorted(map(_key, travelers)) != sorted(map(_key, old)) or (seg.travelers_from_trip and values["kind"] not in SHARED_KINDS):
        changed.append("travelers")
    if ports != ports_before:
        changed.append("itinerary")
    for k, v in {**values, **located(values)}.items():
        setattr(seg, k, v)
    if "itinerary" in changed:
        _set_ports(conn, seg.id, ports)
    if "travelers" in changed or becomes_shared:
        _set_travelers(conn, seg.id, [] if becomes_shared else travelers)
        seg.travelers_from_trip = becomes_shared
        trippeople.keep_lists_inside(conn, seg.trip_id)
    if "price" in changes:
        set_price(seg, check_price(changes["price"]), "manual")
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
    return _after_change(conn, seg, viewer)


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


def _minute(local: str | None) -> str:
    return (local or "")[:16]


def same_booking(seg: Segment, values: Mapping[str, str | None], details: Mapping[str, str]) -> bool:
    if seg.kind != values["kind"] or seg.status != "confirmed" or values["status"] != "confirmed":
        return False
    if not seg.confirmation or not values["confirmation"] or _code_key(seg.confirmation) != _code_key(values["confirmation"]):
        return False
    mine, theirs = flight_key(decode_details(seg.details).get("flight_number")), flight_key(details.get("flight_number"))
    same_flight = seg.kind == "flight" and mine is not None and mine == theirs
    if seg.kind == "flight" and mine is not None and theirs is not None and mine != theirs:
        return False
    named = bool(seg.provider and values["provider"]) and provider_key(seg.provider) == provider_key(values["provider"])
    if not (same_flight or named):
        return False
    if (_minute(seg.start_local) != _minute(values["start_local"]) or seg.start_zone != values["start_zone"]
            or _text_key(seg.destination) != _text_key(values["destination"])):
        return False
    if seg.kind == "flight":
        return _text_key(seg.origin) == _text_key(values["origin"])
    return (_minute(seg.end_local) == _minute(values["end_local"]) and seg.end_zone == values["end_zone"]
            and (_text_key(seg.origin) == _text_key(values["origin"]) or _same_place(seg.origin, values["origin"])))


def find_same_booking(conn: db.Connection, viewer: Viewer, fields: SegmentIn) -> Segment | None:
    values = check(conn, fields)
    details = fields.get("details") or {}
    return next((s for s in visibility.visible_segments(conn, viewer) if same_booking(s, values, details)), None)


def attach_to_same_booking(conn: db.Connection, viewer: Viewer, fields: SegmentIn, touched: list[int] | None = None) -> bool:
    found = find_same_booking(conn, viewer, fields)
    if found is None:
        return False
    merge_email_segment(conn, viewer, fields, touched=touched, fill_only=True, into=found.id)
    return True


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
    old = effective_travelers(conn, seg)
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
    for f, v in located(changed_values).items():
        setattr(seg, f, v)
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
            trippeople.keep_lists_inside(conn, seg.trip_id)
            changed.append("travelers")
    wanted = email_price(fields.get("price"))
    if wanted is not None and (seg.price_minor is None or (seg.price_source == "email" and not fill_only)) and set_price(seg, wanted, "email"):
        changed.append("price")
    conn.orm.flush()
    visibility.note_recipient(conn, viewer, seg)
    trip = conn.orm.get(Trip, seg.trip_id)
    if trip:
        refresh(conn, trip)
    return "updated" if changed else "unchanged"


def emails_of(conn: db.Connection, viewer: Viewer, segment_id: int) -> list[stored_mail.Content] | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    return None if seg is None else stored_mail.for_segment(conn, seg.id)


def email_image_of(conn: db.Connection, viewer: Viewer, segment_id: int, email: int, index: int) -> stored_mail.Image | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    return None if seg is None else stored_mail.image_for_segment(conn, seg.id, email, index)


def clear_emails(conn: db.Connection, viewer: Viewer, trip_id: int, today: date) -> int | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    if not emails_clearable(trip, today):
        raise Invalid(f"The saved emails can be removed once a trip has ended at least {EMAILS_CLEARABLE_AFTER_DAYS} days ago")
    segment_ids = [s.id for s in visibility.visible_segments(conn, viewer, [trip.id])]
    return stored_mail.clear_for_segments(conn, segment_ids)


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


def _known_people(conn: db.Connection, given: Sequence[int]) -> list[int]:
    wanted = list(dict.fromkeys(given))
    known = people.existing(conn, wanted)
    if any(p not in known for p in wanted):
        raise Invalid("Someone on this trip isn’t in People")
    return wanted


def _seen_by_bookings(conn: db.Connection, trip: Trip, apart_from: int | None = None) -> set[int]:
    own = select(Segment.id).where(Segment.trip_id == trip.id, Segment.id != (apart_from or 0))
    listed = set(conn.orm.scalars(select(SegmentTraveler.person_id).where(SegmentTraveler.segment_id.in_(own),
                                                                          SegmentTraveler.person_id.is_not(None))).all())
    booked = {p for p in conn.orm.scalars(select(Segment.booked_by).where(Segment.trip_id == trip.id)).all() if p is not None}
    received = conn.orm.scalars(select(SegmentRecipient.person_id).join(Segment, Segment.id == SegmentRecipient.segment_id)
                                .where(Segment.trip_id == trip.id)).all()
    return {p for p in listed if p is not None} | booked | set(received) | ({trip.booked_by} if trip.booked_by is not None else set())


def _seeing(conn: db.Connection, trip: Trip) -> set[int]:
    _, who = _involved(conn, [trip.id])
    received = conn.orm.scalars(select(SegmentRecipient.person_id).join(Segment, Segment.id == SegmentRecipient.segment_id)
                                .where(Segment.trip_id == trip.id)).all()
    return who[trip.id] | set(received) | ({trip.booked_by} if trip.booked_by is not None else set())


def _confirm_adding(conn: db.Connection, viewer: Viewer, newly: set[int], confirmed: bool) -> None:
    if not newly or viewer.household or confirmed:
        return
    see_trip = _named(conn, newly)
    raise NeedsConfirmation("Adding people changes who sees what. Could newly see this trip: "
                            + ", ".join(p["name"] for p in see_trip) + ". Confirm to add them anyway.", [], see_trip)


def _flight_of(conn: db.Connection, trip_id: int, person_id: int) -> Segment | None:
    return conn.orm.scalars(
        select(Segment).join(SegmentTraveler, SegmentTraveler.segment_id == Segment.id)
        .where(Segment.trip_id == trip_id, Segment.kind == "flight", SegmentTraveler.person_id == person_id)
        .order_by(Segment.id)).first()


def _set_people(conn: db.Connection, viewer: Viewer, trip: Trip, given: Sequence[int], confirmed: bool) -> None:
    wanted = _known_people(conn, given)
    have = trippeople.of(conn, [trip.id])[trip.id]
    leaving = [p for p in have if p not in wanted]
    for person in leaving:
        flight = _flight_of(conn, trip.id, person)
        if flight is not None:
            who = people.existing(conn, [person]).get(person, "They")
            raise Invalid(f"{who} is on a flight in this trip ({flight.origin or '?'} to {flight.destination or '?'}). "
                          "Take them off that flight first.")
    _confirm_adding(conn, viewer, {p for p in wanted if p not in have} - _seeing(conn, trip), confirmed)
    if leaving:
        own = select(Segment.id).where(Segment.trip_id == trip.id)
        conn.execute(delete(SegmentTraveler).where(SegmentTraveler.person_id.in_(leaving), SegmentTraveler.segment_id.in_(own)))
        trippeople.remove(conn, trip.id, leaving)
    trippeople.add(conn, trip.id, wanted)


def create_trip(conn: db.Connection, viewer: Viewer, fields: TripIn, confirmed: bool = False) -> TripOut:
    _needs_person(viewer)
    wanted = _known_people(conn, fields.get("people") or [])
    _confirm_adding(conn, viewer, {p for p in wanted if p != viewer.person_id}, confirmed)
    start, end = fields.get("start_date"), fields.get("end_date")
    if (start is None) != (end is None):
        raise Invalid("Give both dates of a trip, or neither")
    if start and end and end < start:
        raise Invalid("A trip can’t end before it starts")
    given = (fields.get("destination") or "").strip() or None
    trip = Trip(name=fields.get("name") or "", destination=given, destination_manual=given is not None, notes=fields.get("notes"),
                start_date=start, end_date=end, auto=False, booked_by=viewer.person_id)
    conn.orm.add(trip)
    conn.orm.flush()
    trippeople.add(conn, trip.id, wanted)
    return _trip_outs(conn, viewer, [trip])[0]


def edit_trip(conn: db.Connection, viewer: Viewer, trip_id: int, fields: TripIn, confirmed: bool = False) -> TripOut | None:
    trip = visibility.visible_trip(conn, viewer, trip_id)
    if trip is None:
        return None
    if "start_date" in fields or "end_date" in fields:
        raise Invalid("A trip’s dates come from its segments")
    if "people" in fields:
        _set_people(conn, viewer, trip, fields["people"], confirmed)
    if "name" in fields:
        trip.name = fields["name"]
    if "destination" in fields:
        given = (fields["destination"] or "").strip() or None
        trip.destination, trip.destination_manual = given, given is not None
    if "notes" in fields:
        trip.notes = fields["notes"]
    conn.orm.flush()
    refresh(conn, trip)
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
    aboard = trippeople.of(conn, [trip.id, other.id])
    joined = list(dict.fromkeys([*aboard[trip.id], *aboard[other.id]]))
    for seg in conn.orm.scalars(select(Segment).where(Segment.trip_id.in_([trip.id, other.id]), Segment.travelers_from_trip.is_(True))
                                .order_by(Segment.id)).all():
        if set(aboard[seg.trip_id]) != set(joined):
            _freeze(conn, seg, aboard[seg.trip_id])
    conn.execute(update(Segment).where(Segment.trip_id == other.id).values(trip_id=trip.id))
    trippeople.add(conn, trip.id, joined)
    trippeople.clear(conn, other.id)
    trip.auto = False
    if other.destination_manual and not trip.destination_manual:
        trip.destination, trip.destination_manual = other.destination, True
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
    leaving = list(conn.orm.scalars(select(Segment).where(Segment.id.in_(list(moving))).order_by(Segment.id)).all())
    before = trippeople.of(conn, [trip.id])[trip.id]
    listed = [t["person_id"] for s in leaving if not s.travelers_from_trip for t in effective_travelers(conn, s) if t["person_id"] is not None]
    joined = before if any(s.travelers_from_trip for s in leaving) else listed
    trippeople.add(conn, new.id, joined)
    conn.execute(update(Segment).where(Segment.id.in_(list(moving))).values(trip_id=new.id))
    conn.orm.flush()
    if not conn.orm.scalars(select(Segment.id).where(Segment.trip_id == trip.id, Segment.travelers_from_trip.is_(True))).first():
        trippeople.remove(conn, trip.id, [p for p in before if p not in trippeople.on_lists(conn, trip.id)])
    trip.auto = False
    conn.orm.flush()
    conn.orm.expire_all()
    refresh(conn, trip)
    refresh(conn, new)
    return _trip_outs(conn, viewer, [new])[0]


def _named(conn: db.Connection, ids: set[int]) -> list[NamedPerson]:
    names = people.existing(conn, sorted(ids))
    return sorted(({"id": i, "name": names[i]} for i in ids if i in names), key=lambda p: (p["name"], p["id"]))


def _needs_confirmation(conn: db.Connection, seg: Segment, target: Trip) -> None:
    _, who = _involved(conn, [target.id])
    moving = {t["person_id"] for t in effective_travelers(conn, seg) if t["person_id"] is not None} \
        | ({seg.booked_by} if seg.booked_by is not None else set())
    there = who[target.id] | ({target.booked_by} if target.booked_by is not None else set())
    see_booking, see_trip = _named(conn, there - moving), _named(conn, moving - there)
    if not see_booking and not see_trip:
        return
    parts = []
    if see_booking:
        parts.append("could newly see this booking: " + ", ".join(p["name"] for p in see_booking))
    if see_trip:
        parts.append("could newly see that trip: " + ", ".join(p["name"] for p in see_trip))
    said = "; ".join(parts)
    raise NeedsConfirmation(f"Moving this changes who sees what. {said[0].upper()}{said[1:]}. Confirm to move it anyway.", see_booking, see_trip)


def move_segment(conn: db.Connection, viewer: Viewer, segment_id: int, trip_id: int | None, confirmed: bool = False) -> TripOut | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    if trip_id == seg.trip_id:
        raise Invalid("It’s already in that trip")
    source = conn.orm.get(Trip, seg.trip_id)
    target: Trip | None
    if trip_id is None:
        if conn.orm.scalars(select(Segment.id).where(Segment.trip_id == seg.trip_id, Segment.id != seg.id)).first() is None:
            raise Invalid("It’s already in a trip of its own")
        place = _headline(conn, {"kind": seg.kind, "origin": seg.origin, "destination": seg.destination})
        target = Trip(name=_name_for(place, seg.start_local), destination=place, auto=True, booked_by=viewer.person_id)
        conn.orm.add(target)
        conn.orm.flush()
    else:
        target = visibility.visible_trip(conn, viewer, trip_id)
        if target is None:
            return None
        if not viewer.household and not confirmed:
            _needs_confirmation(conn, seg, target)
        target.auto = False
    if seg.travelers_from_trip:
        aboard = trippeople.of(conn, [seg.trip_id, target.id])
        if set(aboard[seg.trip_id]) != set(aboard[target.id]):
            _freeze(conn, seg, aboard[seg.trip_id])
    conn.execute(update(Segment).where(Segment.id == seg.id).values(trip_id=target.id))
    conn.orm.flush()
    conn.orm.expire_all()
    trippeople.keep_lists_inside(conn, target.id)
    refresh(conn, target)
    left = conn.orm.scalars(select(Segment.id).where(Segment.trip_id == source.id)).first() if source else None
    if source is not None:
        if left is None:
            conn.execute(delete(Trip).where(Trip.id == source.id))
        else:
            refresh(conn, source)
    return _trip_outs(conn, viewer, [conn.orm.get(Trip, target.id) or target])[0]


def unmatched(conn: db.Connection, viewer: Viewer) -> list[tuple[SegmentTraveler, SegmentOut]]:
    found = visibility.visible_unmatched(conn, viewer)
    segs = {s.id: s for s in visibility.visible_segments(conn, viewer, None) if s.id in {t.segment_id for t in found}}
    outs = {s["id"]: s for s in _segment_outs(conn, list(segs.values()), [], viewer)}
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
    trip_ids: set[int] = set()
    for t in same:
        owner = conn.orm.get(Segment, t.segment_id)
        if owner is not None:
            trip_ids.add(owner.trip_id)
        already = conn.orm.scalars(select(SegmentTraveler.id).where(SegmentTraveler.segment_id == t.segment_id,
                                                                    SegmentTraveler.person_id == person_id)).first()
        if already is not None:
            conn.execute(delete(SegmentTraveler).where(SegmentTraveler.id == t.id))
        else:
            t.person_id = person_id
        done += 1
    conn.orm.flush()
    for trip_id in sorted(trip_ids):
        trippeople.keep_lists_inside(conn, trip_id)
    if printed:
        people.add_alias(conn, person_id, printed)
    return done
