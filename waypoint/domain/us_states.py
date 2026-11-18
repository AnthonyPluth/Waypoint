from __future__ import annotations

from functools import cache

from ..storage import reference

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

STATE_NAMES = {code: name.title().replace(" Of ", " of ") for name, code in US_NAMES.items()}


@cache
def _state_of_zip3() -> dict[str, str]:
    found: dict[str, str] = {}
    for state, ranges in ZIP_RANGES.items():
        for part in ranges.split(","):
            lo, _, hi = part.partition("-")
            for n in range(int(lo), int(hi or lo) + 1):
                found[f"{n:03d}"] = state
    return found


def state_at(latitude: float, longitude: float, within_km: float) -> str | None:
    near = reference.nearest_place(latitude, longitude, within_km)
    if near is None or near.country != "US":
        return None
    if near.state:
        return STATE_NAMES.get(near.state)
    if near.postal:
        code = _state_of_zip3().get(near.postal[:3])
        return STATE_NAMES.get(code) if code else None
    return reference.airport_states().get(near.airport or "")
