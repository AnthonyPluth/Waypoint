from __future__ import annotations

from datetime import date

from ...domain import offline
from ..contract import Offline, OfflineMessages, StoredEmail
from .trips import _trip, viewer


def api_offline(conn, _q, _b) -> Offline:
    found = offline.projection(conn, viewer(conn), date.today())
    return {"trip": _trip(found["trip"]) if found["trip"] else None,
            "messages": [OfflineMessages(segment_id=m["segment_id"], emails=[StoredEmail(**e) for e in m["emails"]]) for m in found["messages"]]}
