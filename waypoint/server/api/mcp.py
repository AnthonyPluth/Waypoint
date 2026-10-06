from __future__ import annotations

from datetime import datetime

from ... import validate
from .. import mcp_access, mcp_oauth
from ..common import ApiError, _current, row_id
from ..contract import McpConnection, McpSettings, McpWritesBody, Ok


def _when(t: float | None) -> str | None:
    return datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds") if t else None


def api_mcp_settings(conn, _q, _b) -> McpSettings:
    iss = mcp_oauth.issuer(getattr(_current, "host", None))
    return {"allow_writes": mcp_access.allow_writes(conn), "oauth": iss is not None,
            "url": mcp_oauth.resource(iss) if iss else None, "reason": None if iss else mcp_oauth.unavailable_reason(),
            "connections": [McpConnection(id=c["id"], client=c["client"], who=c["who"], scope=c["scope"],
                                          created=_when(c["created"]), last_used=_when(c["last_used"]))
                            for c in mcp_oauth.connections(conn)]}


def api_mcp_writes(conn, _q, body: McpWritesBody) -> McpWritesBody:
    mcp_access.set_allow_writes(conn, validate.on(body.get("allow")))
    return {"allow": mcp_access.allow_writes(conn)}


def api_mcp_revoke(conn, _q, _b, grant_id) -> Ok:
    if not mcp_oauth.revoke_grant(conn, row_id(grant_id), "revoked_in_settings"):
        raise ApiError("That connection isn't there any more.", 404)
    return {"ok": True}
