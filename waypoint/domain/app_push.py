from __future__ import annotations

import os
import re

from typing import TypedDict

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import delete, select

from .. import monitoring
from ..providers import apns
from ..storage import db
from ..storage.models import AppDevice

KEY_FILE_ENV = "WAYPOINT_APNS_KEY_FILE"
KEY_ID_ENV = "WAYPOINT_APNS_KEY_ID"
TEAM_ID_ENV = "WAYPOINT_APNS_TEAM_ID"
TOPIC_ENV = "WAYPOINT_APNS_TOPIC"
MAX_DEVICES = 10
ENVIRONMENTS = ("production", "sandbox")
_TOKEN = re.compile(r"[0-9a-f]{64,200}")
_APPLE_ID = re.compile(r"[A-Z0-9]{10}")
_TOPIC = re.compile(r"[A-Za-z0-9.-]{3,155}")
_TAG = re.compile(r"[A-Za-z0-9-]{1,64}")


class DeviceOut(TypedDict):
    id: int
    service: str
    created: float


class Invalid(Exception):
    pass


def credentials() -> apns.Credentials | None:
    path, key_id, team_id, topic = (os.environ.get(k, "").strip() for k in (KEY_FILE_ENV, KEY_ID_ENV, TEAM_ID_ENV, TOPIC_ENV))
    if not (path and _APPLE_ID.fullmatch(key_id) and _APPLE_ID.fullmatch(team_id) and _TOPIC.fullmatch(topic)):
        return None
    try:
        with open(path, "rb") as f:
            pem = f.read(8192)
    except OSError:
        return None
    try:
        key = serialization.load_pem_private_key(pem, password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm):
        return None
    if not (isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1)):
        return None
    return apns.Credentials(pem, key_id, team_id, topic)


def enabled() -> bool:
    return credentials() is not None


def devices(conn: db.Connection, owner: str) -> list[DeviceOut]:
    rows = conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner).order_by(AppDevice.id)).all()
    return [{"id": d.id, "service": "iPhone", "created": d.created} for d in rows]


def add_device(conn: db.Connection, owner: str, token: str, environment: str, now: float, replaces: str | None = None) -> DeviceOut:
    token = token.strip().lower()
    old = (replaces or "").strip().lower()
    if not _TOKEN.fullmatch(token) or environment not in ENVIRONMENTS:
        raise Invalid("That isn’t a push registration Waypoint can use.")
    if old and old != token:
        conn.execute(delete(AppDevice).where(AppDevice.token == old))
    mine = conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner)).all()
    if len(mine) >= MAX_DEVICES and token not in {d.token for d in mine}:
        raise Invalid(f"Turn notifications off on an iPhone you no longer use first (at most {MAX_DEVICES}).")
    db.upsert(conn, AppDevice, {"owner_sub": owner, "token": token, "environment": environment, "created": now},
              key=["token"], update=["owner_sub", "environment"])
    found = conn.orm.scalars(select(AppDevice).where(AppDevice.token == token)).one()
    conn.orm.refresh(found)
    return {"id": found.id, "service": "iPhone", "created": found.created}


def remove_device(conn: db.Connection, owner: str, device_id: int) -> bool:
    return conn.execute(delete(AppDevice).where(AppDevice.id == device_id, AppDevice.owner_sub == owner)).rowcount > 0


def owners(conn: db.Connection) -> set[str]:
    return set(conn.execute(select(AppDevice.owner_sub)).scalars()) if enabled() else set()


def forget(conn: db.Connection, owner: str) -> None:
    conn.execute(delete(AppDevice).where(AppDevice.owner_sub == owner))


def wake(conn: db.Connection, owner: str, tag: str) -> tuple[int, int]:
    creds = credentials()
    if creds is None:
        return 0, 0
    reached = tried = 0
    for d in conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner).order_by(AppDevice.id)).all():
        tried += 1
        try:
            apns.push(creds, d.token, d.environment, tag if _TAG.fullmatch(tag) else None)
            reached += 1
        except apns.Gone:
            conn.execute(delete(AppDevice).where(AppDevice.id == d.id))
            tried -= 1
        except Exception as e:
            monitoring.report(e, values=False)
    return reached, tried
