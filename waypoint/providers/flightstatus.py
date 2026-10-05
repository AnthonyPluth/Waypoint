"""Live flight status from AeroDataBox, through RapidAPI: the one module that talks to either.

A request asks for one flight by number and local departure date (`GET /flights/number/{number}/{date}`) and carries
nothing else: no names, confirmation codes, loyalty numbers or other segments (AGENTS.md, "Email stays on the server").
The key is RAPIDAPI_KEY, from the environment only: it's never stored in the database, logged or put in an error
message (monitoring.scrub hides it too). Without it the feature is off.

What comes back is reduced to the fields Waypoint shows. Times are the airports' wall-clock times as the service gives
them ("2026-03-01 22:15-05:00"), kept as 2026-03-01T22:15 with the airport's IANA zone; the offset is dropped, not applied,
so nothing is converted to the server's zone or to UTC (AGENTS.md, "Times are where they happen"). The request budget (the
RapidAPI plan allows few calls a month) is kept by waypoint/domain/flightstatus.py; this module only makes the call.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import tls

HOST = "aerodatabox.p.rapidapi.com"
TIMEOUT = 15
DELAYED_AFTER_MINUTES = 15   # a flight expected this much later than booked, not yet away, counts as delayed

SCHEDULED, DELAYED, DEPARTED, LANDED, CANCELLED, DIVERTED, UNKNOWN = (
    "scheduled", "delayed", "departed", "landed", "cancelled", "diverted", "unknown")
STATES = (SCHEDULED, DELAYED, DEPARTED, LANDED, CANCELLED, DIVERTED, UNKNOWN)

# AeroDataBox's flight statuses, as ours.
STATE_OF = {"expected": SCHEDULED, "checkin": SCHEDULED, "boarding": SCHEDULED, "gateclosed": SCHEDULED,
            "delayed": DELAYED, "departed": DEPARTED, "enroute": DEPARTED, "approaching": DEPARTED, "arrived": LANDED,
            "canceled": CANCELLED, "cancelled": CANCELLED, "canceleduncertain": CANCELLED, "diverted": DIVERTED}

FLIGHT_NUMBER = re.compile(r"[A-Z0-9]{2}\d{1,4}[A-Z]?")
LOCAL = re.compile(r"(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d)")


@dataclass(frozen=True)
class Hosts:
    """The service's address. Tests point it at a fake one (and allow its plain http)."""
    base: str = f"https://{HOST}"
    allow_http: bool = False


HOSTS = Hosts()


class FlightStatusError(Exception):
    """Something went wrong asking for a flight's status; the message is fixed text, safe to show and log."""


class NotConfigured(FlightStatusError):
    pass


class RateLimited(FlightStatusError):
    """RapidAPI answered 429: too many requests (or the plan's quota is used up)."""


class Refused(FlightStatusError):
    """RapidAPI doesn't accept the key (wrong, or not subscribed to AeroDataBox)."""


class Unavailable(FlightStatusError):
    """The service couldn't be reached, or answered with something Waypoint can't read."""


@dataclass(frozen=True)
class Status:
    """One flight's live status. Times are `2026-03-01T22:15` wall-clock times at the airports, with their zones."""
    state: str
    origin: str | None = None
    destination: str | None = None
    dep_scheduled: str | None = None
    dep_estimated: str | None = None
    dep_actual: str | None = None
    dep_zone: str | None = None
    dep_terminal: str | None = None
    dep_gate: str | None = None
    arr_scheduled: str | None = None
    arr_estimated: str | None = None
    arr_actual: str | None = None
    arr_zone: str | None = None
    arr_terminal: str | None = None
    arr_gate: str | None = None


# ------------------------------------------------------------------------------------------------ configuration

def key() -> str | None:
    return (os.environ.get("RAPIDAPI_KEY") or "").strip() or None


def configured() -> bool:
    return key() is not None


def normalize(number: str | None) -> str | None:
    """A flight number as the service wants it ("ex 101" -> "EX101"), or None when it isn't one. Only this reaches the
    address, so nothing else can ride along in it."""
    n = re.sub(r"[\s-]", "", number or "").upper()
    return n if FLIGHT_NUMBER.fullmatch(n) else None


# ------------------------------------------------------------------------------------------------ reading the answer

def _text(value: Any, limit: int = 20) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None


def _local(block: Any, name: str) -> str | None:
    """The wall-clock time in a time object ({"utc": ..., "local": "2026-03-01 22:15-05:00"}): the local part as it is."""
    t = block.get(name) if isinstance(block, dict) else None
    m = LOCAL.match(t.get("local") or "") if isinstance(t, dict) and isinstance(t.get("local"), str) else None
    return f"{m.group(1)}T{m.group(2)}" if m else None


