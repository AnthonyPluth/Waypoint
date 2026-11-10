from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .. import es256

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
