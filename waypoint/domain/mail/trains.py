from __future__ import annotations

from dataclasses import replace
from datetime import time, timedelta

from . import fields, labels, when
from .booking import Booking, Parsed
from .fields import Unreadable

MAX_HOURS = 96
TABLE = fields.Table(labels.table("train"))
ABOUT = labels.about("train")
FLIGHT = labels.about("flight")
CORE = ("start", "start_place", "start_date", "start_time", "end", "end_place", "end_date", "end_time")
SPLIT = frozenset({"number", "start_place", "start"})


def _leg(section: fields.Section, rows: list[fields.Row]) -> tuple[Booking, dict[str, str]]:
    leaves, arrives = fields.point(section, "start", rows, TABLE), fields.point(section, "end", rows, TABLE)
    if leaves.place.name is None or arrives.place.name is None:
        raise Unreadable("no departure and arrival station found")
    if leaves.day is None or arrives.day is None or leaves.at is None or arrives.at is None:
        raise Unreadable("no departure and arrival date and time found")
    if leaves.place.zone is None or arrives.place.zone is None:
        raise Unreadable("station's time zone unknown")
    departure = fields.instant(leaves.day, leaves.at, leaves.place.zone)
    arrival = fields.instant(arrives.day, arrives.at, arrives.place.zone)
    if arrival <= departure:
        raise Unreadable("arrival isn't after departure")
    if arrival - departure > timedelta(hours=MAX_HOURS):
        raise Unreadable(f"train trip is longer than {MAX_HOURS} hours")
    sources = {"origin": leaves.place.label, "destination": arrives.place.label, "start_local": leaves.day_label, "end_local": arrives.day_label}
    booking = Booking("train", "confirmed", None, None, when.stamp(leaves.day, leaves.at, time.min), when.stamp(arrives.day, arrives.at, time.min),
                      leaves.place.name, arrives.place.name, start_zone=leaves.place.zone, end_zone=arrives.place.zone)
    return booking, sources


def read(html: str, text: str) -> tuple[Parsed, str | None]:
    rows = fields.read_rows(html, text)
    if not fields.mentions(rows, ABOUT) or fields.mentions(rows, FLIGHT):
        return Parsed(), ""
    found = TABLE.hits(rows)
    legs = [s for s in fields.sections(found, SPLIT) if any(key in s for key in CORE)]
    if not legs:
        return Parsed(), ""
    shared_code, shared_operator = fields.confirmation([h for h in found if h.key == "confirmation"]), fields.named([h for h in found if h.key == "provider"], 100)
    made: dict[tuple[str, str], Booking] = {}
    failed: list[str] = []
    for section in legs:
        try:
            booking, sources = _leg(section, rows)
        except Unreadable as e:
            failed.append(str(e))
            continue
        operator = fields.named(section.get("provider", []), 100) or shared_operator
        code = fields.confirmation(section.get("confirmation", [])) or shared_code
        if operator:
            booking = replace(booking, provider=operator[0])
            sources["provider"] = operator[1]
        if code:
            booking = replace(booking, confirmation=code[0])
            sources["confirmation"] = code[1]
        made.setdefault((booking.origin or "", booking.start), replace(booking, generic=tuple(sources.items())))
    if not made:
        return Parsed(), failed[0]
    return Parsed(tuple(made.values()), unread=len(failed)), None
