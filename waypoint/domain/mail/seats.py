from __future__ import annotations

import re

from .. import seatmaps

SEAT_WORD = re.compile(r"(?<![A-Za-z0-9])(\d{1,3}\s?[A-Za-z])\s*[(\[,:–-]?\s*(window|aisle|middle)\b\)?", re.IGNORECASE)
AIRCRAFT_TEXT = re.compile(r"(?<![A-Za-z])(?:boeing|airbus|embraer|bombardier)\s+[A-Za-z0-9][A-Za-z0-9-]*(?:\s+(?:neo|max|ceo))?",
                           re.IGNORECASE)


def seat_with_position(text: str | None) -> tuple[str | None, str | None]:
    kept = " ".join((text or "").split())
    found = SEAT_WORD.search(kept)
    if found is None:
        return kept or None, None
    return re.sub(r"\s+", "", found[1]).upper(), found[2].casefold()


def aircraft_in(text: str | None) -> str | None:
    found = AIRCRAFT_TEXT.search(text or "")
    return seatmaps.family(found[0]) if found else None
