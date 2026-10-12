from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from . import reference

Precision = Literal["airport", "zip", "city"]
PRECISIONS: tuple[Precision, ...] = ("airport", "zip", "city")
LOCATED_KINDS = ("hotel", "car", "train", "cruise", "parking", "visit")
DOMINANCE = 3

US_STATES = frozenset(
    ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"])
COUNTRIES = {
    "USA": "US", "US": "US", "U.S.A.": "US", "U.S.": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "CANADA": "CA", "UK": "GB", "U.K.": "GB", "UNITED KINGDOM": "GB", "GREAT BRITAIN": "GB", "ENGLAND": "GB",
    "SCOTLAND": "GB", "WALES": "GB", "NORTHERN IRELAND": "GB", "IRELAND": "IE", "FRANCE": "FR", "GERMANY": "DE",
    "DEUTSCHLAND": "DE", "ITALY": "IT", "ITALIA": "IT", "SPAIN": "ES", "ESPANA": "ES", "PORTUGAL": "PT",
    "NETHERLANDS": "NL", "THE NETHERLANDS": "NL", "BELGIUM": "BE", "SWITZERLAND": "CH", "AUSTRIA": "AT",
    "DENMARK": "DK", "NORWAY": "NO", "SWEDEN": "SE", "FINLAND": "FI", "ICELAND": "IS", "POLAND": "PL", "CZECHIA": "CZ",
    "CZECH REPUBLIC": "CZ", "HUNGARY": "HU", "GREECE": "GR", "TURKEY": "TR", "TURKIYE": "TR", "JAPAN": "JP",
    "SOUTH KOREA": "KR", "KOREA": "KR", "CHINA": "CN", "TAIWAN": "TW", "HONG KONG": "HK", "SINGAPORE": "SG",
    "THAILAND": "TH", "VIETNAM": "VN", "MALAYSIA": "MY", "PHILIPPINES": "PH", "INDIA": "IN", "UNITED ARAB EMIRATES": "AE",
    "UAE": "AE", "ISRAEL": "IL", "EGYPT": "EG", "SOUTH AFRICA": "ZA", "KENYA": "KE", "MOROCCO": "MA",
    "NEW ZEALAND": "NZ", "AUSTRALIA": "AU", "MEXICO": "MX", "BRAZIL": "BR", "ARGENTINA": "AR", "CHILE": "CL",
    "PERU": "PE", "COLOMBIA": "CO", "COSTA RICA": "CR", "JAMAICA": "JM", "BAHAMAS": "BS", "DOMINICAN REPUBLIC": "DO",
}

US_STATE_ZIP = re.compile(r"\b([A-Z]{2})\.?\s+(\d{5})(?:-\d{4})?\b")
US_ZIP_TOKEN = re.compile(r"(?:[A-Z]{2}\.?\s+)?(\d{5})(?:-\d{4})?")
CA_POSTAL = re.compile(r"\b([A-Z]\d[A-Z])[ -]?\d[A-Z]\d\b")
GB_POSTCODE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?)\s*\d[A-Z]{2}\b")
AIRPORT_CODE = re.compile(r"[A-Za-z]{3}")
AIRPORT_NEAR_WORD = re.compile(r"\b([A-Za-z]{3})\b(?=[^A-Za-z]{0,4}airport\b)|\bairport[^A-Za-z]{0,4}\(?\b([A-Za-z]{3})\b", re.IGNORECASE)
NUMBER_AFFIX = re.compile(r"^\d{4,6}(?:-\d{4})?\s+|\s+\d{4,6}(?:-\d{4})?$")
STATE_TOKEN = re.compile(r"([A-Z]{2})\.?(?:\s+\d{5}(?:-\d{4})?)?")


@dataclass(frozen=True)
class Point:
    latitude: float
    longitude: float
    precision: Precision


def _tokens(text: str) -> list[str]:
    return [t.strip() for t in re.split(r"[,\n;]+", text) if t.strip()]


def _country(tokens: list[str]) -> str | None:
    for token in reversed(tokens[-2:]):
        plain = " ".join(reference.place_key(token).upper().split())
        for name, code in COUNTRIES.items():
            if plain == " ".join(reference.place_key(name).upper().split()):
                return code
    return None


