"""Every request Waypoint makes to another service over the web (sign-in, push notifications, and later Gmail): one place, so none of them checks certificates differently from the others, and none can be
pointed at anything but a web address.

urllib on its own also opens file:, ftp: and data: addresses, and follows a redirect to ftp:. urlopen() here opens https
only (http too where a caller allows it, for an address you set yourself: a sign-in provider on your network, or a test
server standing in for a service), checked before anything is sent, and its opener has no handler for any other scheme,
so a redirect can't reach one either.
"""
from __future__ import annotations

import functools
import ssl
import urllib.error
import urllib.parse
import urllib.request


@functools.cache
def ssl_context() -> ssl.SSLContext:
    """Certificates checked against the system's, plus certifi's when it's installed. Made once: loading the
    certificates takes a while, and a context can be shared by many connections at once."""
    ctx = ssl.create_default_context()
    try:  # python.org builds on macOS ship without system certs; use certifi when present
        import certifi

        ctx.load_verify_locations(certifi.where())
    except (ImportError, OSError):   # certifi is optional; without it (or its bundle) the system certs still apply
        pass
    return ctx


def check_scheme(url: str, allow_http: bool = False) -> None:
    """Raises urllib.error.URLError (an OSError, as a connection that failed is) unless url is https (or http, when
    allowed)."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme != "https" and not (allow_http and scheme == "http"):
        raise urllib.error.URLError(f"Waypoint only opens {'http(s)' if allow_http else 'https'} addresses, not {scheme or 'this'}:")


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Redirects followed only to the schemes the request itself was allowed."""
    def __init__(self, allow_http: bool):
        self.allow_http = allow_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_scheme(newurl, self.allow_http)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener(*handlers: urllib.request.BaseHandler, allow_http: bool = False) -> urllib.request.OpenerDirector:
    """build_opener() without file:, ftp: and data: (and without http: unless allowed): https with ssl_context(), the
    system's proxy settings, redirects to the allowed schemes only, and HTTP errors raised as HTTPError. A handler given
    replaces the default of its kind (a redirect handler of one's own, say), as with build_opener()."""
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
    """urllib.request.urlopen for every outbound request: the address is checked first (https, or http when
    allow_http), then opened with opener(*handlers). Raises urllib.error.URLError for any other scheme, before
    anything is sent."""
    check_scheme(req.full_url if isinstance(req, urllib.request.Request) else req, allow_http)
    return opener(*handlers, allow_http=allow_http).open(req, timeout=timeout)
