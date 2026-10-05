"""Connecting a Gmail, read-only (waypoint/providers/gmail.py, waypoint/server/api/mailboxes.py), against a fake Google:
the consent screen's address, the code-for-token trade (with PKCE), the profile, refreshing, revoking, the "Reconnect"
state, and a connection ending with the person who made it. Google's servers are never called."""
import hashlib
import json
import os
import secrets
import threading
import time
import unittest
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from sqlalchemy import insert, select, update

from tests.privacy import no_leaks
from tests.shared import DbCase, ServerCase, fetch
from waypoint import oidc
from waypoint.providers import gmail
from waypoint.storage import db, secretbox
from waypoint.storage.models import AuthSession, Mailbox, MailboxPending, User

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CLIENT_ID, CLIENT_SECRET = "google-client-1.example", "google-secret-1"


def b64(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class FakeGoogle(BaseHTTPRequestHandler):
    """Google's OAuth token and revoke endpoints and Gmail's profile, with what a test needs to steer and to see:
    `grants` (a code -> what it trades for), `live` (refresh tokens Google honours), `access` (access tokens it honours),
    `revoked`, `calls` and the failures to give (`refresh_fails`, `revoke_status`)."""

    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        g = self.server
        form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        g.calls.append((self.path, form))
        if self.path == "/revoke":
            if g.revoke_status != 200:
                return self.reply({"error": "backend_error"}, g.revoke_status)
            if form.get("token") not in g.live:
                return self.reply({"error": "invalid_token"}, 400)
            g.live.discard(form["token"])
            g.revoked.append(form["token"])
            return self.reply({})
        if self.path != "/token" or (form.get("client_id"), form.get("client_secret")) != (CLIENT_ID, CLIENT_SECRET):
            return self.reply({"error": "invalid_client"}, 401)
        if form.get("grant_type") == "refresh_token":
            if g.refresh_fails == "unavailable":
                return self.reply({"error": "backend_error"}, 503)
            if g.refresh_fails == "revoked" or form.get("refresh_token") not in g.live:
                return self.reply({"error": "invalid_grant", "error_description": "Token has been expired or revoked."}, 400)
            return self.reply({"access_token": g.new_access(form["refresh_token"]), "expires_in": 3599, "scope": SCOPE,
                               "token_type": "Bearer"})
        grant = g.grants.pop(form.get("code"), None)
        if not grant or form.get("redirect_uri") != grant["redirect_uri"]:
            return self.reply({"error": "invalid_grant"}, 400)
        if b64(hashlib.sha256(form.get("code_verifier", "").encode()).digest()) != grant["challenge"]:
            return self.reply({"error": "invalid_grant", "error_description": "Bad Request"}, 400)
        out = {"access_token": g.new_access(grant["refresh"]), "expires_in": 3599, "scope": grant["scope"], "token_type": "Bearer"}
        if grant["refresh"]:
            out["refresh_token"] = grant["refresh"]
            g.live.add(grant["refresh"])
        self.reply(out)

    def do_GET(self):
        g = self.server
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
        if self.path != "/gmail/v1/users/me/profile" or token not in g.owners:
            return self.reply({"error": "unauthorized"}, 401)
        self.reply({"emailAddress": g.owners[token], "messagesTotal": 10, "historyId": "5550001"})


class Google(HTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), FakeGoogle)
        self.grants, self.live, self.revoked, self.calls, self.owners, self.emails = {}, set(), [], [], {}, {}
        self.refresh_fails, self.revoke_status = None, 200
        self._n = 0

    def new_access(self, refresh):
        self._n += 1
        token = f"fake-access-{self._n}-{secrets.token_hex(4)}"
        self.owners[token] = self.emails.get(refresh, "unknown@gmail.example")
        return token

    def hosts(self) -> gmail.Hosts:
        base = f"http://127.0.0.1:{self.server_port}"
        return gmail.Hosts(auth=base + "/auth", token=base + "/token", revoke=base + "/revoke",
                           api=base + "/gmail/v1/users/me", allow_http=True)


