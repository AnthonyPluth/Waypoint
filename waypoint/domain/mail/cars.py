from __future__ import annotations

from datetime import time, timedelta

from . import fields, labels, when
from .booking import Booking, Parsed
from .fields import Place, Unreadable

MAX_DAYS = 90
PICK_UP = time(12, 0)
DROP_OFF = time(12, 0)
TABLE = fields.Table(labels.table("car"))
ABOUT = labels.about("car")
CORE = ("start", "start_place", "start_date", "start_time", "end", "end_place", "end_date", "end_time", "location")
NONE = Place(None, "", False, None)


def _booking(section: fields.Section, rows: list[fields.Row]) -> Booking:
    pick_up, drop_off = fields.point(section, "start", rows, TABLE), fields.point(section, "end", rows, TABLE)
    shared = fields.place_of(section.get("location", []))
    start = pick_up.place if pick_up.place.name else shared
    if start.name is None:
        raise Unreadable("no pick-up location found")
    end = drop_off.place if drop_off.place.name else start if drop_off.place.same or shared.name else NONE
    if end.name is None:
        raise Unreadable("no drop-off location found")
    if pick_up.day is None:
        raise Unreadable("no pick-up date found")
    if drop_off.day is None:
        raise Unreadable("no drop-off date found")
    if start.zone is None:
        raise Unreadable("pick-up location's time zone unknown")
    if end.zone is None:
        raise Unreadable("drop-off location's time zone unknown")
    first = fields.instant(pick_up.day, pick_up.at or PICK_UP, start.zone)
    last = fields.instant(drop_off.day, drop_off.at or DROP_OFF, end.zone)
    if last <= first:
        raise Unreadable("drop-off isn't after pick-up")
    if last - first > timedelta(days=MAX_DAYS):
        raise Unreadable(f"rental is longer than {MAX_DAYS} days")
    sources = {"origin": start.label, "destination": end.label or start.label, "start_local": pick_up.day_label, "end_local": drop_off.day_label}
    code, company, vehicle = fields.confirmation(section.get("confirmation", [])), fields.named(section.get("provider", []), 100), fields.named(section.get("vehicle", []), 60)
    sources.update({key: found[1] for key, found in (("confirmation", code), ("provider", company)) if found})
    untimed = "yes" if pick_up.at is None or drop_off.at is None else None
    details = tuple((k, v) for k, v in (("car_class", vehicle[0] if vehicle else None), ("time_unknown", untimed)) if v)
    return Booking("car", "confirmed", code[0] if code else None, company[0] if company else None, when.stamp(pick_up.day, pick_up.at, PICK_UP),
                   when.stamp(drop_off.day, drop_off.at, DROP_OFF), start.name, end.name, start_zone=start.zone, end_zone=end.zone,
                   details=details, generic=tuple(sources.items()))


def read(html: str, text: str) -> tuple[Parsed, str | None]:
    rows = fields.read_rows(html, text)
    if not fields.mentions(rows, ABOUT):
        return Parsed(), ""
    [section, *_] = fields.sections(TABLE.hits(rows), frozenset()) or [{}]
    if not any(key in section for key in CORE):
        return Parsed(), ""
    try:
        return Parsed((_booking(section, rows),)), None
    except Unreadable as e:
        return Parsed(), str(e)
