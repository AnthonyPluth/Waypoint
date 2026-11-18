from __future__ import annotations

import time

from ...domain import driving_routes
from ..common import ApiError, row_id
from ..contract import DrivingRouteBody, DrivingRoutes, DrivingRoutesForTrips, DrivingRouteStored
from .trips import NO_TRIP, viewer


def api_driving_routes(conn, q, _b, trip_id) -> DrivingRoutes:
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    try:
        found = driving_routes.cached(conn, who, this, q.get("drive", []))
    except driving_routes.Invalid as e:
        raise ApiError(str(e)) from None
    if found is None:
        raise ApiError(NO_TRIP, 404)
    return {"routes": found}


def api_driving_routes_for_trips(conn, q, _b) -> DrivingRoutesForTrips:
    try:
        return {"trips": driving_routes.cached_for_trips(conn, viewer(conn), q.get("trip", []))}
    except driving_routes.Invalid as e:
        raise ApiError(str(e)) from None


def api_driving_route_store(conn, _q, body: DrivingRouteBody, trip_id) -> DrivingRouteStored:
    who, this = viewer(conn), row_id(trip_id, NO_TRIP)
    try:
        stored = driving_routes.store(conn, who, this, body.get("start"), body.get("end"), body.get("path"), time.time())
    except driving_routes.Invalid as e:
        raise ApiError(str(e)) from None
    if stored is None:
        raise ApiError(NO_TRIP, 404)
    return {"stored": stored}
