from __future__ import annotations

import os
import re
import urllib.parse

from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from ..providers import mapkit

FLAG_ENV = "WAYPOINT_MAPKIT_ENABLED"
KEY_FILE_ENV = "WAYPOINT_MAPKIT_KEY_FILE"
KEY_ID_ENV = "WAYPOINT_MAPKIT_KEY_ID"
TEAM_ID_ENV = "WAYPOINT_MAPKIT_TEAM_ID"
PUBLIC_URL_ENV = "WAYPOINT_PUBLIC_URL"
MAX_KEY_BYTES = 8192
_APPLE_ID = re.compile(r"[A-Z0-9]{10}")
_OFF = {"0", "false", "no", "off"}
DEFAULT_PORTS = {"http": 80, "https": 443}


class Issued(NamedTuple):
    token: str
    expires: int
    script: str


@dataclass(frozen=True)
class Policy:
    script: tuple[str, ...]
    connect: tuple[str, ...]
    img: tuple[str, ...]
    worker: tuple[str, ...]


NO_POLICY = Policy(script=(), connect=(), img=(), worker=())
POLICY = Policy(script=("'wasm-unsafe-eval'",), connect=(mapkit.SERVICE_HOSTS, "blob:"), img=(mapkit.SERVICE_HOSTS, "blob:"), worker=(mapkit.SERVICE_HOSTS, "blob:"))


def flag_on() -> bool:
    return os.environ.get(FLAG_ENV, "").strip().lower() not in _OFF


def origin() -> str | None:
    parts = urllib.parse.urlsplit(os.environ.get(PUBLIC_URL_ENV, "").strip())
    scheme, host = parts.scheme.lower(), parts.hostname
    if scheme not in DEFAULT_PORTS or not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    shown = f"[{host}]" if ":" in host else host
    return f"{scheme}://{shown}" if port in (None, DEFAULT_PORTS[scheme]) else f"{scheme}://{shown}:{port}"


@lru_cache(maxsize=4)
def _load(path: str, key_id: str, team_id: str, stamp: int) -> mapkit.Credentials | None:
    try:
        with open(path, "rb") as f:
            pem = f.read(MAX_KEY_BYTES)
        key = serialization.load_pem_private_key(pem, password=None)
    except (OSError, ValueError, TypeError, UnsupportedAlgorithm):
        return None
    if not (isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1)):
        return None
    return mapkit.Credentials(pem, key_id, team_id)


def credentials() -> mapkit.Credentials | None:
    path, key_id, team_id = (os.environ.get(k, "").strip() for k in (KEY_FILE_ENV, KEY_ID_ENV, TEAM_ID_ENV))
    if not (path and _APPLE_ID.fullmatch(key_id) and _APPLE_ID.fullmatch(team_id)):
        return None
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return None
    return _load(path, key_id, team_id, stamp)


def enabled() -> bool:
    return flag_on() and origin() is not None and credentials() is not None


def issue(now: float) -> Issued | None:
    creds, site = credentials(), origin()
    if not (flag_on() and creds and site):
        return None
    try:
        token, expires = mapkit.sign(creds, site, now)
    except ValueError:
        return None
    return Issued(token, expires, mapkit.SCRIPT_URL)
