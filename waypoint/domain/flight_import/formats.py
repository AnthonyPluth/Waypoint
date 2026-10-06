from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

Row = Mapping[str, str]
Numbered = tuple[int, Row]


@dataclass(frozen=True)
class Clock:
    time: str
    day: str | None = None
    offset: int | None = None


@dataclass(frozen=True)
class Proposed:
    line: int
    day: str
    origin: str
    destination: str
    flight_number: str | None = None
    airline: str | None = None
    dep: Clock | None = None
    arr: Clock | None = None
    seat: str | None = None
    cabin: str | None = None


@dataclass(frozen=True)
class Skipped:
    line: int
    reason: str


Parser = Callable[[Sequence[Numbered]], list[Proposed | Skipped]]

_DAY = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_CLOCK = re.compile(r"(\d{1,2}):(\d\d)(?::\d\d(?:\.\d+)?)?")
_OFFSET = re.compile(r"(Z|[+-]\d\d:?\d\d)$")
_IATA = re.compile(r"[A-Za-z]{3}")
_PAREN_IATA = re.compile(r"\(([A-Za-z]{3})(?:\s*/\s*[A-Za-z]{4})?\)")
_FLIGHT = re.compile(r"(?:[A-Z][A-Z0-9]|[0-9][A-Z])\d{1,4}[A-Z]?")


def shown(cell: str) -> str:
    return cell if len(cell) <= 20 else cell[:19] + "…"


def day_of(cell: str) -> str | None:
    m = _DAY.match(cell.strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


def clock_of(cell: str, day: str | None = None) -> Clock | None:
    text = cell.strip()
    when = day
    m = _DAY.match(text)
    if m:
        when, text = day_of(text), text[m.end():].lstrip(" T")
    offset: int | None = None
    z = _OFFSET.search(text)
    if z:
        text = text[:z.start()].strip()
        offset = 0 if z[1] == "Z" else (1 if z[1][0] == "+" else -1) * (int(z[1][1:3]) * 60 + int(z[1][-2:]))
    c = _CLOCK.fullmatch(text)
    if not c or int(c[1]) > 23 or int(c[2]) > 59:
        return None
    return Clock(f"{int(c[1]):02d}:{c[2]}", when, offset)


def airport_of(cell: str) -> str | None:
    text = cell.strip()
    if _IATA.fullmatch(text):
        return text.upper()
    m = _PAREN_IATA.search(text)
    return m[1].upper() if m else None


def flight_number_of(cell: str) -> str | None:
    text = re.sub(r"\s+", "", cell).upper()
    return text if _FLIGHT.fullmatch(text) else None


def text_of(cell: str | None, limit: int = 100) -> str | None:
    kept = (cell or "").strip()
    return kept[:limit] or None


def cell(row: Row, *names: str) -> str:
    wanted = {re.sub(r"[\s_]+", "", n).casefold() for n in names}
    for header, value in row.items():
        if re.sub(r"[\s_]+", "", header).casefold() in wanted:
            return value
    return ""


def places(line: int, origin_cell: str, destination_cell: str) -> tuple[str, str] | Skipped:
    found = []
    for label, text in (("origin", origin_cell), ("destination", destination_cell)):
        code = airport_of(text)
        if code is None:
            return Skipped(line, f"The {label} airport isn’t a three-letter code" + (f" (“{shown(text)}”)" if text else " (it’s empty)"))
        found.append(code)
    return found[0], found[1]