class GoogleCase(ServerCase):
    """A Waypoint with sign-in on and a Google client set up, two members (Ana and Ben) with sessions, and a fake Google."""
    env = {"OIDC_ISSUER": "https://idp.example.com", "OIDC_CLIENT_ID": "waypoint", "OIDC_ALLOWED_EMAILS": "ana@example.com,ben@example.com",
           "GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        os.environ["WAYPOINT_PUBLIC_URL"] = cls.base
        cls.google = Google()
        threading.Thread(target=cls.google.serve_forever, daemon=True).start()
        cls.addClassCleanup(cls.google.server_close)
        cls.addClassCleanup(cls.google.shutdown)   # (runs first)
        patch = mock.patch.object(gmail, "HOSTS", cls.google.hosts())
        patch.start()
        cls.addClassCleanup(patch.stop)

    def setUp(self):
        g = self.google
        g.grants.clear(); g.live.clear(); g.revoked.clear(); g.calls.clear(); g.owners.clear(); g.emails.clear()
        g.refresh_fails, g.revoke_status = None, 200
        with db.session() as conn:
            for table in (Mailbox, MailboxPending, AuthSession, User):
                conn.execute(table.__table__.delete())
        self.who = {"ana": self.sign_in("sub-ana", "ana@example.com", "Ana"), "ben": self.sign_in("sub-ben", "ben@example.com", "Ben")}

    def sign_in(self, sub, email, name) -> dict:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with db.session() as conn:
            conn.execute(insert(AuthSession).values(token_hash=oidc._hash(token), sub=sub, email=email, name=name, created=now,
                                                    expires=now + 86400))
            oidc.remember_user(conn, sub, email, name, None, now)
        return {"Cookie": f"waypoint_session={token}"}

    def call(self, who, method, path, body=None):
        return self.req(method, path, body if method != "GET" else None, self.who[who])

    def connect(self, who="ana", address="ana@gmail.example", refresh="refresh-token-ana-1", scope=SCOPE, code=None, **grant):
        """Walk the whole flow: start, consent at (fake) Google, come back. Returns the callback's Location."""
        status, started = self.call(who, "POST", "/api/mailboxes/connect", {})
        self.assertEqual(status, 200, started)
        url = urllib.parse.urlsplit(started["url"])
        q = dict(urllib.parse.parse_qsl(url.query))
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", self.google.hosts().auth)
        code = code or "code-" + secrets.token_hex(6)
        self.google.emails[refresh] = address
        self.google.grants[code] = {"challenge": q["code_challenge"], "refresh": refresh, "scope": scope, "email": address,
                                    "redirect_uri": q["redirect_uri"], **grant}
        return self.come_back(who, {"code": code, "state": q["state"]})

    def come_back(self, who, params) -> str:
        status, headers, _ = fetch(self.base, "GET", "/api/mailboxes/callback?" + urllib.parse.urlencode(params), None,
                                   self.who[who], follow=False)
        self.assertEqual(status, 302)
        return headers["Location"]

    def mailboxes(self, who="ana") -> list[dict]:
        status, body = self.call(who, "GET", "/api/mailboxes")
        self.assertEqual(status, 200)
        return body["mailboxes"]

    def stored(self):
        with db.session() as conn:
            return db.rows(conn.execute(select(Mailbox).order_by(Mailbox.id)))


class ConnectTests(GoogleCase):
    def test_the_consent_screen_asks_for_read_only_access_with_pkce(self):
        _, started = self.call("ana", "POST", "/api/mailboxes/connect", {})
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started["url"]).query))
        self.assertEqual((q["scope"], q["access_type"], q["response_type"], q["code_challenge_method"], q["client_id"]),
                         (SCOPE, "offline", "code", "S256", CLIENT_ID))
        self.assertEqual(q["redirect_uri"], self.base + "/api/mailboxes/callback")
        self.assertIn("consent", q["prompt"])
        self.assertNotIn("include_granted_scopes", q)
        with db.session() as conn:   # the state is bound to Ana
            self.assertEqual(conn.execute(select(MailboxPending.owner_sub).where(MailboxPending.state == q["state"])).scalar(), "sub-ana")

    def test_connecting_keeps_the_token_encrypted_and_the_address(self):
        self.assertEqual(self.connect(refresh="canary-refresh-token"), "/?gmail=connected#settings")
        [row] = self.stored()
        self.assertEqual((row["owner_sub"], row["address"], row["status"], row["history_id"], row["last_error"]),
                         ("sub-ana", "ana@gmail.example", "connected", "5550001", None))
        self.assertTrue(secretbox.is_encrypted(row["token"]))
        self.assertNotIn("canary-refresh-token", row["token"])
        self.assertEqual(secretbox.decrypt(row["token"]), "canary-refresh-token")
        with db.session() as conn:   # the state was used up
            self.assertEqual(conn.execute(select(MailboxPending.state)).fetchall(), [])
        [m] = self.mailboxes()
        self.assertEqual((m["address"], m["status"], m["last_error"], m["last_scan"]), ("ana@gmail.example", "connected", None, None))
        self.assertNotIn("token", m)

    def test_each_member_sees_only_their_own(self):
        self.connect("ana", "ana@gmail.example", "refresh-ana")
        self.assertEqual(self.mailboxes("ben"), [])
        self.connect("ben", "ben@gmail.example", "refresh-ben")
        self.assertEqual([m["address"] for m in self.mailboxes("ana")], ["ana@gmail.example"])
        self.assertEqual([m["address"] for m in self.mailboxes("ben")], ["ben@gmail.example"])
        [anas] = self.mailboxes("ana")
        status, body = self.call("ben", "DELETE", f"/api/mailboxes/{anas['id']}")
        self.assertEqual((status, body["error"]), (404, "Not found"))   # as one that isn't there
        self.assertEqual(self.google.revoked, [])
        self.assertEqual(len(self.stored()), 2)

    def test_a_member_may_connect_several_and_connecting_one_again_repairs_it(self):
        self.connect("ana", "one@gmail.example", "refresh-one")
        self.connect("ana", "two@gmail.example", "refresh-two")
        self.assertEqual([m["address"] for m in self.mailboxes()], ["one@gmail.example", "two@gmail.example"])
        with db.session() as conn:   # a scan has got somewhere
            conn.execute(update(Mailbox).where(Mailbox.address == "one@gmail.example").values(history_id="777", status="reconnect",
                                                                                           last_error="Google no longer lets Waypoint read this mailbox."))
        self.connect("ana", "ONE@gmail.example", "refresh-one-again")   # the same address, however Google spells it
        rows = {r["address"]: r for r in self.stored()}
        self.assertEqual(sorted(rows), ["one@gmail.example", "two@gmail.example"])
        one = rows["one@gmail.example"]
        self.assertEqual((one["status"], one["last_error"], one["history_id"]), ("connected", None, "777"))
        self.assertEqual(secretbox.decrypt(one["token"]), "refresh-one-again")

    def test_a_forged_return_is_refused(self):
        _, started = self.call("ana", "POST", "/api/mailboxes/connect", {})
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started["url"]).query))["state"]
        self.google.grants["code-forged"] = {"challenge": "x", "refresh": "r", "scope": SCOPE, "email": "a@gmail.example", "redirect_uri": ""}
        for who, params in (("ana", {"code": "code-forged", "state": "made-up-state"}),   # a state this Waypoint never made
                            ("ben", {"code": "code-forged", "state": state}),             # another member's connection
                            ("ana", {"code": "code-forged"}),                             # no state at all
                            ("ana", {"state": state})):                                   # no code
            with self.subTest(who=who, params=sorted(params)):
                self.assertEqual(self.come_back(who, params), "/?gmail=refused#settings")
        self.assertEqual(self.stored(), [])
        self.assertEqual([c for c in self.google.calls if c[0] == "/token"], [])   # Google was never asked

    def test_a_connection_can_be_finished_once_and_not_late(self):
        self.connect("ana", "ana@gmail.example", "refresh-ana", code="code-once")
        _, started = self.call("ana", "POST", "/api/mailboxes/connect", {})
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started["url"]).query))["state"]
        self.google.grants["code-again"] = {"challenge": "x", "refresh": "r2", "scope": SCOPE, "email": "a@gmail.example", "redirect_uri": ""}
        with db.session() as conn:
            conn.execute(update(MailboxPending).values(created=time.time() - gmail.PENDING_TTL - 5))
        self.assertEqual(self.come_back("ana", {"code": "code-again", "state": state}), "/?gmail=refused#settings")
        self.assertEqual(self.come_back("ana", {"code": "code-again", "state": state}), "/?gmail=refused#settings")   # already used up

    def test_a_code_that_was_not_issued_for_this_pkce_challenge_is_refused_by_google(self):
        self.assertEqual(self.connect(challenge="not-the-challenge-for-this-verifier"), "/?gmail=failed#settings")
        self.assertEqual(self.stored(), [])

    def test_saying_no_at_google_connects_nothing(self):
        _, started = self.call("ana", "POST", "/api/mailboxes/connect", {})
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started["url"]).query))["state"]
        self.assertEqual(self.come_back("ana", {"error": "access_denied", "state": state}), "/?gmail=denied#settings")
        self.assertEqual((self.stored(), self.mailboxes()), ([], []))
        self.assertEqual(self.come_back("ana", {"error": "access_denied", "state": state}), "/?gmail=refused#settings")

    def test_a_grant_without_read_access_is_dropped(self):
        self.assertEqual(self.connect(refresh="refresh-no-scope", scope="https://www.googleapis.com/auth/userinfo.email"),
                         "/?gmail=scope#settings")
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.google.revoked, ["refresh-no-scope"])   # and Google was told to forget it

    def test_a_grant_that_isnt_lasting_is_dropped(self):
        self.assertEqual(self.connect(refresh=None), "/?gmail=failed#settings")
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.mailboxes(), [])

    def test_without_google_credentials_gmail_says_it_isnt_set_up(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
            status, body = self.call("ana", "GET", "/api/mailboxes")
            self.assertEqual((status, body), (200, {"configured": False, "mailboxes": []}))
            status, body = self.call("ana", "POST", "/api/mailboxes/connect", {})
            self.assertEqual(status, 400)
            self.assertIn("GOOGLE_CLIENT_ID", body["error"])
        self.assertTrue(self.call("ana", "GET", "/api/mailboxes")[1]["configured"])

    def test_google_not_answering_connects_nothing(self):
        _, started = self.call("ana", "POST", "/api/mailboxes/connect", {})
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started["url"]).query))["state"]
        dead = gmail.Hosts(auth="x", token="http://127.0.0.1:9/token", revoke="http://127.0.0.1:9/revoke", api="http://127.0.0.1:9", allow_http=True)
        with mock.patch.object(gmail, "HOSTS", dead):
            self.assertEqual(self.come_back("ana", {"code": "c", "state": state}), "/?gmail=failed#settings")
        self.assertEqual(self.stored(), [])


