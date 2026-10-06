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
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def server_error(e: BaseException, method: str, route: str) -> ApiError:
    ref = request_ref()
    monitoring.log(f"[error {ref}] {method} {route}", "error")
    monitoring.report(e, values=False)
    return ApiError(f"Something went wrong on Waypoint's side (reference {ref}; the details are in its log).", 500)


@dataclass
class Response:
    body: bytes
    content_type: str
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    cache: str = "no-store"
    etag: str | None = None
    csp: str | None = None
    sent: Callable[[], None] | None = None
    stream: Generator[bytes] | None = None


def header_value(v: str) -> str:
    if "\r" in v or "\n" in v:
        raise ValueError("A response header can't contain a line break")
    return v


def download(data: bytes, content_type: str, filename: str, sent: Callable[[], None] | None = None) -> Response:
    return Response(data, content_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}, sent=sent)


class BadJson(ValueError):
    pass


NOT_READ = object()


def upload(limit: int):
    def mark(fn):
        fn.upload = limit
        return fn
    return mark


def own_session(fn):
    fn.own_session = True
    return fn


_ID = re.compile(r"[0-9]{1,18}")
_query = validate.Validator(ApiError, drop="", not_number="The {label} must be a whole number")


def row_id(value, missing: str = "Not found", status: int = 404) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ApiError(missing, status)
    return int(value)


def clamped_int(v, label: str, default: int, low: int, high: int) -> int:
    n = _query.number(v, label)
    if isinstance(v, bool) or (n is not None and n != int(n)):
        raise ApiError(_query.not_number.format(label=label))
    return max(low, min(default if n is None else int(n), high))


def query_int(q, key: str, default: int, low: int, high: int, label: str | None = None) -> int:
    return clamped_int((q.get(key) or [""])[0], label or key, default, low, high)


def text(v, field: str) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ApiError(f'Send "{field}" as text')
    return v


def request_ref() -> str:
    return secrets.token_hex(4)


_current = threading.local()
EXTRA_HOSTS = {h.strip().lower() for h in (os.environ.get("WAYPOINT_ALLOWED_HOSTS") or "").split(",") if h.strip()}
if os.environ.get("WAYPOINT_PUBLIC_URL"):
    EXTRA_HOSTS.add((urllib.parse.urlsplit(os.environ["WAYPOINT_PUBLIC_URL"]).hostname or "").lower())
SAFE_SUFFIXES = (".local", ".lan", ".home.arpa", ".internal", ".ts.net")


def host_allowed(host_header: str) -> bool:
    host = host_header.strip().lower()
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else host
    elif host.count(":") == 1:
        host = host.split(":")[0]
    if not host:
        return False
    if "*" in EXTRA_HOSTS or host in EXTRA_HOSTS or host == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private or ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        pass
    return host.endswith(SAFE_SUFFIXES) or "." not in host
