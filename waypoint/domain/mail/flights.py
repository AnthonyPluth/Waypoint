from __future__ import annotations

import re
from dataclasses import dataclass, replace
from itertools import pairwise
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from ...storage import reference
from . import when, words
from .booking import Booking, Parsed
from .parsers._text import lines

MAX_HOURS = 30
NUMBER = re.compile(r"(?<![\w:.#-])([A-Z][A-Z0-9]|[0-9][A-Z])\s?(\d{1,4})(?![\w:])")
AIRPORT = re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}(?![A-Za-z0-9])")
ARROW = re.compile(r"[→>⇒✈➔]|->")
CODE = re.compile(r"(?<![A-Za-z0-9])[A-Z0-9]{5,10}(?![A-Za-z0-9])")
NOT_AIRLINES = {"AM", "PM"}
Hint = Literal["dep", "arr"] | None


class Unreadable(Exception):
    pass


@dataclass(frozen=True)
class _Stamp:
    day: date
    at: time
    hint: Hint


def _number(row: str) -> tuple[str, str] | None:
    airlines = reference.airline_names()
    for m in NUMBER.finditer(row):
        if m[1] in airlines and m[1] not in NOT_AIRLINES:
            return m[1], m[2]
    return None


def _usable(row: str) -> bool:
    return not words.CANCEL.search(row) and not words.BOOKED.search(row)


def _labelled_code(row: str) -> bool:
    lowered = row.lower()
    return any(label in lowered for label in words.CONFIRMATION)


def _hint(row: str) -> Hint:
    leaving, arriving = bool(words.DEPARTURE.search(row)), bool(words.ARRIVAL.search(row))
    return "dep" if leaving and not arriving else "arr" if arriving and not leaving else None


def _label(row: str, key: Literal["dep", "arr"]) -> str:
    found = (words.DEPARTURE if key == "dep" else words.ARRIVAL).search(row)
    return found[0].lower() if found else ("departure" if key == "dep" else "arrival")


def _legs(rows: list[str]) -> list[tuple[str, str, int, int]]:
    starts = [(n, hit) for n, row in enumerate(rows) if _usable(row) and not _labelled_code(row) and (hit := _number(row))]
    legs: list[tuple[str, str, int, int]] = []
    for at, (n, (code, digits)) in enumerate(starts):
        end = starts[at + 1][0] if at + 1 < len(starts) else len(rows)
        if legs and legs[-1][:2] == (code, digits) and sum(1 for r in rows[legs[-1][2]:n] if when.date_spans(r)) < 2:
            legs[-1] = (code, digits, legs[-1][2], end)
        else:
            legs.append((code, digits, n, end))
    return legs


def _markers(row: str, known: dict[str, str]) -> list[int]:
    found = [m.start() for m in AIRPORT.finditer(row) if m[0] in known]
    found += [m.start() for m in words.DEPARTURE.finditer(row)] + [m.start() for m in words.ARRIVAL.finditer(row)]
    return sorted(found)


