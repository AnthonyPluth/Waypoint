from __future__ import annotations

import gzip
import hashlib
import os
import secrets
import threading
from typing import TYPE_CHECKING

from .common import header_value

if TYPE_CHECKING:
    from .handler import Handler

CONTENT_TYPES = {
    ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
    ".webmanifest": "application/manifest+json", ".txt": "text/plain", ".xml": "application/xml",
    ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".webp": "image/webp", ".ico": "image/vnd.microsoft.icon",
    ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".wasm": "application/wasm",
}
DEFAULT_TYPE = "application/octet-stream"


def content_type(path: str) -> str:
    return CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), DEFAULT_TYPE)

STATIC = os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static"))
APP_DIR = os.path.join(STATIC, "app")
APP_INDEX = os.path.join(APP_DIR, "index.html")
_static_files: dict[str, dict] = {}
_static_lock = threading.Lock()


WEEK = "public, max-age=604800"
STABLE_FILES = {"logo.svg", "logo-180.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"}


def cache_control(full: str) -> str:
    if full.startswith(APP_DIR + os.sep + "assets" + os.sep):
        return "public, max-age=31536000, immutable"
    if full.startswith(os.path.join(STATIC, "fonts") + os.sep) or full in {os.path.join(STATIC, name) for name in STABLE_FILES}:
        return WEEK
    return "no-cache"


def serve(h: Handler, path: str) -> None:
    if path == "/next" or path.startswith("/next/"):
        return h._redirect("/")
    rel = path.lstrip("/")
    full = None
    for base in (APP_DIR, STATIC):
        cand = os.path.realpath(os.path.join(base, rel))
        if rel and cand.startswith(base + os.sep) and os.path.isfile(cand):
            full = cand
            break
    if full is None or full == APP_INDEX:
        full = APP_INDEX
        if not os.path.isfile(full):
            return h._page(404, "The web app isn't built", "Run npm run build in frontend/ (the Docker image does this for you).")
    ctype = content_type(full)
    gz_ok = "gzip" in (h.headers.get("Accept-Encoding") or "")
    if full == APP_INDEX:
        nonce = secrets.token_urlsafe(16)
        with open(full, "rb") as f:
            data = f.read().replace(b"<script ", f'<script nonce="{nonce}" '.encode())
        return send_file(h, data, ctype, "no-store", None, gz_ok, nonce)
    entry = _static_entry(full)
    cache = cache_control(full)
    if h.headers.get("If-None-Match") == entry["etag"]:
        h.send_response(304)
        h.send_header("ETag", entry["etag"])
        h.send_header("Cache-Control", cache)
        h._security_headers()
        h.end_headers()
        return None
    return send_file(h, entry["data"], ctype, cache, entry["etag"], gz_ok, None, entry.get("gz"))


def send_file(h: Handler, data: bytes, ctype: str, cache: str, etag: str | None, gz_ok: bool, nonce: str | None,
              gz: bytes | None = None, extra: dict[str, str] | None = None) -> None:
    if gz_ok and _compressible(ctype) and len(data) > 1024:
        data, encoded = gz or gzip.compress(data, 6), True
    else:
        encoded = False
    ctype, cache = header_value(ctype), header_value(cache)
    etag = header_value(etag) if etag else None
    extra = {header_value(k): header_value(v) for k, v in (extra or {}).items()}
    h.send_response(200)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(data)))
    h.send_header("Cache-Control", cache)
    h.send_header("Vary", "Accept-Encoding")
    if etag:
        h.send_header("ETag", etag)
    if encoded:
        h.send_header("Content-Encoding", "gzip")
    for k, v in extra.items():
        h.send_header(k, v)
    h._security_headers(nonce)
    h.end_headers()
    if h.command != "HEAD":
        h.wfile.write(data)


def _compressible(ctype: str) -> bool:
    return ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml",
                                                  "application/manifest+json")


def _static_entry(full: str) -> dict:
    st = os.stat(full)
    key = (st.st_mtime_ns, st.st_size)
    with _static_lock:
        entry = _static_files.get(full)
        if entry and entry["key"] == key:
            return entry
    with open(full, "rb") as f:
        data = f.read()
    ctype = content_type(full)
    entry = {"key": key, "data": data, "etag": '"' + hashlib.sha256(data).hexdigest()[:20] + '"',
             "gz": gzip.compress(data, 6) if _compressible(ctype) and len(data) > 1024 else None}
    with _static_lock:
        _static_files[full] = entry
    return entry
