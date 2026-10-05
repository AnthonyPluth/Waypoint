"""Waypoint's MCP server: the tools that let an AI assistant (Claude and the like) read the household's travel, and, only if
the household switched it on in Settings and the member allowed it when connecting, see full ID numbers or change trips.

Waypoint serves it at POST /mcp (waypoint/server/handler.py), to an assistant connected with OAuth (waypoint/server/mcp_oauth.py).
The assistant is the member who approved it: handle() answers one JSON-RPC message, and every page it reads or change it
makes goes through the `fetch` it's given (mcp_http.fetch_for), which runs it as that member through the same routes the web
app uses, allows only the pages and changes mcp_access opens, and checks the connection's scopes and their switches ("Let
assistants see full ID numbers", "Let assistants change trips") on every call, so turning a switch off takes effect at
once. Every changing tool tells the assistant to ask first.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from . import mcp_access

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXT = 200_000   # characters in one reply: enough for years of trips, not enough to flood the assistant's context

Fetch = Callable[..., Any]   # fetch(path, query) reads; fetch(path, query, body) POSTs a change; fetch(path, query, body, "DELETE") deletes

READ, IDS, WRITE = mcp_access.READ, mcp_access.IDS, mcp_access.WRITE


class ToolError(Exception):
    """Something to tell the assistant instead of a result (a bad argument, or Waypoint refusing)."""


# ------------------------------------------------------------------------------------------------ tools

def _schema(props: dict[str, dict] | None = None, required: list[str] | None = None) -> dict:
    out: dict[str, Any] = {"type": "object", "properties": props or {}, "additionalProperties": False}
    if required:
        out["required"] = required
    return out


_ID = {"type": "integer", "minimum": 1}
_DAY = {"type": "string", "description": "A day, like 2026-09-30."}
_TRIP_ID = {**_ID, "description": "A trip's id (from list_trips)."}
_SEGMENT_ID = {**_ID, "description": "A segment's id (from get_trip or upcoming)."}
_PERSON_ID = {**_ID, "description": "A person's id (from list_people)."}
_LOYALTY_ID = {**_ID, "description": "A membership's id (from get_loyalty_ids)."}


def _need(a: dict, name: str) -> int:
    raw = a.get(name)
    if raw in (None, "") or isinstance(raw, bool):
        raise ToolError(f"Give a {name}.")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a whole number.") from None


def _day(a: dict, name: str, default: date) -> date:
    raw = a.get(name)
    if raw in (None, ""):
        return default
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise ToolError(f"{name} must be a day like 2026-09-30.") from None


def _trip_summary(t: dict) -> dict:
    keep = ("id", "name", "start_date", "end_date", "destination", "notes")
    kinds: dict[str, int] = {}
    for s in t.get("segments", []):
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    return {**{k: t.get(k) for k in keep}, "segments": kinds}


def list_trips(fetch: Fetch, a: dict) -> Any:
    today = date.today().isoformat()
    trips = fetch("trips", {})["trips"]
    when = a.get("when") or "all"
    if when == "upcoming":
        trips = [t for t in trips if (t.get("end_date") or t.get("start_date") or "9999") >= today]
    elif when == "past":
        trips = [t for t in trips if (t.get("end_date") or t.get("start_date") or "") < today]
    return {"today": today, "trips": [_trip_summary(t) for t in trips]}


def upcoming(fetch: Fetch, a: dict) -> Any:
    """The next segments (flights, stays, rentals, trains) of every trip, soonest first. Times are wall-clock at the place."""
    today = date.today()
    start = _day(a, "from", today)
    days = min(max(int(a.get("days") or 60), 1), 730)
    last = start + timedelta(days=days)
    out = []
    for t in fetch("trips", {})["trips"]:
        for s in t.get("segments", []):
            if s["status"] != "cancelled" and start.isoformat() <= s["end_local"][:10] and s["start_local"][:10] <= last.isoformat():
                out.append({"trip_id": t["id"], "trip": t["name"], **s})
    out.sort(key=lambda s: (s["start_local"], s["id"]))
    return {"today": today.isoformat(), "from": start.isoformat(), "through": last.isoformat(), "segments": out}


def get_loyalty_ids(fetch: Fetch, a: dict) -> Any:
    """Memberships with their numbers masked (last four characters); with `reveal` and a person or a membership, in full
    (needs "ids:read" and its switch; each is logged by Waypoint, never the number)."""
    listing = fetch("loyalty", {})
    rows = [r for r in listing["loyalty"]
            if (not a.get("person_id") or r["person_id"] == a["person_id"]) and (not a.get("loyalty_id") or r["id"] == a["loyalty_id"])]
    if a.get("reveal"):
        if not (a.get("person_id") or a.get("loyalty_id")):
            raise ToolError("To see full numbers, say whose (person_id) or which membership (loyalty_id).")
        rows = [{**r, "number": fetch(f"loyalty/{r['id']}/reveal", {}, {})["number"]} for r in rows if r["readable"]]
    return {"loyalty": rows, "conflicts": listing["conflicts"], "programs": listing["programs"]}


def flight_status(fetch: Fetch, a: dict) -> Any:
    """What's already held (Waypoint doesn't fetch anything new for an assistant)."""
    out = fetch("flight-status", {})
    statuses = [s for s in out["statuses"] if not a.get("segment_id") or s["segment_id"] == a["segment_id"]]
    return {"enabled": out["enabled"], "paused": out["paused"], "statuses": statuses}


TOOLS: list[dict[str, Any]] = [
    {"name": "upcoming", "description": "What's coming up: flights, stays, rentals and trains in the next days (default 60), soonest "
     "first, with their trip, confirmation code and travellers. Times are the wall-clock times at the place, in the zone each carries.",
     "inputSchema": _schema({"days": {"type": "integer", "minimum": 1, "maximum": 730, "description": "How many days ahead (default 60)."},
                             "from": {**_DAY, "description": "Start from this day instead of today."}}),
     "run": upcoming, "needs": (READ,)},
    {"name": "list_trips", "description": "The trips you're on (or booked), with dates, destination and how many segments of each kind. "
     "Use get_trip for one trip's segments.",
     "inputSchema": _schema({"when": {"type": "string", "enum": ["all", "upcoming", "past"], "description": "Which trips (default all)."}}),
     "run": list_trips, "needs": (READ,)},
    {"name": "get_trip", "description": "One trip with every segment (flights, stays, rentals, trains) and who is travelling.",
     "inputSchema": _schema({"trip_id": _TRIP_ID}, ["trip_id"]),
     "run": lambda fetch, a: fetch(f"trips/{_need(a, 'trip_id')}", {}), "needs": (READ,)},
    {"name": "list_people", "description": "Everyone who travels: household members, then guests, with the names airlines print.",
     "inputSchema": _schema(), "run": lambda fetch, _a: fetch("people", {}), "needs": (READ,)},
    {"name": "get_loyalty_ids", "description": "Loyalty, Known Traveler and redress memberships: program, tier, expiry and the number's "
     "last four characters. To see a full number (to fill in a booking), set reveal with a person_id or loyalty_id: that needs "
     "the connection to be allowed full ID numbers and the household's switch on, and Waypoint notes each reveal in its log.",
     "inputSchema": _schema({"person_id": _PERSON_ID, "loyalty_id": _LOYALTY_ID,
                             "reveal": {"type": "boolean", "description": "Give the full numbers (default false: last four only)."}}),
     "run": get_loyalty_ids, "needs": (READ,)},
    {"name": "get_stats", "description": "Travel stats over the trips you can see: flights, distance, airports, airlines, stays, cars and places, "
     "for one person or everyone, for a year or all time.",
     "inputSchema": _schema({"person": {"type": "string", "description": "A person's id from list_people, or all (default)."},
                             "year": {"type": "string", "description": "A four-digit year, or all (default)."}}),
     "run": lambda fetch, a: fetch("stats", {"person": a.get("person"), "year": a.get("year")}), "needs": (READ,)},
    {"name": "flight_status", "description": "The live status Waypoint already holds for your flights (delays, gates, landed). It never "
     "looks anything new up for an assistant, so a flight with no status has none held.",
     "inputSchema": _schema({"segment_id": _SEGMENT_ID}), "run": flight_status, "needs": (READ,)},
]

# ------------------------------------------------------------------------------------------------ changes (opt-in)

_SWITCHES = {WRITE: "Let assistants change trips", IDS: "Let assistants see full ID numbers"}
# What an assistant allowed "write" is told when it connects: it reads these, the person doesn't.
WRITE_RULES = (
    "You can change the household's travel: the changing tools, and call_endpoint (list_endpoints) for anything else. Rules: "
    "1) Before every change, say in plain words what you'll change and wait for the person's explicit yes. "
    "2) A destructive change (removing a trip, segment, person or membership, merging or splitting trips; such tools are marked "
    "destructive) also needs the person to confirm what will be lost, separately from any other yes. Ask for each change on its own, "
    "never under one blanket yes for several. "
    "3) Times are wall-clock times at the place (start_local in start_zone); never convert them. "
    "Mailboxes, the “Couldn’t read” queue, AI settings, backups, sign-in and these assistant settings are out of reach.")
# How every changing tool's description ends: the assistant asks first, and for a destructive one, says what goes.
ASK = "Ask the person before calling this."
DESTRUCTIVE = "Destructive: tell the person exactly what will be removed or merged and get a clear yes first."


def allowed(fetch: Fetch, scopes: tuple[str, ...]) -> bool:
    """Whether this connection may use every one of `scopes` right now (allowed when it connected, and the switch in
    Settings). Unsure: no."""
    try:
        return all(fetch("access", {"scope": s}).get("allowed") for s in scopes if s != READ)
    except (ToolError, AttributeError):
        return False


def _refusal(fetch: Fetch, scopes: tuple[str, ...]) -> str:
    """Why a call can't be made: the switch is off, or this connection wasn't allowed it when it connected."""
    for scope in (s for s in scopes if s != READ):
        try:
            answer = fetch("access", {"scope": scope})
        except (ToolError, AttributeError):
            answer = {}
        if not answer.get("allowed"):
            return answer.get("why") or f"Not allowed. Turn on “{_SWITCHES[scope]}” in Waypoint under Settings."
    return "Not found"


def _change(template: str, id_arg: str | None = None, fields: bool = False, extra: tuple[str, ...] = (),
            method: str = "POST") -> Callable[[Fetch, dict], Any]:
    """A tool that makes one change: POSTs (or DELETEs) to `template` (its {id} from `id_arg`, a number) the `fields`
    object and any of the `extra` arguments, as the web app's forms send them."""
    def run(fetch: Fetch, a: dict) -> Any:
        path = template.replace("{id}", str(_need(a, id_arg)), 1) if id_arg else template
        body = dict(a.get("fields") or {}) if fields else {}
        body.update({k: a[k] for k in extra if a.get(k) is not None})
        return fetch(path, {}, body) if method == "POST" else fetch(path, {}, body, method)
    return run


