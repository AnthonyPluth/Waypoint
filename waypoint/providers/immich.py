from __future__ import annotations

import ipaddress
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import IO, Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import tls

TIMEOUT = 15
IMAGE_TIMEOUT = 10
ORIGINAL_TIMEOUT = 30
JSON_SECONDS = 60.0
IMAGE_SECONDS = 20.0
ORIGINAL_SECONDS = 600.0
MAX_JSON_BYTES = 32_000_000
CAPS = {"thumbnail": 2_000_000, "preview": 10_000_000}
CHUNK = 65_536
POLL_FLOOR = 0.01
MAX_URL = 200

USER_AGENT = "Waypoint/1"
JSON_TYPE = "application/json"
IMAGE_TYPES = "image/webp,image/jpeg,image/png"
ORIGINAL_TYPES = "*/*"

PING = "/api/server/ping"
ME = "/api/users/me"
SEARCH = "/api/search/metadata"
MARKERS = "/api/map/markers"
ASSETS = "/api/assets/"

MAX_OFFSET_MINUTES = 18 * 60
PAGE_SIZE = 1000
LAST_PAGE = None
SEARCH_FILTERS: dict[str, Any] = {"withExif": True, "visibility": "timeline", "order": "asc", "size": PAGE_SIZE}
MARKER_FILTERS = {"isArchived": "false", "withPartners": "false", "withSharedAlbums": "false"}
KINDS: dict[str, Literal["image", "video"]] = {"IMAGE": "image", "VIDEO": "video"}

ASSET_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z-]{0,63}")
KEY = re.compile(r"[\x21-\x7e]{1,512}")
HOST_LABEL = re.compile(r"(?!-)[a-z0-9-]{1,63}(?<!-)")
LOCAL = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d)", re.ASCII)
UTC_NAME = re.compile(r"UTC(?:([+-])(\d{1,2})(?::?(\d\d))?)?", re.ASCII)
DIGITS = re.compile(r"[0-9]{1,10}")
BYTE_RANGE = re.compile(r"bytes=(?:([0-9]{1,15})-([0-9]{0,15})|-([0-9]{1,15}))")
RENDITION_MISSING = (404, 410)
SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))
SNIFF_BYTES = 4096
INLINE = True
ATTACHMENT = False
PLAIN_SIGNATURES: tuple[tuple[bytes, str, bool], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", INLINE), (b"\xff\xd8\xff", "image/jpeg", INLINE), (b"GIF87a", "image/gif", INLINE), (b"GIF89a", "image/gif", INLINE),
    (b"II*\x00", "image/tiff", ATTACHMENT), (b"MM\x00*", "image/tiff", ATTACHMENT), (b"IIU\x00", "application/octet-stream", ATTACHMENT),
    (b"IIRO", "application/octet-stream", ATTACHMENT), (b"MMOR", "application/octet-stream", ATTACHMENT), (b"IIRS", "application/octet-stream", ATTACHMENT),
    (b"FUJIFILMCCD-RAW", "application/octet-stream", ATTACHMENT), (b"FOVb", "application/octet-stream", ATTACHMENT),
)
BRANDS: dict[bytes, tuple[str, bool]] = {
    b"avif": ("image/avif", INLINE), b"avis": ("image/avif", INLINE),
    b"heic": ("image/heic", ATTACHMENT), b"heix": ("image/heic", ATTACHMENT), b"hevc": ("image/heic", ATTACHMENT), b"hevx": ("image/heic", ATTACHMENT),
    b"heim": ("image/heic", ATTACHMENT), b"heis": ("image/heic", ATTACHMENT), b"mif1": ("image/heif", ATTACHMENT), b"msf1": ("image/heif", ATTACHMENT),
    b"qt  ": ("video/quicktime", INLINE),
    b"isom": ("video/mp4", INLINE), b"iso2": ("video/mp4", INLINE), b"iso4": ("video/mp4", INLINE), b"iso5": ("video/mp4", INLINE), b"iso6": ("video/mp4", INLINE),
    b"mp41": ("video/mp4", INLINE), b"mp42": ("video/mp4", INLINE), b"mp4v": ("video/mp4", INLINE), b"avc1": ("video/mp4", INLINE), b"dash": ("video/mp4", INLINE),
    b"M4V ": ("video/mp4", INLINE), b"M4A ": ("video/mp4", INLINE), b"3gp4": ("video/mp4", INLINE), b"3gp5": ("video/mp4", INLINE),
}
GENERIC_BRANDS = (b"mif1", b"msf1")
MATROSKA = b"\x1a\x45\xdf\xa3"

