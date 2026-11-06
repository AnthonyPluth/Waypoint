from __future__ import annotations

import functools
import http.client
import io
import ipaddress
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


@functools.cache
def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except (ImportError, OSError):
        pass
    return ctx


def check_scheme(url: str, allow_http: bool = False) -> None:
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme != "https" and not (allow_http and scheme == "http"):
        raise urllib.error.URLError(f"Waypoint only opens {'http(s)' if allow_http else 'https'} addresses, not {scheme or 'this'}:")


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_http: bool):
        self.allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_scheme(newurl, self.allow_http)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener(*handlers: urllib.request.BaseHandler, allow_http: bool = False) -> urllib.request.OpenerDirector:
    defaults: list[urllib.request.BaseHandler] = [
        urllib.request.ProxyHandler(), urllib.request.UnknownHandler(), urllib.request.HTTPDefaultErrorHandler(),
        _Redirects(allow_http), urllib.request.HTTPErrorProcessor(), urllib.request.HTTPSHandler(context=ssl_context())]
    if allow_http:
        defaults.append(urllib.request.HTTPHandler())
    kinds = (urllib.request.ProxyHandler, urllib.request.UnknownHandler, urllib.request.HTTPDefaultErrorHandler,
             urllib.request.HTTPRedirectHandler, urllib.request.HTTPErrorProcessor, urllib.request.HTTPSHandler,
             urllib.request.HTTPHandler)
    director = urllib.request.OpenerDirector()
    for default in defaults:
        kind = next(k for k in kinds if isinstance(default, k))
        if not any(isinstance(h, kind) for h in handlers):
            director.add_handler(default)
    for h in handlers:
        director.add_handler(h)
    return director


NETWORK_ERRORS = (OSError, ValueError, http.client.HTTPException)


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def public_addresses(host: str, port: int) -> list[str]:
    found = [str(info[4][0]) for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    if not found or not all(is_public(a) for a in found):
        raise urllib.error.URLError("Waypoint only opens addresses on the public internet here")
    return found


class _PublicConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        failure: OSError | None = None
        for address in public_addresses(self.host, self.port):
            try:
                sock = socket.create_connection((address, self.port), self.timeout)
            except OSError as e:
                failure = e
                continue
            self.sock = ssl_context().wrap_socket(sock, server_hostname=self.host)
            return
        raise failure or urllib.error.URLError("No address answered")


class _PublicHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request):
        return self.do_open(_PublicConnection, req, context=ssl_context())


def _left(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("the time for this request ran out")
    return left


class _DeadlineReader(io.RawIOBase):
    def __init__(self, owner: _DeadlineSocket):
        super().__init__()
        self._owner = owner

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        sock = self._owner.sock
        sock.settimeout(self._owner.wait())
        return sock.recv_into(buffer)

    def close(self) -> None:
        if not self.closed:
            self._owner.reader_closed()
        super().close()


class _DeadlineSocket:
    def __init__(self, sock: socket.socket, deadline: float, timeout):
        self.sock = sock
        self.deadline = deadline
        self.timeout = timeout
        self._readers = 0
        self._closing = False

    def makefile(self, *args, **kwargs) -> io.BufferedReader:
        self._readers += 1
        return io.BufferedReader(_DeadlineReader(self))

    def wait(self) -> float:
        return _bounded(self.timeout, self.deadline)

    def sendall(self, data, *args) -> None:
        self.sock.settimeout(self.wait())
        self.sock.sendall(data, *args)

    def reader_closed(self) -> None:
        self._readers -= 1
        if self._closing and self._readers == 0:
            self.sock.close()

    def close(self) -> None:
        self._closing = True
        if self._readers == 0:
            self.sock.close()


def _bounded(timeout, deadline: float) -> float:
    left = _left(deadline)
    return min(timeout, left) if isinstance(timeout, int | float) else left


def _connect_within(address, idle, deadline: float, source_address=None) -> socket.socket:
    failure: OSError | None = None
    host, port = address
    for family, kind, proto, _, sockaddr in socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM):
        wait = _bounded(idle, deadline)
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(wait)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as e:
            sock.close()
            failure = e
    raise failure or OSError("no address to connect to")


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, deadline: float, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadline = deadline
        self._create_connection = self._connect_within

    def _connect_within(self, address, timeout=None, source_address=None, *args) -> socket.socket:
        return _connect_within(address, self.idle, self.deadline, source_address)

    def connect(self) -> None:
        self.idle, self.timeout = self.timeout, _bounded(self.timeout, self.deadline)
        super().connect()
        self.sock = _DeadlineSocket(self.sock, self.deadline, self.idle)


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, deadline: float, **kwargs):
        super().__init__(*args, **kwargs)
        self.deadline = deadline
        self._create_connection = self._connect_within

    def _connect_within(self, address, timeout=None, source_address=None, *args) -> socket.socket:
        return _connect_within(address, self.idle, self.deadline, source_address)

    def connect(self) -> None:
        self.idle, self.timeout = self.timeout, _bounded(self.timeout, self.deadline)
        super().connect()
        self.sock = _DeadlineSocket(self.sock, self.deadline, self.idle)

    def _tunnel(self) -> None:
        plain = self.sock
        self.sock = _DeadlineSocket(plain, self.deadline, self.idle)
        try:
            super()._tunnel()   # type: ignore[misc]
        finally:
            if isinstance(self.sock, _DeadlineSocket):
                self.sock = plain


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, deadline: float):
        super().__init__()
        self.deadline = deadline

    def http_open(self, req: urllib.request.Request):
        return self.do_open(functools.partial(_DeadlineHTTPConnection, deadline=self.deadline), req)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, deadline: float):
        super().__init__(context=ssl_context())
        self.deadline = deadline

    def https_open(self, req: urllib.request.Request):
        return self.do_open(functools.partial(_DeadlineHTTPSConnection, deadline=self.deadline), req, context=ssl_context())


def urlopen(req: urllib.request.Request | str, timeout: float, *, allow_http: bool = False,
            handlers: tuple[urllib.request.BaseHandler, ...] = (), public_only: bool = False, deadline: float | None = None):
    check_scheme(req.full_url if isinstance(req, urllib.request.Request) else req, allow_http and not public_only)
    if deadline is not None:
        if public_only:
            raise ValueError("a deadline isn't supported for public-only requests")
        _left(deadline)
        handlers = (*handlers, _DeadlineHTTPSHandler(deadline), *((_DeadlineHTTPHandler(deadline),) if allow_http else ()))
    if public_only:
        handlers = (*handlers, urllib.request.ProxyHandler({}), _PublicHandler())
    return opener(*handlers, allow_http=allow_http and not public_only).open(req, timeout=timeout)
