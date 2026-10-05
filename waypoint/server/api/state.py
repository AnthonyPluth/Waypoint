"""The app's state: who's signed in, the version, and what Settings shows."""
from __future__ import annotations

import os
from datetime import UTC, datetime

from ...domain import trips
from ...domain.mail import review
from ...storage import db
from ...storage import settings_keys as sk
from ..common import _current
from .mailboxes import owner
from .trips import viewer
from ..contract import State


def api_state(conn, _q, _b) -> State:
    user = getattr(_current, "user", None)
    return {
        "version": os.environ.get("WAYPOINT_VERSION") or "dev",
        "database": "postgres" if db.using_postgres() else "sqlite",
        "user": user,
        "last_backup": with_offset(db.get_setting(conn, sk.LAST_BACKUP)),   # the last backup downloaded from Settings
        "review_count": review.count(conn, owner()) + trips.unmatched_count(conn, viewer(conn)),
    }


def with_offset(stamp: str | None, utc: bool = False) -> str | None:
    """A stored timestamp with its UTC offset, so the browser shows it in its own time zone. Settings hold the server's
    local time ("2026-09-30T07:02:00"); one that has an offset keeps it."""
    if not stamp:
        return stamp
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC) if utc else t.astimezone()
    return t.isoformat(timespec="seconds")
