from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .. import es256

SCRIPT_URL = "https://cdn.apple-mapkit.com/mk/5.x.x/mapkit.js"
SCRIPT_HOST = "https://cdn.apple-mapkit.com"
SERVICE_HOSTS = "https://*.apple-mapkit.com"
TOKEN_LIFETIME = 30 * 60


@dataclass(frozen=True)
class Credentials:
    key_pem: bytes
    key_id: str
    team_id: str


def sign(creds: Credentials, origin: str, now: float) -> tuple[str, int]:
    key = serialization.load_pem_private_key(creds.key_pem, password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise ValueError("the MapKit key isn't an elliptic-curve key")
    issued = int(now)
    expires = issued + TOKEN_LIFETIME
    token = es256.sign_jwt(key, {"alg": "ES256", "kid": creds.key_id, "typ": "JWT"},
                           {"iss": creds.team_id, "iat": issued, "exp": expires, "origin": origin})
    return token, expires