NOT_CONFIGURED = "This Immich library isn’t set up: its address or API key is missing or malformed."
REFUSED = "Immich didn’t accept this library’s API key (check it, and the permissions it was given)."
RATE_LIMITED = "Immich says Waypoint has made too many requests; it will try again later."
UNAVAILABLE = "Immich had a problem answering."
UNREACHABLE = "Couldn’t reach Immich."
UNREADABLE = "Immich answered with something Waypoint can’t read."
TOO_LARGE = "Immich’s answer was larger than Waypoint accepts."
TOO_SLOW = "Immich took too long to answer."
NOT_AN_IMAGE = "Immich didn’t answer with a picture Waypoint can show."

Kind = Literal["image", "video"]
Size = Literal["thumbnail", "preview"]
Marker = tuple[str, float, float]


class ImmichError(Exception):
    pass


class NotConfigured(ImmichError):
    pass


class Refused(ImmichError):
    pass


class RateLimited(ImmichError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Unavailable(ImmichError):
    pass


class NotAnImage(Unavailable):
    pass


@dataclass(frozen=True)
class Source:
    url: str = field(repr=False)
    key: str = field(repr=False)
    allow_http: bool = False
    user_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Account:
    user_id: str
    name: str | None
    email: str | None


@dataclass(frozen=True)
class Asset:
    id: str
    kind: Kind
    taken_utc: str
    taken_local: str
    taken_offset: int | None
    latitude: float | None
    longitude: float | None
    state: str | None
    country: str | None
    updated_at: str


@dataclass(frozen=True)
class Page:
    assets: tuple[Asset, ...]
    next_page: int | None
    last_taken: datetime | None = None
    one_instant: bool = False
    dropped: int = 0


class Original:
    def __init__(self, response: Any, deadline: float) -> None:
        self._response = response
        self._deadline = deadline
        status, headers = getattr(response, "status", None), getattr(response, "headers", None)
        found = headers.get if headers is not None else (lambda name: None)
        length = _text(found("Content-Length"), 20)
        self.status = status if isinstance(status, int) else 200
        self.content_range = _text(found("Content-Range"))
        self.content_length = int(length) if length is not None and DIGITS.fullmatch(length) else None
        self.accept_ranges = _text(found("Accept-Ranges"), 40)
        self._fed = time.monotonic()

    def _poll(self, size: int, wait: float) -> bytes | None:
        owner = getattr(getattr(getattr(self._response, "fp", None), "raw", None), "_owner", None)
        if owner is None:
            return cast(bytes, self._response.read1(size))
        idle = owner.timeout
        owner.timeout = max(min(wait, idle) if isinstance(idle, int | float) else wait, POLL_FLOOR)
        try:
            return cast(bytes, self._response.read1(size))
        except TimeoutError:
            return None
        finally:
            owner.timeout = idle

    def read(self, size: int = CHUNK, wait: float | None = None) -> bytes | None:
        problem = TOO_SLOW
        chunk = None
        now = time.monotonic()
        if self._deadline > now and self._fed + ORIGINAL_TIMEOUT > now:
            try:
                chunk = self._response.read1(size) if wait is None else self._poll(size, wait)
            except TimeoutError:
                chunk = None
            except tls.NETWORK_ERRORS:
                problem = UNREACHABLE
            else:
                if wait is not None and chunk is None:
                    return None
        if not isinstance(chunk, bytes):
            raise Unavailable(problem)
        self._fed = time.monotonic()
        return chunk

    def close(self) -> None:
        self._response.close()

    def __enter__(self) -> Original:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: Message,
                         newurl: str) -> urllib.request.Request | None:
        return None


def _host(hostname: str) -> str | None:
    if "%" in hostname:
        return None
    if ":" in hostname:
        return f"[{ipaddress.IPv6Address(hostname).compressed}]"
    host = hostname.removesuffix(".")
    labels = host.split(".")
    return host if host and all(HOST_LABEL.fullmatch(label) for label in labels) else None


