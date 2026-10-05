"""What a flight import's parsers share: the rows they read, the flights they propose, and the small readers for the
cells every export has (a day, a time of day, an airport code, a flight number). A parser is a pure function from the
rows of one export to what each row proposes (`Proposed`) or why it can't be read (`Skipped`); it never looks anything up
(the airports' zones are for `resolve`) and it reads only the columns a flight needs: a notes column, a booking
reference or anyone's name in the file is never looked at, so it can't be kept."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

Row = Mapping[str, str]   # one data row: the cell under each header, headers as the file spells them, cells stripped
Numbered = tuple[int, Row]   # a row with its line in the file (the header is line 1)


@dataclass(frozen=True)
class Clock:
    """A time a file gives for a flight's departure or arrival, as written: the wall-clock `time` (HH:MM), the `day` it
    says it is on when it says (YYYY-MM-DD), and the UTC offset it carries, in minutes, when it has one (so the time can
    be put at the airport's own zone; a time with no offset is taken to be the airport's)."""
    time: str
    day: str | None = None
    offset: int | None = None


@dataclass(frozen=True)
class Proposed:
    """A flight a row proposes. `line` is the row's line in the file (the header is line 1)."""
    line: int
    day: str                          # the departure's local day, YYYY-MM-DD
    origin: str                       # IATA codes, upper case
    destination: str
    flight_number: str | None = None  # no spaces, upper case: EX101
    airline: str | None = None
    dep: Clock | None = None
    arr: Clock | None = None
    seat: str | None = None
    cabin: str | None = None


@dataclass(frozen=True)
class Skipped:
    """A row that can't be a flight, and why (a message for the person)."""
    line: int
    reason: str


Parser = Callable[[Sequence[Numbered]], list[Proposed | Skipped]]

_DAY = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_CLOCK = re.compile(r"(\d{1,2}):(\d\d)(?::\d\d(?:\.\d+)?)?")
_OFFSET = re.compile(r"(Z|[+-]\d\d:?\d\d)$")
_IATA = re.compile(r"[A-Za-z]{3}")
_PAREN_IATA = re.compile(r"\(([A-Za-z]{3})(?:\s*/\s*[A-Za-z]{4})?\)")
_FLIGHT = re.compile(r"(?:[A-Z][A-Z0-9]|[0-9][A-Z])\d{1,4}[A-Z]?")   # an airline's code (it has a letter), then the number


def shown(cell: str) -> str:
    """A cell, short enough to quote in a reason."""
    return cell if len(cell) <= 20 else cell[:19] + "…"


def day_of(cell: str) -> str | None:
    """The day in a cell that starts with one (2026-03-01, 2026-03-01 14:30, 2026-03-01T14:30:00Z), else None."""
    m = _DAY.match(cell.strip())
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return None


def clock_of(cell: str, day: str | None = None) -> Clock | None:
    """The time of day in a cell: 14:30, 14:30:00, 2026-03-01 14:30 or 2026-03-01T14:30:00-05:00. None for a cell with
    none (empty, or only a day), which is how a file says it doesn't know. Its offset is kept, never applied."""
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
    """An airport's IATA code from a cell that is one (SFO), or names one ("San Francisco Intl (SFO/KSFO)"); None when
    there's none to find."""
    text = cell.strip()
    if _IATA.fullmatch(text):
        return text.upper()
    m = _PAREN_IATA.search(text)
    return m[1].upper() if m else None


def flight_number_of(cell: str) -> str | None:
    """A flight number as it is kept (EX101: no spaces, upper case), or None when the cell isn't one."""
    text = re.sub(r"\s+", "", cell).upper()
    return text if _FLIGHT.fullmatch(text) else None


def text_of(cell: str | None, limit: int = 100) -> str | None:
    """A cell as a short text, or None when it's empty."""
    kept = (cell or "").strip()
    return kept[:limit] or None


def cell(row: Row, *names: str) -> str:
    """The first of these columns the row has, ignoring case and spaces in the header ("" when it has none)."""
    wanted = {re.sub(r"[\s_]+", "", n).casefold() for n in names}
    for header, value in row.items():
        if re.sub(r"[\s_]+", "", header).casefold() in wanted:
            return value
    return ""


def places(line: int, origin_cell: str, destination_cell: str) -> tuple[str, str] | Skipped:
    """A row's two airports, or why it hasn't got them."""
    found = []
    for label, text in (("origin", origin_cell), ("destination", destination_cell)):
        code = airport_of(text)
        if code is None:
            return Skipped(line, f"The {label} airport isn’t a three-letter code" + (f" (“{shown(text)}”)" if text else " (it’s empty)"))
        found.append(code)
    return found[0], found[1]

