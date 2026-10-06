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
    "FL": (NY, {"324": None, "325": CHI}),                                    # (the panhandle west of the Apalachicola; 324 mixes Panama City with Port St. Joe)
    "TX": (CHI, {"799": DEN, "885": DEN}),                                    # (El Paso)
    "ID": ("America/Boise", {"835": LA, "838": LA}),                          # (the north)
    "OR": (LA, {"979": "America/Boise"}),                                     # (Malheur County)
    "IN": (NY, {"463": CHI, "464": CHI, "476": CHI, "477": CHI}),            # (Gary, Evansville)
    "KY": (NY, {"420": CHI, "421": CHI, "422": CHI, "423": CHI, "424": CHI, "425": None, "426": None, "427": None}),   # (the west; 425-427 mix both)
    "TN": (CHI, {"373": None, "374": NY, "376": NY, "377": NY, "378": NY, "379": NY}),   # (the east; 373 mixes Cleveland with Tullahoma)
    "MI": (None, {str(n): NY for n in range(480, 498)}),                      # (Eastern but for four Upper Peninsula counties, whose ZIPs 498 and 499 are shared)
    "KS": (None, {}), "NE": (None, {}), "ND": (None, {}), "SD": (None, {}),  # (zones split mid-state: a city, or the person)
}
# The ZIP prefixes (first three digits) each state's ZIP codes fall in: a state and ZIP with no country named is read only when
# they agree, since "DE 10115" is Berlin, not Delaware.
ZIP_RANGES: dict[str, str] = {
    "AL": "350-352,354-369", "AK": "995-999", "AZ": "850-865", "AR": "716-729", "CA": "900-908,910-928,930-961", "CO": "800-816",
    "CT": "060-069", "DE": "197-199", "DC": "200,202-205", "FL": "320-342,344,346-347,349", "GA": "300-319,398-399", "HI": "967-968",
    "ID": "832-838", "IL": "600-629", "IN": "460-479", "IA": "500-516,520-528", "KS": "660-679", "KY": "400-427", "LA": "700-701,703-714",
    "ME": "039-049", "MD": "206-212,214-219", "MA": "010-027,055", "MI": "480-499", "MN": "550-567", "MS": "386-397",
    "MO": "630-631,633-641,644-658", "MT": "590-599", "NE": "680-681,683-693", "NV": "889-898", "NH": "030-038", "NJ": "070-089",
    "NM": "870-871,873-884", "NY": "005,100-149", "NC": "270-289", "ND": "580-588", "OH": "430-458", "OK": "730-731,734-741,743-749",
    "OR": "970-979", "PA": "150-196", "RI": "028-029", "SC": "290-299", "SD": "570-577", "TN": "370-385", "TX": "733,750-799,885",
    "UT": "840-847", "VT": "050-054,056-059", "VA": "201,220-246", "WA": "980-986,988-994", "WV": "247-268",
    "WI": "530-532,534-535,537-539,541-549", "WY": "820-831",
}


def _zip_in_state(state: str, zip3: str) -> bool:
    """Whether a ZIP code's first three digits are ones this state's ZIP codes start with."""
    n = int(zip3)
    for part in ZIP_RANGES.get(state, "").split(","):
        lo, _, hi = part.partition("-")
        if part and int(lo) <= n <= int(hi or lo):
            return True
    return False


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


def _us_zone(address: str, tokens: list[str], country: str | None) -> str | None:
    """A US address's zone from its state (and ZIP, where the state spans zones): "Honolulu, HI 96815", "Dallas, Texas 75201".
    A state is taken only from a state and ZIP together, or when the address says it is in the US: a bare "DE", "CO" or "IL"
    is as likely Germany, Colombia or Israel, and a wrong zone is worse than none."""
    found = re.search(r"\b([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b", address)   # state and ZIP together: the surest reading
    state: str | None = found.group(1) if found and found.group(1) in US_STATES else None
    zip3: str | None = found.group(2)[:3] if state and found else None
    if state and zip3 and country != "US" and not _zip_in_state(state, zip3):
        state, zip3 = None, None   # (not that state's ZIP: "Berlin, DE 10115" is not Delaware)
    if state is None and country == "US":
        for token in tokens:
            bare = ZIP.sub("", token).strip().rstrip(".").strip()
            if bare in US_STATES or bare.upper() in US_NAMES:
                state = bare if bare in US_STATES else US_NAMES[bare.upper()]
                break
    if state is None:
        return None
    zone, exceptions = US_STATES[state]
    if zip3 is None:
        z = ZIP.search(address)
        zip3 = z.group(1)[:3] if z else None
    if zip3 in exceptions:
        return exceptions[zip3]
    return zone


# A province and what splits it: the postal-code starts (forward sortation areas) in another zone, and for the provinces whose
# zones split widely the ones left to the person. Anything without a postal code in such a province is left to the person too.
CA_SPLIT = {"BC": ("V0", "V1"), "ON": ("P",), "QC": ("G4T",), "NL": ("A0P", "A0R")}


def _ca_zone(address: str, tokens: list[str], country: str | None) -> str | None:
    """A Canadian address's zone from its province, taken only when the address has a Canadian postal code or says it is in
    Canada (a bare "NL" or "PE" is as likely the Netherlands or Peru)."""
    postal = CA_POSTAL.search(address)
    if country != "CA" and not postal:
        return None
    for token in tokens:
        bare = CA_POSTAL.sub("", token).strip().rstrip(".").strip()
        code = bare if bare in CA_PROVINCES else CA_NAMES.get(bare.upper())
        if code:
            # (part of the split provinces is in another zone: only a postal code outside those parts settles it)
            if code in CA_SPLIT and (not postal or postal.group(0).replace(" ", "").upper().startswith(CA_SPLIT[code])):
                return None
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
        zone = _us_zone(text, tokens, country)
        if zone:
            return zone
    if country in (None, "CA"):
        zone = _ca_zone(text, tokens, country)
        if zone:
            return zone
    zone = _city_zone(conn, tokens, country)
    if zone:
        return zone
    return airports.zone_for_place(conn, None, country) if country else None
