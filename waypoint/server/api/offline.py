from __future__ import annotations

from datetime import date

from ...domain import offline
from ..common import _current
from ..contract import Offline, OfflineMessages, OfflinePicture, OfflineTrip, StoredEmail
from .trips import _trip, viewer


def _saved(c: offline.SavedTrip, with_codes: bool) -> OfflineTrip:
    messages = [OfflineMessages(segment_id=m["segment_id"], emails=[StoredEmail(**e) for e in m["emails"]]) for m in c["messages"]]
    saved = OfflineTrip(trip=_trip(c["trip"]), messages=messages)
    if with_codes:
        saved["codes"] = [OfflinePicture(**p) for p in c["codes"]]
    return saved


def api_offline(conn, _q, _b) -> Offline:
    with_codes = bool((getattr(_current, "user", None) or {}).get("app"))
    found = offline.projection(conn, viewer(conn), date.today(), with_codes)
    return {"version": offline.VERSION, "trips": [_saved(c, with_codes) for c in found["trips"]]}
