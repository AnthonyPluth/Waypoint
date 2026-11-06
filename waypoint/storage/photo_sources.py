from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from sqlalchemy import ColumnElement, delete, func, select, true, update

from . import db, secretbox
from .models import Person, Photo, PhotoSource

Status = Literal["ok", "refused", "unreachable", "off"]
OK: Status = "ok"
REFUSED: Status = "refused"
UNREACHABLE: Status = "unreachable"
OFF: Status = "off"
STATUSES: tuple[Status, ...] = (OK, REFUSED, UNREACHABLE, OFF)
ON_A_TRIP = ("place", "time", "far")


class Stored(TypedDict):
    id: int
    person_id: int
    owner_sub: str
    url: str
    immich_user_id: str
    label: str | None
    status: Status
    last_sync: float | None
    last_error: str | None
    created: float


@dataclass(frozen=True)
class Unlocked:
    id: int
    url: str = field(repr=False)
    key: str = field(repr=False)
    user_id: str = field(repr=False)


COLUMNS = (PhotoSource.id, PhotoSource.person_id, PhotoSource.owner_sub, PhotoSource.url, PhotoSource.immich_user_id, PhotoSource.label,
           PhotoSource.status, PhotoSource.last_sync, PhotoSource.last_error, PhotoSource.created)


def _stored(row: dict) -> Stored:
    status = row["status"] if row["status"] in STATUSES else UNREACHABLE
    return {"id": int(row["id"]), "person_id": int(row["person_id"]), "owner_sub": str(row["owner_sub"]), "url": str(row["url"]),
            "immich_user_id": str(row["immich_user_id"]), "label": row["label"], "status": status, "last_sync": row["last_sync"],
            "last_error": row["last_error"], "created": float(row["created"])}


def list_all(conn: db.Connection) -> list[Stored]:
    return [_stored(r) for r in db.rows(conn.execute(select(*COLUMNS).order_by(PhotoSource.id)))]


def get(conn: db.Connection, source_id: int) -> Stored | None:
    row = conn.execute(select(*COLUMNS).where(PhotoSource.id == source_id)).fetchone()
    return _stored(dict(row)) if row is not None else None


def for_person(conn: db.Connection, person_id: int) -> list[Stored]:
    return [_stored(r) for r in db.rows(conn.execute(select(*COLUMNS).where(PhotoSource.person_id == person_id).order_by(PhotoSource.id)))]


def lock_person(conn: db.Connection, person_id: int) -> bool:
    return conn.execute(select(Person.id).where(Person.id == person_id).with_for_update()).fetchone() is not None


def save(conn: db.Connection, person_id: int, owner_sub: str, url: str, immich_user_id: str, key: str, label: str | None, now: float) -> int | None:
    values = {"person_id": person_id, "owner_sub": owner_sub, "url": url, "immich_user_id": immich_user_id, "api_key": secretbox.encrypt(key) or "",
              "label": label, "status": OK, "last_sync": None, "last_error": None, "created": now}
    if db.insert_ignore(conn, PhotoSource, values, key=["person_id", "url"]).rowcount == 0:
        return None
    found = conn.execute(select(PhotoSource.id).where(PhotoSource.person_id == person_id, PhotoSource.url == url, PhotoSource.owner_sub == owner_sub)).scalar()
    return int(found) if found is not None else None


def _held_by(source_id: int, owner: str | None) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return PhotoSource.id == source_id, PhotoSource.owner_sub == owner if owner is not None else true()


def set_key(conn: db.Connection, source_id: int, key: str, owner: str | None = None) -> bool:
    return int(conn.execute(update(PhotoSource).where(*_held_by(source_id, owner)).values(api_key=secretbox.encrypt(key) or "")).rowcount) > 0


def set_label(conn: db.Connection, source_id: int, label: str | None, owner: str | None = None) -> bool:
    return int(conn.execute(update(PhotoSource).where(*_held_by(source_id, owner)).values(label=label)).rowcount) > 0


def mark(conn: db.Connection, source_id: int, status: Status, error: str | None = None, synced: float | None = None,
         owner: str | None = None) -> bool:
    values: dict[str, object] = {"status": status, "last_error": error}
    if synced is not None:
        values["last_sync"] = synced
    return int(conn.execute(update(PhotoSource).where(*_held_by(source_id, owner)).values(**values)).rowcount) > 0


def remove(conn: db.Connection, source_id: int, owner: str | None = None) -> bool:
    return int(conn.execute(delete(PhotoSource).where(*_held_by(source_id, owner))).rowcount) > 0


def source_for_provider(conn: db.Connection, source_id: int) -> Unlocked | None:
    row = conn.execute(select(PhotoSource.id, PhotoSource.url, PhotoSource.api_key, PhotoSource.immich_user_id)
                       .where(PhotoSource.id == source_id)).fetchone()
    if row is None:
        return None
    return Unlocked(id=int(row["id"]), url=str(row["url"]), key=secretbox.decrypt(row["api_key"]) or "", user_id=str(row["immich_user_id"]))


def counts(conn: db.Connection) -> dict[int, tuple[int, int]]:
    rows = conn.execute(select(Photo.source_id, func.count(Photo.id), func.count(Photo.trip_id.distinct()))
                        .where(Photo.trip_id.is_not(None), Photo.match.in_(ON_A_TRIP)).group_by(Photo.source_id)).fetchall()
    return {int(r[0]): (int(r[1]), int(r[2])) for r in rows}


def claim(conn: db.Connection, guest_id: int, member_id: int, sub: str) -> int:
    taken = select(PhotoSource.url).where(PhotoSource.person_id == member_id)
    conn.execute(delete(PhotoSource).where(PhotoSource.person_id == guest_id, PhotoSource.url.in_(taken)))
    return int(conn.execute(update(PhotoSource).where(PhotoSource.person_id == guest_id).values(person_id=member_id, owner_sub=sub)).rowcount)
