from __future__ import annotations

import re
from datetime import date, datetime

from ..booking import Booking, Parsed, Passenger, Port
from ._text import clock, lines

PROVIDER = "Disney Cruise Line"
MAX_DAYS = 120
EAST = "America/New_York"
BAHAMAS = "America/Nassau"
PORTS: dict[str, tuple[str, str]] = {
    "fort lauderdale": ("Fort Lauderdale", EAST),
    "port everglades": ("Fort Lauderdale", EAST),
    "port canaveral": ("Port Canaveral", EAST),
    "miami": ("Miami", EAST),
    "jacksonville": ("Jacksonville", EAST),
    "charleston": ("Charleston", EAST),
    "new york": ("New York", EAST),
    "key west": ("Key West", EAST),
    "nassau": ("Nassau", BAHAMAS),
    "castaway cay": ("Castaway Cay", BAHAMAS),
    "lookout cay": ("Lookout Cay", BAHAMAS),
    "freeport": ("Freeport", BAHAMAS),
}
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?,?"
RESERVATION = re.compile(r"reservation(?: number| #)?\s*:?\s*([A-Z0-9]{5,12})", re.IGNORECASE)
EMBARK = re.compile(r"(?:embark(?:ation)?|sail(?:ing)?) date\s*:?\s*(\S.*)", re.IGNORECASE)
DEBARK = re.compile(r"(?:debark(?:ation)?|disembark(?:ation)?|return) date\s*:?\s*(\S.*)", re.IGNORECASE)
SHIP = re.compile(r"ship:?\s+(\S.{0,40})", re.IGNORECASE)
STATEROOM = re.compile(r"stateroom(?: number| #)?:?\s+([A-Z0-9]{2,8})", re.IGNORECASE)
DECK = re.compile(r"deck:?\s+([A-Z0-9]{1,3})", re.IGNORECASE)
GUEST = re.compile(r"guest(?: \d{1,2})?\s*:\s*(\S.{0,80})", re.IGNORECASE)
ITINERARY = re.compile(r"cruise itinerary", re.IGNORECASE)
DATE = re.compile(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2})(?:,? (\d{4}))?")
DAY = re.compile(rf"{WEEKDAY}\s+({DATE.pattern})(?:\s*[-–—|]\s*(\S.*))?", re.IGNORECASE)
TIME = re.compile(r"(ashore|on ?board|all aboard)\s*:?\s*(\d{1,2}):(\d{2})\s*([AP])M", re.IGNORECASE)
SEA = "at sea"


def _date(month: str, day: str, year: str | None, floor: date) -> date | None:
    number = MONTHS.get(month.lower())
    if number is None:
        return None
    try:
        found = date(int(year), number, int(day)) if year else date(floor.year, number, int(day))
        if not year and found < floor:
            found = date(floor.year + 1, number, int(day))
    except ValueError:
        return None
    return found


def _named(row: str) -> tuple[str, str] | None:
    return PORTS.get(row.split(",")[0].strip().casefold())


class _Day:
    def __init__(self, day: date, port: str | None) -> None:
        self.day, self.port = day, port
        self.ashore: str | None = None
        self.onboard: str | None = None


def _days(rows: list[str], embark: date, debark: date) -> list[_Day] | None:
    found: list[_Day] = []
    for row in rows:
        m = DAY.fullmatch(row)
        if m:
            day = _date(m[2], m[3], m[4], embark)
            if day is None or not embark <= day <= debark or any(d.day == day for d in found):
                return None
            found.append(_Day(day, m[5]))
            continue
        if not found:
            continue
        times = list(TIME.finditer(row))
        if not times and found[-1].port is None:
            found[-1].port = row
            continue
        for t in times:
            at = clock(int(t[2]), int(t[3]), t[4])
            if at is None:
                return None
            stamp = datetime.combine(found[-1].day, at).isoformat(timespec="seconds")
            if t[1].lower() == "ashore":
                found[-1].ashore = stamp
            else:
                found[-1].onboard = stamp
    return found


def parse(html: str, text: str) -> Parsed:
    rows = lines(html, text)
    code = next((m[1].upper() for r in rows if (m := RESERVATION.fullmatch(r))), None)
    if code is None:
        return Parsed()
    start = next((m[1] for r in rows if (m := EMBARK.fullmatch(r))), None)
    end = next((m[1] for r in rows if (m := DEBARK.fullmatch(r))), None)
    section = next((i for i, r in enumerate(rows) if ITINERARY.fullmatch(r)), None)
    embark = DATE.search(start or "")
    debark = DATE.search(end or "")
    if section is None or embark is None or debark is None or not embark[3] or not debark[3]:
        return Parsed((), 1)
    left, right = _date(embark[1], embark[2], embark[3], date.min), _date(debark[1], debark[2], debark[3], date.min)
    if left is None or right is None or not 0 < (right - left).days <= MAX_DAYS:
        return Parsed((), 1)
    days = _days(rows[section + 1:], left, right)
    if not days:
        return Parsed((), 1)
    by_date = {d.day: d for d in days}
    origin, destination = by_date.get(left), by_date.get(right)
    if origin is None or destination is None or origin.onboard is None or destination.ashore is None:
        return Parsed((), 1)
    start_port = _named(origin.port or "")
    end_port = _named(destination.port or "")
    if start_port is None or end_port is None:
        return Parsed((), 1)
    ports: list[Port] = []
    for d in days:
        if d.day in (left, right) or (d.port or "").strip().casefold() == SEA:
            continue
        known = _named(d.port or "")
        if known is None or (d.ashore is None and d.onboard is None):
            return Parsed((), 1)
        ports.append(Port(known[0], known[1], d.ashore, d.onboard))
    names = [m[1].strip() for r in rows[:section] if (m := GUEST.fullmatch(r))]
    ship = next((m[1].strip() for r in rows[:section] if (m := SHIP.fullmatch(r))), None)
    room = next((m[1].upper() for r in rows[:section] if (m := STATEROOM.fullmatch(r))), None)
    deck = next((m[1].upper() for r in rows[:section] if (m := DECK.fullmatch(r))), None)
    details = tuple((k, v) for k, v in (("ship", ship), ("room", room), ("deck", deck)) if v)
    return Parsed((Booking("cruise", "confirmed", code, PROVIDER, origin.onboard, destination.ashore, start_port[0], end_port[0],
                           details=details, passengers=tuple(Passenger(n) for n in names), start_zone=start_port[1],
                           end_zone=end_port[1], ports=tuple(ports)),))
