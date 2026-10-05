"""The API's routes: which handler answers each method and path (ROUTES), finding a request's (match) and answering it
(dispatch)."""
from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..storage import db
from .common import ApiError, server_error

from .api.ai import api_ai, api_ai_save
from .api.backups import api_backup, api_backup_inspect, api_restore
from .api.trips import (api_airport, api_segment, api_segment_add, api_segment_edit, api_segment_remove, api_trip,
                        api_trip_add, api_trip_edit, api_trip_merge, api_trip_remove, api_trip_split, api_trips)
from .api.flight_import import api_import, api_import_preview
from .api.flightstatus import api_flight_status_refresh, api_flight_statuses
from .api.loyalty import api_loyalty, api_loyalty_add, api_loyalty_edit, api_loyalty_remove, api_loyalty_reveal
from .api.people import api_people, api_person_add, api_person_edit, api_person_remove
from .api.mailboxes import api_mailbox_callback, api_mailbox_connect, api_mailbox_disconnect, api_mailbox_scan, api_mailboxes
from .api.reminders import (api_device_add, api_device_remove, api_feed_make, api_feed_off, api_reminders,
                            api_reminders_set)
from .api.review import (api_review, api_review_dismiss, api_review_ignore, api_review_preview, api_review_suggest,
                         api_review_who)
from .api.state import api_state
from .api.stats import api_stats


# (method, path pattern, handler): each handler takes (conn, query, body, *path params) and returns the JSON reply, or
# a common.Response for anything else (a download, a logo, a stream). A HEAD is answered as its GET, without the body.
ROUTES: list[tuple[str, str, Callable[..., Any]]] = [
    ("GET", "/api/ai", api_ai),
    ("POST", "/api/ai", api_ai_save),
    ("GET", "/api/backup", api_backup),
    ("POST", "/api/backup/inspect", api_backup_inspect),
    ("POST", "/api/restore", api_restore),
    ("GET", "/api/people", api_people),
    ("POST", "/api/people", api_person_add),
    ("POST", "/api/people/{id}", api_person_edit),
    ("DELETE", "/api/people/{id}", api_person_remove),
    ("GET", "/api/trips", api_trips),
    ("POST", "/api/trips", api_trip_add),
    ("GET", "/api/trips/{id}", api_trip),
    ("POST", "/api/trips/{id}", api_trip_edit),
    ("DELETE", "/api/trips/{id}", api_trip_remove),
    ("POST", "/api/trips/{id}/merge", api_trip_merge),
    ("POST", "/api/trips/{id}/split", api_trip_split),
    ("POST", "/api/segments", api_segment_add),
    ("GET", "/api/segments/{id}", api_segment),
    ("POST", "/api/segments/{id}", api_segment_edit),
    ("DELETE", "/api/segments/{id}", api_segment_remove),
    ("GET", "/api/airports/{id}", api_airport),
    ("POST", "/api/import/preview", api_import_preview),
    ("POST", "/api/import", api_import),
    ("GET", "/api/stats", api_stats),
    ("GET", "/api/flight-status", api_flight_statuses),
    ("POST", "/api/flight-status/{id}", api_flight_status_refresh),
    ("GET", "/api/loyalty", api_loyalty),
    ("POST", "/api/loyalty", api_loyalty_add),
    ("POST", "/api/loyalty/{id}", api_loyalty_edit),
    ("DELETE", "/api/loyalty/{id}", api_loyalty_remove),
    ("POST", "/api/loyalty/{id}/reveal", api_loyalty_reveal),
    ("GET", "/api/mailboxes", api_mailboxes),
    ("POST", "/api/mailboxes/connect", api_mailbox_connect),
    ("GET", "/api/mailboxes/callback", api_mailbox_callback),
    ("DELETE", "/api/mailboxes/{id}", api_mailbox_disconnect),
    ("POST", "/api/mailboxes/{id}/scan", api_mailbox_scan),
    ("GET", "/api/reminders", api_reminders),
    ("POST", "/api/reminders", api_reminders_set),
    ("POST", "/api/reminders/devices", api_device_add),
    ("DELETE", "/api/reminders/devices/{id}", api_device_remove),
    ("POST", "/api/feed", api_feed_make),
    ("DELETE", "/api/feed", api_feed_off),
    ("GET", "/api/review", api_review),
    ("POST", "/api/review/who/{id}", api_review_who),
    ("POST", "/api/review/{id}/ignore", api_review_ignore),
    ("GET", "/api/review/{id}/preview", api_review_preview),
    ("POST", "/api/review/{id}/suggest", api_review_suggest),
    ("DELETE", "/api/review/{id}", api_review_dismiss),
    ("GET", "/api/state", api_state),
]


@dataclass(frozen=True)
class Route:
    method: str
    pattern: str
    fn: Callable[..., Any]
    parts: tuple[str | None, ...]   # the pattern's segments, None for an {id}
    upload: int | None = None       # the body is a file of up to this many bytes, as it is (common.upload); else JSON
    own_session: bool = False       # the handler opens its own database sessions (common.own_session)


@dataclass(frozen=True)
class Match:
    """A request's route, and the values of the {id}s in its address (unquoted)."""
    route: Route
    params: list[str]


def _segments(path: str) -> list[str]:
    return path.strip("/").split("/")


class Table:
    """ROUTES, split up once: each method's routes by how many segments their address has, in ROUTES' order (the
    first that matches answers, so /api/trips/new goes before /api/trips/{id})."""

    def __init__(self, routes):
        self.routes = [Route(m, pattern, fn, tuple(None if s == "{id}" else s for s in _segments(pattern)),
                             getattr(fn, "upload", None), getattr(fn, "own_session", False))
                       for m, pattern, fn in routes]
        self._by_shape: dict[tuple[str | None, int], list[Route]] = {}
        for r in self.routes:
            for method in (r.method, None):   # (None: any method, for naming a request)
                self._by_shape.setdefault((method, len(r.parts)), []).append(r)

    def match(self, method: str | None, path: str) -> Match | None:
        """The route that answers `method path` (any method, for None), or None."""
        parts = _segments(path)
        for r in self._by_shape.get((method, len(parts)), ()):
            params = []
            for want, got in zip(r.parts, parts, strict=True):
                if want is None:
                    params.append(urllib.parse.unquote(got))
                elif want != got:
                    break
            else:
                return Match(r, params)
        return None


TABLE = Table(ROUTES)
match = TABLE.match

BUSY = "Waypoint is busy saving something else. Try again in a few seconds."


def dispatch(found: Match, query: dict, body) -> Any:
    """Answer a request that matched a route: its handler's reply (what to send as JSON, or a common.Response), run with
    a database connection that's committed if it succeeds and rolled back if not (or none, for a route with its own
    sessions). `body` is the request's JSON object, or for an upload its bytes. Every way it can fail comes out as
    ApiError: the handler's own, saying what was wrong (a 4xx); 503 when the database was busy with something else; and
    anything else, which is a bug, 500 with only a reference, logged and reported without what the error said
    (common.server_error)."""
    r = found.route
    try:
        if r.own_session:
            return r.fn(None, query, body, *found.params)
        with db.session() as conn:
            return r.fn(conn, query, body, *found.params)
    except ApiError:
        raise
    except Exception as e:
        if db.is_busy(e):
            raise ApiError(BUSY, 503) from None
        raise server_error(e, r.method, r.pattern) from None
