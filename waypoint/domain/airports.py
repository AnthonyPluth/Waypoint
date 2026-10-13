from __future__ import annotations

import math
from functools import cache
from typing import NamedTuple, TypedDict

from sqlalchemy import func, select

from ..storage import db, reference
from ..storage.models import Airport


MAX_MATCHES = 8


class Found(TypedDict):
    code: str
    name: str
    city: str
    country: str
    zone: str


def lookup(conn: db.Connection, code: str) -> Found | None:
    a = conn.orm.get(Airport, code.strip().upper())
    return {"code": a.code, "name": a.name, "city": a.city, "country": a.country, "zone": a.zone} if a else None


class _Entry(NamedTuple):
    found: Found
    code: str
    city: str
    name: str
    words: tuple[str, ...]


def _key(text: str) -> str:
    return " ".join("st" if word == "saint" else word for word in reference.place_key(text).split())


@cache
def _index() -> tuple[_Entry, ...]:
    entries = []
    for row in reference.airport_rows():
        city, name = _key(row["city"]), _key(row["name"])
        found: Found = {"code": row["code"], "name": row["name"], "city": row["city"], "country": row["country"], "zone": row["zone"]}
        entries.append(_Entry(found, row["code"].casefold(), city, name, tuple(dict.fromkeys(f"{city} {name}".split()))))
    return tuple(entries)


def _tier(entry: _Entry, query: str, tokens: list[str]) -> int | None:
    if entry.code == query:
        return 0
    if entry.city.startswith(query):
        return 1
    if entry.name.startswith(query):
        return 2
    if all(any(word.startswith(token) for word in entry.words) for token in tokens):
        return 3
    if len(tokens) == 1 and entry.code.startswith(query):
        return 4
    return None


def search(conn: db.Connection, text: str, limit: int = MAX_MATCHES) -> list[Found]:
    query = _key(" ".join(text.split())[:60])
    if len(query) < 2:
        return []
    tokens = query.split()
    ranked = [(tier, entry.city, entry.code, entry.found) for entry in _index() if (tier := _tier(entry, query, tokens)) is not None]
    return [found for _tier_, _city, _code, found in sorted(ranked, key=lambda r: r[:3])[:limit]]


def zones(conn: db.Connection, codes: list[str]) -> dict[str, str]:
    wanted = [c.strip().upper() for c in codes]
    return dict(conn.execute(select(Airport.code, Airport.zone).where(Airport.code.in_(wanted))).fetchall())


def coords(conn: db.Connection, code: str) -> tuple[float, float] | None:
    a = conn.orm.get(Airport, code.strip().upper())
    return (a.latitude, a.longitude) if a else None


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def zone_for_place(conn: db.Connection, city: str | None, country: str | None) -> str | None:
    wanted_country = (country or "").strip().upper()
    if city and city.strip():
        q = select(Airport.zone).where(func.lower(Airport.city) == city.strip().lower())
        if wanted_country:
            q = q.where(Airport.country == wanted_country)
        by_city: set[str] = set(conn.execute(q).scalars())
        if len(by_city) == 1:
            return by_city.pop()
    if wanted_country:
        by_country: set[str] = set(conn.execute(select(Airport.zone).where(Airport.country == wanted_country)).scalars())
        if len(by_country) == 1:
            return by_country.pop()
    return None
