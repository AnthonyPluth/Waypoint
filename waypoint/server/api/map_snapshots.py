from __future__ import annotations

import time

from ...domain import driving_routes, map_snapshots
from ..common import ApiError
from ..contract import MapSnapshots
from .trips import viewer


def api_map_snapshots(conn, q, _b) -> MapSnapshots:
    try:
        return {"snapshots": map_snapshots.for_trips(conn, viewer(conn), q.get("trip", []), q.get("w", []), q.get("h", []), q.get("lang", []), time.time())}
    except driving_routes.Invalid as e:
        raise ApiError(str(e)) from None
