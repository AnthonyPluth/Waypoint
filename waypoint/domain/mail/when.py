from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, time

from . import words

ISO = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
JAPANESE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
DOTTED = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
SLASHED = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
WORD = r"[^\W\d_]{3,}"
MONTH_FIRST = re.compile(rf"(?<![^\W\d_])({WORD})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})")
DAY_FIRST = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th|er|\.)?\s+(?:de\s+)?({WORD})\.?,?\s+(?:de\s+)?(\d{{4}})")
CLOCK = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})\s*([AaPp])?\.?[Mm]?\.?(?!\d)")
FRENCH_CLOCK = re.compile(r"(?<![\d:])(\d{1,2})\s?h\s?(\d{2})(?!\d)")
JP_CLOCK = re.compile(r"(\d{1,2})\s*時(?:\s*(\d{1,2})\s*分)?")


def month_number(word: str) -> int | None:
    lowered = word.lower().rstrip(".")
    return words.FULL_MONTHS.get(lowered) or words.ENGLISH_PREFIX.get(lowered[:3])


def _numeric(first: str, second: str, year: str) -> date | None:
    a, b = int(first), int(second)
    if a > 12 >= b:
        return date(int(year), b, a)
    if b > 12 >= a:
        return date(int(year), a, b)
    return None


def find_date(text: str) -> date | None:
    try:
        if m := ISO.search(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := JAPANESE.search(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := DOTTED.search(text):
            return date(int(m[3]), int(m[2]), int(m[1]))
        for m in MONTH_FIRST.finditer(text):
            if month := month_number(m[1]):
                return date(int(m[3]), month, int(m[2]))
        for m in DAY_FIRST.finditer(text):
            if month := month_number(m[2]):
                return date(int(m[3]), month, int(m[1]))
        if m := SLASHED.search(text):
            return _numeric(m[1], m[2], m[3])
    except ValueError:
        return None
    return None


Build = Callable[[re.Match[str]], date | None]


def _ymd(m: re.Match[str]) -> date | None:
    return date(int(m[1]), int(m[2]), int(m[3]))


def _dmy(m: re.Match[str]) -> date | None:
    return date(int(m[3]), int(m[2]), int(m[1]))


def _month_day_year(m: re.Match[str]) -> date | None:
    return date(int(m[3]), month_number(m[1]) or 0, int(m[2]))


def _day_month_year(m: re.Match[str]) -> date | None:
    return date(int(m[3]), month_number(m[2]) or 0, int(m[1]))


def _slashed(m: re.Match[str]) -> date | None:
    return _numeric(m[1], m[2], m[3])


FORMS: tuple[tuple[re.Pattern[str], Build], ...] = (
    (ISO, _ymd), (JAPANESE, _ymd), (DOTTED, _dmy), (MONTH_FIRST, _month_day_year), (DAY_FIRST, _day_month_year), (SLASHED, _slashed),
)


def date_spans(text: str) -> list[tuple[int, int, date]]:
    found: list[tuple[int, int, date]] = []
    for pattern, build in FORMS:
        for m in pattern.finditer(text):
            try:
                day = build(m)
            except ValueError:
                continue
            if day is not None:
                found.append((m.start(), m.end(), day))
    found.sort()
    spans: list[tuple[int, int, date]] = []
    for span in found:
        if not spans or span[0] >= spans[-1][1]:
            spans.append(span)
    return spans


def find_time(text: str) -> time | None:
    try:
        if m := CLOCK.search(text):
            hour, minute = int(m[1]), int(m[2])
            if m[3]:
                if not 1 <= hour <= 12:
                    return None
                hour = hour % 12 + (12 if m[3].lower() == "p" else 0)
            return time(hour, minute)
        if m := FRENCH_CLOCK.search(text):
            return time(int(m[1]), int(m[2]))
        if m := JP_CLOCK.search(text):
            return time(int(m[1]), int(m[2] or 0))
    except ValueError:
        return None
    return None


def stamp(day: date, at: time | None, fallback: time) -> str:
    return datetime.combine(day, at or fallback).strftime("%Y-%m-%dT%H:%M")
