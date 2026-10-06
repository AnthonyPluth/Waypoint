"""Logos for the airlines, hotels, rental companies and cruise lines in bookings, from Logo.dev (waypoint/providers/logodev.py).

A booking's `provider` names its brand ("American Airlines", "Marriott"); a flight with none is named by its flight number's
airline code. A hotel whose name starts with one of a hotel group's own brands ("Hyatt Regency Chicago", "Courtyard Denver") is
asked about by that brand ("Hyatt Regency", "Courtyard by Marriott") first, so each has its own logo, and by its provider's when
Logo.dev has none for it. Only the brand, never the rest of the hotel's name (a place), is sent. Once the household saves a Logo.dev key (Settings), a background round (jobs.fetch_logos) asks Logo.dev for each
brand it hasn't asked about, keeps the answer in `brand_logos` and Waypoint serves it itself, so the app never asks
anyone else for an image and the page's content policy stays "images from Waypoint only". A brand Logo.dev has none for is
remembered as such and asked again after a month, as is one it has, in case the brand's logo changed. Logo.dev only ever
learns brand names, never who travelled, when, or what the confirmation was.

A logo is served only through a segment the viewer can see (`GET /api/segments/{id}/logo`): who has stayed where is not
for anyone else to find out by guessing a brand.
"""
from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import TypedDict

from sqlalchemy import insert, select, update

from ..providers import logodev
from ..storage import db
from ..storage import settings_keys as sk
from ..storage.models import Airline, BrandLogo, Segment
from . import visibility
from .visibility import Viewer

PER_ROUND = 20        # brands asked about in one round at most
REFRESH_DAYS = 30     # a brand is asked about again after this long
FLIGHT_NUMBER = re.compile(r"\s*([A-Za-z0-9]{2})\s*\d{1,4}[A-Za-z]?\s*")


class Status(TypedDict):
    configured: bool
    searchable: bool           # a secret key is saved too, so a brand is picked by Brand Search
    with_logo: int             # brands that have a logo
    unknown: int               # brands Logo.dev has none for
    waiting: int               # brands not asked about yet
    last_error: str | None     # why the last round failed (fixed text), or None


def configured(conn: db.Connection) -> bool:
    return bool(db.get_setting(conn, sk.LOGODEV_TOKEN))


def searchable(conn: db.Connection) -> bool:
    return configured(conn) and bool(db.get_setting(conn, sk.LOGODEV_SECRET))


def key(name: str | None) -> str:
    return " ".join((name or "").lower().split())


def _name(provider: str | None) -> str | None:
    """A provider worth asking about: some letters, and not a code or a sentence."""
    text = " ".join((provider or "").split())
    return text if 2 <= len(text) <= 100 and len(re.findall(r"[A-Za-z]", text)) >= 2 else None


