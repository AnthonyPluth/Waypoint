from __future__ import annotations

import re
from dataclasses import dataclass

from ..storage import db
from ..storage import settings_keys as sk
from . import mcp_oauth

READ, WRITE = "read", "write"

READABLE = frozenset({
    "/api/trips", "/api/trips/{id}", "/api/segments/{id}", "/api/airports/{id}", "/api/people", "/api/stats",
    "/api/distance-unit", "/api/flight-status",
})

SWITCHES = {WRITE: sk.MCP_ALLOW_WRITES}

BLOCKED = (
    "/api/mcp-settings", "/api/mailboxes", "/api/review", "/api/ai", "/api/backup", "/api/restore", "/api/state", "/api/feed",
    "/api/reminders", "/api/flight-status/{id}", "/api/import", "/api/loyalty", "/api/logodev", "/api/segments/{id}/emails",
)

WRITE_READABLE = ("/api/people/claim-suggestions",)

MANY = frozenset({"/api/trips/{id}/merge", "/api/trips/{id}/split", "/api/people/{id}/claim"})


def blocked(template: str) -> bool:
    return any(template == b or template.startswith(b + "/") for b in BLOCKED)


def destructive(method: str, template: str) -> bool:
    return method == "DELETE" or "remove" in template.split("/") or template in MANY


def writable_routes(routes) -> list[tuple[str, str]]:
    return [(m, p) for m, p, *_fn in routes if m in ("POST", "DELETE") and not blocked(p)]


@dataclass(frozen=True)
class Access:
    scopes: frozenset[str]
    grant_id: int | None
    sub: str | None
    email: str | None

    def has(self, scope: str) -> bool:
        return scope in self.scopes


def resolve_bearer(conn, authorization: str | None, resource: str | None) -> Access | None:
    m = re.fullmatch(r"Bearer\s+(\S+)", (authorization or "").strip(), re.I)
    if not m or not resource:
        return None
    grant = mcp_oauth.access_grant(conn, m.group(1), resource)
    if grant is None:
        return None
    return Access(frozenset(grant["scope"].split()), grant["id"], grant["sub"], grant["email"])


def switched_on(conn, scope: str) -> bool:
    return scope in SWITCHES and db.get_setting(conn, SWITCHES[scope]) == "1"


def allow_writes(conn) -> bool:
    return switched_on(conn, WRITE)


def set_allow_writes(conn, on: bool) -> None:
    db.set_setting(conn, sk.MCP_ALLOW_WRITES, "1" if on else "0")
