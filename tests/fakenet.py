from __future__ import annotations

import base64
import contextlib
import io
import socket
from collections.abc import Callable, Iterator
from unittest import mock

from waypoint import tls

PNG = b"\x89PNG\r\n\x1a\n" + b"CANARY-IMAGE-BYTES-4F8K" + bytes(range(32))
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-bytes" + bytes(20)
GIF = b"GIF89a" + b"gif-bytes" + bytes(20)
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + bytes(20)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'

REAL_GETADDRINFO = socket.getaddrinfo
REAL_CREATE_CONNECTION = socket.create_connection

Answer = tuple[int, dict[str, str], bytes]


def ok(body: bytes, kind: str = "image/png", **headers: str) -> Answer:
    return 200, {"Content-Type": kind, "Content-Length": str(len(body)), **headers}, body


def moved(where: str) -> Answer:
    return 302, {"Location": where, "Content-Length": "0"}, b""


PUBLIC = "93.184.216.34"
SENDER_HOSTS = {"img.example-air.example": [PUBLIC], "inside.example-air.example": ["10.0.0.5"]}
SENDER_PAGES: dict[str, Callable[[str], Answer] | Answer] = {
    "img.example-air.example/banner.png": ok(JPEG, "image/jpeg"),
    "img.example-air.example/pixel.gif": ok(GIF, "image/gif"),
    "img.example-air.example/redirect.png": moved("https://inside.example-air.example/internal.png"),
    "img.example-air.example/huge.png": ok(PNG + bytes(1_000_000)),
    "img.example-air.example/page.png": ok(b"<html>Not an image</html>", "image/png"),
    "img.example-air.example/vector.svg": ok(SVG, "image/svg+xml"),
    "inside.example-air.example/internal.png": ok(PNG),
}
IMAGE_CANARIES = ("CANARY-IMAGE-BYTES-4F8K", base64.b64encode(PNG).decode()[12:40], base64.b64encode(JPEG).decode()[8:32],
                  "CANARY-BODY-RICH-FLIGHT-2J6V", "CANARY-BODY-RICH-NOTE-8K1Q", "CANARY-SUBJECT-RICH-5P3H", "CANARY-SUBJECT-RICHNOTE-7L4B")


class Wire:
    def __init__(self, hosts: dict[str, list[str]], pages: dict[str, Callable[[str], Answer] | Answer]) -> None:
        self.hosts = hosts
        self.pages = pages
        self.connected: list[tuple[str, int]] = []
        self.resolved: list[str] = []
        self.requests: list[str] = []
        self.asked: list[str] = []

    def getaddrinfo(self, host: str, port: int, *args: object, **kwargs: object) -> list[tuple[object, ...]]:
        self.resolved.append(host)
        found = self.hosts.get(host)
        if found is None:
            return REAL_GETADDRINFO(host, port, *args, **kwargs)
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in found]

    def create_connection(self, address: tuple[str, int], *args: object, **kwargs: object) -> object:
        if address[0] not in {a for found in self.hosts.values() for a in found}:
            return REAL_CREATE_CONNECTION(address, *args, **kwargs)
        self.connected.append(address)
        return _Raw(address)

    def answer(self, host: str, path: str) -> Answer:
        path = path.split("?")[0]
        self.asked.append(f"{host}{path}")
        page = self.pages.get(f"{host}{path}")
        if page is None:
            return 404, {"Content-Length": "0"}, b""
        return page(f"{host}{path}") if callable(page) else page


class _Raw:
    def __init__(self, address: tuple[str, int]) -> None:
        self.address = address

    def close(self) -> None:
        pass


class _Socket:
    def __init__(self, wire: Wire, host: str) -> None:
        self.wire, self.host, self.sent = wire, host, b""
        self.reply = io.BytesIO()

    def sendall(self, data: bytes) -> None:
        self.sent += data
        if b"\r\n\r\n" not in self.sent:
            return
        text = self.sent.decode("latin-1")
        self.wire.requests.append(text)
        path = text.split(" ", 2)[1]
        status, headers, body = self.wire.answer(self.host, path)
        head = f"HTTP/1.1 {status} X\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "Connection: close\r\n\r\n"
        self.reply = io.BytesIO(head.encode("latin-1") + body)

    def makefile(self, *args: object, **kwargs: object) -> io.BufferedReader:
        return io.BufferedReader(self.reply)

    def settimeout(self, *args: object) -> None:
        pass

    def close(self) -> None:
        pass


class _Context:
    def __init__(self, wire: Wire) -> None:
        self.wire = wire

    def wrap_socket(self, raw: object, server_hostname: str | None = None, **kwargs: object) -> _Socket:
        return _Socket(self.wire, server_hostname or "")


@contextlib.contextmanager
def internet(hosts: dict[str, list[str]], pages: dict[str, Callable[[str], Answer] | Answer]) -> Iterator[Wire]:
    wire = Wire(hosts, pages)
    with mock.patch("socket.getaddrinfo", wire.getaddrinfo), mock.patch("socket.create_connection", wire.create_connection), \
            mock.patch.object(tls, "ssl_context", lambda: _Context(wire)):
        yield wire