class UseTests(GoogleCase):
    def setUp(self):
        super().setUp()
        self.connect("ana", "ana@gmail.example", "refresh-ana")
        [self.row] = self.stored()

    def token(self, **kw):
        with db.session() as conn:
            return gmail.access_token(conn, self.row["id"], **kw)

    def test_refreshing_gives_an_access_token_for_the_mailbox(self):
        token = self.token()
        self.assertEqual(self.google.owners[token], "ana@gmail.example")
        refresh_call = [form for path, form in self.google.calls if form.get("grant_type") == "refresh_token"]
        self.assertEqual(refresh_call, [{"grant_type": "refresh_token", "refresh_token": "refresh-ana", "client_id": CLIENT_ID,
                                         "client_secret": CLIENT_SECRET}])
        self.assertEqual(self.mailboxes()[0]["status"], "connected")

    def test_a_grant_google_no_longer_honours_shows_as_reconnect(self):
        self.google.live.clear()   # removed at myaccount.google.com/permissions, or expired
        with self.assertRaises(gmail.Reconnect):
            self.token()
        [m] = self.mailboxes()
        self.assertEqual(m["status"], "reconnect")
        self.assertIn("no longer lets Waypoint read", m["last_error"])
        self.connect("ana", "ana@gmail.example", "refresh-ana-new")   # Reconnect: the same row is repaired
        [m] = self.mailboxes()
        self.assertEqual((m["status"], m["last_error"]), ("connected", None))
        self.assertEqual(len(self.stored()), 1)
        self.assertEqual(self.google.owners[self.token()], "ana@gmail.example")

    def test_google_being_unreachable_is_an_error_not_a_reconnect(self):
        self.google.refresh_fails = "unavailable"
        with self.assertRaises(gmail.GmailError) as raised:
            self.token()
        self.assertNotIsInstance(raised.exception, gmail.Reconnect)
        [m] = self.mailboxes()
        self.assertEqual(m["status"], "error")
        self.assertEqual(m["last_error"], "Google refused to refresh the connection just now.")
        self.google.refresh_fails = None
        self.token()
        self.assertEqual(self.mailboxes()[0]["status"], "connected")   # and it clears itself

    def test_a_key_that_cant_unlock_the_token_shows_as_reconnect(self):
        with db.session() as conn:
            conn.execute(update(Mailbox).values(token="enc:v1:not-a-token-this-key-made"))
        with self.assertRaises(gmail.Reconnect):
            self.token()
        self.assertEqual(self.mailboxes()[0]["status"], "reconnect")

    def test_disconnecting_revokes_at_google_and_deletes(self):
        status, body = self.call("ana", "DELETE", f"/api/mailboxes/{self.row['id']}")
        self.assertEqual((status, body), (200, {"ok": True, "revoked": True}))
        self.assertEqual(self.google.revoked, ["refresh-ana"])
        self.assertEqual((self.stored(), self.mailboxes()), ([], []))

    def test_a_mailbox_that_cant_be_revoked_stays_connected(self):
        self.google.revoke_status = 503
        status, body = self.call("ana", "DELETE", f"/api/mailboxes/{self.row['id']}")
        self.assertEqual(status, 502)
        self.assertIn("still connected", body["error"])
        self.assertEqual(len(self.stored()), 1)   # not said to be gone while Google still honours it
        self.google.revoke_status = 200
        self.assertEqual(self.call("ana", "DELETE", f"/api/mailboxes/{self.row['id']}")[0], 200)
        self.assertEqual(self.stored(), [])

    def test_a_token_google_already_dropped_is_disconnected_all_the_same(self):
        self.google.live.clear()   # revoked at Google's side already: it answers 400
        status, body = self.call("ana", "DELETE", f"/api/mailboxes/{self.row['id']}")
        self.assertEqual((status, body["revoked"]), (200, True))
        self.assertEqual(self.stored(), [])

    def test_a_token_the_key_cant_unlock_is_deleted_and_says_it_wasnt_revoked(self):
        with db.session() as conn:
            conn.execute(update(Mailbox).values(token="enc:v1:not-a-token-this-key-made"))
        status, body = self.call("ana", "DELETE", f"/api/mailboxes/{self.row['id']}")
        self.assertEqual((status, body), (200, {"ok": True, "revoked": False}))
        self.assertEqual((self.stored(), self.google.revoked), ([], []))

    def test_an_id_that_isnt_a_number_is_not_found(self):
        for bad in ("abc", "1%20OR%201", "99999999999999999999", "-1"):
            self.assertEqual(self.call("ana", "DELETE", f"/api/mailboxes/{bad}")[0], 404, bad)
        self.assertEqual(len(self.stored()), 1)


