from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence

from sqlalchemy import select

from ..storage import bundled_logos, db
from ..storage.models import Airline, BrandLogo, LoyaltyId, Segment
from . import loyalty, visibility
from .visibility import Viewer

FLIGHT_NUMBER = re.compile(r"\s*([A-Za-z0-9]{2})\s*\d{1,4}[A-Za-z]?\s*")


def key(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def _name(provider: str | None) -> str | None:
    text = " ".join((provider or "").split())
    return text if 2 <= len(text) <= 100 and len(re.findall(r"[A-Za-z]", text)) >= 2 else None


_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("Hyatt", (
        ("hyatt regency", "Hyatt Regency"), ("hyatt place", "Hyatt Place"), ("hyatt house", "Hyatt House"), ("grand hyatt", "Grand Hyatt"),
        ("park hyatt", "Park Hyatt"), ("hyatt centric", "Hyatt Centric"), ("andaz", "Andaz"), ("hyatt ziva", "Hyatt Ziva"),
        ("hyatt zilara", "Hyatt Zilara"), ("alila", "Alila Hotels"), ("miraval", "Miraval"),
        ("caption by hyatt", "Caption by Hyatt"), ("hyatt studios", "Hyatt Studios"), ("unbound collection", "The Unbound Collection by Hyatt"),
        ("destination by hyatt", "Destination by Hyatt"), ("hyatt vacation club", "Hyatt Vacation Club"), ("tommie", "Tommie Hotels"))),
    ("Marriott", (
        ("courtyard", "Courtyard by Marriott"), ("residence inn", "Residence Inn by Marriott"), ("fairfield inn", "Fairfield by Marriott"),
        ("fairfield by marriott", "Fairfield by Marriott"), ("springhill suites", "SpringHill Suites by Marriott"),
        ("towneplace suites", "TownePlace Suites by Marriott"), ("sheraton", "Sheraton"), ("westin", "Westin"), ("renaissance", "Renaissance Hotels"),
        ("autograph collection", "Autograph Collection"), ("aloft", "Aloft Hotels"), ("moxy", "Moxy Hotels"), ("four points", "Four Points by Sheraton"),
        ("le meridien", "Le Méridien"), ("ritz carlton", "The Ritz-Carlton"), ("st regis", "The St. Regis"), ("jw marriott", "JW Marriott"),
        ("gaylord", "Gaylord Hotels"), ("w hotel", "W Hotels"), ("ac hotel", "AC Hotels by Marriott"),
        ("element by westin", "Element Hotels"), ("tribute portfolio", "Tribute Portfolio"),
        ("luxury collection", "The Luxury Collection"), ("delta hotels", "Delta Hotels by Marriott"), ("protea hotel", "Protea Hotels by Marriott"),
        ("design hotels", "Design Hotels"), ("city express", "City Express by Marriott"), ("bvlgari hotel", "Bvlgari Hotels & Resorts"),
        ("marriott vacation club", "Marriott Vacation Club"), ("marriott executive apartments", "Marriott Executive Apartments"))),
    ("Hilton", (
        ("hampton inn", "Hampton by Hilton"), ("hampton by hilton", "Hampton by Hilton"), ("hilton garden inn", "Hilton Garden Inn"),
        ("doubletree", "DoubleTree by Hilton"), ("embassy suites", "Embassy Suites by Hilton"), ("homewood suites", "Homewood Suites by Hilton"),
        ("home2 suites", "Home2 Suites by Hilton"), ("tru by hilton", "Tru by Hilton"), ("conrad hotel", "Conrad Hotels"),
        ("waldorf astoria", "Waldorf Astoria Hotels"), ("curio collection", "Curio Collection by Hilton"), ("canopy by hilton", "Canopy by Hilton"),
        ("lxr", "LXR Hotels & Resorts"), ("signia by hilton", "Signia by Hilton"), ("tapestry collection", "Tapestry Collection by Hilton"),
        ("motto by hilton", "Motto by Hilton"), ("spark by hilton", "Spark by Hilton"), ("hilton grand vacations", "Hilton Grand Vacations"))),
    ("IHG Hotels & Resorts", (
        ("holiday inn express", "Holiday Inn Express"), ("holiday inn", "Holiday Inn"), ("crowne plaza", "Crowne Plaza"),
        ("intercontinental", "InterContinental Hotels"), ("staybridge suites", "Staybridge Suites"), ("candlewood suites", "Candlewood Suites"),
        ("hotel indigo", "Hotel Indigo"), ("kimpton", "Kimpton Hotels"), ("even hotel", "EVEN Hotels"), ("avid hotel", "avid hotels"),
        ("six senses", "Six Senses"), ("regent hotels", "Regent Hotels"), ("vignette collection", "Vignette Collection"), ("voco", "voco Hotels"),
        ("atwell suites", "Atwell Suites"))),
    ("Wyndham Hotels & Resorts", (
        ("la quinta", "La Quinta by Wyndham"), ("wyndham garden", "Wyndham Garden"), ("wyndham grand", "Wyndham Grand"),
        ("wyndham alltra", "Wyndham Alltra"), ("ramada", "Ramada by Wyndham"), ("days inn", "Days Inn by Wyndham"), ("super 8", "Super 8 by Wyndham"),
        ("microtel", "Microtel by Wyndham"), ("baymont", "Baymont by Wyndham"), ("hawthorn suites", "Hawthorn Suites by Wyndham"),
        ("wingate", "Wingate by Wyndham"), ("howard johnson", "Howard Johnson by Wyndham"), ("tryp by wyndham", "TRYP by Wyndham"),
        ("registry collection", "Registry Collection Hotels"), ("trademark collection", "Trademark Collection by Wyndham"),
        ("dazzler", "Dazzler by Wyndham"), ("americinn", "AmericInn by Wyndham"), ("knights inn", "Knights Inn"))),
    ("Choice Hotels", (
        ("comfort inn", "Comfort Inn"), ("comfort suites", "Comfort Suites"), ("quality inn", "Quality Inn"), ("sleep inn", "Sleep Inn"),
        ("cambria hotel", "Cambria Hotels"), ("ascend hotel collection", "Ascend Hotel Collection"),
        ("mainstay suites", "MainStay Suites"), ("econo lodge", "Econo Lodge"), ("rodeway inn", "Rodeway Inn"),
        ("suburban extended stay", "Suburban Extended Stay"), ("woodspring suites", "WoodSpring Suites"), ("everhome suites", "Everhome Suites"))),
    ("Best Western", (
        ("best western plus", "Best Western Plus"), ("best western premier", "Best Western Premier"), ("surestay", "SureStay Hotels"),
        ("aiden by best western", "Aiden by Best Western"), ("executive residency", "Executive Residency by Best Western"))),
    ("Radisson Hotel Group", (
        ("radisson blu", "Radisson Blu"), ("radisson red", "Radisson RED"), ("radisson collection", "Radisson Collection"),
        ("radisson individuals", "Radisson Individuals"), ("park plaza", "Park Plaza"), ("park inn", "Park Inn by Radisson"),
        ("country inn suites", "Country Inn & Suites by Radisson"))),
    ("Accor", (
        ("fairmont", "Fairmont Hotels"), ("sofitel", "Sofitel"), ("novotel", "Novotel"), ("pullman", "Pullman Hotels"), ("mercure", "Mercure Hotels"),
        ("raffles", "Raffles Hotels"), ("swissotel", "Swissôtel"), ("movenpick", "Mövenpick Hotels"), ("ibis styles", "ibis Styles"),
        ("ibis budget", "ibis budget"), ("mgallery", "MGallery"), ("mama shelter", "Mama Shelter"),
        ("grand mercure", "Grand Mercure"), ("adagio", "Adagio"), ("25hours", "25hours Hotels"), ("rixos", "Rixos Hotels"))),
    ("Sonesta", (
        ("royal sonesta", "Royal Sonesta"), ("sonesta es suites", "Sonesta ES Suites"), ("sonesta select", "Sonesta Select"),
        ("sonesta simply suites", "Sonesta Simply Suites"))),
)
SUB_BRANDS: tuple[tuple[str, str], ...] = tuple((start, brand) for _, brands in _GROUPS for start, brand in brands)
_SUB_BRANDS = sorted(SUB_BRANDS, key=lambda b: -len(b[0]))
GROUP_OF: dict[str, str] = {key(brand): group for group, brands in _GROUPS for _, brand in brands}
SUB_KEYS = frozenset(GROUP_OF)