def _postal(text: str, country: str | None, tokens: list[str]) -> Point | None:
    postal = reference.postal_points()
    upper = text.upper()
    if country in (None, "CA") and (found := CA_POSTAL.search(upper)) and (point := postal.get(("CA", found.group(1)))):
        return Point(*point, "zip")
    if country in (None, "GB") and (found := GB_POSTCODE.search(upper)) and (point := postal.get(("GB", found.group(1)))):
        return Point(*point, "zip")
    if country in (None, "US"):
        for state, zip5 in US_STATE_ZIP.findall(upper):
            if state in US_STATES and (point := postal.get(("US", zip5))):
                return Point(*point, "zip")
        if country == "US":
            for token in reversed(tokens[1:]):
                if (found := US_ZIP_TOKEN.fullmatch(token.upper())) and (point := postal.get(("US", found.group(1)))):
                    return Point(*point, "zip")
    return None


def _state(tokens: list[str]) -> str | None:
    for token in tokens:
        found = STATE_TOKEN.fullmatch(token.upper())
        if found and found.group(1) in US_STATES:
            return found.group(1)
    return None


def _city(name: str, country: str | None, state: str | None) -> Point | None:
    found = list(reference.city_points().get(reference.place_key(name), ()))
    if country:
        found = [c for c in found if c[0] == country]
    if state and (in_state := [c for c in found if c[1] == state]):
        found = in_state
    if not found:
        return None
    found.sort(key=lambda c: -c[4])
    narrowed = country is not None or state is not None
    if len(found) > 1 and not narrowed and found[0][4] < DOMINANCE * found[1][4]:
        return None
    return Point(found[0][2], found[0][3], "city")


def _city_in(text: str, country: str | None, state: str | None) -> Point | None:
    tokens = _tokens(text)
    country = country or _country(tokens)
    state = state or (_state(tokens) if country in (None, "US") else None)
    for token in reversed(tokens):
        name = NUMBER_AFFIX.sub("", token)
        if not name or name[0].isdigit() or STATE_TOKEN.fullmatch(name.upper()) or name.upper() in COUNTRIES:
            continue
        if (point := _city(name, country, state)):
            return point
    return None


def _airport(text: str, airports: Mapping[str, tuple[float, float]]) -> Point | None:
    plain = text.strip()
    code = plain if AIRPORT_CODE.fullmatch(plain) else next(
        (g for m in AIRPORT_NEAR_WORD.finditer(plain) for g in m.groups() if g), None)
    if code and (point := airports.get(code.upper())):
        return Point(*point, "airport")
    return None


def places_of(kind: str, origin: str | None, destination: str | None) -> list[str]:
    ordered = {"hotel": [destination], "parking": [destination], "car": [origin, destination], "train": [destination, origin],
               "cruise": [origin, destination]}.get(kind, [])
    return [p.strip() for p in ordered if p and p.strip()]


def locate(kind: str, origin: str | None, destination: str | None, address: str | None, visit_state: str | None = None) -> Point | None:
    if kind not in LOCATED_KINDS:
        return None
    if kind == "visit":
        nation = (destination or "").strip().upper()
        if nation == "US" and (code := (visit_state or "").strip().upper()) in US_STATES and (inside := reference.us_state_points().get(code)):
            return Point(inside[0], inside[1], "city")
        found = reference.country_points().get(nation)
        return Point(found[0], found[1], "city") if found else None
    places = places_of(kind, origin, destination)
    where = (address or "").strip()
    tokens = _tokens(where)
    country = _country(tokens)
    if where and (point := _postal(where, country, tokens)):
        return point
    if kind in ("car", "train"):
        for place in places:
            if (point := _airport(place, reference.airport_points())):
                return point
    state = _state(tokens) if country in (None, "US") else None
    for place in places:
        if (point := _city_in(place, country, state)):
            return point
    return _city_in(where, country, state) if where else None



def locate_port(name: str) -> Point | None:
    return _city_in(name.strip(), None, None) if name.strip() else None
