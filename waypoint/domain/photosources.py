from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict
from urllib.parse import urlsplit

from sqlalchemy import select

from .. import oidc
from ..providers import immich
from ..storage import db, photo_sources, secretbox
from ..storage.models import Person, User
from ..storage.photo_sources import OFF, OK, REFUSED, UNREACHABLE, Status, Stored

NO_SOURCE = "No such photo library"
NO_PERSON = "No such person"
NOT_YOURS = "A member who signs in connects their own libraries; ask them to connect it."
OTHER_STEWARD = "This person’s library is managed by another member; ask them to connect it."
ALREADY = "That library is already connected for this person."
OTHER_ACCOUNT = "That key belongs to a different Immich account; remove this library and connect it again."
KEY_LOST = secretbox.KEY_LOST
HTTPS_ONLY = "Use https:// for an Immich server outside your own network."
RESUME_ASKS = "Resuming this library would add its photos to trips shared with everyone on them; confirming that isn’t available yet."
RECORD_TRIES = 3
PERMISSIONS = ("asset.read", "asset.view", "user.read", "map.read", "asset.download")


class Refused(Exception):
    pass


class NoSuchPerson(Exception):
    pass


class NoSuchSource(Exception):
    pass


@dataclass(frozen=True)
class Actor:
    sub: str
    person_id: int | None


class Listed(TypedDict):
    id: int
    person_id: int
    url: str
    label: str | None
    status: Status
    mine: bool
    last_sync: str | None
    last_error: str | None
    photos: int | None
    trips: int | None


class Tested(TypedDict):
    name: str | None
    same_account: bool | None


def allow_http(url: str) -> bool:
    return oidc.local_host(urlsplit(url).hostname or "")


def _when(stamp: float | None) -> str | None:
    return datetime.fromtimestamp(stamp, UTC).isoformat(timespec="seconds") if stamp else None


def acts_for(actor: Actor, source: Stored) -> bool:
    return source["owner_sub"] == actor.sub or (actor.person_id is not None and source["person_id"] == actor.person_id)


def listing(conn: db.Connection, actor: Actor) -> list[Listed]:
    counted = photo_sources.counts(conn)
    out: list[Listed] = []
    for s in photo_sources.list_all(conn):
        near = acts_for(actor, s)
        photos, trips = counted.get(s["id"], (0, 0))
        out.append({"id": s["id"], "person_id": s["person_id"], "url": s["url"], "label": s["label"] if near else None, "status": s["status"],
                    "mine": s["owner_sub"] == actor.sub, "last_sync": _when(s["last_sync"]) if near else None,
                    "last_error": s["last_error"] if near else None, "photos": photos if near else None, "trips": trips if near else None})
    return out


def listed(conn: db.Connection, actor: Actor, source_id: int) -> Listed:
    found = next((s for s in listing(conn, actor) if s["id"] == source_id), None)
    if found is None:
        raise NoSuchSource()
    return found


def owned(conn: db.Connection, actor: Actor, source_id: int) -> Stored:
    source = photo_sources.get(conn, source_id)
    if source is None or source["owner_sub"] != actor.sub:
        raise NoSuchSource()
    return source


def _steward_ok(conn: db.Connection, actor: Actor, person_id: int) -> bool:
    person = conn.execute(select(Person.id, Person.user_sub).where(Person.id == person_id)).fetchone()
    if person is None:
        raise NoSuchPerson()
    if person["user_sub"] is not None:
        if person_id != actor.person_id:
            raise Refused(NOT_YOURS)
        return False
    held = {photo_sources.steward_of(conn, person_id), *(s["owner_sub"] for s in photo_sources.for_person(conn, person_id))}
    if held - {None, actor.sub}:
        raise Refused(OTHER_STEWARD)
    return True


def provider_source(url: str, key: str, user_id: str | None = None) -> immich.Source:
    return immich.Source(url=url, key=key, allow_http=allow_http(url), user_id=user_id)


def _ping(source: immich.Source) -> immich.Account:
    if source.url.startswith("http://") and not source.allow_http:
        raise Refused(HTTPS_ONLY)
    return immich.ping(source)


def test_new(url: str, key: str) -> Tested:
    return {"name": _ping(provider_source(url, key)).name, "same_account": None}


def _not_yet(conn: db.Connection, person_id: int, url: str, user_id: str) -> None:
    if any(s["url"] == url and s["immich_user_id"] == user_id for s in photo_sources.for_person(conn, person_id)):
        raise Refused(ALREADY)