def _plain(text: str | None) -> str:
    ascii_text = unicodedata.normalize("NFKD", (text or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"^the ", "", " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text).split()))


def sub_brand(hotel: str | None) -> str | None:
    words = _plain(hotel)
    for start, brand in _SUB_BRANDS:
        if words == start or words.startswith(start + " "):
            return brand
    return None


_CHIP_TAIL = re.compile(r"\s+(by\s+.+|hotels?(\s*&\s*resorts)?|resorts?)$", re.IGNORECASE)


def chip_label(brand: str) -> str:
    return _CHIP_TAIL.sub("", brand.strip()) or brand


def _candidates(kind: str, provider: str | None, number: str | None, hotel: str | None, airlines: Mapping[str, str]) -> list[str]:
    own = sub_brand(hotel) if kind == "hotel" else None
    if own:
        return [own, GROUP_OF[key(own)]]
    brand = _name(provider)
    if brand is None and kind == "flight":
        found = FLIGHT_NUMBER.fullmatch(number or "")
        brand = airlines.get(found.group(1).upper()) if found else None
    return [brand] if brand else []


def brands_of(segments: Iterable[tuple[str, str | None, str | None] | tuple[str, str | None, str | None, str | None]],
              airlines: Mapping[str, str]) -> list[str | None]:
    out: list[str | None] = []
    for s in segments:
        found = _candidates(s[0], s[1], s[2], s[3] if len(s) > 3 else None, airlines)
        out.append(found[0] if found else None)
    return out


def _airlines(conn: db.Connection, numbers: Iterable[str | None]) -> dict[str, str]:
    codes = {m.group(1).upper() for n in numbers if (m := FLIGHT_NUMBER.fullmatch(n or ""))}
    if not codes:
        return {}
    return dict(conn.execute(select(Airline.code, Airline.name).where(Airline.code.in_(sorted(codes)))).fetchall())


def brand_names(conn: db.Connection, segments: Sequence[Segment], details: Sequence[Mapping[str, str]]) -> list[str | None]:
    numbers = [d.get("flight_number") for d in details]
    airlines = _airlines(conn, numbers)
    each = [_candidates(s.kind, s.provider, n, s.origin, airlines) for s, n in zip(segments, numbers, strict=True)]
    kept = have(conn, [b for found in each for b in found])
    return [next((b for b in found if key(b) in kept), found[0] if found else None) for found in each]


def chip(kind: str, hotel: str | None, brand: str | None) -> str | None:
    own = sub_brand(hotel) if kind == "hotel" else None
    return chip_label(own) if own and brand and key(brand) != key(own) else None


def have(conn: db.Connection, brands: Iterable[str | None]) -> set[str]:
    keys = sorted({key(b) for b in brands if b})
    if not keys:
        return set()
    return {k for k in keys if bundled_logos.has(k)} | {
        k for (k,) in conn.execute(select(BrandLogo.key).where(BrandLogo.key.in_(keys), BrandLogo.logo.is_not(None))).fetchall()}


def segment_logo(conn: db.Connection, viewer: Viewer, segment_id: int) -> tuple[bytes, str] | None:
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    return logo(conn, brand_names(conn, [seg], [{"flight_number": _flight_number(seg.details) or ""}])[0])


def membership_logo(conn: db.Connection, loyalty_id: int) -> tuple[bytes, str] | None:
    row = conn.execute(select(LoyaltyId.kind, LoyaltyId.program).where(LoyaltyId.id == loyalty_id)).fetchone()
    return logo(conn, loyalty.logo_brand(row[0], row[1])) if row else None


def with_logo(conn: db.Connection, kind_programs: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    pairs = {(k, p): loyalty.logo_brand(k, p) for k, p in kind_programs}
    kept = have(conn, pairs.values())
    return {pair for pair, brand in pairs.items() if brand and key(brand) in kept}


def logo(conn: db.Connection, brand: str | None) -> tuple[bytes, str] | None:
    if not brand:
        return None
    if bundled := bundled_logos.read(brand):
        return bundled
    row = conn.execute(select(BrandLogo.logo, BrandLogo.logo_type).where(BrandLogo.key == key(brand))).fetchone()
    return (bytes(row[0]), row[1]) if row and row[0] and row[1] else None


def _flight_number(details: str | None) -> str | None:
    try:
        found = json.loads(details) if details else {}
    except ValueError:
        return None
    number = found.get("flight_number") if isinstance(found, dict) else None
    return number if isinstance(number, str) else None
