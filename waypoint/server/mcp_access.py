"""What an AI assistant connected to Waypoint's MCP endpoint (/mcp) may reach, and the switches for whether it may see full
ID numbers or change trips.

An assistant connects with OAuth (waypoint/server/mcp_oauth.py) and gets a token for the scopes the member approved, and
acts as that member: every tool goes through the same API routes the web app uses, with the approver as the signed-in
person, so it sees exactly the trips they see and their numbers are masked as theirs are. "read" (always granted) opens
the pages in READABLE; "ids:read" also opens the request that reveals a membership's full number (REVEALS), only while
"Let assistants see full ID numbers" is on (allow_ids); "write" allows every change the web app makes outside BLOCKED
(writable_routes, deletes included) and the pages in WRITE_READABLE, only while "Let assistants change trips" is on
(allow_writes). A change that takes a number (NEEDS_IDS: adding or editing a membership) needs "ids:read" and its switch
as well. The switches are off unless turned on, and are read on every call, so turning one off takes effect at once for
every connection, without revoking any.

BLOCKED is the boundary: mailboxes and scanning, the "Couldn't read" queue, the AI settings, backup and restore, sign-in,
the calendar feed, push devices, the flight-status refresh (its budget and key) and these settings are never reachable
from /mcp, whatever the scope or switch. Nothing from mail is reachable either: no route that returns a message's
content is allowed (the preview is under /api/review).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..storage import db
from ..storage import settings_keys as sk
from . import mcp_oauth

READ, IDS, WRITE = "read", "ids:read", "write"

# The GET /api/... pages an assistant may read (each also has to be a route in server/routes.py). A membership's number is
# masked in /api/loyalty (its last four characters); the full number comes only from REVEALS.
READABLE = frozenset({
    "/api/trips", "/api/trips/{id}", "/api/segments/{id}", "/api/airports/{id}", "/api/people", "/api/loyalty", "/api/stats",
    "/api/distance-unit", "/api/flight-status",
})

# The one request that reads a full number: needs "ids:read" and its switch, and is logged (which membership, which connection).
REVEALS = frozenset({("POST", "/api/loyalty/{id}/reveal")})

# Changes that take a number as the assistant sends it: "write" isn't enough, the connection also needs "ids:read".
NEEDS_IDS = frozenset({("POST", "/api/loyalty"), ("POST", "/api/loyalty/{id}")})

# "write": any change the web app makes (every POST and DELETE route, writable_routes) except what's BLOCKED, while
# "Let assistants change trips" is on.
SWITCHES = {IDS: sk.MCP_ALLOW_IDS, WRITE: sk.MCP_ALLOW_WRITES}

# Never reachable from /mcp, whatever the scope or switch: each blocks its own path and everything under it. Gmail
# mailboxes and scanning (/api/mailboxes), the "Couldn't read" queue and what's in it (/api/review: mail's content comes
# out only in its preview), the AI settings, backup and restore, sign-in and who's signed in (/api/state), the calendar feed's
# key and the push devices (/api/reminders and /api/feed), the flight-status refresh (it spends the budget and uses the key) and
# these settings. Importing past flights takes a file, which /mcp (JSON only) can't send.
BLOCKED = (
    "/api/mcp-settings", "/api/mailboxes", "/api/review", "/api/ai", "/api/backup", "/api/restore", "/api/state", "/api/feed",
    "/api/reminders", "/api/flight-status/{id}", "/api/import",
)

# GET pages "write" also opens: what its changes need to find what to change. None holds a number or a secret.
WRITE_READABLE = ("/api/people/claim-suggestions",)

# Changes that merge or fold records together (or put one person in place of another): destructive, like a delete or remove.
MANY = frozenset({"/api/trips/{id}/merge", "/api/trips/{id}/split", "/api/people/{id}/claim"})


def blocked(template: str) -> bool:
    """Whether a route (its pattern, as in server/routes.py) is out of every assistant's reach."""
    return any(template == b or template.startswith(b + "/") for b in BLOCKED)


def destructive(method: str, template: str) -> bool:
    """Whether a change removes or deletes something, or folds records into each other."""
    return method == "DELETE" or "remove" in template.split("/") or template in MANY


def writable_routes(routes) -> list[tuple[str, str]]:
    """The changes "write" allows, as (method, pattern), from server/routes.py's ROUTES: every POST and DELETE that
    isn't BLOCKED or a request that only reveals a number (REVEALS). A new route is allowed unless it's added to BLOCKED
    (tests/test_mcp_routes.py lists every route as allowed or blocked, so a new one has to be decided on)."""
    return [(m, p) for m, p, *_fn in routes if m in ("POST", "DELETE") and not blocked(p) and (m, p) not in REVEALS]


@dataclass(frozen=True)
class Access:
    """What one caller of /mcp may do: its scopes ("read", "ids:read", "write"), the grant it came from and the member who
    approved it (sub and email: None without sign-in, when the assistant is the local household). A scope's calls also
    need its switch on at that moment (switched_on)."""
    scopes: frozenset[str]
    grant_id: int | None
    sub: str | None
    email: str | None

    def has(self, scope: str) -> bool:
        return scope in self.scopes


def resolve_bearer(conn, authorization: str | None, resource: str | None) -> Access | None:
    """What an OAuth access token (Authorization: Bearer wpa_...) for this MCP endpoint (`resource`) may do: its grant's
    scopes. None for anything else: no token, an unknown, expired or revoked one, or one for another resource, or one
    whose approver can no longer sign in (mcp_oauth.access_grant)."""
    m = re.fullmatch(r"Bearer\s+(\S+)", (authorization or "").strip(), re.I)
    if not m or not resource:
        return None
    grant = mcp_oauth.access_grant(conn, m.group(1), resource)
    if grant is None:
        return None
    return Access(frozenset(grant["scope"].split()), grant["id"], grant["sub"], grant["email"])


def switched_on(conn, scope: str) -> bool:
    """Whether the calls `scope` allows are switched on right now. False for a scope that has no switch."""
    return scope in SWITCHES and db.get_setting(conn, SWITCHES[scope]) == "1"


def allow_ids(conn) -> bool:
    """Whether full ID numbers may be revealed to assistants allowed "ids:read" (off until turned on)."""
    return switched_on(conn, IDS)


def set_allow_ids(conn, on: bool) -> None:
    db.set_setting(conn, sk.MCP_ALLOW_IDS, "1" if on else "0")


def allow_writes(conn) -> bool:
    """Whether the changes "write" allows are switched on (off until turned on)."""
    return switched_on(conn, WRITE)


def set_allow_writes(conn, on: bool) -> None:
    db.set_setting(conn, sk.MCP_ALLOW_WRITES, "1" if on else "0")
