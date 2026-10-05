"""The pieces every part of the server shares: the error a handler raises and what a server error says, an answer
that isn't JSON (Response) and how a route takes its body, reading what a request sends (ids, whole numbers, texts),
the signed-in person for this request, request references, and which host names Waypoint answers to."""
from __future__ import annotations

import ipaddress
import os
import re
import secrets
import threading
import urllib.parse
from collections.abc import Callable, Generator
from dataclasses import dataclass, field

from .. import monitoring, validate


class ApiError(Exception):
    """What a handler answers when it can't do what was asked: a message for the person, and the status (400 unless
    said otherwise). Anything else a handler raises is a bug: a 500 with a reference (server_error)."""
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def server_error(e: BaseException, method: str, route: str) -> ApiError:
    """A handler (or the server) failed in a way it didn't expect: log and report it, without what the error says (it
    may quote what the request sent, or name a row), and answer only a reference to it. `route` is the route's pattern
    (/api/rules/{id}), never the address itself."""
    ref = request_ref()
    monitoring.log(f"[error {ref}] {method} {route}", "error")
    monitoring.report(e, values=False)
    return ApiError(f"Something went wrong on Waypoint's side (reference {ref}; the details are in its log).", 500)


@dataclass
class Response:
    """A route's answer when it isn't JSON: a download, a logo, a stream. Sent as Content-Type, `headers`,
    Content-Length (not for a stream), Cache-Control, the ETag, the security headers every answer has, and `csp`, a
    stricter policy on top of the usual one. A request that already has this `etag` (If-None-Match) gets a 304."""
    body: bytes
    content_type: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    cache: str = "no-store"
    etag: str | None = None
    csp: str | None = None
    sent: Callable[[], None] | None = None   # run once the body has gone out (never for a HEAD)
    stream: Generator[bytes] | None = None   # Server-Sent Events: written and flushed a piece at a time, not `body`


def header_value(v: str) -> str:
    """v, checked to be safe in a response header: a line break would end the header and start another of someone
    else's choosing (response splitting). Handler.send_header refuses one too; this says so where a value is chosen."""
    if "\r" in v or "\n" in v:
        raise ValueError("A response header can't contain a line break")
    return v


def download(data: bytes, content_type: str, filename: str, sent: Callable[[], None] | None = None) -> Response:
    """A file the browser saves (as `filename`) rather than shows."""
    return Response(data, content_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}, sent=sent)


class BadJson(ValueError):
    """A request's body isn't JSON: not UTF-8, not JSON, or nested deeper than Python reads (Handler._read_json)."""


NOT_READ = object()   # Handler._read_json's answer when it has already answered the request (too large, a bad length)


def upload(limit: int):
    """A route whose body is a file of up to `limit` bytes, handed to its handler as it is (bytes) rather than JSON."""
    def mark(fn):
        fn.upload = limit
        return fn
    return mark


def own_session(fn):
    """A route whose handler opens its own database sessions (a sync, a restore), so it's given None for `conn`: a
    connection held open for minutes would only hold a place in the pool (and, on SQLite, an old snapshot)."""
    fn.own_session = True
    return fn


# ------------------------------------------------------------------------------------------ reading a request

_ID = re.compile(r"[0-9]{1,18}")   # a row's number: digits only (no sign, spaces or other scripts' digits), fits 64 bits
_query = validate.Validator(ApiError, drop="", not_number="The {label} must be a whole number")


def row_id(value, missing: str = "Not found", status: int = 404) -> int:
    """A row's number from the address (/api/rules/12) or a request: anything else is `missing` (404, as a number
    that isn't there would be)."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ApiError(missing, status)
    return int(value)


def clamped_int(v, label: str, default: int, low: int, high: int) -> int:
    """A whole number someone sent, kept between low and high (a bigger or smaller one is moved in, as these always
    were); `default` (kept in too) when there's none, and a 400 for one that isn't a whole number."""
    n = _query.number(v, label)
    if isinstance(v, bool) or (n is not None and n != int(n)):
        raise ApiError(_query.not_number.format(label=label))
    return max(low, min(default if n is None else int(n), high))


def query_int(q, key: str, default: int, low: int, high: int, label: str | None = None) -> int:
    """A whole number from the query string (?limit=50): clamped_int."""
    return clamped_int((q.get(key) or [""])[0], label or key, default, low, high)


def text(v, field: str) -> str:
    """A text field as sent ("" when it's left out), so a handler's own check of it ("Enter a name") answers; anything
    else (a number, a list, an object, true) is refused, rather than taken as empty (which can mean "clear it")."""
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ApiError(f'Send "{field}" as text')
    return v


def request_ref() -> str:
    return secrets.token_hex(4)


_current = threading.local()
EXTRA_HOSTS = {h.strip().lower() for h in (os.environ.get("WAYPOINT_ALLOWED_HOSTS") or "").split(",") if h.strip()}
if os.environ.get("WAYPOINT_PUBLIC_URL"):   # the address you open Waypoint at is always allowed
    EXTRA_HOSTS.add((urllib.parse.urlsplit(os.environ["WAYPOINT_PUBLIC_URL"]).hostname or "").lower())
# Names that can't be pointed at an outside website: this machine, mDNS (.local), home-router names, Tailscale.
SAFE_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".ts.net")


def host_allowed(host_header: str) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):                      # [::1]:8765
        host = host[1:host.find("]")] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":")[0]
    if not host:
        return False
    if "*" in EXTRA_HOSTS or host in EXTRA_HOSTS or host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
        # An address typed directly (not a name) can't be used for DNS rebinding.
        return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        pass
    return host.endswith(SAFE_SUFFIXES) or "." not in host   # bare names like "nas" or "homeserver"