# The brands a hotel group runs under their own names: what a hotel's name starts with (lower case, letters and digits), and the
# brand asked about for it. Not every brand has a logo of its own at Logo.dev; the booking's provider is the fallback.
SUB_BRANDS: tuple[tuple[str, str], ...] = (
    ("hyatt regency", "Hyatt Regency"), ("hyatt place", "Hyatt Place"), ("hyatt house", "Hyatt House"), ("grand hyatt", "Grand Hyatt"),
    ("park hyatt", "Park Hyatt"), ("hyatt centric", "Hyatt Centric"), ("andaz", "Andaz"), ("hyatt ziva", "Hyatt Ziva"),
    ("courtyard", "Courtyard by Marriott"), ("residence inn", "Residence Inn by Marriott"), ("fairfield inn", "Fairfield by Marriott"),
    ("fairfield by marriott", "Fairfield by Marriott"), ("springhill suites", "SpringHill Suites by Marriott"),
    ("towneplace suites", "TownePlace Suites by Marriott"), ("sheraton", "Sheraton"), ("westin", "Westin"), ("renaissance", "Renaissance Hotels"),
    ("autograph collection", "Autograph Collection"), ("aloft", "Aloft Hotels"), ("moxy", "Moxy Hotels"), ("four points", "Four Points by Sheraton"),
    ("le meridien", "Le Méridien"), ("ritz carlton", "The Ritz-Carlton"), ("st regis", "The St. Regis"), ("jw marriott", "JW Marriott"),
    ("gaylord", "Gaylord Hotels"), ("w hotel", "W Hotels"), ("ac hotel", "AC Hotels by Marriott"), ("element by westin", "Element Hotels"),
    ("hampton inn", "Hampton by Hilton"), ("hampton by hilton", "Hampton by Hilton"), ("hilton garden inn", "Hilton Garden Inn"),
    ("doubletree", "DoubleTree by Hilton"), ("embassy suites", "Embassy Suites by Hilton"), ("homewood suites", "Homewood Suites by Hilton"),
    ("home2 suites", "Home2 Suites by Hilton"), ("tru by hilton", "Tru by Hilton"), ("conrad", "Conrad Hotels"),
    ("waldorf astoria", "Waldorf Astoria Hotels"), ("curio collection", "Curio Collection by Hilton"), ("canopy by hilton", "Canopy by Hilton"),
    ("holiday inn express", "Holiday Inn Express"), ("holiday inn", "Holiday Inn"), ("crowne plaza", "Crowne Plaza"),
    ("intercontinental", "InterContinental Hotels"), ("staybridge suites", "Staybridge Suites"), ("candlewood suites", "Candlewood Suites"),
    ("hotel indigo", "Hotel Indigo"), ("kimpton", "Kimpton Hotels"), ("even hotel", "EVEN Hotels"), ("avid hotel", "avid hotels"),
    ("best western plus", "Best Western Plus"), ("best western premier", "Best Western Premier"), ("comfort inn", "Comfort Inn"),
    ("comfort suites", "Comfort Suites"), ("quality inn", "Quality Inn"), ("sleep inn", "Sleep Inn"), ("la quinta", "La Quinta by Wyndham"),
    ("wyndham garden", "Wyndham Garden"), ("radisson blu", "Radisson Blu"), ("radisson red", "Radisson RED"), ("fairmont", "Fairmont Hotels"),
    ("sofitel", "Sofitel"), ("novotel", "Novotel"), ("pullman", "Pullman Hotels"), ("mercure", "Mercure Hotels"),
)
_SUB_BRANDS = sorted(SUB_BRANDS, key=lambda b: -len(b[0]))   # (the longest first: "holiday inn express" before "holiday inn")


def sub_brand(hotel: str | None) -> str | None:
    """The hotel group brand a hotel's name starts with ("Hyatt Place Chicago River North" -> "Hyatt Place"), or None."""
    words = " ".join(re.sub(r"[^a-z0-9]+", " ", (hotel or "").lower()).split())
    for start, brand in _SUB_BRANDS:
        if words == start or words.startswith(start + " "):
            return brand
    return None


def _candidates(kind: str, provider: str | None, number: str | None, hotel: str | None, airlines: Mapping[str, str]) -> list[str]:
    """The brands a segment may show a logo of, best first: a hotel's own brand, then its provider's (a flight with none: its
    airline's)."""
    brand = _name(provider)
    if brand is None and kind == "flight":
        found = FLIGHT_NUMBER.fullmatch(number or "")
        brand = airlines.get(found.group(1).upper()) if found else None
    own = sub_brand(hotel) if kind == "hotel" else None
    return [b for b in (own, brand) if b and (b is own or not own or key(b) != key(own))]


