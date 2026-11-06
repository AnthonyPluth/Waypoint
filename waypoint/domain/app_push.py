from __future__ import annotations

import os
import re
import urllib.parse

from typing import TypedDict

from sqlalchemy import delete, select

from .. import monitoring
from ..providers import relay
from ..storage import app_devices, db
from ..storage.models import AppDevice

RELAY_ENV = "WAYPOINT_PUSH_RELAY_URL"
MAX_DEVICES = 10
_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
_SECRET = re.compile(r"[A-Za-z0-9_-]{20,100}")
_TAG = re.compile(r"[A-Za-z0-9-]{1,64}")


class DeviceOut(TypedDict):
    id: int
    service: str
    created: float


class Invalid(Exception):
    pass


def relay_url() -> str | None:
    value = (os.environ.get(RELAY_ENV) or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(value)
    return value if parts.scheme == "https" and parts.hostname and not (parts.query or parts.fragment or parts.username) else None


def devices(conn: db.Connection, owner: str) -> list[DeviceOut]:
    rows = conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner).order_by(AppDevice.id)).all()
    return [{"id": d.id, "service": "iPhone", "created": d.created} for d in rows]


def add_device(conn: db.Connection, owner: str, device_id: str, secret: str, now: float) -> DeviceOut:
    if not _ID.fullmatch(device_id) or not _SECRET.fullmatch(secret):
        raise Invalid("That isn’t a push registration Waypoint can use.")
    mine = conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner)).all()
    if len(mine) >= MAX_DEVICES and device_id not in {d.device_id for d in mine}:
        raise Invalid(f"Turn notifications off on an iPhone you no longer use first (at most {MAX_DEVICES}).")
    db.upsert(conn, AppDevice, {"owner_sub": owner, "device_id": device_id, "secret": app_devices.seal(secret), "created": now},
              key=["owner_sub", "device_id"], update=["secret"])
    found = conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner, AppDevice.device_id == device_id)).one()
    conn.orm.refresh(found)
    return {"id": found.id, "service": "iPhone", "created": found.created}


def remove_device(conn: db.Connection, owner: str, device_id: int) -> bool:
    return conn.execute(delete(AppDevice).where(AppDevice.id == device_id, AppDevice.owner_sub == owner)).rowcount > 0


def owners(conn: db.Connection) -> set[str]:
    return set(conn.execute(select(AppDevice.owner_sub)).scalars()) if relay_url() else set()


def forget(conn: db.Connection, owner: str) -> None:
    conn.execute(delete(AppDevice).where(AppDevice.owner_sub == owner))


def wake(conn: db.Connection, owner: str, tag: str) -> tuple[int, int]:
    base = relay_url()
    if base is None:
        return 0, 0
    reached = tried = 0
    for d in conn.orm.scalars(select(AppDevice).where(AppDevice.owner_sub == owner).order_by(AppDevice.id)).all():
        tried += 1
        try:
            relay.wake(base, d.device_id, app_devices.secret_of(d), tag if _TAG.fullmatch(tag) else None)
            reached += 1
        except relay.Gone:
            conn.execute(delete(AppDevice).where(AppDevice.id == d.id))
            tried -= 1
        except Exception as e:
            monitoring.report(e, values=False)
    return reached, tried
