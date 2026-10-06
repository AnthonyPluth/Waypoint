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
