from __future__ import annotations

from datetime import time, timedelta

from . import fields, labels, when
from .booking import Booking, Parsed
from .fields import Unreadable

MAX_DAYS = 200
EMBARK = time(12, 0)
DISEMBARK = time(8, 0)
TABLE = fields.Table(labels.table("cruise"))
ABOUT = labels.about("cruise")
CORE = ("start", "start_place", "start_date", "end", "end_place", "end_date")


def _booking(section: fields.Section, rows: list[fields.Row]) -> Booking:
    embark, disembark = fields.point(section, "start", rows, TABLE), fields.point(section, "end", rows, TABLE)
    ship, line = fields.named(section.get("ship", []), 100), fields.named(section.get("provider", []), 100)
    if ship is None and line is None:
        raise Unreadable("no ship or cruise line found")
    if embark.place.name is None or disembark.place.name is None:
        raise Unreadable("no embarkation and disembarkation port found")
    if embark.day is None or disembark.day is None:
        raise Unreadable("no embarkation and disembarkation date found")
    if embark.place.zone is None or disembark.place.zone is None:
        raise Unreadable("port's time zone unknown")
    first = fields.instant(embark.day, embark.at or EMBARK, embark.place.zone)
    last = fields.instant(disembark.day, disembark.at or DISEMBARK, disembark.place.zone)
    if last <= first:
        raise Unreadable("disembarkation isn't after embarkation")
    if last - first > timedelta(days=MAX_DAYS):
        raise Unreadable(f"cruise is longer than {MAX_DAYS} days")
    sources = {"origin": embark.place.label, "destination": disembark.place.label, "start_local": embark.day_label, "end_local": disembark.day_label}
    code = fields.confirmation(section.get("confirmation", []))
    sources.update({key: found[1] for key, found in (("confirmation", code), ("provider", line)) if found})
    untimed = "yes" if embark.at is None or disembark.at is None else None
    details = tuple((k, v) for k, v in (("ship", ship[0] if ship else None), ("time_unknown", untimed)) if v)
    return Booking("cruise", "confirmed", code[0] if code else None, line[0] if line else None, when.stamp(embark.day, embark.at, EMBARK),
                   when.stamp(disembark.day, disembark.at, DISEMBARK), embark.place.name, disembark.place.name,
                   details=details, start_zone=embark.place.zone, end_zone=disembark.place.zone, generic=tuple(sources.items()))


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
