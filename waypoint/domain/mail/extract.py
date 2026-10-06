from __future__ import annotations

import base64
import binascii
import email
import email.policy
import email.utils
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ... import monitoring
from ...storage.stored_mail import Content
from . import parsers, safe_html
from .booking import Booking as Booking
from .booking import Kind, Parsed
from .booking import Passenger as Passenger
from .booking import Place as Place
from .booking import Status

RESERVATIONS: dict[str, Kind] = {"FlightReservation": "flight", "LodgingReservation": "hotel",
                                 "RentalCarReservation": "car", "TrainReservation": "train"}
MAX_PART = 2_000_000
MAX_NODES = 200
IATA = re.compile(r"[A-Z]{3}")
CLOCK = re.compile(r"(?<![\d:.])(\d{1,2}):(\d{2})(?::\d{2})?(?!\d)(?:\s*([AaPp])\.?[Mm]\.?)?")
BASE64URL = re.compile(r"[A-Za-z0-9_=-]+")
VOID = {"meta", "link", "img", "source", "area", "br", "hr", "input", "wbr", "col", "embed", "track", "base"}


@dataclass(frozen=True)
class Message:
    sender_domain: str | None
    received: str | None
    bookings: tuple[Booking, ...] = ()
    unread: int = 0
    broken: bool = False
    markup: bool = False
    gaps: tuple[str, ...] = ()
    other_markup: bool = False


class _Frame:
    __slots__ = ("attrs", "item", "props", "tag", "text")

    def __init__(self, tag: str, attrs: dict[str, str], item: dict[str, Any] | None):
        self.tag, self.attrs, self.item = tag, attrs, item
        self.props = (attrs.get("itemprop") or "").split()
        self.text: list[str] = []


def _type_name(itemtype: str) -> str:
    return itemtype.strip().split()[0].rstrip("/").rsplit("/", 1)[-1] if itemtype.strip() else ""


def _put(item: dict[str, Any], name: str, value: Any) -> None:
    if name not in item:
        item[name] = value
    elif isinstance(item[name], list):
        item[name].append(value)
    else:
        item[name] = [item[name], value]


class _Markup(HTMLParser):

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jsonld: list[str] = []
        self.items: list[dict[str, Any]] = []
        self._ld: list[str] | None = None
        self._script = False
        self._stack: list[_Frame] = []

    def _scope(self) -> dict[str, Any] | None:
        return next((f.item for f in reversed(self._stack) if f.item is not None), None)

    @staticmethod
    def _value(tag: str, attrs: dict[str, str], text: str) -> str:
        if "content" in attrs:
            return attrs["content"].strip()
        for key, tags in (("href", ("a", "area", "link")), ("src", ("img", "source", "embed", "track")),
                          ("datetime", ("time",)), ("value", ("data", "meter"))):
            if tag in tags and key in attrs:
                return attrs[key].strip()
        return " ".join(text.split())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            if a.get("type", "").lower().split(";")[0].strip() == "application/ld+json":
                self._ld = []
            else:
                self._script = True
            return
        item = {"@type": _type_name(a.get("itemtype", ""))} if "itemscope" in a else None
        frame = _Frame(tag, a, item)
        if tag in VOID:
            self._attach(frame, self._value(tag, a, ""))
            return
        self._stack.append(frame)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID and tag != "script":
            self.handle_endtag(tag)

    def _attach(self, frame: _Frame, text: str) -> None:
        parent = self._scope()
        if frame.item is not None:
            if frame.props and parent is not None:
                for name in frame.props:
                    _put(parent, name, frame.item)
            elif not frame.props:
                self.items.append(frame.item)
            return
        if parent is not None:
            value = self._value(frame.tag, frame.attrs, text)
            for name in frame.props:
                _put(parent, name, value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            if self._ld is not None:
                self.jsonld.append("".join(self._ld))
                self._ld = None
            self._script = False
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                break
        else:
            return
        while len(self._stack) > i:
            frame = self._stack.pop()
            self._attach(frame, "".join(frame.text))
            if self._stack:
                self._stack[-1].text.extend(frame.text)

    def handle_data(self, data: str) -> None:
        if self._ld is not None:
            self._ld.append(data)
            return
        if self._stack and not self._script and self._scope() is not None:
            self._stack[-1].text.append(data)


def _jsonld_nodes(raw: str) -> Iterator[dict[str, Any]]:
    try:
        found = json.loads(raw)
    except (ValueError, RecursionError):
        return
    todo = [found]
    while todo:
        node = todo.pop()
        if isinstance(node, list):
            todo.extend(node)
        elif isinstance(node, dict):
            yield node
            graph = node.get("@graph")
            if graph is not None:
                todo.append(graph)


def _types(node: Mapping[str, Any]) -> list[str]:
    t = node.get("@type")
    return [_type_name(x) for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def _one(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def _text(v: Any) -> str | None:
    v = _one(v)
    if isinstance(v, dict):
        v = v.get("name") or v.get("@value")
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (str, int, float)):
        return " ".join(str(v).split()) or None
    return None


def _node(v: Any) -> Mapping[str, Any]:
    v = _one(v)
    return v if isinstance(v, dict) else {}


def _nodes(v: Any) -> list[Mapping[str, Any]]:
    return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)]


