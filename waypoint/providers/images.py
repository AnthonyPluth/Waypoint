from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence

from .. import imagetype, tls
from ..imagetype import MAX_COUNT, MAX_IMAGE, MAX_TOTAL, Fetched

MAX_URL = 2_000
READ_TIMEOUT = 6
IMAGE_SECONDS = 8
MESSAGE_SECONDS = 30
CHUNK = 16_384
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "image/png,image/jpeg,image/gif,image/webp", "Accept-Encoding": "identity"}


def allowed(url: str) -> bool:
    if len(url) > MAX_URL or not url.isascii() or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == "https" and bool(parts.hostname) and "@" not in parts.netloc and port in (None, 443)


def fetch_one(url: str, limit: int, seconds: float = IMAGE_SECONDS) -> Fetched | None:
    if limit <= 0 or not allowed(url):
        return None
    deadline = time.monotonic() + seconds
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with tls.urlopen(req, timeout=READ_TIMEOUT, handlers=tls.public_handlers()) as resp:
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                return None
            data = b""
            while len(data) <= limit:
                if time.monotonic() > deadline:
                    return None
                chunk = resp.read1(min(CHUNK, limit + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
    except urllib.error.HTTPError as e:
        e.close()
        return None
    except tls.ERRORS:
        return None
    kind = imagetype.sniff(data)
    return (kind, data) if kind and len(data) <= limit else None


def fetch_many(urls: Sequence[str], budget: int = MAX_TOTAL) -> dict[str, Fetched]:
    found: dict[str, Fetched] = {}
    started = time.monotonic()
    for url in dict.fromkeys(urls):
        if len(found) >= MAX_COUNT or budget <= 0:
            break
        left = MESSAGE_SECONDS - (time.monotonic() - started)
        if left <= 0:
            break
        got = fetch_one(url, min(MAX_IMAGE, budget), min(IMAGE_SECONDS, left))
        if got is not None:
            found[url] = got
            budget -= len(got[1])
    return found