def brands_of(segments: Iterable[tuple[str, str | None, str | None] | tuple[str, str | None, str | None, str | None]],
              airlines: Mapping[str, str]) -> list[str | None]:
    """The brand of each (kind, provider, flight number, and for a hotel its name): a hotel's own brand, else its provider, else
    for a flight its airline's name."""
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
    """The brand each segment shows (details: its decoded details, in the same order), or None: the first of its brands that
    Waypoint has a logo for (a hotel's own brand, then its provider's), else the first."""
    numbers = [d.get("flight_number") for d in details]
    airlines = _airlines(conn, numbers)
    each = [_candidates(s.kind, s.provider, n, s.origin, airlines) for s, n in zip(segments, numbers, strict=True)]
    kept = have(conn, [b for found in each for b in found])
    return [next((b for b in found if key(b) in kept), found[0] if found else None) for found in each]


def have(conn: db.Connection, brands: Iterable[str | None]) -> set[str]:
    """Which of these brands (by key) Waypoint has a logo for."""
    keys = sorted({key(b) for b in brands if b})
    if not keys:
        return set()
    return {k for (k,) in conn.execute(select(BrandLogo.key).where(BrandLogo.key.in_(keys), BrandLogo.logo.is_not(None))).fetchall()}


def segment_logo(conn: db.Connection, viewer: Viewer, segment_id: int) -> tuple[bytes, str] | None:
    """The logo of a segment's brand, or None when the segment isn't the viewer's (as one that isn't there), has no brand or
    its brand has no logo."""
    seg = visibility.visible_segment(conn, viewer, segment_id)
    if seg is None:
        return None
    return logo(conn, brand_names(conn, [seg], [{"flight_number": _flight_number(seg.details) or ""}])[0])


def logo(conn: db.Connection, brand: str | None) -> tuple[bytes, str] | None:
    """The brand's logo and its content type, if Waypoint has one."""
    if not brand:
        return None
    row = conn.execute(select(BrandLogo.logo, BrandLogo.logo_type).where(BrandLogo.key == key(brand))).fetchone()
    return (bytes(row[0]), row[1]) if row and row[0] and row[1] else None


# ------------------------------------------------------------------------------------------------ choosing a brand

_FILLER = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company|the|hotel|hotels|resort|resorts|airlines|airline|air lines|airways)\b")


def _norm(s: str | None) -> str:
    s = (s or "").lower().replace("&", " and ").replace("'", "").replace("’", "")
    return " ".join(_FILLER.sub(" ", re.sub(r"[^a-z0-9 ]+", " ", s)).split())


def best_match(name: str, candidates: Sequence[Mapping[str, str]]) -> Mapping[str, str] | None:
    """The brand Brand Search found that is clearly this one, or None: better no logo than someone else's. A match is the
    same name (or website) give or take spaces, punctuation and "Inc", a brand the name starts with ("Hyatt Regency Chicago"
    is "Hyatt Regency"), or a close spelling."""
    n = _norm(name)
    squashed = n.replace(" ", "")
    if len(squashed) < 3:
        return None
    best: Mapping[str, str] | None = None
    score = 0.0
    for c in candidates:
        cn = _norm(c.get("name"))
        dom = (c.get("domain") or "").split(".")[0].replace("-", "")
        s = difflib.SequenceMatcher(None, n, cn).ratio() if cn else 0.0
        if cn.replace(" ", "") == squashed or dom == squashed:
            s = 1.0
        elif cn and len(cn) >= 5 and n.startswith(cn + " "):
            s = max(s, 0.9)
        if s > score:
            best, score = c, s
    return best if score >= 0.85 else None


# ------------------------------------------------------------------------------------------------ fetching

def _flight_number(details: str | None) -> str | None:
    try:
        found = json.loads(details) if details else {}
    except ValueError:
        return None
    number = found.get("flight_number") if isinstance(found, dict) else None
    return number if isinstance(number, str) else None


