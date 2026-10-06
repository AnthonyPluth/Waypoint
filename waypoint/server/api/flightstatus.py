from __future__ import annotations

from datetime import UTC, datetime

from ...domain import flightstatus
from ...providers import flightstatus as service
from ..common import ApiError, row_id
from ..contract import FlightStatusList
from .trips import NO_SEGMENT, viewer


def _now() -> datetime:
    return datetime.now(UTC)


def api_flight_statuses(conn, _q, _b) -> FlightStatusList:
    return flightstatus.overview(conn, viewer(conn), _now())


def api_flight_status_refresh(conn, _q, _b, segment_id) -> FlightStatusList:
    who, number = viewer(conn), row_id(segment_id, NO_SEGMENT)
    try:
        found = flightstatus.refresh(conn, who, number, _now())
    except (flightstatus.NotAFlight, service.NotConfigured) as e:
        raise ApiError(str(e)) from None
    except service.FlightStatusError as e:
        raise ApiError(str(e), 502) from None
    if found is None:
        raise ApiError(NO_SEGMENT, 404)
    return found
