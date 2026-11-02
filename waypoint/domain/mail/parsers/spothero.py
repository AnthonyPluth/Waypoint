from __future__ import annotations

import re
from datetime import date, timedelta

from ..booking import Booking, Parsed, Status
from ._text import clock, lines

PROVIDER = "SpotHero"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
STAMP = r"([A-Za-z]{3})[a-z]*,?\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{1,2}):(\d{2})\s*([AaPp])\.?[Mm]"
RANGE = re.compile(rf"^{STAMP}\s*[-–—]\s*{STAMP}$")
CONFIRMATION = re.compile(r"^(?:rental|reservation|booking)\s*(?:id|number|#)\s*:?\s*([A-Za-z0-9][A-Za-z0-9-]{3,19})$", re.IGNORECASE)
ENTRANCE = re.compile(r"^enter at\s*:?\s*(\S.{0,198})$", re.IGNORECASE)
DIRECTIONS = re.compile(r"\s*get directions$", re.IGNORECASE)
PHONE = re.compile(r"^\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}$")
CANCELLED = re.compile(r"reservation\s+(?:has\s+been\s+)?cancell?ed|cancell?ation\s+confirm", re.IGNORECASE)
HEADLINE = 6
WINDOW = 800
LOT_LIMIT = 100


def _day(stamp: tuple[str, ...], received: date, after: date | None = None) -> date | None:
    weekday, month, number = DAYS.index(stamp[0].lower()) if stamp[0].lower() in DAYS else -1, MONTHS.get(stamp[1].lower()), int(stamp[2])
    if weekday < 0 or month is None:
        return None
    found: list[date] = []
    for year in range(received.year - 2, received.year + 4):
        try:
            candidate = date(year, month, number)
        except ValueError:
            continue
        if candidate.weekday() == weekday and (after is None or candidate >= after):
            found.append(candidate)
    if after is not None:
        return found[0] if found and found[0] - after < timedelta(days=366) else None
    near = [d for d in found if abs((d - received).days) <= WINDOW]
    return min(near, key=lambda d: abs((d - received).days)) if near else None


def _stamp(day: date, stamp: tuple[str, ...]) -> str | None:
    at = clock(int(stamp[3]), int(stamp[4]), stamp[5])
    return f"{day.isoformat()}T{at.isoformat(timespec='seconds')}" if at else None


def parse(html: str, text: str, received: str | None = None) -> Parsed:
    rows = lines(html, text)
    spot = next((i for i, row in enumerate(rows) if RANGE.match(row)), None)
    if spot is None:
        return Parsed()
    try:
        sent = date.fromisoformat(received or "")
    except ValueError:
        return Parsed((), 1)
    lot = rows[spot - 1][:LOT_LIMIT].strip() if spot else ""
    both = RANGE.match(rows[spot])
    if not lot or CONFIRMATION.match(lot) or both is None:
        return Parsed((), 1)
    first, last = both.groups()[:6], both.groups()[6:]
    entry = _day(first, sent)
    leave = _day(last, sent, entry) if entry else None
    start, end = (_stamp(entry, first), _stamp(leave, last)) if entry and leave else (None, None)
    if not start or not end or end <= start:
        return Parsed((), 1)
    code = next((m[1] for row in rows if (m := CONFIRMATION.match(row))), None)
    address = next((DIRECTIONS.sub("", m[1]).strip() for row in rows if (m := ENTRANCE.match(row))), None)
    phone = next((row for row in rows[spot + 1:] if PHONE.match(row)), None)
    details = tuple((k, v) for k, v in (("address", address), ("phone", phone)) if v)
    status: Status = "cancelled" if any(CANCELLED.search(row) for row in rows[:HEADLINE]) else "confirmed"
    return Parsed((Booking("parking", status, code, PROVIDER, start, end, lot, None, details=details),))