def connect(conn: db.Connection, actor: Actor, person_id: int, url: str, key: str, label: str | None, now: float | None = None) -> Listed:
    stewarded = _steward_ok(conn, actor, person_id)
    account = _ping(provider_source(url, key))
    _not_yet(conn, person_id, url, account.user_id)
    if not photo_sources.lock_person(conn, person_id):
        raise NoSuchPerson()
    status: Status = OFF if photo_sources.trip_shared(conn, person_id) else OK
    source_id = photo_sources.save(conn, person_id, actor.sub, url, account.user_id, key, label, time.time() if now is None else now, status)
    if source_id is None:
        raise Refused(ALREADY)
    if stewarded and not photo_sources.set_steward(conn, person_id, actor.sub):
        raise Refused(OTHER_STEWARD)
    _steward_ok(conn, actor, person_id)
    return listed(conn, actor, source_id)


def unlock(conn: db.Connection, source_id: int) -> immich.Source | None:
    found = photo_sources.source_for_provider(conn, source_id)
    return provider_source(found.url, found.key, found.user_id) if found is not None else None


def _unlocked(conn: db.Connection, stored: Stored) -> immich.Source:
    try:
        found = unlock(conn, stored["id"])
    except secretbox.SecretError:
        _record(conn, stored, REFUSED, KEY_LOST)
        conn.commit()
        raise Refused(KEY_LOST) from None
    if found is None:
        raise NoSuchSource()
    return found


def _record(conn: db.Connection, source: Stored, status: Status, error: str | None, synced: float | None = None) -> None:
    current: Stored | None = source
    for _ in range(RECORD_TRIES):
        if current is None or current["owner_sub"] != source["owner_sub"]:
            break
        kept = OFF if current["status"] == OFF else status
        if photo_sources.mark(conn, source["id"], kept, error, synced, owner=source["owner_sub"], was=(current["status"], current["last_error"])):
            return
        current = photo_sources.get(conn, source["id"])
    raise NoSuchSource()


def _outcome(conn: db.Connection, source: Stored, error: immich.ImmichError) -> None:
    _record(conn, source, REFUSED if isinstance(error, immich.Refused | immich.NotConfigured) else UNREACHABLE, str(error))
    conn.commit()


def test(conn: db.Connection, actor: Actor, source_id: int, key: str | None) -> Tested:
    source = owned(conn, actor, source_id)
    if key is not None:
        account = _ping(provider_source(source["url"], key))
        return {"name": account.name, "same_account": account.user_id == source["immich_user_id"]}
    try:
        account = _ping(_unlocked(conn, source))
    except immich.ImmichError as e:
        _outcome(conn, source, e)
        raise
    _record(conn, source, OK, None, source["last_sync"])
    return {"name": account.name, "same_account": account.user_id == source["immich_user_id"]}


def change_key(conn: db.Connection, actor: Actor, source_id: int, key: str) -> Listed:
    source = owned(conn, actor, source_id)
    account = _ping(provider_source(source["url"], key))
    if account.user_id != source["immich_user_id"]:
        raise Refused(OTHER_ACCOUNT)
    if not photo_sources.set_key(conn, source_id, key, owner=source["owner_sub"]):
        raise NoSuchSource()
    _record(conn, source, OK, None)
    return listed(conn, actor, source_id)


def edit(conn: db.Connection, actor: Actor, source_id: int, label: str | None, paused: bool | None, had_label: bool) -> Listed:
    source = owned(conn, actor, source_id)
    if had_label and not photo_sources.set_label(conn, source_id, label, owner=source["owner_sub"]):
        raise NoSuchSource()
    if paused is True and source["status"] != OFF:
        changed = photo_sources.mark(conn, source_id, OFF, None, owner=source["owner_sub"])
    elif paused is False and source["status"] == OFF:
        if photo_sources.trip_shared(conn, source["person_id"]):
            raise Refused(RESUME_ASKS)
        changed = photo_sources.mark(conn, source_id, OK, None, owner=source["owner_sub"])
    else:
        changed = True
    if not changed:
        raise NoSuchSource()
    return listed(conn, actor, source_id)


def remove(conn: db.Connection, actor: Actor, source_id: int) -> None:
    source = owned(conn, actor, source_id)
    if not photo_sources.remove(conn, source_id, owner=source["owner_sub"]):
        raise NoSuchSource()


def _lapsed(conn: db.Connection, sub: str, now: float) -> bool:
    email = conn.execute(select(User.email).where(User.sub == sub)).scalar()
    return oidc.access_lapsed(conn, sub, email, now) is not None


def end_lapsed(conn: db.Connection, now: float | None = None) -> int:
    now = time.time() if now is None else now
    ended = 0
    for s in photo_sources.list_all(conn):
        if not _lapsed(conn, s["owner_sub"], now):
            continue
        photo_sources.lock_owner(conn, s["owner_sub"])
        if _lapsed(conn, s["owner_sub"], now) and photo_sources.remove(conn, s["id"], owner=s["owner_sub"]):
            ended += 1
    return ended
