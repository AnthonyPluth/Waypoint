from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypedDict

from sqlalchemy import delete, func, select, update

from . import db, secretbox
from .models import Photo, PhotoSource

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


def save(conn: db.Connection, person_id: int, owner_sub: str, url: str, immich_user_id: str, key: str, label: str | None, now: float) -> int:
    row = PhotoSource(person_id=person_id, owner_sub=owner_sub, url=url, immich_user_id=immich_user_id, api_key=secretbox.encrypt(key) or "",
                      label=label, status=OK, last_sync=None, last_error=None, created=now)
    conn.orm.add(row)
    conn.orm.flush()
    return int(row.id)


def set_key(conn: db.Connection, source_id: int, key: str) -> None:
    conn.execute(update(PhotoSource).where(PhotoSource.id == source_id).values(api_key=secretbox.encrypt(key) or "", status=OK, last_error=None))


def set_label(conn: db.Connection, source_id: int, label: str | None) -> None:
    conn.execute(update(PhotoSource).where(PhotoSource.id == source_id).values(label=label))


def mark(conn: db.Connection, source_id: int, status: Status, error: str | None = None, synced: float | None = None) -> None:
    values: dict[str, object] = {"status": status, "last_error": error}
    if synced is not None:
        values["last_sync"] = synced
    conn.execute(update(PhotoSource).where(PhotoSource.id == source_id).values(**values))


def remove(conn: db.Connection, source_id: int) -> bool:
    return int(conn.execute(delete(PhotoSource).where(PhotoSource.id == source_id)).rowcount) > 0


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