def _pieces(row: str, known: dict[str, str]) -> list[str]:
    spans = when.date_spans(row)
    if len(spans) < 2:
        return [row]
    markers = _markers(row, known)
    cuts = [0]
    for (_, left_end, _), (right_start, _, _) in pairwise(spans):
        between = [m for m in markers if left_end <= m < right_start]
        cuts.append(between[-1] if between else (left_end + right_start) // 2)
    cuts.append(len(row))
    return [row[a:b] for a, b in pairwise(cuts)]


def _eligible(row: str) -> bool:
    return bool(when.date_spans(row) or _number(row) or ARROW.search(row) or "(" in row or _hint(row)
                or any(row.lower().startswith(label) for label in words.ORIGIN + words.DESTINATION))


def _airports(rows: list[str], known: dict[str, str]) -> list[str]:
    found: list[str] = []
    for row in rows:
        if not _usable(row) or not _eligible(row):
            continue
        found += [m[0] for m in AIRPORT.finditer(row) if m[0] in known]
    return list(dict.fromkeys(found))


def _stamps(rows: list[str], known: dict[str, str]) -> list[_Stamp]:
    found: list[_Stamp] = []
    for n, row in enumerate(rows):
        if not _usable(row):
            continue
        for piece in _pieces(row, known):
            day = when.find_date(piece)
            if day is None:
                continue
            at = when.find_time(piece[when.date_spans(piece)[0][0]:] if when.date_spans(piece) else piece)
            rest = rows[n + 1] if n + 1 < len(rows) else ""
            if at is None and when.find_date(rest) is None and _usable(rest):
                at = when.find_time(rest)
            if at is None:
                continue
            before = rows[n - 1] if n else ""
            hint = _hint(piece) or (_hint(before) if n and when.find_date(before) is None and not _airports([before], known) else None)
            found.append(_Stamp(day, at, hint))
    return found


def _pick(stamps: list[_Stamp]) -> tuple[_Stamp, _Stamp]:
    if len(stamps) < 2:
        raise Unreadable("no departure and arrival date and time found")
    if len(stamps) == 2:
        first, second = stamps
        return (second, first) if first.hint == "arr" and second.hint == "dep" else (first, second)
    leaving, arriving = [s for s in stamps if s.hint == "dep"], [s for s in stamps if s.hint == "arr"]
    if len(leaving) == 1 and len(arriving) == 1:
        return leaving[0], arriving[0]
    raise Unreadable("more than two dates and times for one flight")


def _confirmation(rows: list[str]) -> tuple[str, str] | None:
    for row in rows:
        if not _usable(row):
            continue
        lowered = row.lower()
        for label in words.CONFIRMATION:
            at = lowered.find(label)
            if at < 0 or (label.isascii() and at and lowered[at - 1].isalnum()):
                continue
            if found := CODE.search(row[at + len(label):]):
                return label, found[0]
    return None


def _instant(day: date, at: time, zone: str) -> datetime:
    return datetime.combine(day, at, tzinfo=ZoneInfo(zone))


def _leg(code: str, digits: str, rows: list[str], known: dict[str, str]) -> tuple[Booking, dict[str, str]]:
    ports = _airports(rows, known)
    if len(ports) < 2:
        raise Unreadable("fewer than two known airports found for the flight")
    if len(ports) > 2:
        raise Unreadable("more than two airports found for one flight")
    leaves, arrives = _pick(_stamps(rows, known))
    origin, destination = ports
    start_zone, end_zone = known[origin], known[destination]
    departure, arrival = _instant(leaves.day, leaves.at, start_zone), _instant(arrives.day, arrives.at, end_zone)
    if arrival <= departure:
        raise Unreadable("arrival isn't after departure")
    if arrival - departure > timedelta(hours=MAX_HOURS):
        raise Unreadable(f"flight is longer than {MAX_HOURS} hours")
    sources = {"origin": "airport code", "destination": "airport code", "start_local": _label(" ".join(rows), "dep") if leaves.hint else "departure",
               "end_local": _label(" ".join(rows), "arr") if arrives.hint else "arrival"}
    name = reference.airline_names().get(code)
    booking = Booking("flight", "confirmed", None, name, departure.strftime("%Y-%m-%dT%H:%M"), arrival.strftime("%Y-%m-%dT%H:%M"),
                      origin, destination, details=(("flight_number", f"{code} {digits}"),))
    return booking, sources


def read(html: str, text: str) -> tuple[Parsed, str | None]:
    rows = lines(html, text)
    legs = _legs(rows)
    if not legs:
        return Parsed(), ""
    known = reference.airport_zones()
    made: list[Booking] = []
    kept: list[tuple[str, str, int, int]] = []
    failed: list[str] = []
    for at, (code, digits, start, end) in enumerate(legs):
        body = rows[start:end]
        try:
            try:
                booking, sources = _leg(code, digits, body, known)
            except Unreadable:
                if at:
                    raise
                booking, sources = _leg(code, digits, rows[:end], known)
        except Unreadable as e:
            failed.append(str(e))
            continue
        made.append(replace(booking, generic=tuple(sources.items())))
        kept.append((code, digits, start, end))
    if not made:
        return Parsed(), failed[0] if failed else ""
    shared = _confirmation(rows)
    unique: dict[tuple[str, str, str], Booking] = {}
    for b, (_, _, begin, finish) in zip(made, kept, strict=True):
        found = _confirmation(rows[begin:finish]) or shared
        if found:
            b = replace(b, confirmation=found[1], generic=(*b.generic, ("confirmation", found[0])))
        unique.setdefault((dict(b.details)["flight_number"], b.origin or "", b.start), b)
    return Parsed(tuple(unique.values()), unread=len(failed)), None


def parse(html: str, text: str) -> Parsed:
    return read(html, text)[0]
