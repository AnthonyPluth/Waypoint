"""Fixes from the September 2026 review of the server: sign-in, slow clients, restore, and smaller hardening (limits,
backup sizes, secret keys)."""
import contextlib
import gzip
import json
import os
import socket
import time
import unittest
from datetime import datetime
from unittest import mock


from cryptography.fernet import Fernet

from sqlalchemy import insert, select

from waypoint.storage import backup, db, secretbox
from waypoint.storage import settings_keys as sk
from waypoint import oidc, server
from waypoint.storage.models import AuthSession, Setting
from tests.shared import ServerCase, fetch, own_database, scratch_dir

ENV = ("OIDC_ALLOWED_EMAILS", "OIDC_ALLOWED_GROUPS", "OIDC_ALLOW_ANY_USER", "OIDC_TRUST_UNVERIFIED_EMAIL")


class SignInTests(unittest.TestCase):
    def setUp(self):
        own_database(self)   # its sessions are its own, and the environment is put back afterwards
        for k in ENV:
            os.environ.pop(k, None)
        os.environ["OIDC_ALLOWED_EMAILS"] = "me@example.com"

    def test_email_must_be_verified(self):
        ok = {"sub": "u1", "email": "me@example.com"}
        self.assertEqual(oidc.authorize({**ok, "email_verified": True})["email"], "me@example.com")
        self.assertEqual(oidc.authorize({**ok, "email_verified": "true"})["email"], "me@example.com")
        for claim in ({}, {"email_verified": False}, {"email_verified": "false"}, {"email_verified": None}):
            with self.assertRaisesRegex(oidc.OIDCError, "verified"):
                oidc.authorize({**ok, **claim})

    def test_unverified_email_can_be_trusted_on_purpose(self):
        os.environ["OIDC_TRUST_UNVERIFIED_EMAIL"] = "1"
        self.assertEqual(oidc.authorize({"sub": "u1", "email": "me@example.com"})["email"], "me@example.com")

    def test_groups_dont_need_a_verified_email(self):
        os.environ["OIDC_ALLOWED_GROUPS"] = "finance"
        self.assertEqual(oidc.authorize({"sub": "u1", "email": "me@example.com", "groups": ["finance"]})["sub"], "u1")
        with self.assertRaises(oidc.OIDCError):
            oidc.authorize({"sub": "u2", "email": "other@example.com", "groups": ["sales"], "email_verified": True})

    def test_removed_email_ends_sessions(self):
        with db.session() as c:
            c.execute(insert(AuthSession).values(token_hash=oidc._hash("tok"), sub="u1", email="me@example.com",
                                                 name="Me", created=time.time(), expires=time.time() + 3600))
            self.assertEqual(oidc.session_user(c, "tok")["email"], "me@example.com")
        os.environ["OIDC_ALLOWED_EMAILS"] = "someone@example.com"
        with db.session() as c:
            self.assertIsNone(oidc.session_user(c, "tok"))
            self.assertIsNone(c.execute(select(AuthSession.token_hash)).fetchone())   # and it's gone for good
        os.environ["OIDC_ALLOWED_EMAILS"] = "me@example.com"
        with db.session() as c:
            self.assertIsNone(oidc.session_user(c, "tok"))


class ServerTests(ServerCase):
    server_class = server.Server

    def open(self, path, method="GET", body=None, headers=None):
        return fetch(self.base, method, path, body, headers, timeout=10, follow=False)

    def test_trickled_headers_are_hung_up_on(self):
        with mock.patch.object(server.handler, "HEADER_DEADLINE", 1):
            s = socket.create_connection(("127.0.0.1", self.httpd.server_port), timeout=10)
            s.setblocking(False)
            started, closed = time.monotonic(), False
            try:
                s.sendall(b"GET /healthz HTTP/1.1\r\n")
                while time.monotonic() - started < 5 and not closed:
                    s.send(b"X")   # a header byte every 0.1s: each read is quick, the headers never finish
                    time.sleep(0.1)
                    with contextlib.suppress(BlockingIOError):
                        closed = s.recv(1024) == b""
            except OSError:
                closed = True
            elapsed = time.monotonic() - started
            s.close()
        self.assertTrue(closed)
        self.assertLess(elapsed, 3.5)
        self.assertEqual(self.open("/healthz")[0], 200)   # everyone else is served as usual

    def test_a_restore_that_cant_start_yet_is_refused(self):
        # A restore replaces the whole database (and on Postgres restarts its ids), so not the one the class shares.
        own_database(self)
        with db.session() as c:
            raw = backup.dump(c)
        headers = {"X-Waypoint": "1", "Content-Type": "application/octet-stream"}
        with mock.patch.object(backup, "restore_all", side_effect=backup.Busy("Something else is saving right now.")):
            code, _, body = self.open("/api/restore", "POST", raw, headers)
        self.assertEqual(code, 409)
        self.assertEqual(json.loads(body)["error"], "Something else is saving right now.")
        self.assertEqual(self.open("/api/restore", "POST", raw, headers)[0], 200)

    def test_a_header_is_never_split(self):
        # Any header with a line break in it is refused: the request fails cleanly (500), and nothing of the half-built
        # answer (not the 200, not the injected cookie) goes out.
        def bad_header(handler, _method):
            handler._send(200, b"ok", "text/plain", extra={"X-Next": "/x\r\nSet-Cookie: stolen=1"})
        with mock.patch.object(server.Handler, "_route", bad_header), mock.patch("waypoint.monitoring.report"):
            code, h, body = self.open("/api/anything")
        self.assertEqual(code, 500)
        self.assertIsNone(h["Set-Cookie"])
        self.assertIsNone(h["X-Next"])
        self.assertIn("reference", json.loads(body)["error"])
        # The same for a cookie queued for whatever the request answers: the 500 goes out without it.
        def bad_cookie(handler, _method):
            handler._set_cookies.append("waypoint_session=x\r\nX-Injected: 1")
            handler._send(200, b"ok", "text/plain")
        with mock.patch.object(server.Handler, "_route", bad_cookie), mock.patch("waypoint.monitoring.report"):
            code, h, body = self.open("/api/anything")
        self.assertEqual((code, h["Set-Cookie"], h["X-Injected"]), (500, None, None))
        self.assertIn("reference", json.loads(body)["error"])
        # A redirect somewhere with a line break in it goes home instead.
        def bad_redirect(handler, _method):
            handler._redirect("/x\r\nSet-Cookie: stolen=1")
        with mock.patch.object(server.Handler, "_route", bad_redirect):
            code, h, _ = self.open("/anything")
        self.assertEqual((code, h["Location"], h["Set-Cookie"]), (302, "/", None))


