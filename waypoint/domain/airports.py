"""Airports by IATA code: where a flight's times are written. A flight's start and end zones come from its airports
(waypoint/storage/airports.tsv.gz, loaded by migration 0004), and a person can still name a zone by hand for an airport
the list doesn't have."""
from __future__ import annotations

from typing import TypedDict

from sqlalchemy import select

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
