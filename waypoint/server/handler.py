from __future__ import annotations

import contextlib
import html
from http.cookies import SimpleCookie
import json
import os
import socket
import sys
import threading
import time
import urllib.parse
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ..storage import db, secretbox
from .. import monitoring, oidc
from . import feed, jobs, mcp_http, mcp_oauth, mcp_server, oauth_http, routes, static
from .common import NOT_READ, ApiError, BadJson, Response, _current, header_value, host_allowed, server_error

PUBLIC_FILES = {"/page.css", "/logo.svg", "/logo-180.png", "/fonts/Geist-Variable.woff2", "/manifest.webmanifest", "/sw.js",
                "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png"}

MAX_JSON_BODY = 1024 * 1024
REQUEST_TIMEOUT = 60
HEADER_DEADLINE = 30
MIN_BODY_RATE = 16 * 1024
MAX_CONCURRENT_REQUESTS = 64

NOT_SAME_SITE = ("Blocked a request that didn’t come from Waypoint’s own address. If you run Waypoint behind a proxy, check "
                 "WAYPOINT_PUBLIC_URL and WAYPOINT_ALLOWED_HOSTS.")
NO_APP_HEADER = ("Blocked a change that didn’t come from Waypoint’s app (it was missing the X-Waypoint header). Reload the page "
                 "and try again; if you run Waypoint behind a proxy, make sure it passes that header on.")

def content_security_policy(nonce: str | None = None) -> str:
    scripts = f"'nonce-{nonce}' 'strict-dynamic' 'self'" if nonce else "'self'"
    return ("default-src 'self'; "
            f"script-src {scripts}; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; "
            "frame-src 'none'; worker-src 'self'; manifest-src 'self'; "
            "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")


AUTH_PATHS = {"/auth/login", "/auth/callback", "/auth/logout", "/auth/signed-out"}


def route_name(path: str) -> str:
    if path.startswith("/api/"):
        found = routes.match(None, path)
        return found.route.pattern if found else "/api/*"
    if path in AUTH_PATHS or path in oauth_http.OAUTH_PUBLIC or path in oauth_http.OAUTH_METADATA or path in ("/mcp", "/oauth/authorize"):
        return path
    if path.startswith(("/.well-known/", "/oauth/")):
        return path[:path.index("/", 1)] + "/*"
    return "/"


