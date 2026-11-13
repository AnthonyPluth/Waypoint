from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from .. import oidc
from ..providers import immich
from ..storage import db, photo_sources, secretbox
from . import demo, photomatch, photos
from .photomatch import PhotoIn, TripWindow

COUNT_SECONDS = 30.0
COUNT_TOTAL = 60.0
COUNT_AT_ONCE = 4
DEMO_URL = "demo"
COUNT_KEPT = 600.0
UNCHECKED = (photo_sources.REFUSED, photo_sources.UNREACHABLE)
Key = tuple[object, ...]
_counted: dict[Key, tuple[float, int]] = {}
_tried: dict[Key, float] = {}
_memory = threading.Lock()


def _key(inputs: photos.Unshared, granted: Sequence[TripWindow], at_home: photomatch.HomeIn | None) -> Key:
    matched = hashlib.sha256(repr((inputs.window, sorted(granted, key=lambda w: w.trip_id), at_home, inputs.excluded)).encode()).hexdigest()
    return (inputs.person_id, inputs.trip_id, inputs.window.start, inputs.window.end, inputs.libraries, matched)


def _held(key: Key, now: float) -> int | None:
    with _memory:
        kept = _counted.get(key)
        return kept[1] if kept is not None and now - kept[0] < COUNT_KEPT else None


def _hold(key: Key, count: int, now: float) -> None:
    with _memory:
        for old in [k for k, (at, _) in _counted.items() if now - at >= COUNT_KEPT]:
            del _counted[old]
        _counted[key] = (now, count)


def _tried_at(key: Key, now: float) -> float | None:
    with _memory:
        at = _tried.get(key)
        return at if at is not None and now - at < COUNT_KEPT else None


def _note_try(key: Key, now: float) -> None:
    with _memory:
        for old in [k for k, at in _tried.items() if now - at >= COUNT_KEPT]:
            del _tried[old]
        _tried[key] = now


def forget_counts() -> None:
    with _memory:
        _counted.clear()
        _tried.clear()


class Unchecked(Exception):
    pass


def search_pages(source: immich.Source, start: datetime, end: datetime, deadline: float, dense: str) -> Iterator[immich.Page]:
    after, page = start, 1
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise immich.Unavailable(immich.TOO_SLOW)
        got = immich.search(source, after, end, page=page, seconds=left)
        if time.monotonic() >= deadline or got.dropped:
            raise immich.Unavailable(dense)
        yield got
        if got.next_page is None:
            return
        if got.last_taken is None or (got.one_instant and page == 1 and not got.foreign):
            raise immich.Unavailable(dense)
        if got.one_instant:
            page += 1
        else:
            after, page = max(after, got.last_taken), 1


@dataclass(frozen=True)
class _Counting:
    inputs: photos.Unshared
    key: Key
    candidates: tuple[TripWindow, ...]
    home: photomatch.HomeIn | None
    left_out: Mapping[str, frozenset[int]]
    libraries: tuple[immich.Source, ...]
    demo: int


def _libraries(conn: db.Connection, inputs: photos.Unshared) -> list[immich.Source]:
    found: list[immich.Source] = []
    for source_id, status, url in inputs.sources:
        if status in UNCHECKED:
            raise Unchecked()
        if url == DEMO_URL:
            continue
        try:
            unlocked = photo_sources.source_for_provider(conn, source_id)
        except secretbox.SecretError:
            raise Unchecked() from None
        if unlocked is None:
            raise Unchecked()
        found.append(immich.Source(url=unlocked.url, key=unlocked.key, allow_http=oidc.local_host(urlsplit(unlocked.url).hostname or ""),
                                   user_id=unlocked.user_id))
    return found


def _counting(conn: db.Connection, inputs: photos.Unshared, key: Key, granted: Sequence[TripWindow], at_home: photomatch.HomeIn | None) -> _Counting:
    candidates = tuple(sorted([*(w for w in granted if w.trip_id != inputs.trip_id), inputs.window], key=lambda w: w.trip_id))
    shown = demo.unshared_inventory(inputs.person_id, inputs.trip_id) if any(url == DEMO_URL for _, _, url in inputs.sources) else 0
    return _Counting(inputs=inputs, key=key, candidates=candidates, home=at_home, left_out=inputs.left_out(), libraries=tuple(_libraries(conn, inputs)),
                     demo=shown)


def _count_live(job: _Counting, deadline: float) -> int:
    inputs, seen, total = job.inputs, set[str](), job.demo
    try:
        for library in job.libraries:
            for got in search_pages(library, inputs.window.start, inputs.window.end, deadline, immich.TOO_SLOW):
                for asset in got.assets:
                    if asset.id in seen:
                        continue
                    seen.add(asset.id)
                    shot = PhotoIn(photos.instant(asset.taken_utc), asset.latitude, asset.longitude, inputs.person_id)
                    skipped = job.left_out.get(asset.id, frozenset())
                    inside = [w for w in job.candidates if w.start <= shot.taken <= w.end and w.trip_id not in skipped]
                    placed = photomatch.match(shot, inside, job.home)
                    total += placed.trip_id == inputs.trip_id and placed.match in photos.SHOWN
    except immich.ImmichError:
        raise Unchecked() from None
    return total


def unshared_counts(conn: db.Connection, person_id: int, trip_ids: Sequence[int], cap: float | None = None) -> dict[int, int | None]:
    out: dict[int, int | None] = {}
    waiting: list[tuple[photos.Unshared, Key]] = []
    granted: list[TripWindow] | None = None
    at_home: photomatch.HomeIn | None = None
    now = time.monotonic()
    for trip_id in trip_ids:
        inputs = photos.unshared_inputs(conn, person_id, trip_id)
        if inputs is None or not inputs.sources:
            out[trip_id] = 0
            continue
        if granted is None:
            granted, at_home = photos.candidate_windows(conn, person_id), photos.home_in(conn)
        key = _key(inputs, [w for w in granted if w.trip_id != trip_id], at_home)
        kept = _held(key, now)
        if kept is not None:
            out[trip_id] = kept
        else:
            waiting.append((inputs, key))
    if not waiting or granted is None:
        return out
    pending: list[_Counting] = []
    for inputs, key in waiting:
        try:
            pending.append(_counting(conn, inputs, key, granted, at_home))
        except Unchecked:
            out[inputs.trip_id] = None
    started = time.monotonic()
    pending.sort(key=lambda job: _tried_at(job.key, started) or 0.0)
    cap = started + COUNT_TOTAL if cap is None else cap

    def one(job: _Counting) -> int | None:
        begun = time.monotonic()
        if begun >= cap:
            return None
        _note_try(job.key, begun)
        try:
            return _count_live(job, min(begun + COUNT_SECONDS, cap))
        except Unchecked:
            return None
    with ThreadPoolExecutor(max_workers=COUNT_AT_ONCE, thread_name_prefix="photo-count") as pool:
        for job, counted in zip(pending, pool.map(one, pending), strict=True):
            out[job.inputs.trip_id] = counted
            if counted is not None:
                _hold(job.key, counted, time.monotonic())
    return out


def one_cap() -> Callable[[db.Connection, int, Sequence[int]], dict[int, int | None]]:
    ends: list[float] = []

    def count(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> dict[int, int | None]:
        if not ends:
            ends.append(time.monotonic() + COUNT_TOTAL)
        return unshared_counts(conn, person_id, trip_ids, ends[0])
    return count


def unshared_count(conn: db.Connection, person_id: int, trip_id: int) -> int:
    counted = unshared_counts(conn, person_id, [trip_id])[trip_id]
    if counted is None:
        raise Unchecked()
    return counted