def _fields(description: str) -> dict:
    return {"type": "object", "description": description}


def _write_tool(name: str, description: str, run: Callable[[Fetch, dict], Any], props: dict, required: list[str], *,
                route: tuple[str, str], idempotent: bool = False, ids: bool = False) -> dict:
    """A tool that changes something: offered, and run, only while this connection may make changes (and, for a number,
    see full ones). Destructive as mcp_access.destructive says of its route."""
    harm = mcp_access.destructive(*route)
    return {"name": name, "description": f"{description} {ASK}" + (f" {DESTRUCTIVE}" if harm else ""),
            "inputSchema": _schema(props, required), "run": run, "needs": (WRITE, IDS) if ids else (WRITE,),
            "write": True, "idempotent": idempotent, "destructive": harm}


_SEGMENT_FIELDS = _fields("kind (flight, hotel, car or train), start_local and end_local (YYYY-MM-DDTHH:MM, wall-clock at the "
                          "place), and optionally status (confirmed, changed or cancelled), confirmation, provider, origin and "
                          "destination (a flight's airport codes; a stay's or a rental's place), start_zone and end_zone (IANA; a "
                          "flight's come from its airports), details (flight_number, terminal, seat, cabin, room, car_class, "
                          "address, phone: texts), manage_url and travelers ([{person_id}] or [{name}], the person asking when left out).")
