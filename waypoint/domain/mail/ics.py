from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...storage import reference
from . import fields, labels, when, words
from .places import zone_of
from .booking import Booking, Kind, Parsed
from .fields import Unreadable
from .flights import AIRPORT, NOT_AIRLINES, NUMBER

MAX_EVENTS = 50
MAX_HOURS = {"flight": 30, "train": 96}
MAX_DAYS = {"hotel": 60, "car": 90, "cruise": 200}
CHECK_IN = time(15, 0)
CHECK_OUT = time(11, 0)
HOTEL = re.compile(r"hotel|hôtel|resort|lodging|accommodation|check-in|unterkunft|alojamiento|ホテル|宿泊", re.IGNORECASE)
ABOUT = {name: labels.about(name) for name in ("cruise", "train", "car")}
ROUTE = re.compile(r"\s*(?:→|->|⇒|➔|\bto\b|\bvers\b|\bnach\b|\ba\b)\s*", re.IGNORECASE)


@dataclass(frozen=True)
class _Stamp:
    day: date
    at: time | None
    zone: str | None


@dataclass(frozen=True)
class _Event:
    summary: str
    location: str
    description: str
    uid: str
    start: _Stamp | None
    end: _Stamp | None


def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        elif line:
            out.append(line)
    return out


def _unescape(value: str) -> str:
    return re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], value).strip()


def _split(line: str) -> tuple[str, dict[str, str], str] | None:
    quoted = False
    for at, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ":" and not quoted:
            head, value = line[:at], line[at + 1:]
            name, *params = re.split(r';(?=(?:[^"]*"[^"]*")*[^"]*$)', head)
            parsed = {k.upper(): v.strip('"') for p in params if "=" in p for k, v in [p.split("=", 1)]}
            return name.upper(), parsed, value
    return None


def _stamp(params: dict[str, str], value: str) -> _Stamp | None:
    value = value.strip()
    try:
        if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", value):
            return _Stamp(datetime.strptime(value[:8], "%Y%m%d").date(), None, None)
        utc = value.endswith(("Z", "z"))
        moment = datetime.strptime(value.rstrip("Zz")[:15], "%Y%m%dT%H%M%S")
        zone = params.get("TZID")
        if zone is not None:
            ZoneInfo(zone)
        return _Stamp(moment.date(), moment.time(), None if utc else zone)
    except (ValueError, ZoneInfoNotFoundError, OSError):
        return None


def _event(props: dict[str, tuple[dict[str, str], str]]) -> _Event:
    def text(key: str) -> str:
        return _unescape(props[key][1]) if key in props else ""

    start = _stamp(*props["DTSTART"]) if "DTSTART" in props else None
    end = _stamp(*props["DTEND"]) if "DTEND" in props else None
    return _Event(text("SUMMARY"), text("LOCATION"), text("DESCRIPTION"), text("UID"), start, end)


def _events(text: str) -> list[_Event]:
    found: list[_Event] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    for line in _unfold(text):
        if line.strip().upper() == "BEGIN:VEVENT":
            current = {}
        elif line.strip().upper() == "END:VEVENT":
            if current is not None:
                found.append(_event(current))
            current = None
        elif current is not None and (split := _split(line)) is not None:
            current.setdefault(split[0], (split[1], split[2]))
    return found[:MAX_EVENTS]


def _kind(event: _Event) -> Kind | None:
    text = f"{event.summary}\n{event.location}\n{event.description}"
    if _flight_number(text) and len(_airports(text)) >= 2:
        return "flight"
    if _about("cruise", event):
        return "cruise"
    if _about("train", event):
        return "train"
    if _about("car", event):
        return "car"
    if HOTEL.search(event.summary) or HOTEL.search(event.description):
        return "hotel"
    return None


def _about(name: str, event: _Event) -> bool:
    pattern = ABOUT[name]
    return bool(pattern.search(event.summary) or pattern.search(event.description))


def _flight_number(text: str) -> tuple[str, str] | None:
    airlines = reference.airline_names()
    for m in NUMBER.finditer(text):
        if m[1] in airlines and m[1] not in NOT_AIRLINES:
            return m[1], m[2]
    return None


def _airports(text: str) -> list[str]:
    known = reference.airport_zones()
    return list(dict.fromkeys(m[0] for m in AIRPORT.finditer(text) if m[0] in known))


def _confirmation(description: str) -> str | None:
    for row in description.splitlines():
        lowered = row.lower()
        for label in words.CONFIRMATION:
            at = lowered.find(label)
            if at >= 0 and (found := fields.code(row[at + len(label):])):
                return found
    return None


