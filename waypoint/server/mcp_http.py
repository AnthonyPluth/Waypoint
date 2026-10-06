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

CREDENTIAL_CHECKS: tuple[Callable[[Any, str | None, str | None], mcp_access.Access | None], ...] = (mcp_access.resolve_bearer,)

ANYTHING = frozenset(mcp_access.writable_routes(routes.ROUTES))

WRITES_OFF = "Changes are switched off. Turn on “Let assistants change trips” in Waypoint under Settings."
READ_ONLY = ("This connection can only read. To let the assistant change trips, reconnect Waypoint in the assistant and "
             "allow “Change trips” when Waypoint asks.")
REFUSALS = {mcp_access.WRITE: (READ_ONLY, WRITES_OFF)}
OUT_OF_REACH = ("Not found: assistants can't reach mailboxes, the “Couldn’t read” queue, AI settings, backups, loyalty and Known "
                "Traveler numbers, sign-in, the calendar feed, notifications or the assistant settings. Use Waypoint itself for those.")
METHODS = ("GET", "POST", "DELETE")


def fetch_for(access: mcp_access.Access) -> Callable[..., Any]:
    return lambda path, params, body=None, method=None: local_fetch(path, params, body, access, method)


def authorized(conn, authorization: str | None, resource: str | None = None) -> mcp_access.Access | None:
    for check in CREDENTIAL_CHECKS:
        access = check(conn, authorization, resource)
        if access is not None:
            return access
    return None


def needs(method: str, pattern: str) -> tuple[str, ...] | None:
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
    out: dict[str, list[str]] = defaultdict(list)
    for r in routes.TABLE.routes:
        m, pattern = r.method, r.pattern
        if needs(m, pattern):
            out[pattern.split("/")[2]].append(f"{m} {pattern}" + (" (destructive)" if m != "GET" and mcp_access.destructive(m, pattern) else ""))
    return dict(out)


def _why_not(access: mcp_access.Access, scope: str) -> str | None:
    if scope not in REFUSALS:
        return "Not found"
    if not access.has(scope):
        return REFUSALS[scope][0]
    with db.session() as conn:
        if mcp_access.switched_on(conn, scope):
            return None
    return REFUSALS[scope][1]


def _acting_as(access: mcp_access.Access) -> dict:
    if not oidc.enabled():
        return {"local": True}
    with db.session() as conn:
        name = conn.execute(select(User.name).where(User.sub == access.sub)).scalar() if access.sub else None
    return {"sub": access.sub, "email": access.email, "name": name}


def local_fetch(path: str, params: dict[str, Any], body: dict | None, access: mcp_access.Access, method: str | None = None) -> Any:
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
    if scopes is None or found.route.upload:
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
    except ApiError as e:
        raise ToolError(str(e)) from None
    finally:
        _current.user = None
    if isinstance(result, Response):
        raise ToolError("Not found")
    return result