_TRIP_FIELDS = _fields("name, and optionally destination, notes; start_date and end_date (YYYY-MM-DD) for a trip with no segments yet.")
_PERSON_FIELDS = _fields("display_name, and optionally first_name, legal_name (as on an ID) and aliases (a list of how airlines print the "
                         "name). Changing replaces all of them: send every name to keep.")
_LOYALTY_FIELDS = _fields("person_id, kind (airline, hotel, car, known_traveler or redress), program (one of get_loyalty_ids' programs "
                          "for the kind, Other if it isn't there), number, and optionally tier, expiry (YYYY-MM-DD) and notes. "
                          "Changing: leave number out to keep the one saved.")

WRITE_TOOLS: list[dict[str, Any]] = [
    _write_tool("add_segment", "Add a flight, stay, rental or train. Without a trip_id it goes into the trip it falls into (one is "
                "made if none does).", _change("segments", None, True, ("trip_id",)),
                {"fields": _SEGMENT_FIELDS, "trip_id": _TRIP_ID}, ["fields"], route=("POST", "/api/segments")),
    _write_tool("update_segment", "Change only the fields sent of a segment (what ends up different is locked, so a later email "
                "won't put it back). travelers replaces who it's for.", _change("segments/{id}", "segment_id", True),
                {"segment_id": _SEGMENT_ID, "fields": _SEGMENT_FIELDS}, ["segment_id", "fields"], route=("POST", "/api/segments/{id}"),
                idempotent=True),
    _write_tool("remove_segment", "Remove a segment (a grouped trip left with none goes too).", _change("segments/{id}", "segment_id", method="DELETE"),
                {"segment_id": _SEGMENT_ID}, ["segment_id"], route=("DELETE", "/api/segments/{id}")),
    _write_tool("create_trip", "Make a trip by hand, with no segments yet.", _change("trips", None, True), {"fields": _TRIP_FIELDS},
                ["fields"], route=("POST", "/api/trips")),
    _write_tool("update_trip", "Rename a trip, or change its destination or notes.", _change("trips/{id}", "trip_id", True),
                {"trip_id": _TRIP_ID, "fields": _TRIP_FIELDS}, ["trip_id", "fields"], route=("POST", "/api/trips/{id}"), idempotent=True),
    _write_tool("merge_trips", "Fold another trip into this one: its segments move here and it goes.", _change("trips/{id}/merge", "trip_id", extra=("merge",)),
                {"trip_id": {**_TRIP_ID, "description": "The trip that stays."}, "merge": {**_TRIP_ID, "description": "The trip folded into it."}},
                ["trip_id", "merge"], route=("POST", "/api/trips/{id}/merge")),
    _write_tool("add_guest", "Add a guest: someone who travels with the household but has no login.", _change("people", None, True),
                {"fields": _PERSON_FIELDS}, ["fields"], route=("POST", "/api/people")),
    _write_tool("update_person", "Change a person's names (a guest's or a member's).", _change("people/{id}", "person_id", True),
                {"person_id": _PERSON_ID, "fields": _PERSON_FIELDS}, ["person_id", "fields"], route=("POST", "/api/people/{id}"),
                idempotent=True),
    _write_tool("add_loyalty_id", "Save a loyalty, Known Traveler or redress membership for a member or a guest. The number is "
                "kept encrypted and shown masked afterwards. Needs the connection to be allowed full ID numbers too.",
                _change("loyalty", None, True), {"fields": _LOYALTY_FIELDS}, ["fields"], route=("POST", "/api/loyalty"), ids=True),
    _write_tool("update_loyalty_id", "Change a membership; leave number out to keep the one saved. Needs the connection to be allowed "
                "full ID numbers too.", _change("loyalty/{id}", "loyalty_id", True), {"loyalty_id": _LOYALTY_ID, "fields": _LOYALTY_FIELDS},
                ["loyalty_id", "fields"], route=("POST", "/api/loyalty/{id}"), idempotent=True, ids=True),
    _write_tool("remove_loyalty_id", "Remove a membership.", _change("loyalty/{id}", "loyalty_id", method="DELETE"), {"loyalty_id": _LOYALTY_ID},
                ["loyalty_id"], route=("DELETE", "/api/loyalty/{id}")),
]