def _instants(event: _Event, kind: Kind) -> tuple[_Stamp, _Stamp, datetime, datetime]:
    if event.start is None or event.end is None:
        raise Unreadable("event has no start and end")
    first, last = event.start, event.end
    if kind != "hotel":
        if first.at is None or last.at is None:
            raise Unreadable("event has no start and end time")
        if first.zone is None:
            raise Unreadable("event has no time zone")
        last = replace(last, zone=last.zone or first.zone)
    zone_in, zone_out = ZoneInfo(first.zone or "UTC"), ZoneInfo(last.zone or first.zone or "UTC")
    began = datetime.combine(first.day, first.at or CHECK_IN, tzinfo=zone_in)
    ended = datetime.combine(last.day, last.at or CHECK_OUT, tzinfo=zone_out)
    if ended <= began:
        raise Unreadable("event ends before it starts")
    limit = timedelta(hours=MAX_HOURS[kind]) if kind in MAX_HOURS else timedelta(days=MAX_DAYS[kind])
    if ended - began > limit:
        raise Unreadable(f"{kind} event is longer than allowed")
    return first, last, began, ended


def _booking(event: _Event, kind: Kind) -> Booking:
    first, last, _, _ = _instants(event, kind)
    code = _confirmation(event.description)
    start = when.stamp(first.day, first.at, CHECK_IN)
    end = when.stamp(last.day, last.at, CHECK_OUT)
    sources = {"start_local": "DTSTART", "end_local": "DTEND"}
    if code:
        sources["confirmation"] = "description"
    end_zone = last.zone or first.zone
    if kind == "flight":
        text = f"{event.summary}\n{event.location}\n{event.description}"
        airline, digits = _flight_number(text) or ("", "")
        ports = _airports(text)
        sources |= {"origin": "airport code", "destination": "airport code"}
        return Booking("flight", "confirmed", code, reference.airline_names().get(airline), start, end, ports[0], ports[1],
                       details=(("flight_number", f"{airline} {digits}"),), generic=tuple(sources.items()), start_zone=first.zone, end_zone=end_zone)
    if kind == "hotel":
        name = event.summary[:100]
        if not name:
            raise Unreadable("event has no hotel name")
        sources["origin"] = "summary"
        address = event.location[:300]
        details = tuple((k, v) for k, v in (("address", address), ("time_unknown", "yes" if first.at is None or last.at is None else None)) if v)
        zone = first.zone or zone_of(address)
        return Booking("hotel", "confirmed", code, name, start, end, name, None, details=details, generic=tuple(sources.items()),
                       start_zone=zone, end_zone=last.zone or zone)
    if kind == "train":
        route = event.location or event.summary
        route = route.rsplit(":", 1)[-1] if ":" in route else route
        parts = [p.strip() for p in ROUTE.split(route, maxsplit=1)]
        if len(parts) != 2 or not all(parts):
            raise Unreadable("no departure and arrival station found")
        sources |= {"origin": "location" if event.location else "summary", "destination": "location" if event.location else "summary"}
        return Booking("train", "confirmed", code, None, start, end, parts[0][:100], parts[1][:100], generic=tuple(sources.items()), start_zone=first.zone, end_zone=end_zone)
    place = event.location.splitlines()[0][:100] if event.location else ""
    if not place:
        raise Unreadable("event has no location")
    sources |= {"origin": "location", "destination": "location"}
    if kind == "cruise":
        return Booking("cruise", "confirmed", code, None, start, end, place, place, details=(("ship", event.summary[:100]),) if event.summary else (),
                       generic=tuple(sources.items()), start_zone=first.zone, end_zone=end_zone)
    return Booking("car", "confirmed", code, event.summary[:100] or None, start, end, place, place, generic=tuple(sources.items()), start_zone=first.zone, end_zone=end_zone)


def read(calendars: list[str]) -> tuple[Parsed, str | None]:
    made: dict[tuple[str, str, str], Booking] = {}
    failed: list[str] = []
    seen: set[str] = set()
    for text in calendars:
        try:
            events = _events(text)
        except (ValueError, KeyError, RecursionError):
            failed.append("calendar attachment couldn't be parsed")
            continue
        for event in events:
            if event.uid and event.uid in seen:
                continue
            seen.add(event.uid)
            kind = _kind(event)
            if kind is None:
                continue
            try:
                booking = _booking(event, kind)
            except Unreadable as e:
                failed.append(str(e))
                continue
            made.setdefault((kind, booking.origin or "", booking.start), booking)
    if not made:
        return Parsed(), failed[0] if failed else ""
    return Parsed(tuple(made.values()), unread=len(failed)), None
