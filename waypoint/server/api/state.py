from __future__ import annotations

import os
from datetime import UTC, datetime

from ...domain import trips
from ...domain.mail import ai, review
from ...storage import db
from ...storage import settings_keys as sk
from ..common import _current
from .mailboxes import owner
from .trips import viewer
from ..contract import ShowCosts, ShowCostsBody, State
from ..common import ApiError


def api_state(conn, _q, _b) -> State:
    user = getattr(_current, "user", None)
    return {
        "version": os.environ.get("WAYPOINT_VERSION") or "dev",
        "database": "postgres" if db.using_postgres() else "sqlite",
        "user": user,
        "last_backup": with_offset(db.get_setting(conn, sk.LAST_BACKUP)),
        "review_count": review.count(conn, owner()) + trips.unmatched_count(conn, viewer(conn)),
        "person_id": viewer(conn).person_id,
        "ai": ai.config(conn) is not None,
        "show_costs": shows_costs(conn),
    }


def shows_costs(conn) -> bool:
    return db.get_setting(conn, sk.SHOW_COSTS) != "off"


def api_show_costs_save(conn, _q, body: ShowCostsBody) -> ShowCosts:
    show = body.get("show_costs")
    if not isinstance(show, bool):
        raise ApiError("Send show_costs as true or false")
    db.set_setting(conn, sk.SHOW_COSTS, "on" if show else "off")
    return {"show_costs": show}


def with_offset(stamp: str | None, utc: bool = False) -> str | None:
    if not stamp:
        return stamp
    try:
        t = datetime.fromisoformat(stamp)
    except ValueError:
        return stamp
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC) if utc else t.astimezone()
    return t.isoformat(timespec="seconds")