def _link(v: Any) -> str | None:
    t = _text(v)
    return t if t and urlsplit(t).scheme in ("http", "https") else None


def _place(v: Any) -> Place:
    n = _node(v)
    address = _node(n.get("address"))
    return Place(_text(address.get("addressLocality")), _text(address.get("addressCountry")))


def _address(v: Any) -> str | None:
    one = _one(v)
    if isinstance(one, str):
        return _text(one)
    n = _node(one)
    parts = [_text(n.get(k)) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry")]
    return ", ".join(p for p in parts if p) or None


def _status(res: Mapping[str, Any]) -> Status:
    return "cancelled" if "cancel" in (_text(res.get("reservationStatus")) or "").lower() else "confirmed"


def _passengers(res: Mapping[str, Any]) -> tuple[Passenger, ...]:
    members = [_text(_node(m).get("memberNumber")) for m in _nodes(res.get("programMembership"))]
    who = []
    for p in _nodes(res.get("underName")):
        name = _text(p.get("name")) or " ".join(x for x in (_text(p.get("givenName")), _text(p.get("familyName"))) if x)
        if name:
            who.append(name)
    number = next((m for m in members if m), None)
    return tuple(Passenger(name, number if len(who) == 1 else None) for name in who)


def _details(**found: str | None) -> tuple[tuple[str, str], ...]:
    return tuple((k, v) for k, v in found.items() if v)


def _flight(res: Mapping[str, Any]) -> Booking | None:
    trip = _node(res.get("reservationFor"))
    airline = _node(trip.get("airline"))
    number = _text(trip.get("flightNumber"))
    code = _text(airline.get("iataCode"))
    if number and code and not number.upper().startswith(code.upper()):
        number = f"{code} {number}"
    origin = (_text(_node(trip.get("departureAirport")).get("iataCode")) or "").upper()
    destination = (_text(_node(trip.get("arrivalAirport")).get("iataCode")) or "").upper()
    start, end = _text(trip.get("departureTime")), _text(trip.get("arrivalTime"))
    if not (IATA.fullmatch(origin) and IATA.fullmatch(destination) and start and end):
        return None
    seat = _node(_node(res.get("reservedTicket")).get("ticketedSeat"))
    return Booking("flight", _status(res), _text(res.get("reservationNumber")), _text(airline.get("name")) or code, start, end,
                   origin, destination, details=_details(flight_number=number, terminal=_text(trip.get("departureTerminal")),
                                                         seat=_text(seat.get("seatNumber")), cabin=_text(seat.get("seatingType"))),
                   manage_url=_link(res.get("modifyReservationUrl")) or _link(res.get("url")), passengers=_passengers(res))


def _hotel(res: Mapping[str, Any]) -> Booking | None:
    stay = _node(res.get("reservationFor"))
    name = _text(stay.get("name"))
    start, end = _text(res.get("checkinTime")), _text(res.get("checkoutTime"))
    if not (name and start and end):
        return None
    place = _place(stay)
    return Booking("hotel", _status(res), _text(res.get("reservationNumber")), _text(_node(res.get("provider")).get("name")) or name,
                   start, end, name, None, place, place,
                   _details(address=_address(stay.get("address")), phone=_text(stay.get("telephone")),
                            room=_text(res.get("lodgingUnitDescription")) or _text(res.get("lodgingUnitType"))),
                   _link(res.get("modifyReservationUrl")) or _link(res.get("url")), _passengers(res))


def _car(res: Mapping[str, Any]) -> Booking | None:
    car = _node(res.get("reservationFor"))
    company = _text(_node(car.get("rentalCompany")).get("name")) or _text(_node(res.get("provider")).get("name"))
    pick, drop = _node(res.get("pickupLocation")), _node(res.get("dropoffLocation"))
    origin, destination = _text(pick.get("name")), _text(drop.get("name")) or _text(pick.get("name"))
    start, end = _text(res.get("pickupTime")), _text(res.get("dropoffTime"))
    if not (origin and start and end):
        return None
    return Booking("car", _status(res), _text(res.get("reservationNumber")), company, start, end, origin, destination,
                   _place(pick), _place(drop) if drop else _place(pick),
                   _details(car_class=_text(car.get("name")) or _text(car.get("model")),
                            address=_address(pick.get("address"))),
                   _link(res.get("modifyReservationUrl")) or _link(res.get("url")), _passengers(res))


def _train(res: Mapping[str, Any]) -> Booking | None:
    trip = _node(res.get("reservationFor"))
    dep, arr = _node(trip.get("departureStation")), _node(trip.get("arrivalStation"))
    origin, destination = _text(dep.get("name")), _text(arr.get("name"))
    start, end = _text(trip.get("departureTime")), _text(trip.get("arrivalTime"))
    if not (origin and destination and start and end):
        return None
    seat = _node(_node(res.get("reservedTicket")).get("ticketedSeat"))
    return Booking("train", _status(res), _text(res.get("reservationNumber")), _text(_node(trip.get("provider")).get("name")),
                   start, end, origin, destination, _place(dep), _place(arr),
                   _details(seat=_text(seat.get("seatNumber")), cabin=_text(seat.get("seatingClass")) or _text(seat.get("seatingType"))),
                   _link(res.get("modifyReservationUrl")) or _link(res.get("url")), _passengers(res))


_BUILD = {"flight": _flight, "hotel": _hotel, "car": _car, "train": _train}


def _gaps(kind: str, res: Mapping[str, Any]) -> list[str]:
    trip = _node(res.get("reservationFor"))
    lacks: list[str] = []
    if kind == "flight":
        for label, key in (("origin airport", "departureAirport"), ("destination airport", "arrivalAirport")):
            if not IATA.fullmatch((_text(_node(trip.get(key)).get("iataCode")) or "").upper()):
                lacks.append(label)
        lacks += [label for label, key in (("departure time", "departureTime"), ("arrival time", "arrivalTime")) if not _text(trip.get(key))]
    elif kind == "hotel":
        lacks += [label for label, ok in (("hotel name", _text(trip.get("name"))), ("check-in time", _text(res.get("checkinTime"))),
                                          ("check-out time", _text(res.get("checkoutTime")))) if not ok]
        if not res.get("checkinTime") and (res.get("checkinDate") or res.get("checkoutDate")):
            lacks.append("dates without times")
    elif kind == "car":
        lacks += [label for label, ok in (("pick-up place", _text(_node(res.get("pickupLocation")).get("name"))),
                                          ("pick-up time", _text(res.get("pickupTime"))), ("drop-off time", _text(res.get("dropoffTime")))) if not ok]
    else:
        lacks += [label for label, ok in (("departure station", _text(_node(trip.get("departureStation")).get("name"))),
                                          ("arrival station", _text(_node(trip.get("arrivalStation")).get("name"))),
                                          ("departure time", _text(trip.get("departureTime"))), ("arrival time", _text(trip.get("arrivalTime")))) if not ok]
    return lacks or ["details"]


def _bookings(nodes: list[dict[str, Any]]) -> tuple[list[Booking], int, bool, list[str]]:
    found: list[Booking] = []
    unread, seen = 0, False
    gaps: list[str] = []
    for node in nodes[:MAX_NODES]:
        for t in _types(node):
            if t in RESERVATIONS:
                seen = True
                made = _BUILD[RESERVATIONS[t]](node)
                if made is None:
                    unread += 1
                    gaps += _gaps(RESERVATIONS[t], node)
                elif made not in found:
                    found.append(made)
            elif t.endswith("Reservation"):
                seen, unread = True, unread + 1
                gaps.append("another kind of reservation")
    return found, unread, seen, gaps


def written_clock(text: str) -> str | None:
    text = text.strip()
    if "T" not in text.upper() and " " not in text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return None


def real_offset(text: str) -> bool:
    try:
        t = datetime.fromisoformat(text.strip())
    except ValueError:
        return False
    return t.utcoffset() not in (None, timedelta(0))


def has_offset(text: str) -> bool:
    try:
        return datetime.fromisoformat(text.strip()).tzinfo is not None
    except ValueError:
        return False


def wall_clock(text: str, zone: str | None = None) -> str | None:
    text = text.strip()
    if "T" not in text.upper() and " " not in text:
        return None
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        return None
    if t.tzinfo is not None:
        if zone:
            try:
                t = t.astimezone(ZoneInfo(zone))
            except (ZoneInfoNotFoundError, ValueError, OSError):
                return None
        elif t.utcoffset() == timedelta(0):
            return None
    return t.replace(tzinfo=None).isoformat(timespec="seconds")


def utc_marked(text: str) -> bool:
    try:
        t = datetime.fromisoformat(text.strip())
    except ValueError:
        return False
    return t.tzinfo is not None and t.utcoffset() == timedelta(0)


def _as_written(text: str) -> str:
    return datetime.fromisoformat(text.strip()).replace(tzinfo=None).isoformat(timespec="seconds")


def clock_times(text: str) -> frozenset[str]:
    found: set[str] = set()
    for m in CLOCK.finditer(text):
        hour, minute, half = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
        if half:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if half == "p" else 0)
        if hour < 24 and minute < 60:
            found.add(f"{hour:02d}:{minute:02d}")
    return frozenset(found)