class LapseTests(GoogleCase):
    """Access that outlives the person: a connection ends when its owner can no longer sign in, checked before every use."""

    def setUp(self):
        super().setUp()
        self.connect("ben", "ben@gmail.example", "refresh-ben")
        [self.row] = self.stored()

    def use(self):
        with db.session() as conn:
            return gmail.access_token(conn, self.row["id"])

    def test_it_works_while_the_owner_may_sign_in(self):
        self.assertTrue(self.use())

    def test_taken_off_the_allow_list_ends_it_at_once_and_revokes_it(self):
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}):
            with self.assertRaises(gmail.Lapsed):
                self.use()
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.google.revoked, ["refresh-ben"])
        self.assertEqual([c for c in self.google.calls if c[1].get("grant_type") == "refresh_token"], [])   # never used

    def test_with_groups_it_ends_when_they_last_signed_in_too_long_ago(self):
        groups = {"OIDC_ALLOWED_EMAILS": "", "OIDC_ALLOWED_GROUPS": "household"}
        with mock.patch.dict(os.environ, groups):
            self.assertTrue(self.use())   # signed in just now
            with db.session() as conn:
                conn.execute(update(User).where(User.sub == "sub-ben").values(last_seen=time.time() - 15 * 86400))
            with self.assertRaises(gmail.Lapsed):
                self.use()
        self.assertEqual(self.stored(), [])

    def test_the_sweep_ends_a_lapsed_owners_connection_without_anything_using_it(self):
        self.connect("ana", "ana@gmail.example", "refresh-ana")
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}):
            with db.session() as conn:
                self.assertEqual(gmail.end_lapsed(conn), 1)   # Ben's; Ana may still sign in
            self.assertEqual([r["owner_sub"] for r in self.stored()], ["sub-ana"])
        self.assertEqual(self.google.revoked, ["refresh-ben"])
        with db.session() as conn:
            self.assertEqual(gmail.end_lapsed(conn), 0)

    def test_listing_mailboxes_also_ends_anyones_lapsed_connection(self):
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}):
            self.assertEqual(self.mailboxes("ana"), [])
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.google.revoked, ["refresh-ben"])

    def test_the_hourly_job_runs_the_sweep_and_survives_a_failure(self):
        from waypoint.server import jobs
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}):
            jobs.sweep_lapsed()
        self.assertEqual(self.stored(), [])
        with mock.patch.object(gmail, "end_lapsed", side_effect=RuntimeError("boom")):
            jobs.sweep_lapsed()   # reported without its text, not raised

    def test_a_lapsed_owners_connection_is_ended_even_if_google_cant_be_told(self):
        self.google.revoke_status = 503
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "ana@example.com"}):
            with self.assertRaises(gmail.Lapsed):
                self.use()
        self.assertEqual(self.stored(), [])


