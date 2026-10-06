from __future__ import annotations

import base64
import json
from typing import Any

import py_vapid
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException, webpush

from ..storage import db
from ..storage import settings_keys as sk


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def valid_public_key(p256dh: str) -> bool:
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(p256dh))
        return True
    except (ValueError, TypeError):
        return False


def vapid_keys(conn: db.Connection) -> tuple[py_vapid.Vapid02, str]:
    raw = db.get_setting(conn, sk.VAPID_PRIVATE_KEY)
    if not raw:
        key = ec.generate_private_key(ec.SECP256R1())
        raw = format(key.private_numbers().private_value, "064x")
        db.set_setting(conn, sk.VAPID_PRIVATE_KEY, raw)
    vapid = py_vapid.Vapid02.from_raw(b64u(bytes.fromhex(raw)).encode())
    public = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return vapid, b64u(public)


class Gone(Exception):
    pass


def _session() -> requests.Session:
    s = requests.Session()
    s.max_redirects = 0
    return s


def send(sub: dict[str, str], message: dict[str, Any], vapid: py_vapid.Vapid02, subject: str, ttl: int = 86400,
         urgency: str = "normal", timeout: int = 15) -> int:
    try:
        r = webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                    data=json.dumps(message, separators=(",", ":")), vapid_private_key=vapid,
                    vapid_claims={"sub": subject}, ttl=ttl, timeout=timeout, headers={"Urgency": urgency},
                    requests_session=_session())
        return int(r.status_code)
    except requests.TooManyRedirects as e:
        raise RuntimeError("the push service redirected; not followed") from e
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 410):
            raise Gone(sub["endpoint"]) from e
        raise RuntimeError(f"push service said {status}" if status else "couldn't reach the push service") from e
