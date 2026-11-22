from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import NamedTuple, TypedDict

from ..providers import mapkit
from ..storage import db
from . import driving_routes, maps, tripmap
from .visibility import Viewer

MAX_TRIPS = driving_routes.MAX_TRIPS
MAX_ZOOM = 12
MIN_ZOOM = mapkit.SNAPSHOT_ZOOMS[0]
MIN_SIDE, MAX_SIDE = mapkit.SNAPSHOT_SIDES
SCALE = 2
SCHEME = "dark"
DEFAULT_LANG = "en-US"
PADDING = 28
DAY = 86_400
CENTRE_DECIMALS = 2
MAX_LATITUDE = 85.0511
KEPT = 2048
_LANG = re.compile(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2}")
WORLD = 256.0


class Invalid(driving_routes.Invalid):
    pass


class Centre(TypedDict):
    latitude: float
    longitude: float


class Snapshot(TypedDict):
    trip_id: int
    url: str
    center: Centre
    zoom: int
    width: int
    height: int


class Fit(NamedTuple):
    latitude: float
    longitude: float
    zoom: int
    width: int
    height: int


def _world(latitude: float, longitude: float) -> tuple[float, float]:
    lat = max(-MAX_LATITUDE, min(MAX_LATITUDE, latitude))
    x = (longitude + 180) / 360 * WORLD
    y = (0.5 - math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) / (2 * math.pi)) * WORLD
    return x, y


def _ground(x: float, y: float) -> tuple[float, float]:
    longitude = x / WORLD * 360 - 180
    latitude = math.degrees(2 * math.atan(math.exp((0.5 - y / WORLD) * 2 * math.pi)) - math.pi / 2)
    return latitude, longitude


def _unwrapped(longitudes: list[float]) -> list[float]:
    ordered = sorted(longitudes)
    gaps = [(ordered[(i + 1) % len(ordered)] - ordered[i]) % 360 for i in range(len(ordered))]
    start = ordered[(gaps.index(max(gaps)) + 1) % len(ordered)]
    return [lon if lon >= start else lon + 360 for lon in longitudes]


def fit(points: list[tuple[float, float]], width: int, height: int) -> Fit | None:
    if not points:
        return None
    wrapped = _unwrapped([lon for _, lon in points])
    ground = [_world(lat, lon) for (lat, _), lon in zip(points, wrapped, strict=True)]
    xs, ys = [g[0] for g in ground], [g[1] for g in ground]
    latitude, spread = (round(v, CENTRE_DECIMALS) for v in _ground((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2))
    cx, cy = _world(latitude, spread)
    longitude = round((spread + 180) % 360 - 180, CENTRE_DECIMALS)
    reach_x, reach_y = max(abs(x - cx) for x in xs), max(abs(y - cy) for y in ys)
    for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
        scale = 2 ** zoom
        if reach_x * scale <= width / 2 - PADDING and reach_y * scale <= height / 2 - PADDING:
            return Fit(latitude, longitude, zoom, width, height)
    shrink = max(1.0, reach_x * 2 ** MIN_ZOOM / max(width / 2 - PADDING, 1.0), reach_y * 2 ** MIN_ZOOM / max(height / 2 - PADDING, 1.0))
    wide, tall = math.ceil(width * shrink), math.ceil(height * shrink)
    if max(wide, tall) > MAX_SIDE:
        grow = MAX_SIDE / max(wide, tall)
        wide, tall = max(MIN_SIDE, math.floor(wide * grow)), max(MIN_SIDE, math.floor(tall * grow))
    return Fit(latitude, longitude, MIN_ZOOM, wide, tall)


def parse_side(texts: list[str], what: str) -> int:
    text = texts[0] if len(texts) == 1 else ""
    if not text.isascii() or not text.isdigit() or len(text) > 4 or not MIN_SIDE <= int(text) <= MAX_SIDE:
        raise Invalid(f"Send the {what} in pixels, from {MIN_SIDE} to {MAX_SIDE}")
    return int(text)


def parse_lang(texts: list[str]) -> str:
    text = texts[0].strip() if len(texts) == 1 else ""
    return text if _LANG.fullmatch(text) else DEFAULT_LANG


@lru_cache(maxsize=KEPT)
def _address(creds: mapkit.Credentials, latitude: float, longitude: float, zoom: int, width: int, height: int, lang: str, day: int) -> str:
    return mapkit.snapshot_url(creds, (latitude, longitude), zoom, (width, height), SCALE, SCHEME, lang, day * DAY)


def for_trips(conn: db.Connection, viewer: Viewer, texts: list[str], widths: list[str], heights: list[str], langs: list[str], now: float) -> list[Snapshot]:
    asked = list(dict.fromkeys(driving_routes.parse_trips(texts)))
    width, height, lang = parse_side(widths, "width"), parse_side(heights, "height"), parse_lang(langs)
    creds = maps.credentials()
    if creds is None or not maps.enabled():
        return []
    out: list[Snapshot] = []
    for trip_id in asked:
        points = tripmap.route_points(conn, viewer, trip_id)
        found = fit(points, width, height) if points is not None else None
        if found is None:
            continue
        url = _address(creds, found.latitude, found.longitude, found.zoom, found.width, found.height, lang, int(now // DAY))
        out.append({"trip_id": trip_id, "url": url, "center": {"latitude": found.latitude, "longitude": found.longitude}, "zoom": found.zoom, "width": found.width, "height": found.height})
    return out
