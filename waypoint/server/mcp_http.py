"""How the MCP server (POST /mcp) reaches Waypoint's pages, in this process: who the caller is (authorized), what a route
needs (needs) and the call itself. The assistant is the member who approved it: each call runs as that member (their
visibility, their masked numbers), through routes.dispatch as the web app's calls do. Every page is found by
routes.match, in ROUTES only (so nothing outside /api/'s routes, like sign-in or OAuth, can be reached); it refuses
mcp_access.BLOCKED (mailboxes, the review queue, AI settings, backups and more), and allows mcp_access.READABLE, the
changes in mcp_access.writable_routes and, for "write", mcp_access.WRITE_READABLE; the connection's scopes and each
scope's switch apply to every call. This is the gate: the tools are a convenience."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from .. import oidc
from ..storage import db
from ..storage.models import User
from . import mcp_access, routes
from .common import ApiError, Response, _current
from .mcp_server import ToolError

# The ways to prove a caller may use the MCP server: each takes (conn, Authorization header, this server's resource)
# and answers what the caller may do (mcp_access.Access), or None.
CREDENTIAL_CHECKS: tuple[Callable[[Any, str | None, str | None], mcp_access.Access | None], ...] = (mcp_access.resolve_bearer,)

# The changes "write" allows: (method, pattern), from ROUTES.
ANYTHING = frozenset(mcp_access.writable_routes(routes.ROUTES))

WRITES_OFF = "Changes are switched off. Turn on “Let assistants change trips” in Waypoint under Settings."
READ_ONLY = ("This connection can only read. To let the assistant change trips, reconnect Waypoint in the assistant and "
             "allow “Change trips” when Waypoint asks.")
# Why a call of each scope can't be made: (the connection wasn't allowed it, the switch is off).
REFUSALS = {mcp_access.WRITE: (READ_ONLY, WRITES_OFF)}
OUT_OF_REACH = ("Not found: assistants can't reach mailboxes, the “Couldn’t read” queue, AI settings, backups, loyalty and Known "
                "Traveler numbers, sign-in, the calendar feed, notifications or the assistant settings. Use Waypoint itself for those.")
METHODS = ("GET", "POST", "DELETE")


def fetch_for(access: mcp_access.Access) -> Callable[..., Any]:
    """local_fetch as this caller: what mcp_server.handle() is given for one request to /mcp."""
    return lambda path, params, body=None, method=None: local_fetch(path, params, body, access, method)


def authorized(conn, authorization: str | None, resource: str | None = None) -> mcp_access.Access | None:
    for check in CREDENTIAL_CHECKS:
        access = check(conn, authorization, resource)
        if access is not None:
            return access
    return None


def needs(method: str, pattern: str) -> tuple[str, ...] | None:
    """The scope a route needs: "read" or "write". None for anything an assistant may never use."""
    if mcp_access.blocked(pattern):
        return None
    if method == "GET":
        if pattern in mcp_access.READABLE:
            return (mcp_access.READ,)
        return (mcp_access.WRITE,) if pattern in mcp_access.WRITE_READABLE else None
    if (method, pattern) in ANYTHING:
        return (mcp_access.WRITE,)
    return None


def endpoints() -> dict[str, list[str]]:
    """What "write" can reach with call_endpoint, by area (the path after /api/), destructive changes marked."""
    out: dict[str, list[str]] = defaultdict(list)
    for r in routes.TABLE.routes:
        m, pattern = r.method, r.pattern
        if needs(m, pattern):
            out[pattern.split("/")[2]].append(f"{m} {pattern}" + (" (destructive)" if m != "GET" and mcp_access.destructive(m, pattern) else ""))
    return dict(out)


def _why_not(access: mcp_access.Access, scope: str) -> str | None:
    """Why this connection can't make `scope`'s calls now (not allowed when it connected, or switched off), or None."""
    if scope not in REFUSALS:
        return "Not found"
    if not access.has(scope):
        return REFUSALS[scope][0]
    with db.session() as conn:
        if mcp_access.switched_on(conn, scope):
            return None
    return REFUSALS[scope][1]


def _acting_as(access: mcp_access.Access) -> dict:
    """The signed-in person a call runs as: the member who approved the connection, as their browser's session says it
    (what people.person_for_sub and so the visibility helper go by). Without sign-in, the local household."""
    if not oidc.enabled():
        return {"local": True}
    with db.session() as conn:
        name = conn.execute(select(User.name).where(User.sub == access.sub)).scalar() if access.sub else None
    return {"sub": access.sub, "email": access.email, "name": name}


def local_fetch(path: str, params: dict[str, Any], body: dict | None, access: mcp_access.Access, method: str | None = None) -> Any:
    """mcp_server's fetch(path, query, body, method) as `access` may: the lookup, the scopes and their switches checked
    on every call, and the page's own reply (or refusal, as ToolError). Without a method it's GET with no body and POST
    with one. Two pages aren't Waypoint's: fetch("access", {"scope": ...}) answers whether this connection may use that
    scope right now (write when no scope is given), and fetch("endpoints", {}) lists what "write" reaches (endpoints())."""
    method = (method or ("GET" if body is None else "POST")).upper()
    if method not in METHODS:
        raise ToolError("Not found")
    if body is not None and not isinstance(body, dict):
        raise ToolError("Send the body as a JSON object.")
    full = "/api/" + path
    if method == "GET" and full == "/api/access":
        why = _why_not(access, str(params.get("scope") or mcp_access.WRITE))
        return {"allowed": why is None, **({"why": why} if why else {})}
    if method == "GET" and full == "/api/endpoints":
        why = _why_not(access, mcp_access.WRITE)
        if why:
            raise ToolError(why)
        return endpoints()
    found = routes.match(method, full)
    if found is None:
        raise ToolError("Not found")
    pattern = found.route.pattern
    if mcp_access.blocked(pattern):
        raise ToolError(OUT_OF_REACH)
    scopes = needs(method, pattern)
    if scopes is None or found.route.upload:   # (a file upload isn't something /mcp's JSON can send)
        raise ToolError("Not found")
    for scope in scopes:
        if scope == mcp_access.READ:
            if mcp_access.READ not in access.scopes:
                raise ToolError("Not found")
        elif why := _why_not(access, scope):
            raise ToolError(why)
    query = {k: [str(v)] for k, v in params.items() if v not in (None, "")}
    _current.user = _acting_as(access)
    _current.host = None
    try:
        result = routes.dispatch(found, query, body or {})
    except ApiError as e:   # what was wrong, busy, or a server error's reference: as the web app is told
        raise ToolError(str(e)) from None
    finally:
        _current.user = None
    if isinstance(result, Response):   # a download or a stream is the web app's (BLOCKED keeps them out anyway)
        raise ToolError("Not found")
    return result