class NothingLeaksTests(GoogleCase):
    def test_no_token_or_code_reaches_the_log_or_the_database(self):
        canaries = ("CANARY-CODE-7Q2X", "CANARY-REFRESH-TOKEN-4M8", "CANARY-VERIFIER")
        with no_leaks(self, *canaries, database=self.path_to_database(), sent_ok=True):   # (what's sent to Google is the point)
            self.assertEqual(self.connect(refresh="CANARY-REFRESH-TOKEN-4M8", code="CANARY-CODE-7Q2X"), "/?gmail=connected#settings")
            [row] = self.stored()
            with db.session() as conn:
                access = gmail.access_token(conn, row["id"])
            self.google.refresh_fails = "revoked"
            self.google.live.clear()
            with db.session() as conn, self.assertRaises(gmail.Reconnect):
                gmail.access_token(conn, row["id"])
            self.google.refresh_fails = None
            self.assertEqual(self.connect(refresh="CANARY-REFRESH-TOKEN-4M8", code="CANARY-CODE-7Q2X-B"), "/?gmail=connected#settings")
            self.assertEqual(self.connect(refresh="CANARY-REFRESH-TOKEN-4M8", code="CANARY-CODE-7Q2X-C", challenge="wrong"),
                             "/?gmail=failed#settings")   # a failure is no more talkative
            self.assertEqual(self.call("ana", "DELETE", f"/api/mailboxes/{row['id']}")[0], 200)
        self.assertTrue(access)

    def test_an_error_names_nothing_google_said(self):
        self.google.refresh_fails = "unavailable"
        self.connect(refresh="CANARY-REFRESH-TOKEN-9Z1")
        [row] = self.stored()
        with db.session() as conn, self.assertRaises(gmail.GmailError) as raised:
            gmail.access_token(conn, row["id"])
        self.assertNotIn("CANARY", str(raised.exception) + repr(raised.exception.__cause__ or ""))
        self.assertNotIn("CANARY", json.dumps(self.mailboxes()))

    def path_to_database(self) -> str:
        return os.path.join(os.environ["WAYPOINT_DATA"], "waypoint.db")