def clean_url(text: str) -> str | None:
    text = text.strip()
    if not text or len(text) > MAX_URL or any(c.isspace() or ord(c) < 32 or c in "\\?#@" for c in text):
        return None
    try:
        parts = urllib.parse.urlsplit(text)
        port = parts.port
        host = _host(parts.hostname) if parts.hostname else None
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or parts.path not in ("", "/") or port == 0 or host is None:
        return None
    return f"{parts.scheme}://{host}" + (f":{port}" if port is not None else "")


def retry_after(value: str | None, now: datetime) -> float | None:
    text = (value or "").strip()
    if DIGITS.fullmatch(text):
        return float(int(text))
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        return None
    when = when if when.tzinfo is not None else when.replace(tzinfo=UTC)
    return max(0.0, (when - now).total_seconds())


def _failure(code: int | None, wait: str | None) -> ImmichError:
    if code in (401, 403):
        return Refused(REFUSED)
    if code == 429:
        return RateLimited(RATE_LIMITED, retry_after(wait, datetime.now(UTC)))
    return Unavailable(UNREACHABLE if code is None else UNAVAILABLE)


def _base(source: Source) -> str:
    base = clean_url(source.url)
    if base is None or not KEY.fullmatch(source.key):
        raise NotConfigured(NOT_CONFIGURED)
    return base


def _request(source: Source, path: str, accept: str, *, query: dict[str, str] | None = None,
             body: dict[str, Any] | None = None, byte_range: str | None = None) -> urllib.request.Request:
    url = _base(source) + path + (f"?{urllib.parse.urlencode(query)}" if query else "")
    headers = {"x-api-key": source.key, "User-Agent": USER_AGENT, "Accept": accept}
    if byte_range is not None:
        headers["Range"] = byte_range
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = JSON_TYPE
    return urllib.request.Request(url, data=data, headers=headers, method="GET" if data is None else "POST")


def _open(source: Source, req: urllib.request.Request, timeout: float, deadline: float, *,
          missing: tuple[int, ...] = (404,), accepted: tuple[int, ...] = (200,)) -> Any | None:
    code: int | None
    wait: str | None
    slow = False
    try:
        response = tls.urlopen(req, timeout, allow_http=source.allow_http, handlers=(_NoRedirects(),), deadline=deadline)
    except urllib.error.HTTPError as e:
        if e.code in accepted:
            return e
        code, wait = e.code, e.headers.get("Retry-After") if e.headers is not None else None
        e.close()
    except tls.NETWORK_ERRORS:
        code, wait, slow = None, None, time.monotonic() >= deadline
    else:
        if response.status in accepted:
            return response
        response.close()
        code, wait = response.status, None
    if code in missing:
        return None
    raise Unavailable(TOO_SLOW) if slow else _failure(code, wait)


def _read(response: Any, cap: int, deadline: float) -> bytes:
    declared = response.headers.get("Content-Length") or ""
    if DIGITS.fullmatch(declared) and int(declared) > cap:
        raise Unavailable(TOO_LARGE)
    data = bytearray()
    problem = None
    try:
        while True:
            if deadline - time.monotonic() <= 0:
                problem = TOO_SLOW
                break
            chunk = response.read1(CHUNK)
            if not chunk:
                break
            data += chunk
            if len(data) > cap:
                problem = TOO_LARGE
                break
    except TimeoutError:
        problem = TOO_SLOW
    except tls.NETWORK_ERRORS:
        problem = UNREACHABLE
    if problem is not None:
        raise Unavailable(problem)
    return bytes(data)


def _json(source: Source, req: urllib.request.Request) -> Any:
    deadline = time.monotonic() + JSON_SECONDS
    response = _open(source, req, TIMEOUT, deadline)
    if response is None:
        raise Unavailable(UNAVAILABLE)
    with response:
        raw = _read(response, MAX_JSON_BYTES, deadline)
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        pass
    raise Unavailable(UNREADABLE)


def _text(value: Any, limit: int = 200) -> str | None:
    return value.strip()[:limit] or None if isinstance(value, str) else None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
        parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo is not None else None


