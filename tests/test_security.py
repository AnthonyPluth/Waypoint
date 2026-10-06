import gzip
import json
import os
import re
import tempfile
import unittest
from unittest import mock

from sqlalchemy import insert, select

from waypoint.storage import backup, db, secretbox
from waypoint.storage import settings_keys as sk
from waypoint import oidc, server
from waypoint.server.api import state
from waypoint.storage.models import Setting
from tests.shared import ServerCase, add_database, database_path, fetch, own_database
from tests.test_web_app import built_app, serving


class SafeNextTests(unittest.TestCase):
    def test_only_paths_on_this_site(self):
        for good in ("/", "/#budget", "/plaid/oauth?oauth_state_id=abc"):
            self.assertEqual(oidc.safe_next(good), good)
        for bad in ("//evil.com", "/\\evil.com", "/\\\\evil.com", "https://evil.com", "evil.com", "/\tx", "/a\r\nSet-Cookie: x", "", None):
            self.assertEqual(oidc.safe_next(bad), "/", bad)


class PublicUrlTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(os.environ)
        os.environ.update({"OIDC_ISSUER": "https://auth.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "me@example.com"})

    def tearDown(self):
        os.environ.clear(); os.environ.update(self.saved)

    def problems(self, url, **env):
        os.environ["WAYPOINT_PUBLIC_URL"] = url
        os.environ.update(env)
        return oidc.check_config()

    def test_https_required_on_the_internet(self):
        self.assertTrue(any("https://" in p for p in self.problems("http://waypoint.example.com")))
        self.assertEqual(self.problems("https://waypoint.example.com"), [])
        for home in ("http://192.168.1.20:8765", "http://nas:8765", "http://waypoint.local", "http://localhost:8765", "http://box.tail12.ts.net"):
            self.assertEqual(self.problems(home), [], home)
        self.assertEqual(self.problems("http://waypoint.example.com", WAYPOINT_ALLOW_INSECURE_HTTP="1"), [])


class SecretsTests(unittest.TestCase):
    def setUp(self):
        self.path = own_database(self)
        self.dir = os.path.dirname(self.path)
        self.c = db.connect(self.path)
        self.addCleanup(self.c.close)

    def raw(self, key):
        return self.c.execute(select(Setting.value).where(Setting.key == key)).fetchone()[0]

    def test_secret_settings_are_encrypted(self):
        db.set_setting(self.c, sk.VAPID_PRIVATE_KEY, "made-up-key-123")
        db.set_setting(self.c, sk.LAST_BACKUP, "2026-09-01T07:00:00")
        self.assertTrue(self.raw(sk.VAPID_PRIVATE_KEY).startswith("enc:v1:"))
        self.assertNotIn("made-up-key-123", self.raw(sk.VAPID_PRIVATE_KEY))
        self.assertEqual(db.get_setting(self.c, sk.VAPID_PRIVATE_KEY), "made-up-key-123")
        self.assertEqual(self.raw(sk.LAST_BACKUP), "2026-09-01T07:00:00")

    def test_plaintext_is_encrypted_at_start(self):
        self.c.execute(insert(Setting).values(key=sk.VAPID_PRIVATE_KEY, value="plain-secret"))
        self.assertEqual(secretbox.encrypt_stored(self.c), 1)
        self.assertTrue(self.raw(sk.VAPID_PRIVATE_KEY).startswith("enc:v1:"))
        self.assertEqual(secretbox.decrypt(self.raw(sk.VAPID_PRIVATE_KEY)), "plain-secret")
        self.assertEqual(secretbox.encrypt_stored(self.c), 0)

    def test_backups_carry_secrets_encrypted(self):
        self.c.execute(insert(Setting).values(key=sk.VAPID_PRIVATE_KEY, value="vapid-plain"))
        raw = backup.dump(self.c)
        self.assertNotIn(b"vapid-plain", gzip.decompress(raw))
        data = backup.load(raw)
        settings = {r[0]: r[1] for r in data["tables"]["settings"]["rows"]}
        self.assertTrue(settings[sk.VAPID_PRIVATE_KEY].startswith("enc:v1:"))
        other = add_database(self, os.path.join(self.dir, "o.db"))
        with db.session(other) as c2:
            backup.restore(c2, data)
            self.assertEqual(backup.unreadable_secrets(c2), [])
        with db.session(other) as c2:
            self.assertTrue(c2.execute(select(Setting.value)
                                       .where(Setting.key == sk.VAPID_PRIVATE_KEY)).fetchone()[0].startswith("enc:v1:"))
            self.assertEqual(db.get_setting(c2, sk.VAPID_PRIVATE_KEY), "vapid-plain")
        elsewhere = database_path(self, "e.db")
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": "another-machine-key-abcdefghijklmnopqrstuv"}):
            db.init(elsewhere)
            with db.session(elsewhere) as c3:
                backup.restore(c3, data)
                self.assertEqual(backup.unreadable_secrets(c3), [sk.VAPID_PRIVATE_KEY])
                self.assertIsNone(db.get_setting(c3, sk.VAPID_PRIVATE_KEY))

    def test_key_rotation_and_a_wrong_key(self):
        db.set_setting(self.c, sk.VAPID_PRIVATE_KEY, "k-1")
        old = os.environ["WAYPOINT_SECRET_KEY"]
        new = "a-brand-new-key-abcdefghijklmnopqrstuvwxyz"
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": new, "WAYPOINT_SECRET_KEY_OLD": old}):
            self.assertEqual(db.get_setting(self.c, sk.VAPID_PRIVATE_KEY), "k-1")
            secretbox.encrypt_stored(self.c)
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": new}):
            self.assertEqual(db.get_setting(self.c, sk.VAPID_PRIVATE_KEY), "k-1")
        self.assertIsNone(db.get_setting(self.c, sk.VAPID_PRIVATE_KEY))

    def test_short_keys_are_refused(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": "short"}):
            self.assertTrue(secretbox.check_config())


class HttpTests(ServerCase):
    server_class = server.Server

    def open(self, path, method="GET", body=None, headers=None):
        return fetch(self.base, method, path, body, headers, timeout=10)

    def api(self, method, path, body=None, headers=None):
        h = {"X-Waypoint": "1", "Content-Type": "application/json", **(headers or {})}
        code, _, raw = self.open(path, method, json.dumps(body).encode() if body is not None else None, h)
        return code, json.loads(raw or b"{}")

    def test_security_headers_and_script_nonce(self):
        with tempfile.TemporaryDirectory() as static, serving(static):
            built_app(static)
            code, h, page = self.open("/")
            second = self.open("/")[1]["Content-Security-Policy"]
        self.assertEqual(code, 200)
        csp = h["Content-Security-Policy"]
        nonce = re.search(r"'nonce-([^']+)'", csp).group(1)
        self.assertIn(f'<script nonce="{nonce}" type="module"'.encode(), page)
        for d in ("frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'"):
            self.assertIn(d, csp)
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertEqual(h["Referrer-Policy"], "no-referrer")
        self.assertEqual(h["Server"].strip(), "Waypoint")
        self.assertNotEqual(nonce, re.search(r"'nonce-([^']+)'", second).group(1))
        self.assertIn("frame-ancestors 'none'", self.open("/api/state")[1]["Content-Security-Policy"])

    def test_errors_dont_show_internals(self):
        code, _, raw = self.open("/api/backup/inspect", "POST", b"", {"X-Waypoint": "1"})
        self.assertEqual((code, json.loads(raw)["error"]), (400, "Choose a backup file (up to 200 MB)."))
        with mock.patch.object(state, "with_offset", side_effect=RuntimeError("secret detail")):
            code, body = self.api("GET", "/api/state")
        self.assertEqual(code, 500)
        self.assertNotIn("secret detail", body["error"])
        self.assertIn("reference", body["error"])

    def test_request_limits(self):
        code, _ = self.api("POST", "/api/nothing", headers={"Content-Length": str(server.MAX_JSON_BODY + 1)})
        self.assertEqual(code, 413)
        code, _, _ = self.open("/api/nothing", "POST", b"[1,2]", {"X-Waypoint": "1", "Content-Type": "application/json"})
        self.assertEqual(code, 400)

    def test_cross_site_requests_are_refused(self):
        for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.api("POST", "/api/nothing", {}, headers)[0], 403)
        self.assertEqual(self.api("POST", "/api/nothing", {}, {"Origin": self.base})[0], 404)
        self.assertEqual(self.api("POST", "/api/nothing", {}, {"X-Waypoint": "0"})[0], 403)

    def test_static_files(self):
        code, h, body = self.open("/../server/handler.py")
        self.assertNotIn(b"def serve", body)
        code, h, body = self.open("/sw.js", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(h["Content-Encoding"], "gzip")
        self.assertIn(b"waypoint-shell", gzip.decompress(body))
        self.assertEqual(self.open("/sw.js", headers={"If-None-Match": h["ETag"]})[0], 304)
        code, _, body = self.open("/healthz", "HEAD")
        self.assertEqual((code, body), (200, b""))


if __name__ == "__main__":
    unittest.main()
