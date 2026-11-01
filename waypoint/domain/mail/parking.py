from __future__ import annotations

import re
from datetime import date, time

from . import fields, when
from .booking import Booking, Parsed
from .fields import Unreadable
from .places import STATE, zone_of

ENTRY = time(0, 0)
EXIT = time(23, 59)
ABOUT = re.compile(r"\bparking\b|\bcar park\b|\bgarage\b", re.IGNORECASE)
ADDRESS = re.compile(r"(?:ramp|lot|garage|facility|car park) address(?: is|:)\s*(.+)", re.IGNORECASE)
TABLE = fields.Table({
    "confirmation": ("booking id", "booking reference", "booking number", "confirmation number", "confirmation code", "confirmation #",
                     "confirmation", "reservation number", "reservation id", "reservation"),
    "start": ("entry date and time", "entry date", "entry time", "entry", "check-in date", "arrival date and time", "start date"),
    "end": ("exit date and time", "exit date", "exit time", "exit", "check-out date", "end date"),
    "start_place": ("parking ramp", "parking lot", "parking facility", "parking location", "parking garage", "car park", "facility", "lot"),
    "booked": ("booking date", "invoice date", "booked on"),
})
CORE = ("start", "end")


def _day(value: str, american: bool) -> date | None:
    if (day := when.find_date(value)) is not None or not american:
        return day
    m = when.SLASHED.search(value)
    return date(int(m[3]), int(m[1]), int(m[2])) if m and int(m[1]) <= 12 and int(m[2]) <= 31 else None


def _address(rows: list[fields.Row]) -> str | None:
    for cells in rows:
        if fields.skipped(cells):
            continue
        if m := ADDRESS.search(" ".join(cells)):
            return fields.clean(m[1])[:200] or None
    return None


def _booking(section: fields.Section, rows: list[fields.Row]) -> Booking:
    lot = fields.named(section.get("start_place", []), 100)
    address = _address(rows)
    zone = zone_of(address) if address else None
    zone = zone or (zone_of(lot[0]) if lot else None)
    if lot is None:
        raise Unreadable("no parking lot found")
    if zone is None:
        raise Unreadable("parking lot's time zone unknown")
    american = address is not None and STATE.search(address) is not None
    entry = next(((h, d) for h in section["start"] if (d := _day(h.value, american))), None)
    leave = next(((h, d) for h in section["end"] if (d := _day(h.value, american))), None)
    if entry is None:
        raise Unreadable("no entry date found")
    if leave is None:
        raise Unreadable("no exit date found")
    (entry_hit, entry_day), (leave_hit, exit_day) = entry, leave
    entry_at, exit_at = when.find_time(entry_hit.value), when.find_time(leave_hit.value)
    first, last = fields.instant(entry_day, entry_at or ENTRY, zone), fields.instant(exit_day, exit_at or EXIT, zone)
    if last <= first:
        raise Unreadable("exit isn't after entry")
    code = fields.confirmation(section.get("confirmation", []))
    sources = {"origin": lot[1], "start_local": entry_hit.label, "end_local": leave_hit.label}
    if code:
        sources["confirmation"] = code[1]
    untimed = "yes" if entry_at is None or exit_at is None else None
    details = tuple((k, v) for k, v in (("address", address), ("time_unknown", untimed)) if v)
    return Booking("parking", "confirmed", code[0] if code else None, None, when.stamp(entry_day, entry_at, ENTRY),
                   when.stamp(exit_day, exit_at, EXIT), lot[0], None, start_zone=zone, end_zone=zone, details=details,
                   generic=tuple(sources.items()))


def read(html: str, text: str) -> tuple[Parsed, str | None]:
    rows = fields.read_rows(html, text)
    if not fields.mentions(rows, ABOUT):
        return Parsed(), ""
    [section, *_] = fields.sections(TABLE.hits(rows), frozenset()) or [{}]
    if not all(key in section for key in CORE):
        return Parsed(), ""
    try:
        return Parsed((_booking(section, rows),)), None
    except Unreadable as e:
        return Parsed(), str(e)
