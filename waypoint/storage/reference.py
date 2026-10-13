from __future__ import annotations

import gzip
import re
import unicodedata
from functools import cache
from pathlib import Path

HERE = Path(__file__).resolve().parent

SMALL_PLACE_WEIGHT = 30_000
SMALL_PLACES: tuple[tuple[str, str, float, float], ...] = (
    ("Skagway", "AK", 59.4583, -135.3139), ("Ketchikan", "AK", 55.3422, -131.6461), ("Sitka", "AK", 57.0531, -135.3300),
    ("Seward", "AK", 60.1042, -149.4422), ("Haines", "AK", 59.2358, -135.4458), ("Whittier", "AK", 60.7728, -148.6850),
    ("Wrangell", "AK", 56.4708, -132.3767), ("Petersburg", "AK", 56.8125, -132.9556), ("Valdez", "AK", 61.1308, -146.3483),
    ("Homer", "AK", 59.6425, -151.5483), ("Kodiak", "AK", 57.7900, -152.4072), ("Hoonah", "AK", 58.1103, -135.4439),
    ("Icy Strait Point", "AK", 58.1103, -135.4439), ("Glacier Bay", "AK", 58.6658, -136.9002), ("Denali Park", "AK", 63.7342, -148.9139),
    ("Talkeetna", "AK", 62.3231, -150.1063), ("Cordova", "AK", 60.5428, -145.7575), ("Nome", "AK", 64.5011, -165.4064),
    ("Girdwood", "AK", 60.9425, -149.1653),
)


def _rows(name: str) -> list[list[str]]:
    with gzip.open(HERE / name, "rt", encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t") for line in f if line.strip()]


def airport_rows() -> list[dict]:
    return [{"code": c, "name": n, "city": city, "country": country, "zone": z, "latitude": float(lat), "longitude": float(lon)}
            for c, n, city, country, z, lat, lon in _rows("airports.tsv.gz")]


def airline_rows() -> list[dict]:
    return [{"code": code, "icao": icao or None, "name": name, "country": country or None}
            for code, icao, name, country in _rows("airlines.tsv.gz")]


def place_key(name: str) -> str:
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain.casefold()).split())


@cache
def airport_zones() -> dict[str, str]:
    return {row[0]: row[4] for row in _rows("airports.tsv.gz") if len(row) >= 5 and row[4]}


@cache
def airport_states() -> dict[str, str]:
    return {row[1]: row[2] for row in _rows("regions.tsv.gz") if len(row) >= 3 and row[0] == "A" and row[2]}


@cache
def country_names() -> dict[str, str]:
    return {row[1]: row[2] for row in _rows("regions.tsv.gz") if len(row) >= 3 and row[0] == "C" and row[2]}


@cache
def airline_names() -> dict[str, str]:
    return {row[0]: row[2] for row in _rows("airlines.tsv.gz") if len(row) >= 3 and row[0] and row[2]}


@cache
def airport_places() -> tuple[tuple[str, str, str], ...]:
    return tuple((row[2], row[3], row[4]) for row in _rows("airports.tsv.gz") if len(row) >= 5 and row[2] and row[4])


@cache
def airport_points() -> dict[str, tuple[float, float]]:
    return {row[0]: (float(row[5]), float(row[6])) for row in _rows("airports.tsv.gz") if len(row) >= 7 and row[5] and row[6]}


def _by_country() -> dict[str, list[list[str]]]:
    found: dict[str, list[list[str]]] = {}
    for row in _rows("airports.tsv.gz"):
        if len(row) >= 7 and row[3] and row[4] and row[5] and row[6]:
            found.setdefault(row[3], []).append(row)
    return found


@cache
def country_points() -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for country, rows in _by_country().items():
        lat, lon = (sum(float(r[i]) for r in rows) / len(rows) for i in (5, 6))
        nearest = min(rows, key=lambda r: ((float(r[5]) - lat) ** 2 + (float(r[6]) - lon) ** 2, r[0]))
        out[country] = (float(nearest[5]), float(nearest[6]))
    return out


@cache
def country_zones() -> dict[str, str]:
    out: dict[str, str] = {}
    for country, rows in _by_country().items():
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[4]] = counts.get(r[4], 0) + 1
        out[country] = min(counts, key=lambda z: (-counts[z], z))
    return out


@cache
def postal_points() -> dict[tuple[str, str], tuple[float, float]]:
    return {(row[1], row[2]): (float(row[3]), float(row[4])) for row in _rows("places.tsv.gz") if row[0] == "Z" and len(row) >= 5}


@cache
def city_points() -> dict[str, tuple[tuple[str, str, float, float, int], ...]]:
    found: dict[str, list[tuple[str, str, float, float, int]]] = {}
    for row in _rows("places.tsv.gz"):
        if row[0] == "C" and len(row) >= 6:
            state, _, population = row[5].partition("|")
            found.setdefault(place_key(row[2]), []).append((row[1], state, float(row[3]), float(row[4]), int(population or 0)))
    for name, state, lat, lon in SMALL_PLACES:
        found.setdefault(place_key(name), []).append(("US", state, lat, lon, SMALL_PLACE_WEIGHT))
    return {name: tuple(places) for name, places in found.items()}


@cache
def us_state_points() -> dict[str, tuple[float, float]]:
    largest: dict[str, tuple[float, float, int]] = {}
    for places in city_points().values():
        for country, state, lat, lon, population in places:
            if country == "US" and state and population > largest.get(state, (0.0, 0.0, -1))[2]:
                largest[state] = (lat, lon, population)
    return {state: (lat, lon) for state, (lat, lon, _) in largest.items()}