def _side(block: Any) -> dict[str, str | None]:
    block = block if isinstance(block, dict) else {}
    airport = block.get("airport") if isinstance(block.get("airport"), dict) else {}
    return {"airport": _text(airport.get("iata"), 3), "zone": _text(airport.get("timeZone"), 64),
            "scheduled": _local(block, "scheduledTime"), "estimated": _local(block, "revisedTime") or _local(block, "predictedTime"),
            "actual": _local(block, "runwayTime"), "terminal": _text(block.get("terminal"), 10), "gate": _text(block.get("gate"), 10)}


def minutes_later(later: str, earlier: str) -> int:
    """How many minutes `later` is after `earlier`, two wall-clock times at the same airport."""
    return round((datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds() / 60)


def parse_flight(flight: Any) -> Status | None:
    """One flight from the service's list, or None when it isn't one."""
    if not isinstance(flight, dict) or not (flight.get("status") or flight.get("departure") or flight.get("arrival")):
        return None
    dep, arr = _side(flight.get("departure")), _side(flight.get("arrival"))
    raw = flight.get("status")
    state = STATE_OF.get(raw.replace(" ", "").lower(), UNKNOWN) if isinstance(raw, str) else UNKNOWN
    expected = dep["actual"] or dep["estimated"]
    if state == SCHEDULED and expected and dep["scheduled"] and minutes_later(expected, dep["scheduled"]) >= DELAYED_AFTER_MINUTES:
        state = DELAYED
    return Status(state=state, origin=dep["airport"], destination=arr["airport"],
                  dep_scheduled=dep["scheduled"], dep_estimated=dep["estimated"], dep_actual=dep["actual"], dep_zone=dep["zone"],
                  dep_terminal=dep["terminal"], dep_gate=dep["gate"],
                  arr_scheduled=arr["scheduled"], arr_estimated=arr["estimated"], arr_actual=arr["actual"], arr_zone=arr["zone"],
                  arr_terminal=arr["terminal"], arr_gate=arr["gate"])


def parse(body: Any, origin: str | None = None) -> Status | None:
    """The status in the service's answer (a list of flights: one number can fly several legs a day), or None when there's
    none (an unknown flight). With `origin`, the leg that leaves from there; a flight number's other legs aren't this one."""
    flights = body if isinstance(body, list) else [body] if isinstance(body, dict) and body else []
    found = [s for f in flights if (s := parse_flight(f))]
    if origin:
        found = [s for s in found if s.origin == origin.upper()]
    return found[0] if found else None


# ------------------------------------------------------------------------------------------------ talking to the service

def fetch(number: str, day: str, origin: str | None = None) -> Status | None:
    """The live status of flight `number` (as normalize gives it) on its local departure `day` (YYYY-MM-DD): None when the
    service doesn't know the flight. One call against the monthly budget. Raises NotConfigured, RateLimited, Refused or
    Unavailable; their messages are fixed texts."""
    k = key()
    if not k:
        raise NotConfigured("Flight status isn’t set up: RAPIDAPI_KEY isn’t set.")
    if not FLIGHT_NUMBER.fullmatch(number) or not re.fullmatch(r"\d{4}-\d\d-\d\d", day):
        raise Unavailable("That isn’t a flight number and date Waypoint can ask about.")
    req = urllib.request.Request(f"{HOSTS.base}/flights/number/{number}/{day}", headers={
        "X-RapidAPI-Key": k, "X-RapidAPI-Host": HOST, "Accept": "application/json", "User-Agent": "Waypoint/0.1"})
    try:
        with tls.urlopen(req, timeout=TIMEOUT, allow_http=HOSTS.allow_http) as r:
            raw = r.read(1_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        with e:
            code = e.code
        if code == 204 or code == 404:
            return None
        if code == 429:
            raise RateLimited("RapidAPI says Waypoint has made too many flight status requests.") from None
        if code in (401, 403):
            raise Refused("RapidAPI didn’t accept RAPIDAPI_KEY (check it, and that it’s subscribed to AeroDataBox).") from None
        raise Unavailable("The flight status service had a problem.") from None
    except (urllib.error.URLError, OSError, TimeoutError):   # the reason may quote the address or the proxy
        raise Unavailable("Couldn’t reach the flight status service.") from None
    if not raw.strip():
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        raise Unavailable("The flight status service answered with something Waypoint can’t read.") from None
    return parse(body, origin)
