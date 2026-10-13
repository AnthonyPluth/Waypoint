from __future__ import annotations

import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from waypoint import pmtiles


def tile_bytes(tid: int) -> bytes:
    return gzip.compress(f"tile-{tid}".encode() * (1 + tid % 7), mtime=0)


def build(max_zoom: int = 11, deduplicate: bool = True) -> bytes:
    ids = range(pmtiles.zoom_end(max_zoom))
    data = bytearray()
    entries: list[pmtiles.Entry] = []
    seen: dict[bytes, int] = {}
    for tid in ids:
        body = tile_bytes(0 if tid % 11 == 0 and tid >= 11 else tid)
        if deduplicate and body in seen:
            offset = seen[body]
        else:
            offset = len(data)
            seen[body] = offset
            data += body
        entries.append(pmtiles.Entry(tid, offset, len(body), 1))
    size = 512
    leaves = b""
    pointers = []
    for at in range(0, len(entries), size):
        part = pmtiles.write_directory(entries[at:at + size])
        pointers.append(pmtiles.Entry(entries[at].tile_id, len(leaves), len(part), 0))
        leaves += part
    root = pmtiles.write_directory(pointers)
    metadata = gzip.compress(json.dumps({"name": "fixture"}).encode(), mtime=0)
    head = pmtiles.HEADER_LENGTH
    header = pmtiles.Header(head, len(root), head + len(root), len(metadata), head + len(root) + len(metadata), len(leaves),
                            head + len(root) + len(metadata) + len(leaves), len(data), len(entries), len(entries), len(seen),
                            1, pmtiles.GZIP, pmtiles.GZIP, 1, 0, max_zoom, -1800000000, -850000000, 1800000000, 850000000, 0, 0, 0)
    return pmtiles.build_header(header) + root + metadata + leaves + bytes(data)


def tiny(zooms: int = 2) -> bytes:
    return build(zooms)


class Source(BaseHTTPRequestHandler):
    body = b""
    listing: bytes = b"[]"
    hits: list[str] = []
    ignore_ranges = False
    fail_after: int | None = None
    sent = 0

    def log_message(self, *args):
        pass

    def do_GET(self):
        type(self).hits.append(self.path)
        if self.path == "/builds.json":
            self.send_response(200)
            self.send_header("Content-Length", str(len(self.listing)))
            self.end_headers()
            self.wfile.write(self.listing)
            return
        asked = self.headers.get("Range")
        body = self.body
        if not asked or self.ignore_ranges:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        first, last = asked.split("=")[1].split("-")
        start = int(first)
        end = min(int(last), len(body) - 1) if last else len(body) - 1
        chunk = body[start:end + 1]
        cls = type(self)
        if cls.fail_after is not None and cls.sent + len(chunk) > cls.fail_after:
            allowed = max(0, cls.fail_after - cls.sent)
            cls.fail_after = None
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk[:allowed])
            self.wfile.flush()
            self.close_connection = True
            return
        cls.sent += len(chunk)
        self.send_response(206)
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(body)}")
        self.send_header("Content-Length", str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)


def serve(case, body: bytes, listing: list[dict] | None = None, **flags) -> str:
    handler = type("Handler", (Source,), {"body": body, "listing": json.dumps(listing or []).encode(), "hits": [], "sent": 0, **flags})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    case.addCleanup(httpd.server_close)
    case.addCleanup(httpd.shutdown)
    case.handler = handler
    return f"http://127.0.0.1:{httpd.server_port}/"