def _call_endpoint(fetch: Fetch, a: dict) -> Any:
    method = str(a.get("method") or "").upper()
    path = str(a.get("path") or "").strip().lstrip("/")
    path = path[4:] if path.startswith("api/") else path
    if method not in ("GET", "POST", "DELETE") or not path:
        raise ToolError("Give a method (GET, POST or DELETE) and a path from list_endpoints, like /api/trips/12.")
    query = a.get("query") or {}
    if not isinstance(query, dict):
        raise ToolError("Send the query as an object.")
    if method == "GET":
        return fetch(path, query)
    body = a.get("body") or {}
    return fetch(path, query, body) if method == "POST" else fetch(path, query, body, "DELETE")


ANY_TOOLS: list[dict[str, Any]] = [
    {"name": "list_endpoints", "description": "Every Waypoint endpoint call_endpoint can reach, by area, the destructive ones marked.",
     "inputSchema": _schema(), "run": lambda fetch, _a: fetch("endpoints", {}), "needs": (WRITE,), "reads": True},
    {"name": "call_endpoint", "description": "Last resort, for what no other tool does (splitting a trip, claiming a guest, the "
     "distance unit): call one of Waypoint's endpoints (list_endpoints) as its web app does. body is what the web app's form sends. "
     f"Anything it can't reach is refused. {ASK} {DESTRUCTIVE}",
     "inputSchema": _schema({"method": {"type": "string", "enum": ["GET", "POST", "DELETE"]},
                             "path": {"type": "string", "description": "Like /api/trips/12/split."},
                             "body": {"type": "object"}, "query": {"type": "object"}}, ["method", "path"]),
     "run": _call_endpoint, "needs": (WRITE,), "write": True, "idempotent": False, "destructive": True},
]
ALL_TOOLS = TOOLS + WRITE_TOOLS + ANY_TOOLS
BY_NAME = {t["name"]: t for t in ALL_TOOLS}


