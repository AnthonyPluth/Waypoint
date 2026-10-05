"""What the server sends, header by header, for the endpoints with answers of their own (a backup's download and
uploads), the web app's files and a plain JSON answer; and who may reach them (sign-in, the X-Waypoint header, same-site
checks).

Pinned exactly, in order, so moving these endpoints around the server can't quietly change a security header, a cache
policy or a download's name. Only what differs from one request to the next is left out: the Date, a page's script
nonce, a backup's size and today's date in its name."""
import gzip
import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from unittest import mock

from waypoint.storage import backup, db
from waypoint import oidc, server
from waypoint.storage import settings_keys as sk
from waypoint.server import common
from tests.shared import freeze_today, own_database
from tests.test_web_app import built_app, serving

PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; frame-src 'none'; "
       "worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
PAGE_CSP = CSP.replace("script-src 'self'", "script-src 'nonce-N' 'strict-dynamic' 'self'")


def security(csp: str = CSP, resource: str = "same-origin") -> list[tuple[str, str]]:
    """The headers every answer carries, after its own."""
    return [("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", csp), ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "no-referrer"), ("Cross-Origin-Opener-Policy", "same-origin-allow-popups"),
            ("Cross-Origin-Resource-Policy", resource), ("Permissions-Policy", PERMISSIONS)]


def json_answer(length: int | str, *extra: tuple[str, str]) -> list[tuple[str, str]]:
    return [("Server", "Waypoint "), ("Content-Type", "application/json"), *extra, ("Content-Length", str(length)),
            ("Cache-Control", "no-store"), *security()]