def _utc_text(at: datetime) -> str:
    if at.tzinfo is None:
        raise ValueError("Immich times must carry a zone")
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _minutes(offset: Any) -> int | None:
    return None if offset is None else int(offset.total_seconds() // 60)


def zone_offset(name: Any, at: datetime) -> int | None:
    text = _text(name, 64)
    if text is None:
        return None
    fixed = UTC_NAME.fullmatch(text)
    if fixed:
        sign, hours, minutes = fixed.group(1), int(fixed.group(2) or 0), int(fixed.group(3) or 0)
        if hours * 60 + minutes > MAX_OFFSET_MINUTES or minutes > 59:
            return None
        return (-1 if sign == "-" else 1) * (hours * 60 + minutes)
    try:
        return _minutes(at.astimezone(ZoneInfo(text)).utcoffset())
    except (ZoneInfoNotFoundError, ValueError, OSError, OverflowError):
        return None


def taken_local(value: Any) -> str | None:
    found = LOCAL.match(value) if isinstance(value, str) else None
    if found is None:
        return None
    try:
        datetime.strptime(found.group(1), "%Y-%m-%dT%H:%M")
    except ValueError:
        return None
    return found.group(1)


def _position(exif: dict[str, Any]) -> tuple[float, float] | None:
    lat, lon = _number(exif.get("latitude")), _number(exif.get("longitude"))
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return lat, lon


def parse_asset(item: Any, owner: str) -> Asset | None:
    if not isinstance(item, dict) or item.get("ownerId") != owner:
        return None
    asset_id, kind_name = item.get("id"), item.get("type")
    kind = KINDS.get(kind_name) if isinstance(kind_name, str) else None
    if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id) or kind is None:
        return None
    exif: dict[str, Any] = item["exifInfo"] if isinstance(item.get("exifInfo"), dict) else {}
    taken = _instant(item.get("fileCreatedAt"))
    local, updated = taken_local(item.get("localDateTime")), _instant(item.get("updatedAt"))
    if taken is None or local is None or updated is None:
        return None
    offset = zone_offset(exif.get("timeZone"), taken)
    position = _position(exif)
    return Asset(id=asset_id, kind=kind, taken_utc=_utc_text(taken), taken_local=local, taken_offset=offset,
                 latitude=position[0] if position else None, longitude=position[1] if position else None,
                 state=_text(exif.get("state"), 100), country=_text(exif.get("country"), 100), updated_at=_utc_text(updated))


def next_page(value: Any, page: int) -> int | None:
    if value is LAST_PAGE:
        return None
    if isinstance(value, str) and DIGITS.fullmatch(value) and int(value) == page + 1:
        return page + 1
    raise Unavailable(UNREADABLE)


def parse_page(body: Any, page: int, owner: str) -> Page:
    assets = body.get("assets") if isinstance(body, dict) else None
    items = assets.get("items") if isinstance(assets, dict) else None
    if not isinstance(assets, dict) or not isinstance(items, list) or "nextPage" not in assets:
        raise Unavailable(UNREADABLE)
    found = tuple(a for item in items if (a := parse_asset(item, owner)))
    others = sum(1 for item in items if isinstance(item, dict) and isinstance(item.get("ownerId"), str) and ASSET_ID.fullmatch(item["ownerId"])
                 and (item["ownerId"] != owner or (isinstance(item.get("type"), str) and item["type"] not in KINDS)))
    taken = [_instant(item.get("fileCreatedAt")) if isinstance(item, dict) else None for item in items]
    known = [at.astimezone(UTC) for at in taken if at is not None]
    return Page(assets=found, next_page=next_page(assets.get("nextPage"), page), last_taken=max(known) if len(known) == len(taken) and known else None,
                one_instant=bool(known) and len(known) == len(taken) and len(set(known)) == 1, dropped=len(items) - others - len(found))


def parse_markers(body: Any) -> list[Marker]:
    if not isinstance(body, list):
        raise Unavailable(UNREADABLE)
    out: list[Marker] = []
    for item in body:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not ASSET_ID.fullmatch(item["id"]):
            continue
        position = _position({"latitude": item.get("lat"), "longitude": item.get("lon")})
        if position is not None:
            out.append((item["id"], position[0], position[1]))
    return out


def parse_account(body: Any) -> Account:
    user_id = _text(body.get("id"), 100) if isinstance(body, dict) else None
    if not isinstance(body, dict) or user_id is None:
        raise Unavailable(UNREADABLE)
    return Account(user_id=user_id, name=_text(body.get("name")), email=_text(body.get("email")))


def sniff(data: bytes) -> str | None:
    for signature, kind in SIGNATURES:
        if data.startswith(signature):
            return kind
    return "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None