def offered(fetch: Fetch) -> list[dict[str, Any]]:
    """The tools this server offers: the reading ones, plus the changing ones only while this connection may use them."""
    return [t for t in ALL_TOOLS if t["needs"] == (READ,) or allowed(fetch, t["needs"])]


def _annotations(t: dict) -> dict:
    if not t.get("write"):
        return {"readOnlyHint": True, "openWorldHint": False}
    # A change: the assistant asks you first, and for a destructive one, says what goes
    return {"readOnlyHint": False, "destructiveHint": bool(t.get("destructive")), "idempotentHint": bool(t.get("idempotent")),
            "openWorldHint": False}


def call_tool(name: str, args: dict, fetch: Fetch) -> str:
    tool = BY_NAME.get(name)
    if not tool:
        raise ToolError(f"Unknown tool {name}.")
    if tool["needs"] != (READ,) and not allowed(fetch, tool["needs"]):
        raise ToolError(_refusal(fetch, tool["needs"]))
    text = json.dumps(tool["run"](fetch, args or {}), ensure_ascii=False, separators=(",", ":"))
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f"… (cut at {MAX_TEXT:,} characters: narrow it with days, a trip or a person)"
    return text


# ------------------------------------------------------------------------------------------------ the protocol

def _about(fetch: Fetch) -> str:
    about = ("Access to a Waypoint travel app, as the member who connected you: the trips they are on (flights, stays, rentals, "
             "trains), the people who travel, loyalty and Known Traveler numbers (shown by their last four characters), stats and "
             "live flight status. Times are wall-clock times at the place, with its zone.")
    if allowed(fetch, (WRITE,)):
        return f"{about} {WRITE_RULES}"
    return f"{about} Everything is read-only."


def handle(msg: Any, fetch: Fetch) -> dict | None:
    """One JSON-RPC message in, its reply out (None for a notification)."""
    if not isinstance(msg, dict) or "method" not in msg:
        return None
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def fail(code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    if "id" not in msg:   # notifications (notifications/initialized, /cancelled...) get no reply
        return None
    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "waypoint", "version": "1"},
                   "instructions": _about(fetch)})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": [{"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"],
                              "annotations": _annotations(t)} for t in offered(fetch)]})
    if method == "tools/call":
        try:
            name = params.get("name")
            args = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(args, dict):
                return fail(-32602, "tools/call needs a name and an arguments object")
            return ok({"content": [{"type": "text", "text": call_tool(name, args, fetch)}]})
        except ToolError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
        except (ValueError, TypeError, KeyError) as e:   # an argument of the wrong kind, or a reply that isn't Waypoint's
            return ok({"content": [{"type": "text", "text": f"That didn't work: {type(e).__name__}"}], "isError": True})
    return fail(-32601, f"Method not found: {method}")
