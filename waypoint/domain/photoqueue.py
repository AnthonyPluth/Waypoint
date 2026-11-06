from __future__ import annotations

import threading
from collections.abc import Callable

from .. import monitoring
from ..storage import db, photo_sources
from ..storage.photo_sources import OK, UNREACHABLE

SYNCED = (OK, UNREACHABLE)
DEMO = "demo"

background = threading.Event()
starter: Callable[[int, set[int]], bool] | None = None


def enable(start: Callable[[int, set[int]], bool]) -> None:
    global starter
    starter = start
    background.set()


def disable() -> None:
    global starter
    starter = None
    background.clear()


def syncing(conn: db.Connection, person_id: int | None = None) -> list[int]:
    found = photo_sources.list_all(conn) if person_id is None else photo_sources.for_person(conn, person_id)
    return [s["id"] for s in found if s["status"] in SYNCED and s["url"] != DEMO]


def queue(person_id: int, trip_id: int) -> None:
    start = starter
    if not background.is_set() or start is None:
        return
    try:
        with db.session() as conn:
            ids = syncing(conn, person_id)
    except Exception as e:
        monitoring.report(e, values=False)
        return
    failed = 0
    for source_id in ids:
        try:
            start(source_id, {trip_id})
        except Exception:
            failed += 1
    if failed:
        monitoring.log(f"Photo sync: {failed} queued library sync(s) could not start; the next scheduled sync reads them.", "warning")


def after_commit(conn: db.Connection, person_id: int, trip_id: int) -> None:
    conn.after_commit(lambda: queue(person_id, trip_id))
