from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any, TypedDict

from sqlalchemy import select

from .. import validate
from ..storage import db, geocode
from ..storage import settings_keys as sk
from ..storage.models import Airport, Segment

FALLBACK_COUNTRY = "US"
CITY_LIMIT = 80
STATE_LIMIT = 40
POSTAL_LIMIT = 10
FIELDS = ("city", "state", "zip", "country")
CITY = re.compile(r"[^\W\d_]+(?:[ .'’\-]+[^\W\d_]+)*\.?")
POSTAL = re.compile(r"[A-Za-z0-9]{2,5}(?:[ -][A-Za-z0-9]{2,4})?")
COUNTRY = re.compile(r"[A-Za-z]{2}")


class Invalid(Exception):
    pass


class HomeOut(TypedDict):
    city: str
    state: str
    zip: str
    country: str
    saved: bool
    placed: bool


class HomePoint(TypedDict):
    city: str
    latitude: float
    longitude: float


check = validate.Validator(Invalid)


def default_country(conn: db.Connection) -> str:
    codes: Counter[str] = Counter()
    for origin, destination in conn.execute(select(Segment.origin, Segment.destination).where(Segment.kind == "flight", Segment.status != "cancelled")):
        for code in (origin, destination):
            codes[(code or "").strip().upper()] += 1
    countries: Counter[str] = Counter()
    for code, country in conn.execute(select(Airport.code, Airport.country).where(Airport.code.in_(sorted(c for c in codes if c)))):
        countries[country] += codes[code]
    return countries.most_common(1)[0][0].upper() if countries else FALLBACK_COUNTRY


def _stored(conn: db.Connection) -> dict[str, str] | None:
    raw = db.get_setting(conn, sk.HOME)
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(found, dict) or not all(isinstance(found.get(f), str) for f in FIELDS) or not found["city"]:
        return None
    return {f: found[f] for f in FIELDS}


def _point(home: dict[str, str]) -> geocode.Point | None:
    return geocode.locate_home(home["city"], home["state"], home["zip"], home["country"])


def read(conn: db.Connection) -> HomeOut:
    home = _stored(conn)
    if home is None:
        return {"city": "", "state": "", "zip": "", "country": default_country(conn), "saved": False, "placed": False}
    return {"city": home["city"], "state": home["state"], "zip": home["zip"], "country": home["country"],
            "saved": True, "placed": _point(home) is not None}


def point(conn: db.Connection) -> HomePoint | None:
    home = _stored(conn)
    found = _point(home) if home else None
    if home is None or found is None:
        return None
    return {"city": home["city"], "latitude": found.latitude, "longitude": found.longitude}


def _field(body: dict[str, Any], key: str, label: str, limit: int, pattern: re.Pattern[str] | None = None, required: bool = False) -> str:
    value = body.get(key)
    if value is not None and not isinstance(value, str):
        raise Invalid(f"The {label} must be text")
    text = " ".join((check.text(value, label, limit, required=required) or "").split())
    if text and pattern is not None and not pattern.fullmatch(text):
        raise Invalid(f"The {label} doesn’t look right")
    return text


def save(conn: db.Connection, body: dict[str, Any]) -> HomeOut:
    if set(body) - set(FIELDS):
        raise Invalid("Home takes a city, a state or region, a ZIP or postal code and a country, nothing else")
    state = _field(body, "state", "state or region", STATE_LIMIT, CITY)
    home = {
        "city": _field(body, "city", "city", CITY_LIMIT, CITY, required=True),
        "state": state,
        "zip": _field(body, "zip", "ZIP or postal code", POSTAL_LIMIT, POSTAL).upper(),
        "country": _field(body, "country", "country", 2, COUNTRY).upper() or default_country(conn),
    }
    db.set_setting(conn, sk.HOME, json.dumps(home))
    return {"city": home["city"], "state": home["state"], "zip": home["zip"], "country": home["country"],
            "saved": True, "placed": _point(home) is not None}


def clear(conn: db.Connection) -> HomeOut:
    db.set_setting(conn, sk.HOME, None)
    return read(conn)
