from __future__ import annotations

import functools
import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request


@functools.cache
def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
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


def urlopen(req: urllib.request.Request | str, timeout: float, *, allow_http: bool = False,
            handlers: tuple[urllib.request.BaseHandler, ...] = (), public_only: bool = False):
    check_scheme(req.full_url if isinstance(req, urllib.request.Request) else req, allow_http and not public_only)
    if public_only:
        handlers = (*handlers, urllib.request.ProxyHandler({}), _PublicHandler())
    return opener(*handlers, allow_http=allow_http and not public_only).open(req, timeout=timeout)
