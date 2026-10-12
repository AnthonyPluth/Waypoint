from __future__ import annotations

import re
from dataclasses import dataclass

from . import seats, words

CODE = re.compile(r"(?<![A-Za-z0-9-])[A-Za-z0-9][A-Za-z0-9-]{3,22}[A-Za-z0-9](?![A-Za-z0-9-])")
LABELLED = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in sorted(words.CONFIRMATION, key=len, reverse=True)) + r")\s*(?:[:：#]|\bis\b)?\s*"
    r"(?P<code>[A-Za-z0-9][A-Za-z0-9-]{3,22}[A-Za-z0-9])(?![A-Za-z0-9-])", re.IGNORECASE)
SEAT = re.compile(r"\bseat\s*(?:number|no\.?)?\s*[:#]?\s*(?-i:\d{1,3}[A-Z])\b", re.IGNORECASE)
TERMINAL = re.compile(r"\bterminal\s*[:#]?\s*(?-i:[A-Z0-9]{1,2})\b", re.IGNORECASE)
GATE = re.compile(r"\bgate\s*[:#]?\s*(?-i:[A-Z]?\d{1,3}[A-Z]?)\b", re.IGNORECASE)
ADDRESS = re.compile(r"^\s*(?:address|住所|所在地)\s*[:：]\s*\S", re.IGNORECASE | re.MULTILINE)
CHANGED = re.compile(
    r"\b(?:has|have|had|was|were|is|are|been|being)\s+(?:been\s+)?(?:cancel(?:l)?ed|modified|amended|changed|rescheduled|rebooked)"
    r"|\bwe(?:'ve|’ve| have)\s+(?:cancel(?:l)?ed|modified|amended|changed|rescheduled)"
    r"|\byour (?:booking|reservation|stay|flight|trip|itinerary)\b.{0,40}\b(?:cancel(?:l)?ed|changed|modified|rescheduled)", re.IGNORECASE)
MIN_LENGTH = 5
MAX_TOKENS = 4000
FACT_DETAIL: dict[str, str | None] = {"seat": "seat", "terminal": "terminal", "gate": None, "address": "address"}


@dataclass(frozen=True)
class Found:
    codes: frozenset[str] = frozenset()
    reference: str | None = None
    facts: frozenset[str] = frozenset()


def normal(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def _looks_like_a_code(code: str) -> bool:
    return any(c.isdigit() for c in code) or (code.isupper() and 5 <= len(code) <= 10)


def labelled(text: str) -> frozenset[str]:
    return frozenset(n for m in LABELLED.finditer(text) if _looks_like_a_code(m["code"]) and len(n := normal(m["code"])) >= MIN_LENGTH)


def changes(text: str) -> bool:
    return CHANGED.search(text) is not None


def facts_in(text: str) -> frozenset[str]:
    found = {"seat" if SEAT.search(text) or seats.SEAT_WORD.search(text) else "", "terminal" if TERMINAL.search(text) else "",
             "gate" if GATE.search(text) else "", "address" if ADDRESS.search(text) else ""}
    return frozenset(found - {""})


def read(subject: str, text: str) -> Found:
    whole = f"{subject}\n{text}"
    named = labelled(whole)
    tokens: set[str] = set(named)
    for match in CODE.finditer(whole):
        if len(tokens) >= MAX_TOKENS:
            break
        if any(c.isdigit() for c in match[0]) and len(n := normal(match[0])) >= MIN_LENGTH:
            tokens.add(n)
    return Found(frozenset(tokens), next(iter(named)) if len(named) == 1 else None, facts_in(whole))