class Pinned(unittest.TestCase):
    maxDiff = None
    @classmethod
    def setUpClass(cls):
        own_database(cls)
        for k in ("WAYPOINT_PUBLIC_URL", "OIDC_ISSUER"):
            os.environ.pop(k, None)
        cls.static_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.static_dir.cleanup)
        cls.static = cls.static_dir.name
        built_app(cls.static)
        with open(os.path.join(cls.static, "sw.js"), "wb") as f:
            f.write(b"// service worker " + b"x" * 2000)
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def send(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        """(status, the headers in order without Date, body). A page's nonce reads 'nonce-N'."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            with serving(self.static):
                conn.request(method, path, body=body, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
                resp = conn.getresponse()
                data = resp.read()
            heads = [(k, re.sub(r"'nonce-[^']+'", "'nonce-N'", v)) for k, v in resp.getheaders() if k != "Date"]
            return resp.status, heads, data
        finally:
            conn.close()

    def api(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        return self.send(method, path, body, {"X-Waypoint": "1", **(headers or {})})

    def assertJson(self, got, status: int, reply: dict, *extra: tuple[str, str]):
        code, heads, data = got
        self.assertEqual((code, json.loads(data)), (status, reply))
        self.assertEqual(heads, json_answer(len(data), *extra))


    def test_a_json_answer(self):
        code, heads, data = self.send("GET", "/api/state")
        self.assertEqual((code, json.loads(data)["user"]), (200, {"name": None, "email": None, "local": True}))
        self.assertEqual(heads, json_answer(len(data)))
        self.assertJson(self.send("GET", "/api/nothing-here"), 404, {"error": "Not found"})
        self.assertJson(self.api("POST", "/api/nothing-here", b"{}"), 404, {"error": "Not found"})

    def test_a_backup_download(self):
        today = freeze_today(self)      # the file is named after today
        code, heads, data = self.send("GET", "/api/backup")
        self.assertEqual(code, 200)
        self.assertIn("users", json.loads(gzip.decompress(data))["tables"])
        self.assertEqual(heads, [("Server", "Waypoint "), ("Content-Type", "application/gzip"),
                                 ("Content-Disposition", f'attachment; filename="waypoint-backup-{today.isoformat()}.json.gz"'),
                                 ("Content-Length", str(len(data))), ("Cache-Control", "no-store"), *security()])
        self.assertTrue(self.last_backup())
        with db.session() as conn:
            db.set_setting(conn, sk.LAST_BACKUP, None)
        code, heads, data = self.send("HEAD", "/api/backup")
        self.assertEqual((code, data), (200, b""))
        self.assertIsNone(self.last_backup(wait=0.5))
        with db.session() as conn:
            self.assertIsNone(db.get_setting(conn, sk.LAST_BACKUP))

    @staticmethod
    def last_backup(wait: float = 5.0) -> str | None:
        """When the last backup was downloaded, once the server has noted it (just after sending it), or None after
        `wait` seconds."""
        end = time.monotonic() + wait
        while True:
            with db.session() as conn:
                when = db.get_setting(conn, sk.LAST_BACKUP)
            if when or time.monotonic() > end:
                return when
            time.sleep(0.05)

    def test_backup_inspect_and_restore_uploads(self):
        for path in ("/api/backup/inspect", "/api/restore"):
            with self.subTest(path=path):
                self.assertJson(self.api("POST", path), 400, {"error": "Choose a backup file (up to 200 MB)."})
                code, _h, data = self.api("POST", path, b"not a backup")
                self.assertEqual(code, 400)
                self.assertIn("error", json.loads(data))
                code, heads, data = self.api("POST", path, headers={"Content-Length": str(server.MAX_RESTORE_BODY + 1)})
                self.assertEqual((code, json.loads(data)), (413, {"error": "That request is too large."}))
                self.assertEqual(heads, json_answer(len(data)))
                code, heads, data = self.api("POST", path, headers={"Content-Length": "lots"})
                self.assertEqual((code, json.loads(data)), (400, {"error": "Bad request."}))
        with db.session() as conn:
            raw = backup.dump(conn)
        code, heads, data = self.api("POST", "/api/backup/inspect", raw)
        reply = json.loads(data)
        self.assertEqual((code, reply["database"]), (200, "postgres" if db.using_postgres() else "sqlite"))
        self.assertIn("current", reply)
        self.assertEqual(heads, json_answer(len(data)))
        with mock.patch.object(backup, "restore_all", side_effect=backup.Busy("Something else is saving right now.")):
            self.assertJson(self.api("POST", "/api/restore", raw), 409, {"error": "Something else is saving right now."})
        with mock.patch.object(backup, "restore_all", side_effect=OSError(28, "No space left on device")):
            self.assertJson(self.api("POST", "/api/restore", raw), 500, {
                "error": "Couldn’t save a copy of what’s here first (No space left on device), so nothing was restored."})
        done = {"counts": {"users": 3}, "safety_copy": "copy.json.gz", "unreadable_secrets": []}
        with mock.patch.object(backup, "restore_all", return_value=done):
            code, heads, data = self.api("POST", "/api/restore", raw)
        reply = json.loads(data)
        self.assertEqual((code, reply["ok"], reply["counts"], reply["safety_copy"]), (200, True, {"users": 3}, "copy.json.gz"))
        self.assertEqual(list(reply), ["ok", "created", "source", "counts", "safety_copy", "unreadable_secrets"])
        self.assertEqual(heads, json_answer(len(data)))

    def test_changes_need_the_app_header_and_this_site(self):
        for method, path in (("POST", "/api/restore"), ("POST", "/api/backup/inspect"), ("POST", "/api/nothing-here")):
            with self.subTest(path=path):
                code, heads, data = self.send(method, path, b"{}")
                self.assertEqual((code, json.loads(data)), (403, {"error": server.handler.NO_APP_HEADER}))
                self.assertEqual(heads, json_answer(len(data)))
                code, heads, data = self.api(method, path, b"{}", {"Origin": "https://evil.example"})
                self.assertEqual((code, json.loads(data)), (403, {"error": server.handler.NOT_SAME_SITE}))
                self.assertEqual(self.api(method, path, b"{}", {"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_json_bodies(self):
        code, heads, data = self.api("POST", "/api/nothing-here", b"[1, 2]")
        self.assertEqual((code, json.loads(data)), (400, {"error": "Bad JSON"}))
        self.assertEqual(heads, json_answer(len(data)))
        self.assertJson(self.api("POST", "/api/nothing-here", b"{nope"), 400, {"error": "Bad JSON"})
        self.assertJson(self.api("POST", "/api/nothing-here", b"\xff\xfe"), 400, {"error": "Bad JSON"})
        self.assertJson(self.api("POST", "/api/nothing-here", headers={"Content-Length": str(server.MAX_JSON_BODY + 1)}),
                        413, {"error": "That request is too large."})

    def test_json_nested_deeper_than_python_reads_is_a_400(self):
        deep = b"[" * 200_000 + b"]" * 200_000
        nested = b'{"a": ' + deep + b"}"
        self.assertJson(self.api("POST", "/api/nothing-here", nested), 400, {"error": "Bad JSON"})

    def test_the_web_apps_page_and_files(self):
        code, heads, data = self.send("GET", "/")
        self.assertEqual(code, 200)
        self.assertEqual(heads, [("Server", "Waypoint "), ("Content-Type", "text/html"), ("Content-Length", str(len(data))),
                                 ("Cache-Control", "no-store"), ("Vary", "Accept-Encoding"), *security(PAGE_CSP)])
        code, heads, data = self.send("GET", "/assets/index-abc.js")
        etag = dict(heads)["ETag"]
        self.assertEqual(heads, [("Server", "Waypoint "), ("Content-Type", "text/javascript"), ("Content-Length", "14"),
                                 ("Cache-Control", "public, max-age=31536000, immutable"), ("Vary", "Accept-Encoding"),
                                 ("ETag", etag), *security()])
        code, heads, data = self.send("GET", "/sw.js", headers={"Accept-Encoding": "gzip"})
        sw_etag = dict(heads)["ETag"]
        self.assertEqual(heads, [("Server", "Waypoint "), ("Content-Type", "text/javascript"), ("Content-Length", str(len(data))),
                                 ("Cache-Control", "no-cache"), ("Vary", "Accept-Encoding"), ("ETag", sw_etag),
                                 ("Content-Encoding", "gzip"), *security()])
        code, heads, data = self.send("GET", "/sw.js", headers={"If-None-Match": sw_etag})
        self.assertEqual((code, data), (304, b""))
        self.assertEqual(heads, [("Server", "Waypoint "), ("ETag", sw_etag), ("Cache-Control", "no-cache"), *security()])
        code, heads, data = self.send("GET", "/next/budget")
        self.assertEqual((code, heads), (302, [("Server", "Waypoint "), ("Location", "/"), ("Content-Length", "0"),
                                               ("Cache-Control", "no-store"), *security()]))
        self.assertEqual(self.send("POST", "/", b"", {"X-Waypoint": "1"})[:2], (405, [
            ("Server", "Waypoint "), ("Content-Type", "text/plain"), ("Content-Length", "0"), ("Cache-Control", "no-store"),
            *security()]))

    def test_health_and_unknown_hosts(self):
        self.assertEqual(self.send("GET", "/healthz"), (200, [
            ("Server", "Waypoint "), ("Content-Type", "text/plain"), ("Content-Length", "2"), ("Cache-Control", "no-store"),
            *security()], b"ok"))
        code, heads, _ = self.send("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(code, 403)
        self.assertEqual(heads[1], ("Content-Type", "text/plain"))


USER = {"sub": "pin-sub", "email": "pin@example.com", "name": "Pin"}


class SignInTests(unittest.TestCase):
    """With sign-in on: who may reach each endpoint."""

    @classmethod
    def setUpClass(cls):
        own_database(cls, OIDC_ISSUER="https://id.example", OIDC_CLIENT_ID="waypoint", WAYPOINT_PUBLIC_URL="https://waypoint.example",
                     OIDC_ALLOWED_EMAILS="pin@example.com")
        session_user = mock.patch.object(oidc, "session_user", side_effect=lambda _c, token: USER if token == "good" else None)
        renew = mock.patch.object(oidc, "renew_session", return_value=None)
        hosts = mock.patch.object(common, "EXTRA_HOSTS", {"waypoint.example"})
        for p in (session_user, renew, hosts):
            p.start()
            cls.addClassCleanup(p.stop)
        cls.httpd = server.Server(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.port = cls.httpd.server_port

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    send = Pinned.send
    static = None

    def setUp(self):
        self.static_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.static_dir.cleanup)
        self.static = self.static_dir.name
        built_app(self.static)

    def test_signed_out(self):
        hsts = ("Strict-Transport-Security", "max-age=31536000")
        for method, path in (("GET", "/api/backup"), ("POST", "/api/backup/inspect"), ("POST", "/api/restore"),
                             ("GET", "/api/state"), ("GET", "/api/nothing-here"), ("POST", "/api/nothing-here")):
            with self.subTest(path=path):
                code, heads, data = self.send(method, path, b"{}" if method == "POST" else None, {"X-Waypoint": "1"})
                self.assertEqual((code, json.loads(data)), (401, {"error": "You've been signed out.", "login": "/auth/login"}))
                self.assertEqual(heads, [*json_answer(len(data)), hsts])
        code, heads, _ = self.send("GET", "/trips?month=2026-09")
        self.assertEqual((code, heads), (302, [("Server", "Waypoint "), ("Location", "/auth/login?next=%2Ftrips%3Fmonth%3D2026-09"),
                                               ("Content-Length", "0"), ("Cache-Control", "no-store"), *security(), hsts]))
        self.assertEqual(self.send("GET", "/logo.svg")[0], 200)

    def test_signed_in(self):
        signed_in = {"Cookie": "waypoint_session=good", "X-Waypoint": "1"}
        self.assertEqual(self.send("GET", "/api/state", headers=signed_in)[0], 200)
        self.assertEqual(self.send("GET", "/api/backup", headers=signed_in)[0], 200)
        code, heads, _ = self.send("GET", "/", headers=signed_in)
        self.assertEqual(code, 200)
        self.assertEqual(heads[-1], ("Strict-Transport-Security", "max-age=31536000"))

if __name__ == "__main__":
    unittest.main()
