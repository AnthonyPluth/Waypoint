from __future__ import annotations

import functools
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
