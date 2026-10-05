"""Live flight status (Settings shows the month's calls; the segment card shows the status and a Refresh): the viewer's own
flights only, through the domain's visibility helper (waypoint/domain/visibility.py); a segment that isn't theirs is a 404."""
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
    """The month's calls against the limit, and the live status of each of the viewer's flights that has one."""
    return flightstatus.overview(conn, viewer(conn), _now())


def api_flight_status_refresh(conn, _q, _b, segment_id) -> FlightStatusList:
    """Fetch this flight's status now (a call against the limit), unless the answer held is under 15 minutes old or fetching
    is paused: then what's held. 404 for a segment that isn't the viewer's."""
    who, number = viewer(conn), row_id(segment_id, NO_SEGMENT)
    try:
        found = flightstatus.refresh(conn, who, number, _now())
    except (flightstatus.NotAFlight, service.NotConfigured) as e:
        raise ApiError(str(e)) from None
    except service.FlightStatusError as e:   # (fixed messages: the request, and so any key, never shows)
        raise ApiError(str(e), 502) from None
    if found is None:
        raise ApiError(NO_SEGMENT, 404)
    return found
