"""Waypoint's web server: the JSON API and the web app's files. Standard library only.

handler.py serves requests (who may reach what, security headers, limits, reading bodies, sending answers) and has
serve(); routes.py maps each API path to its handler in api/, one module per area, and answers it (dispatch); static.py
sends the web app's files; common.py holds what they share. The names below are re-exported so
`from waypoint import server; server.serve()` and the tests keep working. They are references, not the state itself: to
change or patch a module's setting (static.STATIC, ...), do it on the module that owns it.
"""
# ruff: noqa: F401
from __future__ import annotations

from .common import ApiError, EXTRA_HOSTS, SAFE_SUFFIXES, host_allowed, request_ref
from .handler import (
    AUTH_PATHS, HEADER_DEADLINE, MAX_CONCURRENT_REQUESTS, MAX_JSON_BODY, MIN_BODY_RATE, NO_APP_HEADER, NOT_SAME_SITE,
    PUBLIC_FILES, REQUEST_TIMEOUT, Handler, Server, ThreadingHTTPServer, content_security_policy, route_name, serve,
)
from .routes import ROUTES
from .static import APP_DIR, APP_INDEX, STATIC
from .api.backups import MAX_RESTORE_BODY
from .api.state import api_state
