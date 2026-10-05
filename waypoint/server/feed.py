"""The calendar feed's address, /feed/<key>.ics: a member's calendar subscription. A calendar app can't sign in, so the key in
the address is what lets it in: 256 random bits, kept only as a hash (waypoint/domain/reminders.py), never written to the log
(Handler.log_request) and gone when the member turns the feed off, makes a new key, or can no longer sign in."""
from __future__ import annotations

import re
import time
from datetime import UTC, datetime

from ..domain import reminders
from ..storage import db
from .common import Response

PREFIX = "/feed/"
ADDRESS = re.compile(r"/feed/([A-Za-z0-9_-]{16,128})\.ics")


def serve(path: str, now: float | None = None) -> Response | None:
    """The feed for this address, or None (a 404, the same for a key that never was, one that was replaced and one whose owner
    can no longer sign in)."""
    found = ADDRESS.fullmatch(path)
    if not found:
        return None
    moment = time.time() if now is None else now
    with db.session() as conn:
        owner = reminders.feed_owner(conn, found.group(1), moment)
        if owner is None:
            return None
        text = reminders.feed_text(conn, owner, datetime.fromtimestamp(moment, UTC))
    return Response(text.encode(), "text/calendar; charset=utf-8", csp="default-src 'none'; sandbox",
                    headers={"Content-Disposition": 'inline; filename="waypoint.ics"'})