class Handler(BaseHTTPRequestHandler):
    server_version = "Waypoint"
    sys_version = ""
    timeout = REQUEST_TIMEOUT
    _set_cookies: list[str]

    def setup(self):
        super().setup()
        self._deadline(HEADER_DEADLINE)

    def finish(self):
        self._deadline(None)
        super().finish()

    def _deadline(self, seconds: float | None) -> None:
        set_deadline = getattr(self.server, "set_deadline", None)
        if set_deadline:
            set_deadline(self.connection, seconds)

    def _read_body(self, n: int) -> bytes:
        self._deadline(REQUEST_TIMEOUT + n / MIN_BODY_RATE)
        try:
            return self.rfile.read(n)
        finally:
            self._deadline(None)

    def log_message(self, fmt, *args):
        pass

    def log_request(self, code="-", size="-"):
        path = urllib.parse.urlsplit(getattr(self, "path", "") or "").path
        if path == "/healthz":
            return
        if path.startswith(feed.PREFIX):
            path = feed.PREFIX + "…"
        started = getattr(self, "_started", None)
        ms = f" {int((time.monotonic() - started) * 1000)}ms" if started else ""
        monitoring.log(f"{self.client_address[0]} {getattr(self, 'command', '-')} {path} {code}{ms}")

    def _security_headers(self, nonce: str | None = None, csp: str | None = None) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", csp or content_security_policy(nonce))
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        if oidc.config()["secure_cookie"]:
            self.send_header("Strict-Transport-Security", "max-age=31536000")

    def _send(self, status: int, body: bytes, ctype: str = "application/json", cache: str = "no-store",
              nonce: str | None = None, extra: dict[str, str] | None = None, csp: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self._security_headers(nonce, csp)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, e: BaseException) -> None:
        err = server_error(e, self.command, route_name(urllib.parse.urlsplit(self.path).path))
        self._json(err.status, {"error": str(err)})

    def _body_length(self, limit: int) -> int | None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > limit:
            self.close_connection = True
            self._json(413 if n > limit else 400, {"error": "That request is too large." if n > limit else "Bad request."})
            return None
        return n

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj, allow_nan=False).encode())

    def _read_json(self, limit: int, empty: Any = BadJson) -> Any:
        n = self._body_length(limit)
        if n is None:
            return NOT_READ
        if not n:
            if empty is BadJson:
                raise BadJson("There's no body")
            return empty
        try:
            return json.loads(self._read_body(n).decode())
        except (ValueError, RecursionError) as e:
            raise BadJson(type(e).__name__) from None

    def _respond(self, r: Response) -> None:
        ctype, cache = header_value(r.content_type), header_value(r.cache)
        etag = header_value(r.etag) if r.etag else None
        csp = header_value(r.csp) if r.csp else None
        headers = {header_value(k): header_value(v) for k, v in r.headers.items()}
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self._security_headers()
            self.end_headers()
            return
        self.send_response(r.status)
        self.send_header("Content-Type", ctype)
        for k, v in headers.items():
            self.send_header(k, v)
        if r.stream is None:
            self.send_header("Content-Length", str(len(r.body)))
        self.send_header("Cache-Control", cache)
        if etag:
            self.send_header("ETag", etag)
        if r.stream is not None:
            self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        if r.stream is not None:
            return self._stream(r.stream)
        if self.command != "HEAD":
            self.wfile.write(r.body)
            if r.sent:
                r.sent()

    def _stream(self, events: Generator[bytes]) -> None:
        self.close_connection = True
        try:
            if self.command == "HEAD":
                return
            for piece in events:
                self.wfile.write(piece)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            events.close()

    def _host_ok(self) -> bool:
        return host_allowed(self.headers.get("Host") or "")

    def _cookie(self, name: str) -> str | None:
        c = SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except Exception:
            return None
        return c[name].value if name in c else None

    def _user(self, renew: bool = False) -> dict | None:
        if not oidc.enabled():
            return {"name": None, "email": None, "local": True}
        token = self._cookie("waypoint_session")
        with db.session() as conn:
            user = oidc.session_user(conn, token)
            if user and token and renew and (max_age := oidc.renew_session(conn, token)):
                self._set_cookies.append(self._cookie_header("waypoint_session", token, max_age))
        return user

    def end_headers(self):
        cookies, self._set_cookies = getattr(self, "_set_cookies", None) or [], []
        for ck in cookies:
            self.send_header("Set-Cookie", ck)
        super().end_headers()

    def _redirect(self, location: str, cookies: list[str] | None = None) -> None:
        if "\r" in location or "\n" in location:
            location = "/"
        self.send_response(302)
        self.send_header("Location", location)
        for ck in cookies or []:
            self.send_header("Set-Cookie", ck)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()

    @staticmethod
    def _page_html(title: str, inner: str, center: bool = True) -> bytes:
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · Waypoint</title><link rel="icon" href="/logo.svg"><link rel="stylesheet" href="/page.css"></head>
<body><main style="max-width:520px;margin:12vh auto"><div class="card"{' style="text-align:center"' if center else ''}>
<img src="/logo.svg" width="48" height="48" alt=""><h1 style="margin-top:12px">{html.escape(title)}</h1>
{inner}</div></main></body></html>""".encode()

    def _page(self, status: int, title: str, message: str, link: tuple[str, str] | None = None,
              other: tuple[str, str] | None = None, cookies: list[str] | None = None) -> None:
        buttons = "".join(f'<a class="btn{" primary" if i == 0 else ""}" href="{html.escape(href)}">{html.escape(text)}</a>'
                          for i, (href, text) in enumerate(x for x in (link, other) if x))
        inner = (f'<p class="help" style="margin:0 auto 16px">{html.escape(message)}</p>\n'
                 + (f'<div class="actions center">{buttons}</div>' if buttons else ''))
        self._send(status, self._page_html(title, inner), "text/html; charset=utf-8",
                   extra={"Set-Cookie": cookies[0]} if cookies else None)

    def _cookie_header(self, name: str, value: str, max_age: int, path: str = "/") -> str:
        secure = "; Secure" if oidc.config()["secure_cookie"] else ""
        return f"{name}={value}; Path={path}; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def _auth_routes(self, url) -> bool:
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/auth/login":
            if not oidc.enabled():
                self._redirect("/"); return True
            try:
                with db.session() as conn:
                    target, state = oidc.start_login(conn, q.get("next") or "/", q.get("prompt") == "select_account")
            except oidc.OIDCError as e:
                self._page(502, "Can't reach sign-in", str(e), ("/auth/login", "Try again")); return True
            self._redirect(target, [self._cookie_header("waypoint_login", state, oidc.LOGIN_TTL, "/auth")]); return True
        if url.path == "/auth/callback":
            try:
                with db.session() as conn:
                    token, nxt = oidc.finish_login(conn, q, self._cookie("waypoint_login"))
            except oidc.NotAllowed as e:
                self._not_allowed(e.who); return True
            except oidc.OIDCError as e:
                self._page(403, "Couldn't sign you in", str(e), ("/auth/login", "Try again")); return True
            days = oidc.config()["session_days"]
            self._redirect(nxt, [self._cookie_header("waypoint_session", token, days * 86400),
                                 self._cookie_header("waypoint_login", "", 0, "/auth")]); return True
        if url.path == "/auth/logout":
            self._page(405, "Sign out from Waypoint", "To sign out, use the Sign out button in Waypoint.", ("/", "Open Waypoint")); return True
        if url.path == "/auth/signed-out":
            self._page(200, "Signed out", "You've signed out of Waypoint.", ("/auth/login", "Sign in again")); return True
        return False

    def _not_allowed(self, who: str) -> None:
        monitoring.log(f"[sign-in] refused {who!r}: not in OIDC_ALLOWED_EMAILS or OIDC_ALLOWED_GROUPS (add them there to let "
                       "them in)", "warning")
        c = oidc.config()
        end = oidc.provider_sign_out(c)
        provider = urllib.parse.urlsplit(c["issuer"]).hostname or "your sign-in provider"
        self._page(403, "Not authorized", f"{who} isn’t allowed to use this Waypoint. Ask whoever runs it to add you, or sign in "
                   "with a different account.", ("/auth/login?prompt=select_account", "Use a different account"),
                   (end, f"Sign out of {provider}") if end else None)

    def send_response(self, code, message=None):
        self._responded, self._status = True, code
        super().send_response(code, message)

    def send_header(self, keyword, value):
        if any(c in f"{keyword}{value}" for c in "\r\n"):
            self._headers_buffer = []
            self._responded = False
            raise ValueError("A response header can't contain a line break")
        super().send_header(keyword, value)

    def _dispatch(self, method: str) -> None:
        self._deadline(None)
        self._started, self._responded = time.monotonic(), False
        self._set_cookies = []
        self._handle(method)

    def _handle(self, method: str) -> None:
        try:
            self._route(method)
        except Exception as e:
            if not self._responded:
                self._error(e)
            else:
                monitoring.report()

    def _same_site(self, form: bool = False) -> bool:
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if site == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if origin == "null" and form:
            return site == "same-origin"
        if origin:
            return origin != "null" and host_allowed(urllib.parse.urlsplit(origin).netloc)
        return True

    def _logout(self) -> None:
        with db.session() as conn:
            target = oidc.logout(conn, self._cookie("waypoint_session")) if oidc.enabled() else "/"
        body = json.dumps({"redirect": target}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", self._cookie_header("waypoint_session", "", 0))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _feed(self, method: str, path: str) -> None:
        if method != "GET":
            return self._send(405, b"", "text/plain")
        found = feed.serve(path)
        if found is None:
            return self._send(404, b"Not found", "text/plain")
        self._respond(found)

    def _route(self, method: str) -> None:
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/healthz" and method == "GET":
            return self._send(200, b"ok", "text/plain")
        if not self._host_ok():
            return self._send(403, b"Waypoint doesn't recognise this address. Add it to WAYPOINT_ALLOWED_HOSTS.", "text/plain")
        if url.path == "/mcp":
            return self._mcp_rpc(method)
        if url.path.startswith(("/.well-known/", "/oauth/")) and url.path != "/oauth/authorize":
            return oauth_http.app_calls(self, method, url)
        if method != "GET" and url.path != "/oauth/authorize" and not self._same_site():
            return self._json(403, {"error": NOT_SAME_SITE})
        if url.path.startswith("/auth/") and method == "GET" and self._auth_routes(url):
            return
        if url.path == "/auth/logout" and method == "POST":
            if self.headers.get("X-Waypoint") != "1":
                return self._json(403, {"error": NO_APP_HEADER})
            return self._logout()
        if url.path.startswith(feed.PREFIX):
            return self._feed(method, url.path)
        if url.path not in PUBLIC_FILES:
            self.user = self._user(renew=url.path.startswith("/api/"))
            if not self.user:
                if url.path.startswith("/api/"):
                    return self._json(401, {"error": "You've been signed out.", "login": "/auth/login"})
                back = (url.path or "/") + ("?" + url.query if url.query else "")
                return self._redirect("/auth/login?next=" + urllib.parse.quote(back, safe=""))
        if url.path == "/oauth/authorize":
            return oauth_http.authorize(self, method, url)
        if not url.path.startswith("/api/"):
            if method != "GET":
                return self._send(405, b"", "text/plain")
            return static.serve(self, url.path)
        if method != "GET" and self.headers.get("X-Waypoint") != "1":
            return self._json(403, {"error": NO_APP_HEADER})
        hit = routes.match(method, url.path)
        body: Any = {}
        if hit is not None and hit.route.upload:
            n = self._body_length(hit.route.upload)
            if n is None:
                return
            body = self._read_body(n) if n else b""
        elif method in ("POST", "DELETE"):
            try:
                body = self._read_json(MAX_JSON_BODY, {})
            except BadJson:
                return self._json(400, {"error": "Bad JSON"})
            if body is NOT_READ:
                return
            if not isinstance(body, dict):
                return self._json(400, {"error": "Bad JSON"})
        if hit is None:
            return self._json(404, {"error": "Not found"})
        q = urllib.parse.parse_qs(url.query)
        _current.user = getattr(self, "user", None)
        _current.host = self.headers.get("Host")
        try:
            result = routes.dispatch(hit, q, body)
        except ApiError as e:
            return self._json(e.status, {"error": str(e)})
        if isinstance(result, Response):
            return self._respond(result)
        return self._json(200, result)

    def _mcp_rpc(self, method: str) -> None:
        if method != "POST":
            return self._send(405, b"", "text/plain", extra={"Allow": "POST"})
        if not self._mcp_origin_ok():
            return self._json(403, {"error": "Origin not allowed."})
        iss = mcp_oauth.issuer(self.headers.get("Host"))
        sent = self.headers.get("Authorization")
        with db.session() as conn:
            access = mcp_http.authorized(conn, sent, mcp_oauth.resource(iss) if iss else None)
        if access is None:
            self.close_connection = True
            challenge = 'Bearer realm="Waypoint"' + (f', resource_metadata="{mcp_oauth.resource_metadata_url(iss)}"' if iss else "")
            if sent:
                challenge += ', error="invalid_token"'
            why = ("Connect with OAuth: add this address to your assistant and approve it in Waypoint." if iss
                   else mcp_oauth.unavailable_reason())
            return self._send(401, json.dumps({"error": why}).encode(), extra={"WWW-Authenticate": challenge})
        try:
            msg = self._read_json(MAX_JSON_BODY, None)
        except BadJson:
            return self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
        if msg is NOT_READ:
            return
        if not isinstance(msg, dict):
            return self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Send one JSON-RPC message per request"}})
        reply = mcp_server.handle(msg, mcp_http.fetch_for(access))
        if reply is None:
            return self._send(202, b"")
        return self._json(200, reply)

    def _mcp_origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin != "null" and urllib.parse.urlsplit(origin).netloc.lower() == (self.headers.get("Host") or "").strip().lower()

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128

    def __init__(self, *a, **k):
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        self._deadlines: dict = {}
        self._deadlines_lock = threading.Lock()
        self._closed = threading.Event()
        super().__init__(*a, **k)
        threading.Thread(target=self._hang_up_late, daemon=True).start()

    def set_deadline(self, sock, seconds: float | None) -> None:
        with self._deadlines_lock:
            if seconds is None:
                self._deadlines.pop(sock, None)
            else:
                self._deadlines[sock] = time.monotonic() + seconds

    def _hang_up_late(self) -> None:
        while not self._closed.wait(0.5):
            now = time.monotonic()
            with self._deadlines_lock:
                late = [sock for sock, t in self._deadlines.items() if t < now]
                for sock in late:
                    del self._deadlines[sock]
            for sock in late:
                with contextlib.suppress(OSError):
                    sock.shutdown(socket.SHUT_RDWR)

    def server_close(self):
        self._closed.set()
        super().server_close()

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], OSError):
            return
        monitoring.report()

    def process_request(self, request, client_address):
        if not self._slots.acquire(timeout=REQUEST_TIMEOUT):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    problems = secretbox.check_config()
    if problems:
        raise SystemExit("\n".join(problems))
    if not os.environ.get("WAYPOINT_SECRET_KEY"):
        monitoring.log(f"Note: set WAYPOINT_SECRET_KEY. Without it, the key that encrypts your saved mailbox access and travel IDs is "
              f"{secretbox.key_file_path()}: losing that file means reconnecting them, and whoever can read the data folder has "
              f"the key along with the database.", "warning")
    if oidc.enabled():
        problems = oidc.check_config()
        if problems:
            raise SystemExit("Sign-in (OIDC) isn't set up correctly:\n  - " + "\n  - ".join(problems))
    elif host not in ("127.0.0.1", "localhost", "::1") and os.environ.get("WAYPOINT_ALLOW_NO_AUTH") != "1":
        raise SystemExit("Waypoint is set to accept connections from other devices, so it needs sign-in.\n"
                         "Set OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, WAYPOINT_PUBLIC_URL and OIDC_ALLOWED_EMAILS\n"
                         "(or WAYPOINT_ALLOW_NO_AUTH=1 if a proxy in front of Waypoint already handles sign-in).")
    db.init()
    httpd = Server((host, port), Handler)
    jobs.start(httpd._closed)
    where = f"http://localhost:{port}" if host in ("127.0.0.1", "localhost") else f"port {port} on all network addresses"
    monitoring.log(f"Waypoint is running at {where}  (data: {db.describe()})"
                   f"{'  · sign-in via ' + oidc.config()['issuer'] if oidc.enabled() else ''}")
    with contextlib.suppress(KeyboardInterrupt):
        httpd.serve_forever()