class LimitsTests(unittest.TestCase):
    def test_numbers_have_a_ceiling(self):
        self.assertEqual(db.number("1e12"), 1e12)
        for huge in ("1e13", "-1e300", 10 ** 15):
            with self.assertRaises(ValueError):
                db.number(huge)

    def test_the_answer_is_json(self):
        # An overflowed sum (inf) would otherwise go out as `Infinity`, which no browser reads.
        from waypoint.server import handler
        h = handler.Handler.__new__(handler.Handler)
        sent = []
        h._send = lambda status, body, *a, **k: sent.append((status, body))
        with self.assertRaises(ValueError):
            h._json(200, {"total": float("inf")})
        self.assertEqual(sent, [])


class BackupSizeTests(unittest.TestCase):
    def test_a_gzip_bomb_is_refused(self):
        bomb = gzip.compress(b"0" * (2 * 1024 * 1024))
        with mock.patch.object(backup, "MAX_UNPACKED", 1024 * 1024):
            with self.assertRaisesRegex(ValueError, "too large"):
                backup.load(bomb)
        with self.assertRaisesRegex(ValueError, "isn't a Waypoint backup"):
            backup.load(gzip.compress(b"{not json"))
        with self.assertRaisesRegex(ValueError, "isn't a Waypoint backup"):
            backup.load(b"\x1f\x8b" + b"garbage")

    def test_copies_made_the_same_second_are_all_kept(self):
        own_database(self)
        directory = scratch_dir(self)
        with db.session() as c, mock.patch.object(backup, "datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 30, 7, 2)
            made = [backup.save_copy(c, "waypoint-before-restore", directory) for _ in range(3)]
        self.assertEqual([os.path.basename(p) for p in made],
                         ["waypoint-before-restore-2026-09-30-070200.json.gz", "waypoint-before-restore-2026-09-30-070200-2.json.gz",
                          "waypoint-before-restore-2026-09-30-070200-3.json.gz"])
        for p in made:
            with open(p, "rb") as f:
                backup.load(f.read())


class SecretKeyTests(unittest.TestCase):
    def setUp(self):
        self.path = own_database(self, WAYPOINT_SECRET_KEY="correct horse battery staple, but longer than 32")
        secretbox._cache.clear()
        self.addCleanup(secretbox._cache.clear)
        self.c = db.connect(self.path)
        self.addCleanup(self.c.close)       # (cleanups run last first: the connection closes before the database goes)

    def test_passphrase_is_stretched_and_old_keys_still_open(self):
        key = os.environ["WAYPOINT_SECRET_KEY"]
        self.assertNotEqual(secretbox._from_passphrase(key), secretbox._from_passphrase_v1(key))
        legacy = secretbox.PREFIX + Fernet(secretbox._from_passphrase_v1(key)).encrypt(b"sk-old").decode()
        self.c.execute(insert(Setting).values(key=sk.VAPID_PRIVATE_KEY, value=legacy))
        self.assertEqual(db.get_setting(self.c, sk.VAPID_PRIVATE_KEY), "sk-old")   # saved by an earlier version
        self.assertEqual(secretbox.encrypt_stored(self.c), 1)                    # moved to the stretched key
        stored = self.c.execute(select(Setting.value).where(Setting.key == sk.VAPID_PRIVATE_KEY)).fetchone()[0]
        Fernet(secretbox._from_passphrase(key)).decrypt(stored[len(secretbox.PREFIX):].encode())
        self.assertEqual(db.get_setting(self.c, sk.VAPID_PRIVATE_KEY), "sk-old")


if __name__ == "__main__":
    unittest.main()