def reading(b: Booking, start_zone: str, end_zone: str) -> Literal["written", "moved"] | None:
    moved = (wall_clock(b.start, start_zone), wall_clock(b.end, end_zone))
    marked = [(t, m) for t, m in zip((b.start, b.end), moved, strict=True) if utc_marked(t)]
    written = [_as_written(t)[11:16] for t, _ in marked]
    converted = [m[11:16] for _, m in marked if m]
    if not marked or len(converted) < len(marked) or written == converted:
        return None
    local = all(w in b.clock_times for w in written)
    utc = all(c in b.clock_times for c in converted)
    return "written" if local and not utc else "moved" if utc and not local else None


def _decode(raw: Any) -> bytes | None:
    if not isinstance(raw, str) or not raw or not BASE64URL.fullmatch(raw):
        return None
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (binascii.Error, ValueError):
        return None


def _domain(header: Any) -> str | None:
    address = email.utils.parseaddr(str(header or ""))[1]
    domain = address.rpartition("@")[2].strip().strip(">").lower()
    return domain if domain and "." in domain else None


def _day(header: Any) -> str | None:
    try:
        sent = email.utils.parsedate_to_datetime(str(header))
    except (TypeError, ValueError, IndexError):
        return None
    return sent.date().isoformat()


def read(message: Mapping[str, Any]) -> Message:
    data = _decode(message.get("raw"))
    if data is None:
        return Message(None, None, broken=True)
    try:
        parsed = email.message_from_bytes(data, policy=email.policy.default)
        sender, received = _domain(parsed.get("From")), _day(parsed.get("Date"))
    except (ValueError, LookupError, TypeError):
        return Message(None, None, broken=True)
    nodes: list[dict[str, Any]] = []
    htmls: list[str] = []
    texts: list[str] = []
    for part in parsed.walk():
        kind = part.get_content_type()
        if kind not in ("text/html", "text/plain"):
            continue
        try:
            html = str(part.get_content())[:MAX_PART]
        except (ValueError, LookupError, KeyError):
            continue
        if kind == "text/plain":
            texts.append(html)
            continue
        htmls.append(html)
        scanner = _Markup()
        try:
            scanner.feed(html)
            scanner.close()
        except (ValueError, RecursionError, AssertionError):
            continue
        for ld in scanner.jsonld:
            nodes.extend(_jsonld_nodes(ld))
        nodes.extend(scanner.items)
    bookings, unread, seen, gaps = _bookings(nodes)
    other = bool(nodes) and not seen
    parse = parsers.for_sender(sender)
    if parse is not None:
        try:
            found = parse("\n".join(htmls), "\n".join(texts))
        except Exception as e:
            monitoring.report(e, values=False)
            found = Parsed(unread=0 if bookings else 1)
        flights = [x for x in bookings if x.kind == "flight"]
        if not bookings:
            bookings, unread = list(found.bookings), unread + found.unread
            seen = seen or bool(found.bookings or found.unread)
            if not found.bookings:
                gaps.append("sender-specific parser found no booking")
        elif len(text_flights := [x for x in found.bookings if x.kind == "flight"]) > len(flights):
            bookings = [x for x in bookings if x.kind != "flight"] + text_flights
            unread += found.unread
    if any(utc_marked(t) for b in bookings for t in (b.start, b.end)):
        shown = clock_times(_visible(htmls, texts))
        bookings = [replace(b, clock_times=shown) if utc_marked(b.start) or utc_marked(b.end) else b for b in bookings]
    return Message(sender, received, tuple(bookings), unread, markup=seen, gaps=tuple(gaps), other_markup=other)


