from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import TypedDict

from sqlalchemy import func, select

from ..storage import db, reference
from ..storage.models import Airport
from . import airports, place_zones

SHOWN = 3
MOST = 4
AIRPORT_WORD = re.compile(r"([A-Z]{3})(?:\s+(?:international\s+)?airport)?", re.IGNORECASE)
UK_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b")
MIN_CITY = 3


class Stop(TypedDict):
    kind: str
    place: str


class Facts(TypedDict):
    name: str
    stops: list[Stop]


def phrase(places: Iterable[str], home: str | None = None) -> str:
    seen: dict[str, str] = {}
    for place in places:
        name = " ".join(place.split())
        if name:
            seen.setdefault(name.casefold(), name)
    names = list(seen.values())
    if home:
        away = [n for n in names if n.casefold() != " ".join(home.split()).casefold()]
        names = away or names
    if len(names) > MOST:
        return f"{', '.join(names[:SHOWN])} & {len(names) - SHOWN} more"
    if len(names) > 1:
        return f"{', '.join(names[:-1])} & {names[-1]}"
    return names[0] if names else ""


def _named(country: str, code: str | None = None) -> str | None:
    if country == "US" and code and (state := reference.airport_states().get(code.upper())):
        return state
    return reference.country_names().get(country)


def of_airport(conn: db.Connection, code: str | None) -> str | None:
    found = airports.lookup(conn, code) if code and len(code.strip()) == 3 else None
    return _named(found["country"], found["code"]) if found else None


def _city(conn: db.Connection, city: str) -> str | None:
    wanted = city.strip().lower()
    if not wanted:
        return None
    query = select(Airport.code, Airport.country).where(func.lower(Airport.city) == wanted)
    counts = Counter(_named(country, code) for code, country in conn.execute(query).fetchall())
    ranked = [(n, name) for name, n in counts.most_common(2) if name]
    if not ranked or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]


def of_place(conn: db.Connection, text: str | None, fallback: bool = True) -> str | None:
    clean = (text or "").strip()
    if not clean:
        return None
    code = AIRPORT_WORD.fullmatch(clean)
    if code and (code.group(1).isupper() or clean.lower().endswith("airport")) and (found := of_airport(conn, code.group(1))):
        return found
    return _city(conn, clean) or (clean if fallback else None)


def of_address(conn: db.Connection, address: str | None) -> str | None:
    parsed = place_zones.parse(address)
    if parsed.state and (name := place_zones.state_name(parsed.state)):
        return name
    if parsed.country:
        return _named(parsed.country)
    for token in parsed.tokens:
        city = UK_POSTCODE.sub("", place_zones.ZIP.sub("", place_zones.CA_POSTAL.sub("", token))).strip()
        if len(city) >= MIN_CITY and not city[0].isdigit() and (found := _city(conn, city)):
            return found
    return None
