from __future__ import annotations

import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .. import tls

MAX_IMAGE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 6_000_000
MAX_ATTEMPTS = 40
MAX_URL = 2000
CONNECT_SECONDS = 6
IMAGE_SECONDS = 8.0
TOTAL_SECONDS = 30.0
CHUNK = 16_384
ACCEPT = "image/png,image/jpeg,image/gif,image/webp"
HEADERS = {"Accept": ACCEPT, "User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"}
SIGNATURES = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
              (b"GIF89a", "image/gif"))


def sniff(data: bytes) -> str | None:
    for signature, kind in SIGNATURES:
        if data.startswith(signature):
            return kind
    return "image/webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None


def allowed_url(url: str) -> bool:
    if not url or len(url) > MAX_URL or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parts = urlsplit(url)
        return parts.scheme == "https" and bool(parts.hostname) and parts.username is None and parts.password is None
    except ValueError:
        return False


class Fetcher:
    def __init__(self) -> None:
        self.attempts = 0
        self.bytes = 0
        self.started = time.monotonic()

    def __call__(self, url: str) -> tuple[str, bytes] | None:
        room = min(MAX_IMAGE_BYTES, MAX_TOTAL_BYTES - self.bytes)
        if self.attempts >= MAX_ATTEMPTS or room <= 0 or time.monotonic() - self.started > TOTAL_SECONDS or not allowed_url(url):
            return None
        self.attempts += 1
        data = self._download(url, room)
        kind = sniff(data) if data else None
        if data is None or kind is None:
            return None
        self.bytes += len(data)
        return kind, data

    def _download(self, url: str, room: int) -> bytes | None:
        began = time.monotonic()
        try:
            with tls.urlopen(urllib.request.Request(url, headers=HEADERS), CONNECT_SECONDS, public_only=True) as res:
                if res.status != 200:
                    return None
                declared = res.headers.get("Content-Length", "")
                if declared.isdigit() and int(declared) > room:
                    return None
                data = bytearray()
                while chunk := res.read(CHUNK):
                    data += chunk
                    if len(data) > room or time.monotonic() - began > IMAGE_SECONDS or time.monotonic() - self.started > TOTAL_SECONDS:
                        return None
        except urllib.error.HTTPError as e:
            e.close()
            return None
        except tls.NETWORK_ERRORS:
            return None
        return bytes(data)
