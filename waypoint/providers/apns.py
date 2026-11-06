from __future__ import annotations

import base64
import json
import threading
import time

from dataclasses import dataclass


from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from .. import tls

HOSTS = {"production": "https://api.push.apple.com", "sandbox": "https://api.sandbox.push.apple.com"}
BODY = json.dumps({"aps": {"alert": {"title": "Waypoint", "body": "Open Waypoint to see an update."}, "sound": "default"}}).encode()
JWT_LIFETIME = 40 * 60
GONE_REASONS = {"Unregistered"}

_lock = threading.Lock()
_issued: dict[tuple[str, str], tuple[str, float]] = {}


class Gone(Exception):
    pass


@dataclass(frozen=True)
class Credentials:
    key_pem: bytes
    key_id: str
    team_id: str
    topic: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def provider_token(creds: Credentials, now: float) -> str:
    with _lock:
        cached = _issued.get((creds.key_id, creds.team_id))
        if cached and now - cached[1] < JWT_LIFETIME:
            return cached[0]
        key = serialization.load_pem_private_key(creds.key_pem, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("the APNs key isn't an elliptic-curve key")
        head = _b64(json.dumps({"alg": "ES256", "kid": creds.key_id}, separators=(",", ":")).encode())
        claims = _b64(json.dumps({"iss": creds.team_id, "iat": int(now)}, separators=(",", ":")).encode())
        r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
        token = f"{head}.{claims}.{_b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
        _issued[(creds.key_id, creds.team_id)] = (token, now)
        return token


def post(url: str, headers: dict[str, str], content: bytes, timeout: float) -> tuple[int, bytes]:
    return tls.post_http2(url, headers, content, timeout)


def push(creds: Credentials, token: str, environment: str, collapse_id: str | None = None, timeout: float = 10) -> None:
    headers = {
        "authorization": f"bearer {provider_token(creds, time.time())}", "apns-topic": creds.topic, "apns-push-type": "alert",
        "apns-priority": "10", "content-type": "application/json"}
    if collapse_id:
        headers["apns-collapse-id"] = collapse_id
    try:
        status, raw = post(f"{HOSTS[environment]}/3/device/{token}", headers, BODY, timeout)
    except ConnectionError as e:
        raise RuntimeError("couldn't reach Apple's push service") from e
    if status == 200:
        return
    try:
        reason = str(json.loads(raw).get("reason", ""))[:60]
    except (ValueError, AttributeError):
        reason = ""
    if status == 410 or reason in GONE_REASONS:
        raise Gone(token)
    raise RuntimeError(f"Apple's push service said {status} {reason}".strip())