def _boxed(data: bytes) -> tuple[str, bool] | None:
    if len(data) < 12 or data[4:8] != b"ftyp":
        return None
    size = int.from_bytes(data[:4], "big")
    end = min(len(data), size) if 16 <= size <= SNIFF_BYTES else min(len(data), 32)
    brands = [data[8:12], *(data[at:at + 4] for at in range(16, end - 3, 4))]
    specific = next((BRANDS[b] for b in brands if b in BRANDS and b not in GENERIC_BRANDS), None)
    return specific or next((BRANDS[b] for b in brands if b in BRANDS), None)


def original_type(data: bytes) -> tuple[str, bool] | None:
    for signature, kind, inline in PLAIN_SIGNATURES:
        if data.startswith(signature):
            return kind, inline
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", INLINE
    if data.startswith(MATROSKA) and len(data) >= 8:
        return ("video/webm", INLINE) if b"webm" in data[4:64] else ("video/x-matroska", ATTACHMENT)
    return _boxed(data)


def ping(source: Source) -> Account:
    pong = _json(source, _request(source, PING, JSON_TYPE))
    if not isinstance(pong, dict) or pong.get("res") != "pong":
        raise Unavailable(UNREADABLE)
    return parse_account(_json(source, _request(source, ME, JSON_TYPE)))


def search_body(taken_after: datetime, taken_before: datetime, updated_after: datetime | None, page: int) -> dict[str, Any]:
    body = {**SEARCH_FILTERS, "takenAfter": _utc_text(taken_after), "takenBefore": _utc_text(taken_before), "page": page}
    if updated_after is not None:
        body["updatedAfter"] = _utc_text(updated_after)
    return body


def search(source: Source, taken_after: datetime, taken_before: datetime, *, updated_after: datetime | None = None,
           page: int = 1) -> Page:
    if not source.user_id:
        raise NotConfigured(NOT_CONFIGURED)
    body = search_body(taken_after, taken_before, updated_after, page)
    return parse_page(_json(source, _request(source, SEARCH, JSON_TYPE, body=body)), page, source.user_id)


def markers(source: Source, after: datetime, before: datetime) -> list[Marker]:
    query = {"fileCreatedAfter": _utc_text(after), "fileCreatedBefore": _utc_text(before), **MARKER_FILTERS}
    return parse_markers(_json(source, _request(source, MARKERS, JSON_TYPE, query=query)))


def thumbnail(source: Source, asset_id: str, size: Size, *, seconds: float | None = None) -> tuple[str, bytes] | None:
    if not ASSET_ID.fullmatch(asset_id) or size not in CAPS:
        return None
    deadline = time.monotonic() + (IMAGE_SECONDS if seconds is None else seconds)
    request = _request(source, f"{ASSETS}{asset_id}/thumbnail", IMAGE_TYPES, query={"size": size})
    response = _open(source, request, IMAGE_TIMEOUT, deadline, missing=RENDITION_MISSING)
    if response is None:
        return None
    with response:
        data = _read(response, CAPS[size], deadline)
    kind = sniff(data)
    if kind is None:
        raise NotAnImage(NOT_AN_IMAGE)
    return kind, data


def asset_exists(source: Source, asset_id: str, *, seconds: float | None = None) -> bool:
    if not ASSET_ID.fullmatch(asset_id):
        return False
    deadline = time.monotonic() + (JSON_SECONDS if seconds is None else seconds)
    response = _open(source, _request(source, f"{ASSETS}{asset_id}", JSON_TYPE), TIMEOUT, deadline, missing=RENDITION_MISSING)
    if response is None:
        return False
    response.close()
    return True


def single_range(value: str | None) -> str | None:
    found = BYTE_RANGE.fullmatch(value) if value is not None else None
    if found is None or (found.group(1) and found.group(2) and int(found.group(2)) < int(found.group(1))):
        return None
    return value


def open_original(source: Source, asset_id: str, *, seconds: float = ORIGINAL_SECONDS, byte_range: str | None = None) -> Original | None:
    if not ASSET_ID.fullmatch(asset_id):
        return None
    deadline = time.monotonic() + seconds
    asked = single_range(byte_range)
    request = _request(source, f"{ASSETS}{asset_id}/original", ORIGINAL_TYPES, byte_range=asked)
    response = _open(source, request, ORIGINAL_TIMEOUT, deadline, accepted=(200, 206, 416) if asked else (200,))
    return None if response is None else Original(response, deadline)
