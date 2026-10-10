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


def urlopen(req: urllib.request.Request | str, timeout: float, *, allow_http: bool = False,
            handlers: tuple[urllib.request.BaseHandler, ...] = ()):
    check_scheme(req.full_url if isinstance(req, urllib.request.Request) else req, allow_http)
    return opener(*handlers, allow_http=allow_http).open(req, timeout=timeout)


ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, ValueError)
_NEVER = (ipaddress.ip_network("64:ff9b::/96"), ipaddress.ip_network("64:ff9b:1::/48"), ipaddress.ip_network("2002::/16"))


def public_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not any(ip in net for net in _NEVER if net.version == ip.version)


class _PublicConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        if getattr(self, "_tunnel_host", None):
            raise urllib.error.URLError("Waypoint opens this address directly, not through a proxy")
        port = self.port or 443
        found = socket.getaddrinfo(self.host, port, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(str(info[4][0]) for info in found))
        if not addresses or not all(public_address(a) for a in addresses):
            raise urllib.error.URLError("Waypoint only opens addresses on the public internet")
        last: OSError | None = None
        for address in addresses:
            try:
                raw = socket.create_connection((address, port), self.timeout, getattr(self, "source_address", None))
            except OSError as e:
                last = e
                continue
            self.sock = ssl_context().wrap_socket(raw, server_hostname=self.host)
            return
        raise last or urllib.error.URLError("no address answered")


class _PublicHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicConnection, req, context=ssl_context())


class _FewRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_scheme(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_handlers() -> tuple[urllib.request.BaseHandler, ...]:
    return urllib.request.ProxyHandler({}), _PublicHTTPS(), _FewRedirects()
