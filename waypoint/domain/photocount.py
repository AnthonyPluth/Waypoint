from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

from .. import oidc
from ..providers import immich
from ..storage import db, photo_sources, secretbox
from . import photomatch, photos
from .photomatch import PhotoIn, TripWindow

COUNT_SECONDS = 30.0
COUNT_AT_ONCE = 4
DEMO_URL = "demo"
UNCHECKED = (photo_sources.REFUSED, photo_sources.UNREACHABLE)


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
    candidates: tuple[TripWindow, ...]
    home: photomatch.HomeIn | None
    left_out: Mapping[str, frozenset[int]]
    libraries: tuple[immich.Source, ...]


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


def _counting(conn: db.Connection, inputs: photos.Unshared, granted: Sequence[TripWindow], at_home: photomatch.HomeIn | None) -> _Counting:
    candidates = tuple(sorted([*(w for w in granted if w.trip_id != inputs.trip_id), inputs.window], key=lambda w: w.trip_id))
    return _Counting(inputs=inputs, candidates=candidates, home=at_home, left_out=inputs.left_out(), libraries=tuple(_libraries(conn, inputs)))


def _count_live(job: _Counting, deadline: float) -> int:
    inputs, seen, total = job.inputs, set[str](), 0
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


def unshared_counts(conn: db.Connection, person_id: int, trip_ids: Sequence[int]) -> dict[int, int | None]:
    out: dict[int, int | None] = {}
    waiting: list[photos.Unshared] = []
    now = time.monotonic()
    for trip_id in trip_ids:
        inputs = photos.unshared_inputs(conn, person_id, trip_id)
        if inputs is None or not inputs.sources:
            out[trip_id] = 0
            continue
        kept = photos.held_count(inputs.key, now)
        if kept is not None:
            out[trip_id] = kept
        else:
            waiting.append(inputs)
    if not waiting:
        return out
    granted, at_home = photos.candidate_windows(conn, person_id), photos.home_in(conn)
    pending: list[_Counting] = []
    for inputs in waiting:
        try:
            pending.append(_counting(conn, inputs, granted, at_home))
        except Unchecked:
            out[inputs.trip_id] = None
    deadline = time.monotonic() + COUNT_SECONDS

    def one(job: _Counting) -> int | None:
        try:
            return _count_live(job, deadline)
        except Unchecked:
            return None
    with ThreadPoolExecutor(max_workers=COUNT_AT_ONCE, thread_name_prefix="photo-count") as pool:
        for job, counted in zip(pending, pool.map(one, pending), strict=True):
            out[job.inputs.trip_id] = counted
            if counted is not None:
                photos.hold_count(job.inputs.key, counted, time.monotonic())
    return out


def unshared_count(conn: db.Connection, person_id: int, trip_id: int) -> int:
    counted = unshared_counts(conn, person_id, [trip_id])[trip_id]
    if counted is None:
        raise Unchecked()
    return counted