class RedirectTests(GoogleCase):
    def test_with_sign_in_a_missing_public_url_is_an_error_not_the_host_header(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_PUBLIC_URL": ""}):
            status, body = self.call("ana", "POST", "/api/mailboxes/connect", {})
        self.assertEqual(status, 400)
        self.assertIn("WAYPOINT_PUBLIC_URL", body["error"])


class LocalTests(ServerCase):
    """Without sign-in (on your own machine) everyone is the one local member, and Google comes back to this address."""
    env = {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET}
    unset = ("OIDC_ISSUER", "WAYPOINT_PUBLIC_URL")

    def test_connect_asks_google_to_return_to_this_address(self):
        _, started = self.req("POST", "/api/mailboxes/connect", {})
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(started["url"]).query))
        self.assertEqual(q["redirect_uri"], self.base + "/api/mailboxes/callback")
        with db.session() as conn:
            self.assertEqual(conn.execute(select(MailboxPending.owner_sub)).scalars(), ["local"])
            conn.execute(MailboxPending.__table__.delete())


class ProviderTests(DbCase):
    """The provider on its own: what start() keeps, and what finish() says when it isn't given a real connection."""

    def setUp(self):
        super().setUp()
        patch = mock.patch.dict(os.environ, {"GOOGLE_CLIENT_ID": CLIENT_ID, "GOOGLE_CLIENT_SECRET": CLIENT_SECRET})
        patch.start()
        self.addCleanup(patch.stop)

    def test_unfinished_connections_are_pruned_and_bounded(self):
        for i in range(3):
            gmail.start(self.c, "sub-a", "https://w.example/api/mailboxes/callback", now=1000.0 + i)
        gmail.start(self.c, "sub-a", "https://w.example/api/mailboxes/callback", now=1000.0 + gmail.PENDING_TTL + 1.5)
        self.assertEqual(len(self.c.execute(select(MailboxPending.state)).fetchall()), 2)   # the two still within their time
        with mock.patch.object(gmail, "MAX_PENDING", 3):
            for i in range(6):
                gmail.start(self.c, "sub-a", "https://w.example/api/mailboxes/callback", now=5000.0 + i)
        self.assertEqual(len(self.c.execute(select(MailboxPending.state)).fetchall()), 3)

    def test_finish_with_a_late_state_is_refused(self):
        url = gmail.start(self.c, "sub-a", "https://w.example/cb", now=1000.0)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))["state"]
        with self.assertRaises(gmail.Refused):
            gmail.finish(self.c, "sub-a", {"code": "c", "state": state}, "https://w.example/cb", now=1000.0 + gmail.PENDING_TTL + 1)

    def test_not_configured(self):
        with mock.patch.dict(os.environ, {"GOOGLE_CLIENT_SECRET": ""}):
            with self.assertRaises(gmail.NotConfigured):
                gmail.start(self.c, "sub-a", "https://w.example/cb")
            self.assertFalse(gmail.configured())

    def test_a_mailbox_that_isnt_there_cant_be_used(self):
        with self.assertRaises(gmail.GmailError):
            gmail.access_token(self.c, 12345)
        self.assertTrue(gmail.end(self.c, 12345))


