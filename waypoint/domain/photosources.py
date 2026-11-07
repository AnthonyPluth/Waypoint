from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict
from urllib.parse import urlsplit

from sqlalchemy import select

from .. import oidc
from ..providers import immich
from ..storage import db, photo_sources, secretbox
from ..storage.models import Person, PhotoExclusion, PhotoGrant, User
from ..storage.photo_sources import OFF, OK, REFUSED, UNREACHABLE, Status, Stored
from . import people, photogrants, photomatch, photoqueue, photos

NO_SOURCE = "No such photo library"
NO_PERSON = "No such person"
NOT_YOURS = "A member who signs in connects their own libraries; ask them to connect it."
OTHER_STEWARD = "This person’s library is managed by another member; ask them to connect it."
ALREADY = "That library is already connected for this person."
OTHER_ACCOUNT = "That key belongs to a different Immich account; remove this library and connect it again."
KEY_LOST = secretbox.KEY_LOST
HTTPS_ONLY = "Use https:// for an Immich server outside your own network."
NEEDS_RESUME_SNAPSHOT = 'Send the "grants" and "sources" the confirmation showed'
STALE_GRANTS = photos.CHANGED
STALE_SOURCES = photogrants.STALE_SOURCES
TOO_DENSE = "Some of your library couldn’t be read."
COUNT_SECONDS = 30.0
SHOWN = ("place", "time", "far")
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


class Stale(Exception):
    pass


class ResumeGrant(TypedDict):
    trip_id: int
    changed: float
    window: photos.WindowOut | None


class Resume(TypedDict):
    asks: bool
    count: int
    grants: list[ResumeGrant]
    sources: list[photogrants.SourceVersion]


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


def is_demo(source: Stored) -> bool:
    return source["url"] == photoqueue.DEMO


def test(conn: db.Connection, actor: Actor, source_id: int, key: str | None) -> Tested:
    source = owned(conn, actor, source_id)
    if is_demo(source):
        return {"name": conn.execute(select(Person.display_name).where(Person.id == source["person_id"])).scalar(), "same_account": True}
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


def trip_grants(conn: db.Connection, person_id: int) -> list[ResumeGrant]:
    rows = conn.execute(select(PhotoGrant.trip_id, PhotoGrant.changed).where(PhotoGrant.person_id == person_id, PhotoGrant.scope == photos.TRIP,
                                                                            PhotoGrant.revoked.is_(None)).order_by(PhotoGrant.trip_id)).fetchall()
    return [{"trip_id": int(trip_id), "changed": float(changed), "window": photos.window_out(photos.trip_window(conn, int(trip_id)))} for trip_id, changed in rows]


def _grants_match(conn: db.Connection, person_id: int, seen: Sequence[Mapping[str, object]]) -> bool:
    try:
        wanted = sorted((int(str(g["trip_id"])), float(str(g["changed"])), _window_key(g.get("window"))) for g in seen)
    except (KeyError, TypeError, ValueError):
        return False
    return wanted == sorted((g["trip_id"], g["changed"], _window_key(g["window"])) for g in trip_grants(conn, person_id))


def _window_key(window: object) -> tuple[str, str] | None:
    if window is None:
        return None
    if not isinstance(window, Mapping):
        raise TypeError
    return str(window["start"]), str(window["end"])


def _shown(asset: immich.Asset, person_id: int, windows: Sequence[photomatch.TripWindow], left_out: set[int], home: photomatch.HomeIn | None) -> int | None:
    shot = photomatch.PhotoIn(photos.instant(asset.taken_utc), asset.latitude, asset.longitude, person_id)
    candidates = [w for w in windows if w.start <= shot.taken <= w.end and w.trip_id not in left_out]
    placed = photomatch.match(shot, candidates, home)
    return placed.trip_id if placed.match in SHOWN else None


