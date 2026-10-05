"""Airports by IATA code: where a flight's times are written. A flight's start and end zones come from its airports
(waypoint/storage/airports.tsv.gz, loaded by migration 0005), and a person can still name a zone by hand for an airport
the list doesn't have."""
from __future__ import annotations

import math
from typing import TypedDict

from sqlalchemy import func, select

from ..storage import db
from ..storage.models import Airport


class Found(TypedDict):
    code: str
    name: str
    city: str
    country: str
    zone: str


def lookup(conn: db.Connection, code: str) -> Found | None:
    """The airport with this IATA code (any case), or None."""
    a = conn.orm.get(Airport, code.strip().upper())
    return {"code": a.code, "name": a.name, "city": a.city, "country": a.country, "zone": a.zone} if a else None


def zones(conn: db.Connection, codes: list[str]) -> dict[str, str]:
    """The zone of each known code among `codes`."""
    wanted = [c.strip().upper() for c in codes]
    return dict(conn.execute(select(Airport.code, Airport.zone).where(Airport.code.in_(wanted))).fetchall())


def coords(conn: db.Connection, code: str) -> tuple[float, float] | None:
    """An airport's latitude and longitude, or None for a code the list doesn't have."""
    a = conn.orm.get(Airport, code.strip().upper())
    return (a.latitude, a.longitude) if a else None


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The great-circle distance between two places (latitude, longitude), in kilometres."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def zone_for_place(conn: db.Connection, city: str | None, country: str | None) -> str | None:
    """The time zone of a place that has no airport code (a hotel, a rental office, a station), from where the booking says
    it is: a city the airports know, in that country when it's given, with one zone; else a country with only one zone.
    None when that doesn't settle it (the person says, in the review queue)."""
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