class StorageTests(DbCase):
    """The token is a secret like the others: re-encrypted with a new key, encrypted in a backup, and named when it can't be read."""

    def add(self, token="refresh-token-1"):
        self.c.execute(insert(Mailbox).values(owner_sub="sub-a", address="a@gmail.example", token=secretbox.encrypt(token),
                                              status="connected", created=1.0))
        self.c.commit()

    def test_a_backup_holds_the_token_encrypted_and_restores_it(self):
        from waypoint.storage import backup
        self.add("canary-refresh-token")
        data = backup.export(self.c)
        cols = data["tables"]["mailboxes"]["columns"]
        [row] = data["tables"]["mailboxes"]["rows"]
        self.assertTrue(secretbox.is_encrypted(row[cols.index("token")]))
        self.assertNotIn("canary-refresh-token", json.dumps(data))
        self.assertNotIn("mailbox_pending", data["tables"])   # a connection still at Google doesn't travel
        self.assertEqual(backup.unreadable_secrets(self.c), [])
        self.c.execute(Mailbox.__table__.delete())
        backup.restore(self.c, data)
        self.assertEqual(secretbox.decrypt(self.c.execute(select(Mailbox.token)).scalar()), "canary-refresh-token")

    def test_a_token_this_key_cant_read_is_named(self):
        from waypoint.storage import backup
        self.add()
        self.c.execute(update(Mailbox).values(token="enc:v1:not-a-token-this-key-made"))
        self.assertEqual(backup.unreadable_secrets(self.c), ["mailboxes"])
        self.assertIn("Gmail", backup.unreadable_summary(["mailboxes"]))

    def test_encrypting_what_is_stored_covers_the_tokens(self):
        self.c.execute(insert(Mailbox).values(owner_sub="sub-a", address="a@gmail.example", token="refresh-in-the-clear",
                                              status="connected", created=1.0))
        self.assertEqual(secretbox.encrypt_stored(self.c), 1)
        token = self.c.execute(select(Mailbox.token)).scalar()
        self.assertTrue(secretbox.is_encrypted(token))
        self.assertEqual(secretbox.encrypt_stored(self.c), 0)


if __name__ == "__main__":
    unittest.main()