class _Text(HTMLParser):
    BREAKS = {"br", "p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BREAKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _visible(htmls: list[str], texts: list[str]) -> str:
    scanner = _Text()
    for h in htmls:
        try:
            scanner.feed(h)
            scanner.close()
        except (ValueError, RecursionError, AssertionError):
            continue
    return "\n".join([*texts, "".join(scanner.parts)])


def _bodies(message: Mapping[str, Any]) -> tuple[list[str], list[str]] | None:
    data = _decode(message.get("raw"))
    if data is None:
        return None
    try:
        parsed = email.message_from_bytes(data, policy=email.policy.default)
        plain: list[str] = []
        html: list[str] = []
        for part in parsed.walk():
            kind = part.get_content_type()
            if kind not in ("text/plain", "text/html"):
                continue
            try:
                (plain if kind == "text/plain" else html).append(str(part.get_content())[:MAX_PART])
            except (ValueError, LookupError, KeyError):
                continue
    except (ValueError, LookupError, TypeError):
        return None
    return plain, html


def safe_markup(message: Mapping[str, Any], limit: int = MAX_PART) -> tuple[str, bool] | None:
    bodies = _bodies(message)
    if bodies is None or not bodies[1]:
        return None
    shown: list[str] = []
    for i, part in enumerate(bodies[1]):
        markup, cut, size = safe_html.clean_counted(part, limit)
        shown.append(markup)
        limit -= size
        if cut or (limit <= 0 and i + 1 < len(bodies[1])):
            return "<hr>".join(shown), True
    return "<hr>".join(shown), False


def plain_text(message: Mapping[str, Any], limit: int = MAX_PART) -> str:
    bodies = _bodies(message)
    if bodies is None:
        return ""
    plain, html = bodies
    if plain:
        return "\n".join(plain)[:limit]
    scanner = _Text()
    for h in html:
        try:
            scanner.feed(h)
            scanner.close()
        except (ValueError, RecursionError, AssertionError):
            continue
    return re.sub(r"\n\s*\n+", "\n", "".join(scanner.parts))[:limit]


SUBJECT_LIMIT = 300
KEPT_LIMIT = 30_000


def keep(message: Mapping[str, Any]) -> Content:
    data = _decode(message.get("raw"))
    subject: str | None = None
    sender: str | None = None
    received: str | None = None
    if data is not None:
        try:
            parsed = email.message_from_bytes(data, policy=email.policy.default)
            subject = " ".join(str(parsed.get("Subject") or "").split())[:SUBJECT_LIMIT] or None
            sender, received = _domain(parsed.get("From")), _day(parsed.get("Date"))
        except (ValueError, LookupError, TypeError):
            subject = None
    text = plain_text(message, KEPT_LIMIT + 1)
    shown = safe_markup(message, KEPT_LIMIT)
    return {"subject": subject, "sender_domain": sender, "received": received, "text": text[:KEPT_LIMIT],
            "html": shown[0] if shown else None, "truncated": len(text) > KEPT_LIMIT or bool(shown and shown[1])}
