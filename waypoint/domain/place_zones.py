"""The time zone of a stay or a rental from its address, worked out here and nowhere else: nothing is looked up, sent or
geocoded (AGENTS.md, "Email stays on the server"; a hotel's address is the household's). The text is read for a US state and
ZIP, a Canadian province, a country, or a city the airport list knows (waypoint/domain/airports.py); a place that doesn't
settle on one zone gives None, and the person says.

A wrong zone is worse than none (every time on the booking would be off), so a state that spans zones is settled only by the
ZIP prefixes that tell them apart, else by a city the airport list knows with one zone."""
from __future__ import annotations

import re

from ..storage import db
from . import airports

NY, CHI, DEN, LA = "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"

# A state with one zone, or the zone most of it is in, and the ZIP prefixes (first three digits) of the part that isn't.
# None as the zone: the state is settled by a city, or by a ZIP prefix listed, and otherwise left to the person.
US_STATES: dict[str, tuple[str | None, dict[str, str | None]]] = {
    "AL": (CHI, {}), "AK": ("America/Anchorage", {}), "AZ": ("America/Phoenix", {}), "AR": (CHI, {}), "CA": (LA, {}),
    "CO": (DEN, {}), "CT": (NY, {}), "DE": (NY, {}), "DC": (NY, {}), "GA": (NY, {}), "HI": ("Pacific/Honolulu", {}),
    "IL": (CHI, {}), "IA": (CHI, {}), "LA": (CHI, {}), "ME": (NY, {}), "MD": (NY, {}), "MA": (NY, {}), "MN": (CHI, {}),
    "MS": (CHI, {}), "MO": (CHI, {}), "MT": (DEN, {}), "NV": (LA, {}), "NH": (NY, {}), "NJ": (NY, {}), "NM": (DEN, {}),
    "NY": (NY, {}), "NC": (NY, {}), "OH": (NY, {}), "OK": (CHI, {}), "PA": (NY, {}), "RI": (NY, {}), "SC": (NY, {}),
    "UT": (DEN, {}), "VT": (NY, {}), "VA": (NY, {}), "WA": (LA, {}), "WV": (NY, {}), "WI": (CHI, {}), "WY": (DEN, {}),
    "FL": (NY, {"324": CHI, "325": CHI}),                                    # (the panhandle west of the Apalachicola)
    "TX": (CHI, {"799": DEN, "885": DEN}),                                    # (El Paso)
    "ID": ("America/Boise", {"835": LA, "838": LA}),                          # (the north)
    "OR": (LA, {"979": "America/Boise"}),                                     # (Malheur County)
    "IN": (NY, {"463": CHI, "464": CHI, "476": CHI, "477": CHI}),            # (Gary, Evansville)
    "KY": (NY, {f"42{n}": CHI for n in range(8)}),                            # (the west)
    "TN": (CHI, {"373": NY, "374": NY, "376": NY, "377": NY, "378": NY, "379": NY}),   # (the east)
    "MI": (None, {str(n): NY for n in range(480, 498)}),                      # (Eastern but for four Upper Peninsula counties, whose ZIPs 498 and 499 are shared)
    "KS": (None, {}), "NE": (None, {}), "ND": (None, {}), "SD": (None, {}),  # (zones split mid-state: a city, or the person)
}
US_NAMES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA", "COLORADO": "CO",
    "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA",
    "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
    "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}

CA_PROVINCES = {
    "BC": "America/Vancouver", "AB": "America/Edmonton", "SK": "America/Regina", "MB": "America/Winnipeg",
    "ON": "America/Toronto", "QC": "America/Toronto", "NB": "America/Moncton", "NS": "America/Halifax",
    "PE": "America/Halifax", "NL": "America/St_Johns", "YT": "America/Whitehorse", "NT": "America/Yellowknife",
}
CA_NAMES = {
    "BRITISH COLUMBIA": "BC", "ALBERTA": "AB", "SASKATCHEWAN": "SK", "MANITOBA": "MB", "ONTARIO": "ON", "QUEBEC": "QC",
    "QUÉBEC": "QC", "NEW BRUNSWICK": "NB", "NOVA SCOTIA": "NS", "PRINCE EDWARD ISLAND": "PE",
    "NEWFOUNDLAND AND LABRADOR": "NL", "YUKON": "YT", "NORTHWEST TERRITORIES": "NT",
}