def _assets(source: immich.Source, window: photomatch.TripWindow, deadline: float) -> list[immich.Asset]:
    found: dict[str, immich.Asset] = {}
    after, page = window.start, 1
    while True:
        if time.monotonic() >= deadline:
            raise immich.Unavailable(immich.TOO_SLOW)
        got = immich.search(source, after, window.end, page=page)
        found.update((a.id, a) for a in got.assets)
        if got.next_page is None:
            return list(found.values())
        if got.last_taken is None or (got.one_instant and page == 1 and not got.foreign):
            raise immich.Unavailable(TOO_DENSE)
        if got.one_instant:
            page += 1
        else:
            after, page = max(after, got.last_taken), 1


def _count(conn: db.Connection, source: Stored, shared: Sequence[ResumeGrant]) -> int:
    if is_demo(source) or not shared:
        return 0
    person_id = source["person_id"]
    windows = photos.candidate_windows(conn, person_id)
    wanted = {g["trip_id"] for g in shared}
    counted = sorted((w for w in windows if w.trip_id in wanted), key=lambda w: w.trip_id)
    if not counted:
        return 0
    unlocked, home, deadline = _unlocked(conn, source), photos.home_in(conn), time.monotonic() + COUNT_SECONDS
    try:
        assets = {a.id: a for w in counted for a in _assets(unlocked, w, deadline)}
    except immich.ImmichError as e:
        _outcome(conn, source, e)
        raise
    excluded: dict[str, set[int]] = {}
    for asset_id, trip_id in conn.execute(select(PhotoExclusion.asset_id, PhotoExclusion.trip_id).where(PhotoExclusion.person_id == person_id)).fetchall():
        excluded.setdefault(str(asset_id), set()).add(int(trip_id))
    return sum(1 for a in assets.values() if _shown(a, person_id, windows, excluded.get(a.id, set()), home) in wanted)


def resume_check(conn: db.Connection, actor: Actor, source_id: int) -> Resume:
    source = owned(conn, actor, source_id)
    shared = trip_grants(conn, source["person_id"])
    asks = source["status"] == OFF and bool(shared)
    return {"asks": asks, "count": _count(conn, source, shared) if asks else 0, "grants": shared,
            "sources": photogrants.sources_of(conn, source["person_id"])}


def _resume(conn: db.Connection, actor: Actor, source: Stored, grants: Sequence[Mapping[str, object]] | None,
            sources: Sequence[Mapping[str, object]] | None) -> bool:
    person_id = source["person_id"]
    photogrants.lock_home(conn)
    if not people.lock(conn, person_id) or not photo_sources.lock(conn, source["id"]):
        return False
    current = photo_sources.get(conn, source["id"])
    if current is None or current["owner_sub"] != actor.sub or current["person_id"] != person_id:
        return False
    if current["status"] != OFF:
        return True
    seen = {int(str(g["trip_id"])) for g in grants or () if isinstance(g.get("trip_id"), int)}
    photogrants.lock_trips(conn, {g["trip_id"] for g in trip_grants(conn, person_id)} | seen)
    photos.lock_grants(conn, person_id, photos.granted_trips(conn, person_id) | seen)
    conn.orm.expire_all()
    shared = trip_grants(conn, person_id)
    if (shared or grants is not None or sources is not None) and (grants is None or sources is None):
        raise Refused(NEEDS_RESUME_SNAPSHOT)
    if grants is not None and not _grants_match(conn, person_id, grants):
        raise Stale(STALE_GRANTS)
    if sources is not None and not photogrants.sources_match(conn, person_id, sources):
        raise Stale(STALE_SOURCES)
    return photo_sources.mark(conn, source["id"], OK, None, owner=source["owner_sub"])


def edit(conn: db.Connection, actor: Actor, source_id: int, label: str | None, paused: bool | None, had_label: bool,
         grants: Sequence[Mapping[str, object]] | None = None, sources: Sequence[Mapping[str, object]] | None = None) -> Listed:
    source = owned(conn, actor, source_id)
    if had_label and not photo_sources.set_label(conn, source_id, label, owner=source["owner_sub"]):
        raise NoSuchSource()
    if paused is True and source["status"] != OFF:
        changed = photo_sources.mark(conn, source_id, OFF, None, owner=source["owner_sub"])
    elif paused is False and source["status"] == OFF:
        changed = _resume(conn, actor, source, grants, sources)
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
