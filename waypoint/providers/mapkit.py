from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .. import es256, tls

SCRIPT_URL = "https://cdn.apple-mapkit.com/mk/x/mapkit.js"
SCOPE = "mapkit_js"
SERVICE_HOSTS = "https://*.apple-mapkit.com"
TOKEN_LIFETIME = 30 * 60


@dataclass(frozen=True)
class Credentials:
    key_pem: bytes
    key_id: str
    team_id: str


def header(creds: Credentials) -> dict[str, str]:
    return {"alg": "ES256", "kid": creds.key_id, "typ": "JWT"}


def claims(creds: Credentials, origin: str, issued: int, expires: int) -> dict[str, str | int]:
    return {"iss": creds.team_id, "iat": issued, "exp": expires, "scope": SCOPE, "origin": origin}


def sign(creds: Credentials, origin: str, now: float) -> tuple[str, int]:
    key = serialization.load_pem_private_key(creds.key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("the MapKit key isn't an elliptic-curve key")
    issued = int(now)
    expires = issued + TOKEN_LIFETIME
    token = es256.sign_jwt(key, header(creds), claims(creds, origin, issued, expires))
    return token, expires


SERVER_HOST = "maps-api.apple.com"
SERVER_BASE = f"https://{SERVER_HOST}"
SERVER_TIMEOUT = 15
MAX_REPLY_BYTES = 8_000_000
TOKEN_MARGIN = 60
USER_AGENT = "Waypoint/0.1"
NO_ROUTE_CODES = (400, 404, 422)


class ServerError(Exception):
    pass


class Refused(ServerError):
    def __init__(self, message: str, expired: bool = False):
        super().__init__(message)
        self.expired = expired


class Unavailable(ServerError):
    pass


SERVER_SCOPE = "server_api"


def server_claims(creds: Credentials, issued: int, expires: int, scoped: bool = False) -> dict[str, str | int]:
    claims: dict[str, str | int] = {"iss": creds.team_id, "iat": issued, "exp": expires}
    if scoped:
        claims["scope"] = SERVER_SCOPE
    return claims


def sign_server(creds: Credentials, now: float, scoped: bool = False) -> str:
    key = serialization.load_pem_private_key(creds.key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("the MapKit key isn't an elliptic-curve key")
    issued = int(now)
    return es256.sign_jwt(key, header(creds), server_claims(creds, issued, issued + TOKEN_LIFETIME, scoped))


def _get(path: str, bearer: str) -> Any:
    req = urllib.request.Request(f"{SERVER_BASE}{path}", headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with tls.urlopen(req, timeout=SERVER_TIMEOUT) as r:
            raw = r.read(MAX_REPLY_BYTES)
    except urllib.error.HTTPError as e:
        with e:
            code = e.code
        if code in (401, 403):
            raise Refused(f"Apple answered {code}", expired=code == 401) from None
        if code in NO_ROUTE_CODES:
            return None
        raise Unavailable(f"Apple answered {code}") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise Unavailable("Couldn't reach Apple's Maps Server API") from None
    try:
        return json.loads(raw)
    except ValueError:
        raise Unavailable("Apple's Maps Server API answered with something unreadable") from None


def _point(value: Any) -> list[float] | None:
    if not isinstance(value, dict):
        return None
    lat, lon = value.get("latitude"), value.get("longitude")
    if not (isinstance(lat, int | float) and isinstance(lon, int | float)) or isinstance(lat, bool) or isinstance(lon, bool):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return [float(lat), float(lon)]


def parse_path(body: Any) -> list[list[float]] | None:
    if not isinstance(body, dict):
        return None
    routes, steps, paths = body.get("routes"), body.get("steps"), body.get("stepPaths")
    if not (isinstance(routes, list) and routes and isinstance(routes[0], dict) and isinstance(steps, list) and isinstance(paths, list)):
        return None
    indexes = routes[0].get("stepIndexes")
    if not isinstance(indexes, list):
        return None
    out: list[list[float]] = []
    for index in indexes:
        step = steps[index] if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(steps) else None
        at = step.get("stepPathIndex") if isinstance(step, dict) else None
        line = paths[at] if isinstance(at, int) and not isinstance(at, bool) and 0 <= at < len(paths) else None
        if not isinstance(line, list):
            return None
        for item in line:
            point = _point(item)
            if point is None:
                return None
            if not out or out[-1] != point:
                out.append(point)
    return out if len(out) >= 2 else None


class Directions:
    def __init__(self, creds: Credentials):
        self.creds = creds
        self.token: str | None = None
        self.expires = 0.0
        self.scoped = False

    def _access(self, now: float) -> str:
        if self.token is not None and now < self.expires - TOKEN_MARGIN:
            return self.token
        try:
            body = self._exchange(now)
        except Refused as e:
            if self.scoped or not e.expired:
                raise
            self.scoped = True
            body = self._exchange(now)
        token = body.get("accessToken") if isinstance(body, dict) else None
        lifetime = body.get("expiresInSeconds") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise Unavailable("Apple's Maps Server API gave no access token")
        self.token = token
        self.expires = now + (lifetime if isinstance(lifetime, int | float) and not isinstance(lifetime, bool) and lifetime > 0 else 300)
        return token

    def _exchange(self, now: float) -> Any:
        try:
            signed = sign_server(self.creds, now, self.scoped)
        except ValueError:
            raise Refused("the MapKit key can't sign") from None
        return _get("/v1/token", signed)

    def route(self, start: tuple[float, float], end: tuple[float, float], now: float) -> list[list[float]] | None:
        query = urllib.parse.urlencode({"origin": f"{start[0]:.6f},{start[1]:.6f}", "destination": f"{end[0]:.6f},{end[1]:.6f}", "transportType": "Automobile"})
        for attempt in (0, 1):
            try:
                return parse_path(_get(f"/v1/directions?{query}", self._access(now)))
            except Refused as e:
                if attempt == 1 or self.token is None or not e.expired:
                    raise
                self.token = None
        return None
