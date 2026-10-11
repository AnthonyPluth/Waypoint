from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from . import labels, when, words
from .places import zone_of
from .parsers._text import lines

SEPARATOR = "\u2063"
CELL_END = re.compile(r"</t[dh]\s*>", re.IGNORECASE)
BAR = re.compile(r"\s*\|\s*")
TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9][A-Za-z0-9-]{3,24}(?![A-Za-z0-9])")
EDGE_WORDS = re.compile(r"^(?:at|on|from|until|after|before|le|à|um|am|ab|el)\s+|\s+(?:at|on|from|until|le|à|um|am|uhr|el)$", re.IGNORECASE)
CLOCKS = (when.CLOCK, when.FRENCH_CLOCK, when.JP_CLOCK)
FREE = frozenset({"start_place", "end_place", "location", "provider", "ship", "vehicle", "number", "confirmation"})
DATED = frozenset({"start", "end"})
Row = tuple[str, ...]


class Unreadable(Exception):
    pass


@dataclass(frozen=True)
class Hit:
    key: str
    label: str
    value: str
    row: int


@dataclass(frozen=True)
class Label:
    key: str
    label: str
    rest: str
    colon: bool


@dataclass(frozen=True)
class Place:
    name: str | None
    label: str
    same: bool
    zone: str | None


@dataclass(frozen=True)
class Point:
    place: Place
    day: date | None
    at: time | None
    day_label: str


Section = dict[str, list[Hit]]


def read_rows(html: str, text: str) -> list[Row]:
    marked = CELL_END.sub(lambda m: m[0] + SEPARATOR, html) if html.strip() else html
    rows: list[Row] = []
    for line in lines(marked, text):
        cells = tuple(cell for part in line.split(SEPARATOR) for cell in BAR.split(part) if cell.strip())
        if cells:
            rows.append(tuple(c.strip() for c in cells))
    return rows


def skipped(cells: Row) -> bool:
    line = " ".join(cells)
    return bool(words.CANCEL.search(line) or words.BOOKED.search(line) or labels.POLICY.search(line))


def mentions(rows: list[Row], about: re.Pattern[str]) -> bool:
    return any(about.search(" ".join(cells)) for cells in rows if not skipped(cells))


class Table:
    def __init__(self, table: labels.Table) -> None:
        self.ordered = sorted(((w.lower(), key) for key, options in table.items() for w in options), key=lambda p: -len(p[0]))

    def match(self, cell: str) -> Label | None:
        bare = cell.replace("’", "'").lstrip("•*·-–— \t")
        low = bare.lower()
        for word, key in self.ordered:
            if not low.startswith(word):
                continue
            after = bare[len(word):]
            if after[:1].isalnum():
                continue
            colon = after.lstrip()[:1] in (":", "：", "#")
            rest = after.lstrip(" :：#.-–—").strip()
            if after.lstrip().startswith("/") and (other := self.match(after.lstrip()[1:].strip())) and other.key == key:
                return Label(key, word, other.rest, colon or other.colon)
            return Label(key, word, rest, colon)
        return None

    def hits(self, rows: list[Row]) -> list[Hit]:
        out: list[Hit] = []
        n = 0
        while n < len(rows):
            cells = rows[n]
            if skipped(cells):
                n += 1
                continue
            found = [self.match(c) for c in cells]
            below = rows[n + 1] if n + 1 < len(rows) else ()
            if (len(cells) >= 2 and all(f and not f.rest for f in found) and len(below) == len(cells)
                    and not skipped(below) and not any(self.match(c) for c in below)):
                out += [Hit(f.key, f.label, v, n) for f, v in zip(found, below, strict=True) if f]
                n += 2
                continue
            for i, f in enumerate(found):
                if f is None:
                    continue
                value, separated = f.rest, f.colon
                if not value and i + 1 < len(cells) and found[i + 1] is None:
                    value, separated = cells[i + 1], True
                elif not value and i == len(cells) - 1 and len(below) == 1 and not skipped(below) and self.match(below[0]) is None:
                    value, separated = below[0], True
                if not value or (f.key in FREE and not separated) or (f.key in DATED and not separated and not when.date_spans(value)):
                    continue
                out.append(Hit(f.key, f.label, value, n))
            n += 1
        return out


def sections(found: list[Hit], split: frozenset[str]) -> list[Section]:
    out: list[Section] = [{}]
    for h in found:
        current = out[-1]
        if h.key in split and h.key in current and (h.key not in DATED or any(when.date_spans(x.value) for x in current[h.key])):
            out.append({})
            current = out[-1]
        current.setdefault(h.key, []).append(h)
    return [s for s in out if s]


def _without_times(value: str) -> str:
    spans = [(a, b) for a, b, _ in when.date_spans(value)] + [(m.start(), m.end()) for pattern in CLOCKS for m in pattern.finditer(value)]
    out, at = [], 0
    for a, b in sorted(spans):
        if a < at:
            continue
        left = re.sub(rf"(?:{labels.WEEKDAYS.pattern})\.?,?\s*$", "", value[at:a], flags=re.IGNORECASE)
        out.append(left)
        at = b
    out.append(value[at:])
    return "".join(out)


def _balanced(text: str) -> str:
    if text.count(")") > text.count("("):
        return text.rstrip(")") if text.endswith(")") else text
    if text.count("(") > text.count(")"):
        return text.rstrip("(")
    return text


def clean(value: str) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"[(\[]\s*[)\]]", " ", _without_times(value))).strip(" ,;:|-–—/@·[]")
    while (trimmed := _balanced(EDGE_WORDS.sub("", text).strip(" ,;:|-–—/@·[]"))) != text:
        text = trimmed
    return text


def code(value: str) -> str | None:
    for m in TOKEN.finditer(value):
        token = m[0]
        if any(c.isdigit() for c in token) or (token.isalpha() and token.isupper() and len(token) >= 5):
            return token.upper()
    return None


def confirmation(found: list[Hit]) -> tuple[str, str] | None:
    return next(((c, h.label) for h in found if (c := code(h.value))), None)


def named(found: list[Hit], limit: int) -> tuple[str, str] | None:
    return next(((text[:limit], h.label) for h in found if (text := clean(h.value))), None)


def place_of(found: list[Hit]) -> Place:
    same, label = False, ""
    for h in found:
        text = clean(h.value)
        if not text:
            continue
        if labels.SAME.match(text):
            same, label = True, h.label
            continue
        return Place(text[:100], h.label, False, zone_of(text))
    return Place(None, label, same, None)


def point(section: Section, role: str, rows: list[Row], table: Table) -> Point:
    day_hits = section.get(f"{role}_date", []) + section.get(role, []) + section.get(f"{role}_place", [])
    day_hit = next((h for h in day_hits if when.find_date(h.value)), None)
    at = next((t for h in section.get(f"{role}_time", []) + day_hits if (t := when.find_time(h.value))), None)
    if at is None and day_hit is not None and day_hit.row + 1 < len(rows):
        below = rows[day_hit.row + 1]
        if len(below) == 1 and table.match(below[0]) is None and not skipped(below) and when.find_date(below[0]) is None:
            at = when.find_time(below[0])
    day = when.find_date(day_hit.value) if day_hit else None
    return Point(place_of(section.get(f"{role}_place", []) + section.get(role, [])), day, at, day_hit.label if day_hit else "")


def instant(day: date, at: time, zone: str) -> datetime:
    return datetime.combine(day, at, tzinfo=ZoneInfo(zone))