# Country names as an address writes them, to the ISO code the airport list uses.
COUNTRIES = {
    "USA": "US", "US": "US", "U.S.A.": "US", "U.S.": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US",
    "CANADA": "CA", "UK": "GB", "U.K.": "GB", "UNITED KINGDOM": "GB", "GREAT BRITAIN": "GB", "ENGLAND": "GB",
    "SCOTLAND": "GB", "WALES": "GB", "NORTHERN IRELAND": "GB", "IRELAND": "IE", "FRANCE": "FR", "GERMANY": "DE",
    "DEUTSCHLAND": "DE", "ITALY": "IT", "ITALIA": "IT", "SPAIN": "ES", "ESPAÑA": "ES", "PORTUGAL": "PT",
    "NETHERLANDS": "NL", "THE NETHERLANDS": "NL", "BELGIUM": "BE", "SWITZERLAND": "CH", "AUSTRIA": "AT",
    "DENMARK": "DK", "NORWAY": "NO", "SWEDEN": "SE", "FINLAND": "FI", "ICELAND": "IS", "POLAND": "PL", "CZECHIA": "CZ",
    "CZECH REPUBLIC": "CZ", "HUNGARY": "HU", "GREECE": "GR", "TURKEY": "TR", "TÜRKIYE": "TR", "JAPAN": "JP",
    "SOUTH KOREA": "KR", "KOREA": "KR", "CHINA": "CN", "TAIWAN": "TW", "HONG KONG": "HK", "SINGAPORE": "SG",
    "THAILAND": "TH", "VIETNAM": "VN", "MALAYSIA": "MY", "PHILIPPINES": "PH", "INDIA": "IN", "UNITED ARAB EMIRATES": "AE",
    "UAE": "AE", "ISRAEL": "IL", "EGYPT": "EG", "SOUTH AFRICA": "ZA", "KENYA": "KE", "MOROCCO": "MA",
    "NEW ZEALAND": "NZ", "AUSTRALIA": "AU", "MEXICO": "MX", "MÉXICO": "MX", "BRAZIL": "BR", "ARGENTINA": "AR",
    "CHILE": "CL", "PERU": "PE", "COLOMBIA": "CO", "COSTA RICA": "CR", "JAMAICA": "JM", "BAHAMAS": "BS",
    "DOMINICAN REPUBLIC": "DO",
}

ZIP = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
CA_POSTAL = re.compile(r"\b[A-Z]\d[A-Z][ -]?\d[A-Z]\d\b")


def _tokens(address: str) -> list[str]:
    """The parts of an address between commas and line breaks, trimmed."""
    return [t.strip() for t in re.split(r"[,\n;]+", address) if t.strip()]


def _country(tokens: list[str]) -> str | None:
    """The ISO country code the address ends in (its last part, or the last before a postal code), if it names one."""
    for token in reversed(tokens[-2:]):
        code = COUNTRIES.get(re.sub(r"[\s.]+$", "", token.upper()))
        if code:
            return code
    return None


def _us_zone(address: str, tokens: list[str]) -> str | None:
    """A US address's zone from its state (and ZIP, where the state spans zones): "Honolulu, HI 96815", "Dallas, Texas 75201"."""
    state: str | None = None
    zip3: str | None = None
    found = re.search(r"\b([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b", address)   # state and ZIP together: the surest reading
    if found and found.group(1) in US_STATES:
        state, zip3 = found.group(1), found.group(2)[:3]
    else:
        for token in tokens:
            bare = ZIP.sub("", token).strip().rstrip(".").strip()
            if bare in US_STATES or bare.upper() in US_NAMES:
                state = bare if bare in US_STATES else US_NAMES[bare.upper()]
                z = ZIP.search(token)
                zip3 = z.group(1)[:3] if z else None
    if state is None:
        return None
    zone, exceptions = US_STATES[state]
    if zip3 is None:
        z = ZIP.search(address)
        zip3 = z.group(1)[:3] if z else None
    if zip3 in exceptions:
        return exceptions[zip3]
    return zone


def _ca_zone(address: str, tokens: list[str]) -> str | None:
    """A Canadian address's zone from its province."""
    for token in tokens:
        bare = CA_POSTAL.sub("", token).strip().rstrip(".").strip()
        code = bare if bare in CA_PROVINCES else CA_NAMES.get(bare.upper())
        if code:
            return CA_PROVINCES.get(code)
    return None


def _city_zone(conn: db.Connection, tokens: list[str], country: str | None) -> str | None:
    """The zone of a city named in the address that the airport list knows by one zone (in the country, when it's known)."""
    for token in tokens:
        city = ZIP.sub("", CA_POSTAL.sub("", token)).strip()
        if not city or len(city) < 3 or city[0].isdigit():
            continue
        zone = airports.zone_for_place(conn, city, None if country is None else country)
        if zone:
            return zone
    return None


def zone_for_address(conn: db.Connection, address: str | None) -> str | None:
    """The time zone an address is in, or None when the text doesn't settle it. Never looks anything up outside Waypoint."""
    text = (address or "").strip()
    if not text:
        return None
    tokens = _tokens(text)
    country = _country(tokens)
    if country in (None, "US"):
        zone = _us_zone(text, tokens)
        if zone:
            return zone
    if country in (None, "CA"):
        zone = _ca_zone(text, tokens)
        if zone:
            return zone
    zone = _city_zone(conn, tokens, country)
    if zone:
        return zone
    return airports.zone_for_place(conn, None, country) if country else None