def note(conn: db.Connection) -> int:
    """Note the brands of every segment that Waypoint hasn't asked about (a row with no answer yet). Returns how many are new."""
    rows = conn.execute(select(Segment.kind, Segment.provider, Segment.details, Segment.origin)).fetchall()
    numbers = [_flight_number(r[2]) for r in rows]
    airlines = _airlines(conn, numbers)
    found: dict[str, str] = {}
    for r, n in zip(rows, numbers, strict=True):
        for brand in _candidates(r[0], r[1], n, r[3], airlines):
            found.setdefault(key(brand), brand)
    if not found:
        return 0
    known = {k for (k,) in conn.execute(select(BrandLogo.key).where(BrandLogo.key.in_(sorted(found)))).fetchall()}
    new = {k: n for k, n in found.items() if k not in known}
    for k, n in new.items():
        conn.execute(insert(BrandLogo).values(key=k, name=n))
    return len(new)


def _due(conn: db.Connection, now: datetime, limit: int) -> list[tuple[str, str]]:
    stale = (now - timedelta(days=REFRESH_DAYS)).isoformat(timespec="seconds")
    rows = conn.execute(select(BrandLogo.key, BrandLogo.name).where(BrandLogo.checked.is_(None) | (BrandLogo.checked < stale))
                        .order_by(BrandLogo.checked.is_not(None), BrandLogo.key).limit(limit)).fetchall()
    return [(r[0], r[1]) for r in rows]


def fetch_due(conn: db.Connection, now: datetime, limit: int = PER_ROUND) -> int:
    """Ask Logo.dev about the brands that are new or last asked a month ago, when there's a key. Returns how many it got a
    logo for. A key it refuses or a connection that fails stops the round, says why in Settings, and leaves the rest unmarked
    so they are asked again next time, rather than a month from now."""
    token = db.get_setting(conn, sk.LOGODEV_TOKEN)
    if not token:
        return 0
    note(conn)
    secret = db.get_setting(conn, sk.LOGODEV_SECRET)
    stamp = now.isoformat(timespec="seconds")
    got = 0
    search_refused = False   # Brand Search said no to the secret key: brands are asked for by name instead
    for k, name in _due(conn, now, limit):
        try:
            found = None
            if secret and not search_refused:   # Brand Search, and only a clear match
                try:
                    candidates: list[dict[str, str]] | None = logodev.search(secret, name)
                except logodev.Refused:   # (the publishable key may be fine, and a plan may not include Brand Search)
                    candidates, search_refused = None, True
                if candidates is not None:
                    picked = best_match(name, candidates)
                    found = logodev.fetch(token, domain=picked["domain"]) if picked else None
            if not secret or search_refused:
                found = logodev.fetch(token, name=name)
        except logodev.LogoError as e:
            db.set_setting(conn, sk.LOGODEV_LAST_ERROR, f"{now:%b %d %H:%M}: {e}")
            return got
        if found:
            conn.execute(update(BrandLogo).where(BrandLogo.key == k).values(
                logo=found[0], logo_type=found[1], checked=stamp))
            got += 1
        else:   # no such brand (a logo Waypoint has is kept: it may only be Logo.dev's gap)
            conn.execute(update(BrandLogo).where(BrandLogo.key == k).values(checked=stamp))
    db.set_setting(conn, sk.LOGODEV_LAST_ERROR, f"{now:%b %d %H:%M}: Logo.dev refused the secret key for Brand Search (or your plan doesn't "
                   "include it), so brands were looked up by name instead" if search_refused else None)
    return got


def status(conn: db.Connection) -> Status:
    rows = conn.execute(select(BrandLogo.logo.is_not(None), BrandLogo.checked.is_not(None))).fetchall()
    return {"configured": configured(conn), "searchable": searchable(conn),
            "with_logo": sum(1 for logo_, _ in rows if logo_), "unknown": sum(1 for logo_, checked in rows if checked and not logo_),
            "waiting": sum(1 for _, checked in rows if not checked), "last_error": db.get_setting(conn, sk.LOGODEV_LAST_ERROR)}
