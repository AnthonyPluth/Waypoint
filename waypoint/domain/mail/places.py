from __future__ import annotations

import re
import unicodedata
from collections import Counter
from functools import cache

from ...storage import reference
from .. import place_zones

AIRPORT = re.compile(r"[(\[]\s*([A-Z]{3})\s*[)\]]|^([A-Z]{3})\s*(?:[-–—,:/]|$)|(?<![A-Za-z])([A-Z]{3})\s+(?i:airport|international|intl)\b|(?i:airport)\s+([A-Z]{3})(?![A-Za-z])")
STATE = re.compile(r",\s*(" + "|".join(place_zones.US_STATES) + r")(?![A-Za-z])")
SHORT_COUNTRIES = {name: code for name, code in place_zones.COUNTRIES.items() if len(name) <= 3}
LONG_COUNTRIES = {name.upper(): code for name, code in place_zones.COUNTRIES.items() if len(name) > 3}
SHORT_COUNTRY = re.compile(r"(?<![A-Za-z])(" + "|".join(map(re.escape, SHORT_COUNTRIES)) + r")(?![A-Za-z])")
LONG_COUNTRY = re.compile(r"(?<![^\W\d_])(" + "|".join(re.escape(n) for n in sorted(LONG_COUNTRIES, key=len, reverse=True)) + r")(?![^\W\d_])", re.IGNORECASE)
COMMON_WORDS = frozenset({"central", "union", "nice", "station", "airport", "port", "city", "north", "south", "east", "west", "centre", "center",
                          "terminal", "international", "gare", "harbor", "harbour", "main"})
Entries = tuple[tuple[str, str], ...]


def fold(text: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", plain).strip()


@cache
def _cities() -> dict[str, Entries]:
    grouped: dict[str, list[tuple[str, str]]] = {}
    for city, country, zone in reference.airport_places():
        grouped.setdefault(fold(city), []).append((country, zone))
    return {name: tuple(entries) for name, entries in grouped.items()}


def _countries(text: str) -> set[str]:
    return ({SHORT_COUNTRIES[m[1]] for m in SHORT_COUNTRY.finditer(text)}
            | {LONG_COUNTRIES[m[1].upper()] for m in LONG_COUNTRY.finditer(text)})


def _state_zones(state: str) -> set[str]:
    default, exceptions = place_zones.US_STATES[state]
    return {zone for zone in (default, *exceptions.values()) if zone}


def _one_zone(entries: Entries) -> str | None:
    zones = {zone for _, zone in entries}
    if len(zones) == 1:
        return next(iter(zones))
    country, count = Counter(c for c, _ in entries).most_common(1)[0]
    in_country = {zone for c, zone in entries if c == country}
    return next(iter(in_country)) if count * 2 > len(entries) and len(in_country) == 1 else None


def zone_of(text: str) -> str | None:
    known = reference.airport_zones()
    codes = {code for m in AIRPORT.finditer(text.strip()) for code in m.groups() if code}
    by_code = {known[c] for c in codes if c in known and c not in place_zones.COUNTRIES}
    if by_code:
        return next(iter(by_code)) if len(by_code) == 1 else None
    named = _countries(text)
    state = STATE.search(text)
    american = "US" in named or state is not None
    if len(named - {"US"}) > 1 or (american and named - {"US"}):
        return None
    cities = _cities()
    tokens = fold(text).split()
    zones: set[str | None] = set()
    at = 0
    while at < len(tokens):
        for size in (4, 3, 2, 1):
            name = " ".join(tokens[at:at + size])
            if len(tokens[at:at + size]) != size or name not in cities or (size == 1 and (name in COMMON_WORDS or len(name) < 4)):
                continue
            entries = cities[name]
            if named:
                entries = tuple(e for e in entries if e[0] in named)
            elif american:
                entries = tuple(e for e in entries if e[0] == "US")
            else:
                entries = tuple(e for e in entries if e[0] != "US")
            if state:
                default = place_zones.US_STATES[state[1]][0]
                entries = tuple(e for e in entries if e[1] == default) or tuple(e for e in entries if e[1] in _state_zones(state[1]))
            zones.add(_one_zone(entries) if entries else None)
            at += size
            break
        else:
            at += 1
    return next(iter(zones)) if len(zones) == 1 else None
