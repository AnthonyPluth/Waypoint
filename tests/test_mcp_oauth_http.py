"""OAuth for the MCP endpoint over HTTP: the metadata, registration, the consent page, tokens, revocation and /mcp
itself, against a real Waypoint (waypoint/server/handler.py). The functions underneath are tested in
tests/test_mcp_oauth.py."""
import base64
import hashlib
import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import HTTPServer
from unittest import mock

from sqlalchemy import delete, func, insert, select, update

from waypoint import oidc
from waypoint.server import common, mcp_access, mcp_oauth, mcp_server
from waypoint.storage import db
from waypoint.storage.models import OAuthClient, OAuthCode, OAuthConsent, OAuthGrant, OAuthToken, Trip, User
from tests.shared import ServerCase, fetch, tag
from tests.test_server import Provider

VERIFIER = "correct-horse-battery-staple-" + "x" * 30
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
CALLBACK = "http://127.0.0.1:43210/callback"


def forget_oauth(conn, client_ids) -> None:
    """Remove what these apps (and any consent form left open) made. For a class with a database of its own."""
    grants = select(OAuthGrant.id).where(OAuthGrant.client_id.in_(client_ids))
    conn.execute(delete(OAuthToken).where(OAuthToken.grant_id.in_(grants)))
    conn.execute(delete(OAuthCode).where(OAuthCode.grant_id.in_(grants)))
    conn.execute(delete(OAuthGrant).where(OAuthGrant.client_id.in_(client_ids)))
    conn.execute(delete(OAuthClient).where(OAuthClient.id.in_(client_ids)))
    conn.execute(delete(OAuthConsent))


class Reply:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    @property
    def json(self):
        return json.loads(self.body or b"null")

    @property
    def location(self):
        return self.headers.get("Location")

    def query(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.location).query))

    def cookie(self, name):
        for h in self.headers.get_all("Set-Cookie") or []:
            c = SimpleCookie()
            c.load(h)
            if name in c:
                return c[name]
        return None


class OAuthServer(ServerCase):
    """A real Waypoint on a database of its own (tests/shared.py's own_database, for the whole class; on Postgres its own
    schema), with no sign-in (so you're "signed in" on this computer). Nothing else writes to it, so another module's
    tests can't end a session or flip a switch under these. Each test still removes what it made and turns the switches
    off, so the tests don't depend on each other's order."""
    unset = ("WAYPOINT_PUBLIC_URL", "OIDC_ISSUER")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.iss = cls.base
        cls.resource = cls.base + "/mcp"

    def setUp(self):
        self.tag = tag()
        self.trip = {"name": "Trip " + self.tag}                                  # what a change made through /mcp adds
        self.clients: list[str] = []
        self.addCleanup(self.forget)

    def forget(self):
        with db.session() as conn:
            forget_oauth(conn, self.clients)
            conn.execute(delete(Trip).where(Trip.name == self.trip["name"]))
            mcp_access.set_allow_writes(conn, False)
            mcp_access.set_allow_ids(conn, False)

    def mine(self, stmt):
        """The first column of this statement's first row (`.in_(self.clients)` picks "this test's clients")."""
        with db.session() as conn:
            row = conn.execute(stmt).fetchone()
        return row[0] if row else None

    def trips_made(self):
        return self.mine(select(func.count()).select_from(Trip).where(Trip.name == self.trip["name"]))

    def http(self, method, path, body=None, headers=None, cookies=None):
        h = dict(headers or {})
        if cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
        return Reply(*fetch(self.base if path.startswith("/") else "", method, path, body, h, follow=False))

    def form(self, path, fields, headers=None, cookies=None):
        return self.http("POST", path, urllib.parse.urlencode(fields).encode(),
                         {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}, cookies)

    def register(self, **meta):
        body = {"client_name": "Claude Code", "redirect_uris": [CALLBACK], **meta}
        r = self.http("POST", "/oauth/register", json.dumps(body).encode(), {"Content-Type": "application/json"})
        if r.status == 201:
            self.clients.append(r.json["client_id"])
        return r

    def client(self, **meta):
        r = self.register(**meta)
        self.assertEqual(r.status, 201, r.body)
        return r.json

    def authorize(self, client, cookies=None, **over):
        q = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": client["redirect_uris"][0],
             "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "xyz/+&=", "resource": self.resource, **over}
        return self.http("GET", "/oauth/authorize?" + urllib.parse.urlencode({k: v for k, v in q.items() if v is not None}),
                         cookies=cookies)

    def consent_token(self, page):
        body = page.body.decode()
        start = body.index('name="consent" value="') + len('name="consent" value="')
        return body[start:body.index('"', start)]

    def answer(self, page, decision="allow", ids=False, write=False, cookies=None, headers=None, token=None):
        """The consent form's answer: `ids` and `write` are the boxes ticked."""
        fields = {"consent": token if token is not None else self.consent_token(page), "decision": decision,
                  **({"ids": "1"} if ids else {}), **({"write": "1"} if write else {})}
        ck = {"waypoint_consent": page.cookie("waypoint_consent").value} if cookies is None else cookies
        return self.form("/oauth/authorize", fields, headers, {**ck, **getattr(self, "session", {})})

    def code(self, client, scope="read", ids=False, write=False):
        page = self.authorize(client, scope=scope, cookies=getattr(self, "session", None))
        self.assertEqual(page.status, 200, page.body)
        back = self.answer(page, ids=ids, write=write)
        self.assertEqual(back.status, 302, back.body)
        return back.query()["code"]

    def exchange(self, client, code, **over):
        fields = {"grant_type": "authorization_code", "code": code, "redirect_uri": client["redirect_uris"][0],
                  "code_verifier": VERIFIER, "client_id": client["client_id"], **over}
        return self.form("/oauth/token", {k: v for k, v in fields.items() if v is not None})

    def tokens(self, client=None, scope="read", ids=False, write=False):
        client = client or self.client()
        r = self.exchange(client, self.code(client, scope, ids, write))
        self.assertEqual(r.status, 200, r.body)
        return r.json

    def granted(self, client, page, **ticked):
        """The scope of the tokens an app gets when this consent page is answered with these boxes ticked."""
        r = self.exchange(client, self.answer(page, **ticked).query()["code"])
        self.assertEqual(r.status, 200, r.body)
        return r.json["scope"]

    def rpc(self, token, method, params=None, mid=1, headers=None):
        msg = {"jsonrpc": "2.0", "id": mid, "method": method, **({"params": params} if params is not None else {})}
        return self.http("POST", "/mcp", json.dumps(msg).encode(),
                         {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {}),
                          **(headers or {})})

    def tool_names(self, token):
        r = self.rpc(token, "tools/list")
        self.assertEqual(r.status, 200, r.body)
        return {t["name"] for t in r.json["result"]["tools"]}

    def call(self, token, name, args=None):
        r = self.rpc(token, "tools/call", {"name": name, "arguments": args or {}})
        self.assertEqual(r.status, 200, r.body)
        return r.json["result"]

    def writes(self, on):
        with db.session() as conn:
            mcp_access.set_allow_writes(conn, on)

    def ids(self, on):
        with db.session() as conn:
            mcp_access.set_allow_ids(conn, on)


class MetadataTests(OAuthServer):
    """The two metadata documents, and which address Waypoint says it is (WAYPOINT_PUBLIC_URL, never the Host header)."""

    def test_the_metadata(self):
        for path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
            with self.subTest(path=path):
                r = self.http("GET", path)
                self.assertEqual(r.status, 200)
                self.assertEqual(r.json, {"resource": self.resource, "authorization_servers": [self.iss],
                                          "scopes_supported": ["read", "ids:read", "write"], "bearer_methods_supported": ["header"]})
                self.assertIsNone(r.headers.get("Access-Control-Allow-Origin"))   # no CORS
        m = self.http("GET", "/.well-known/oauth-authorization-server").json
        self.assertEqual(m, mcp_oauth.authorization_server_metadata(self.iss))
        self.assertEqual(m["token_endpoint"], self.iss + "/oauth/token")
        self.assertEqual(m["code_challenge_methods_supported"], ["S256"])
        for path in ("/.well-known/openid-configuration", "/.well-known/whatever", "/oauth/nothing"):
            with self.subTest(path=path):
                self.assertEqual(self.http("GET", path).status, 404)
        self.assertEqual(self.http("POST", "/.well-known/oauth-authorization-server", b"").status, 405)

    def test_the_issuer_is_waypoint_public_url_never_the_host(self):
        with mock.patch.dict(os.environ, {"WAYPOINT_PUBLIC_URL": "https://waypoint.example.com"}):
            m = self.http("GET", "/.well-known/oauth-authorization-server").json
            self.assertEqual(m["issuer"], "https://waypoint.example.com")
            r = self.http("GET", "/.well-known/oauth-protected-resource/mcp", headers={"X-Forwarded-Host": "evil.example"})
            self.assertEqual(r.json["resource"], "https://waypoint.example.com/mcp")

    def test_without_it_an_internet_address_gets_no_oauth(self):
        common.EXTRA_HOSTS.add("waypoint.example.com")
        try:
            host = {"Host": "waypoint.example.com"}
            for path in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp"):
                r = self.http("GET", path, headers=host)
                self.assertEqual(r.status, 404)
                self.assertIn("WAYPOINT_PUBLIC_URL", r.json["error"])
            self.assertEqual(self.register().status, 201)                         # on the home address, fine
            r = self.http("POST", "/oauth/register", b"{}", {"Content-Type": "application/json", **host})
            self.assertEqual(r.status, 404)
            page = self.http("GET", "/oauth/authorize?client_id=x", headers=host)
            self.assertEqual(page.status, 404)
            self.assertIn(b"WAYPOINT_PUBLIC_URL", page.body)
            r = self.rpc(None, "ping")
            self.assertIn("resource_metadata", r.headers["WWW-Authenticate"])
            r = self.http("POST", "/mcp", b"{}", {"Content-Type": "application/json", **host})
            self.assertEqual((r.status, r.headers["WWW-Authenticate"]), (401, 'Bearer realm="Waypoint"'))
        finally:
            common.EXTRA_HOSTS.discard("waypoint.example.com")

    def test_an_unknown_host_is_refused_first(self):
        self.assertEqual(self.http("GET", "/.well-known/oauth-authorization-server", headers={"Host": "evil.example"}).status, 403)
        self.assertEqual(self.http("POST", "/oauth/token", b"", headers={"Host": "evil.example"}).status, 403)


class RegistrationTests(OAuthServer):
    """Dynamic client registration over HTTP: JSON only, at most 8 KB, and what's refused saves nothing."""

    def test_register(self):
        r = self.register()
        self.assertEqual(r.status, 201)
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertTrue(r.json["client_id"].startswith("wpc_"))
        self.assertEqual(r.json["redirect_uris"], [CALLBACK])
        secret = self.client(token_endpoint_auth_method="client_secret_basic")
        self.assertTrue(secret["client_secret"])

    def test_refusals(self):
        name = "Refused " + self.tag
        r = self.register(client_name=name, redirect_uris=["myapp://callback"])
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_redirect_uri"))
        r = self.register(client_name="x" * 101)
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_client_metadata"))
        r = self.http("POST", "/oauth/register", json.dumps({"client_name": name, "redirect_uris": [CALLBACK]}).encode(),
                      {"Content-Type": "application/x-www-form-urlencoded"})   # what a form on another site could send
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_client_metadata"))
        r = self.http("POST", "/oauth/register", b"{nope", {"Content-Type": "application/json"})
        self.assertEqual(r.status, 400)
        r = self.http("POST", "/oauth/register", json.dumps({"client_name": name, "redirect_uris": [CALLBACK], "x": "y" * 9000}).encode(),
                      {"Content-Type": "application/json"})
        self.assertEqual(r.status, 413)                                           # over 8 KB
        self.assertEqual(self.http("GET", "/oauth/register").status, 405)
        self.assertEqual(self.mine(select(func.count()).select_from(OAuthClient).where(OAuthClient.name == name)), 0)
        self.assertEqual(self.clients, [])

    def test_apps_nobody_approved_are_dropped_after_a_day(self):
        old, recent = self.client(), self.client()
        with db.session() as conn:
            conn.execute(update(OAuthClient).where(OAuthClient.id == old["client_id"])
                         .values(created=time.time() - mcp_oauth.UNCONSENTED_TTL - 60))
            conn.execute(update(OAuthClient).where(OAuthClient.id == recent["client_id"])
                         .values(created=time.time() - mcp_oauth.UNCONSENTED_TTL + 3600))
        self.client()                                                             # registering tidies up
        self.assertIsNone(self.mine(select(OAuthClient.id).where(OAuthClient.id == old["client_id"])))
        self.assertIsNotNone(self.mine(select(OAuthClient.id).where(OAuthClient.id == recent["client_id"])))
        page = self.authorize(old)                                                # and the app is told how to start over
        self.assertEqual(page.status, 400)
        self.assertIn(b"Remove Waypoint from the assistant and add it again", page.body)

    def test_at_most_fifty_unapproved_apps_are_kept_once_they_are_ten_minutes_old(self):
        with db.session() as conn:
            for i in range(53):
                conn.execute(insert(OAuthClient).values(
                    id=f"wpc_{self.tag}{i:02d}", name="Bulk " + self.tag, redirect_uris=json.dumps([CALLBACK]),
                    auth_method="none", kind="dcr", created=time.time() - mcp_oauth.CONSENT_TTL - 100 + i))
        self.clients.extend(f"wpc_{self.tag}{i:02d}" for i in range(53))
        self.client()
        kept = self.mine(select(func.count()).select_from(OAuthClient).where(OAuthClient.name == "Bulk " + self.tag))
        self.assertEqual(kept, mcp_oauth.MAX_UNCONSENTED - 1)                     # the new one makes fifty
        self.assertIsNone(self.mine(select(OAuthClient.id).where(OAuthClient.id == f"wpc_{self.tag}00")))   # the oldest went
        self.assertIsNotNone(self.mine(select(OAuthClient.id).where(OAuthClient.id == f"wpc_{self.tag}52")))


class ConsentTests(OAuthServer):
    """The consent page: a request it can't trust is shown here, one it can goes back to the app, the boxes for
    ids:read and write, and the answer's checks."""

    def test_a_bad_app_or_redirect_is_shown_here_never_redirected(self):
        c = self.client()
        for over in ({"client_id": "wpc_nope"}, {"redirect_uri": "https://evil.example/cb"}, {"redirect_uri": None},
                     {"redirect_uri": "http://127.0.0.1:43210/other"}):
            with self.subTest(over=over):
                r = self.authorize(c, **over)
                self.assertEqual(r.status, 400)
                self.assertIsNone(r.location)
                self.assertIn(b"Can&#x27;t connect this app", r.body)
        self.assertIn(b"Remove Waypoint from the assistant and add it again", self.authorize(c, client_id="wpc_nope").body)

    def test_other_mistakes_are_sent_back_with_the_state(self):
        c = self.client()
        for over, error in (({"code_challenge_method": None}, "invalid_request"), ({"code_challenge_method": "plain"}, "invalid_request"),
                            ({"code_challenge": None}, "invalid_request"), ({"response_type": "token"}, "unsupported_response_type"),
                            ({"resource": "https://other.example/mcp"}, "invalid_target"), ({"scope": "admin"}, "invalid_scope")):
            with self.subTest(over=over):
                r = self.authorize(c, **over)
                self.assertEqual(r.status, 302)
                self.assertTrue(r.location.startswith(CALLBACK + "?"))
                q = r.query()
                self.assertEqual((q["error"], q["state"], q["iss"]), (error, "xyz/+&=", self.iss))
                self.assertNotIn("code", q)

    def test_the_page_escapes_the_app_name_and_says_where_it_goes(self):
        c = self.client(client_name='<script>alert("x")</script>')
        r = self.authorize(c)
        self.assertEqual(r.status, 200)
        page = r.body.decode()
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; wants to connect to Waypoint", page)
        self.assertIn("127.0.0.1:43210", page)
        self.assertIn("Read your travel", page)
        self.assertNotIn("See full ID numbers", page)                             # it didn't ask
        self.assertNotIn("Change trips", page)
        csp = r.headers["Content-Security-Policy"]
        self.assertIn("form-action 'self' http://127.0.0.1:*", csp)
        self.assertIn("default-src 'none'", csp)
        ck = r.cookie("waypoint_consent")
        self.assertEqual((ck["path"], ck["httponly"], ck["samesite"]), ("/oauth", True, "Lax"))
        self.assertEqual(ck.value, self.consent_token(r))

    def test_the_ids_box_follows_its_switch_and_is_never_ticked_for_you(self):
        c = self.client()
        page = self.authorize(c, scope="read ids:read").body.decode()             # asked, switch off: shown, off, and why
        self.assertIn('type="checkbox" disabled><span><b>See full ID numbers', page)
        self.assertIn("Turn on Let assistants see full ID numbers in Settings first", page)
        self.assertNotIn('name="ids"', page)
        self.assertEqual(self.granted(c, self.authorize(c, scope="read ids:read"), ids=True), "read")   # ticked by a script: no
        self.ids(True)
        page = self.authorize(c, scope="read ids:read")
        body = page.body.decode()
        self.assertIn('<input type="checkbox" name="ids" value="1"><span><b>See full ID numbers', body)   # on, not ticked
        self.assertNotIn("checked><span><b>See full ID numbers", body)
        self.assertIn("Loyalty, Known Traveler and redress numbers in full", body)
        self.assertEqual(self.granted(c, page), "read")                           # left unticked: read only
        self.assertEqual(self.granted(c, self.authorize(c, scope="read ids:read"), ids=True), "read ids:read")
        self.assertNotIn("See full ID numbers", self.authorize(c, scope="read write").body.decode())   # not asked: not there
        self.assertEqual(self.granted(c, self.authorize(c, scope="read write"), ids=True), "read")     # nor granted

    def test_the_write_box_follows_its_switch_and_is_never_ticked_for_you(self):
        c = self.client()
        page = self.authorize(c, scope="read write").body.decode()                # asked, switch off: shown, off, and why
        self.assertIn('type="checkbox" disabled><span><b>Change trips', page)
        self.assertIn("Turn on Let assistants change trips in Settings first", page)
        self.assertNotIn('name="write"', page)
        self.assertEqual(self.granted(c, self.authorize(c, scope="read write"), write=True), "read")
        self.writes(True)
        page = self.authorize(c, scope="read write")
        body = page.body.decode()
        self.assertIn('<input type="checkbox" name="write" value="1"><span><b>Change trips', body)   # on, not ticked
        self.assertIn("Add, change and remove trips, bookings, travellers, people, guests and loyalty entries", body)
        self.assertIn("AI settings, backups, sign-in or these assistant settings", body)
        self.assertEqual(self.granted(c, page), "read")                           # left unticked: read only
        self.assertEqual(self.granted(c, self.authorize(c, scope="read write"), write=True), "read write")
        self.assertNotIn("Change trips", self.authorize(c, scope="read ids:read").body.decode())   # not asked: not there
        self.assertEqual(self.granted(c, self.authorize(c, scope="read ids:read"), write=True), "read")   # nor granted

    def test_each_box_has_its_own_switch(self):
        c = self.client()
        self.writes(True)                                                         # the write switch isn't the ids one
        page = self.authorize(c, scope="read ids:read write")
        body = page.body.decode()
        self.assertIn('type="checkbox" disabled><span><b>See full ID numbers', body)
        self.assertIn('name="write" value="1"', body)
        self.assertEqual(self.granted(c, page, ids=True, write=True), "read write")
        self.writes(False)
        self.ids(True)
        page = self.authorize(c, scope="read ids:read write")
        self.assertEqual(self.granted(c, page, ids=True, write=True), "read ids:read")
        self.writes(True)
        page = self.authorize(c, scope="read ids:read write")
        self.assertEqual(self.granted(c, page, ids=True, write=True), "read ids:read write")
        page = self.authorize(c, scope="read ids:read write")
        self.assertEqual(self.granted(c, page, write=True), "read write")        # you unticked ids

    def test_the_switch_is_read_again_when_you_answer(self):
        c = self.client()
        self.writes(True)
        self.ids(True)
        page = self.authorize(c, scope="read ids:read write")
        self.writes(False)
        self.ids(False)
        self.assertEqual(self.granted(c, page, ids=True, write=True), "read")     # turned off while the page was open
        self.writes(True)
        page = self.authorize(c, scope="read write")
        self.assertEqual(self.granted(c, page, write=False), "read")             # you unticked it

    def test_allow_and_deny(self):
        c = self.client()
        page = self.authorize(c)
        r = self.answer(page)
        self.assertEqual(r.status, 302)
        q = r.query()
        self.assertTrue(q["code"].startswith("wpo_"))
        self.assertEqual((q["state"], q["iss"]), ("xyz/+&=", self.iss))
        self.assertEqual(r.cookie("waypoint_consent").value, "")                  # the cookie is cleared
        r = self.answer(self.authorize(c), "deny")
        self.assertEqual((r.query()["error"], r.query()["state"]), ("access_denied", "xyz/+&="))
        self.assertNotIn("code", r.query())
        r = self.answer(self.authorize(c), "maybe")
        self.assertEqual((r.status, r.location), (400, None))

    def test_the_answer_must_come_from_this_browser_and_waypoint(self):
        c = self.client()
        page = self.authorize(c)
        token = self.consent_token(page)
        for kwargs in ({"token": ""}, {"cookies": {}}, {"cookies": {"waypoint_consent": "other"}}, {"token": "other"},
                       {"headers": {"Sec-Fetch-Site": "cross-site"}}, {"headers": {"Origin": "https://evil.example"}},
                       {"headers": {"Origin": "null"}}, {"headers": {"Origin": "null", "Sec-Fetch-Site": "cross-site"}}):
            with self.subTest(kwargs=kwargs):
                r = self.answer(page, **kwargs)
                self.assertEqual(r.status, 403)
                self.assertIsNone(r.location)
        r = self.answer(page)                                                     # the real one still works, once
        self.assertEqual(r.status, 302)
        again = self.answer(page, token=token)
        self.assertEqual((again.status, again.location), (403, None))

    def test_a_browsers_own_form_post_is_accepted(self):
        """Under Referrer-Policy: no-referrer a browser sends a page's form post with Origin "null"; it's Waypoint's own
        page when the browser also says same-origin."""
        c = self.client()
        r = self.answer(self.authorize(c), headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status, 302)
        self.assertTrue(r.query()["code"].startswith("wpo_"))

    def test_an_expired_form_is_refused(self):
        c = self.client()
        page = self.authorize(c)
        with db.session() as conn:
            conn.execute(update(OAuthConsent).values(created=time.time() - mcp_oauth.CONSENT_TTL - 5))
        r = self.answer(page)
        self.assertEqual((r.status, r.location), (403, None))
        self.assertIn(b"expired or was already answered", r.body)
        self.assertEqual(self.mine(select(func.count()).select_from(OAuthGrant).where(OAuthGrant.client_id.in_(self.clients))), 0)


class TokenTests(OAuthServer):
    """/oauth/token and /oauth/revoke: codes, refusals, a code used twice, confidential clients, refresh and revoking."""

    def test_tokens_for_a_code(self):
        c = self.client()
        r = self.exchange(c, self.code(c), resource=self.resource)
        self.assertEqual(r.status, 200, r.body)
        self.assertEqual((r.headers["Cache-Control"], r.headers["Pragma"]), ("no-store", "no-cache"))
        self.assertEqual((r.json["token_type"], r.json["expires_in"], r.json["scope"]), ("Bearer", 3600, "read"))
        self.assertTrue(r.json["access_token"].startswith("wpa_") and r.json["refresh_token"].startswith("wpr_"))

    def test_refusals(self):
        c = self.client()
        for over, error in (({"code_verifier": "wrong-" + "y" * 50}, "invalid_grant"), ({"redirect_uri": "http://127.0.0.1:43210/x"}, "invalid_grant"),
                            ({"client_id": self.client()["client_id"]}, "invalid_grant"), ({"resource": "https://other.example/mcp"}, "invalid_target"),
                            ({"client_id": "wpc_nope"}, "invalid_client"), ({"grant_type": "client_credentials"}, "unsupported_grant_type"),
                            ({"code_verifier": None}, "invalid_request")):
            with self.subTest(over=over):
                r = self.exchange(c, self.code(c), **over)
                self.assertIn(r.status, (400, 401))
                self.assertEqual(r.json["error"], error)
                self.assertNotIn("access_token", r.json)
        r = self.http("POST", "/oauth/token", json.dumps({"grant_type": "authorization_code"}).encode(), {"Content-Type": "application/json"})
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_request"))
        r = self.http("POST", "/oauth/token", b"grant_type=a&grant_type=b", {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_request"))
        self.assertEqual(self.http("GET", "/oauth/token").status, 405)

    def test_pkce_is_required_and_only_s256(self):
        c = self.client()
        wrong = "z" * 50                                                          # a verifier that isn't this request's
        self.assertEqual(self.exchange(c, self.code(c), code_verifier=wrong).json["error"], "invalid_grant")
        self.assertEqual(self.exchange(c, self.code(c), code_verifier="short").json["error"], "invalid_grant")
        self.assertEqual(self.exchange(c, self.code(c), code_verifier=None).json["error"], "invalid_request")
        r = self.authorize(c, code_challenge_method="plain")
        self.assertEqual(r.query()["error"], "invalid_request")

    def test_a_code_works_once_and_a_second_try_revokes_it(self):
        c = self.client()
        code = self.code(c)
        first = self.exchange(c, code)
        self.assertEqual(first.status, 200)
        again = self.exchange(c, code)
        self.assertEqual((again.status, again.json["error"]), (400, "invalid_grant"))
        self.assertEqual(self.rpc(first.json["access_token"], "ping").status, 401)   # the tokens from it are gone too
        self.assertEqual(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id.in_(self.clients))), "code_reuse")

    def test_an_expired_code(self):
        c = self.client()
        code = self.code(c)
        with db.session() as conn:
            conn.execute(update(OAuthCode).where(OAuthCode.client_id == c["client_id"])
                         .values(created=OAuthCode.created - 601))
        self.assertEqual(self.exchange(c, code).json["error"], "invalid_grant")

    def test_a_confidential_client(self):
        c = self.client(token_endpoint_auth_method="client_secret_basic")
        basic = "Basic " + base64.b64encode(f"{c['client_id']}:{c['client_secret']}".encode()).decode()
        wrong = "Basic " + base64.b64encode(f"{c['client_id']}:nope".encode()).decode()
        code = self.code(c)
        fields = {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK, "code_verifier": VERIFIER}
        r = self.form("/oauth/token", fields, {"Authorization": wrong})
        self.assertEqual((r.status, r.json["error"], r.headers["WWW-Authenticate"]), (401, "invalid_client", 'Basic realm="Waypoint"'))
        r = self.form("/oauth/token", {**fields, "client_id": c["client_id"]})       # no secret at all
        self.assertEqual(r.status, 401)
        r = self.form("/oauth/token", fields, {"Authorization": basic})
        self.assertEqual(r.status, 200, r.body)

    def test_refresh_rotates_and_a_replay_revokes_the_connection(self):
        c = self.client()
        self.writes(True)
        first = self.tokens(c, scope="read write", write=True)
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": c["client_id"]})
        self.assertEqual(r.status, 200, r.body)
        second = r.json
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.assertEqual(second["scope"], "read write")                           # what was approved, no more or less
        self.assertEqual(self.rpc(second["access_token"], "ping").status, 200)
        self.assertEqual(self.rpc(first["access_token"], "ping").status, 200)     # the old access token lives out its hour
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": c["client_id"],
                                       "scope": "read ids:read"})                 # a refresh can't add scopes
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_scope"))
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": first["refresh_token"], "client_id": c["client_id"]})
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_grant"))     # the spent one again: revoke it all
        for t in (first, second):
            self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": second["refresh_token"], "client_id": c["client_id"]})
        self.assertEqual(r.json["error"], "invalid_grant")
        self.assertEqual(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id.in_(self.clients))), "refresh_reuse")

    def test_another_app_cannot_use_a_refresh_token(self):
        c, other = self.client(), self.client()
        t = self.tokens(c)
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": other["client_id"]})
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_grant"))
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)         # and it didn't end the real one's

    def test_revoke(self):
        c = self.client()
        t = self.tokens(c)
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)
        r = self.form("/oauth/revoke", {"token": "wpr_unknown", "client_id": c["client_id"]})
        self.assertEqual(r.status, 200)                                           # unknown tokens are fine too
        other = self.client()
        r = self.form("/oauth/revoke", {"token": t["refresh_token"], "client_id": other["client_id"]})
        self.assertEqual(r.status, 200)                                           # another app's token: quietly nothing
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)
        r = self.form("/oauth/revoke", {"token": t["refresh_token"], "client_id": c["client_id"], "token_type_hint": "refresh_token"})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": c["client_id"]})
        self.assertEqual(r.json["error"], "invalid_grant")
        self.assertEqual(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id == c["client_id"])), "revoked_by_client")

    def test_revoking_with_an_access_token_ends_the_connection_too(self):
        c = self.client()
        t = self.tokens(c)
        self.assertEqual(self.form("/oauth/revoke", {"token": t["access_token"], "client_id": c["client_id"]}).status, 200)
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)
        r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": c["client_id"]})
        self.assertEqual(r.json["error"], "invalid_grant")


class McpTests(OAuthServer):
    """/mcp with a token: who may call it (no token, an expired one, one for another address, a web page), and what a
    token's scopes and the two switches allow."""

    def test_no_token_is_401_pointing_at_the_metadata(self):
        r = self.rpc(None, "ping")
        self.assertEqual(r.status, 401)
        self.assertEqual(r.headers["WWW-Authenticate"],
                         f'Bearer realm="Waypoint", resource_metadata="{self.iss}/.well-known/oauth-protected-resource/mcp"')
        for token in ("wpa_nope", "garbage"):
            r = self.rpc(token, "ping")
            self.assertEqual(r.status, 401)
            self.assertTrue(r.headers["WWW-Authenticate"].endswith(', error="invalid_token"'))
        self.assertEqual(self.http("GET", "/mcp").status, 405)

    def test_a_web_page_is_refused_whatever_token_it_holds(self):
        t = self.tokens()
        host = urllib.parse.urlsplit(self.base).netloc
        for origin in ("https://evil.example", "http://evil.example", "null", f"http://{host}.evil.example", "http://127.0.0.1:1"):
            with self.subTest(origin=origin):
                for token in (t["access_token"], None):                           # refused before the token is even looked at
                    r = self.rpc(token, "ping", headers={"Origin": origin})
                    self.assertEqual((r.status, r.json), (403, {"error": "Origin not allowed."}))
                    self.assertNotIn("WWW-Authenticate", r.headers)
        self.assertEqual(self.rpc(t["access_token"], "ping", headers={"Origin": self.base}).status, 200)   # Waypoint's own address
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)         # an app sends no Origin

    def test_an_expired_token_or_one_for_another_resource(self):
        t = self.tokens()
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)
        with db.session() as conn:
            grants = select(OAuthGrant.id).where(OAuthGrant.client_id == self.clients[-1])
            conn.execute(update(OAuthToken).where(OAuthToken.kind == "access", OAuthToken.grant_id.in_(grants)).values(expires=1))
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)
        with db.session() as conn:   # a token Waypoint issued at another address (another WAYPOINT_PUBLIC_URL)
            c = mcp_oauth.register(conn, {"redirect_uris": [CALLBACK]})
            self.clients.append(c["client_id"])
            params = {"client_id": c["client_id"], "redirect_uri": CALLBACK, "code_challenge": CHALLENGE,
                      "resource": "https://elsewhere.example/mcp"}
            code = mcp_oauth.approve(conn, params, frozenset({"read"}), None, None)
            other = mcp_oauth.token(conn, mcp_oauth.get_client(conn, c["client_id"]),
                                    {"grant_type": "authorization_code", "code": code, "redirect_uri": CALLBACK, "code_verifier": VERIFIER},
                                    "https://elsewhere.example")
        self.assertEqual(self.rpc(other["access_token"], "ping").status, 401)

    def test_a_read_only_connection_is_told_to_reconnect(self):
        t = self.tokens()
        self.writes(True)
        self.ids(True)
        self.assertEqual(self.tool_names(t["access_token"]), {x["name"] for x in mcp_server.TOOLS})
        for name, args, words in (("create_trip", {"fields": self.trip}, "reconnect"),
                                  ("add_loyalty_id", {"fields": {}}, "reconnect")):
            with self.subTest(tool=name):
                result = self.call(t["access_token"], name, args)
                self.assertTrue(result["isError"])
                self.assertIn(words, result["content"][0]["text"])
        self.assertNotIn("isError", self.call(t["access_token"], "list_trips"))
        self.assertEqual(self.trips_made(), 0)

    def test_changes_need_the_scope_and_the_switch(self):
        self.writes(True)
        t = self.tokens(scope="read write", write=True)
        self.assertEqual(t["scope"], "read write")
        token = t["access_token"]
        offered = {x["name"] for x in mcp_server.ALL_TOOLS if mcp_access.IDS not in x["needs"]}
        self.assertEqual(self.tool_names(token), offered)
        self.assertIn("create_trip", offered)
        self.assertNotIn("isError", self.call(token, "create_trip", {"fields": self.trip}))
        self.assertEqual(self.trips_made(), 1)
        self.writes(False)                                                        # off: at once, without revoking
        self.assertEqual(self.tool_names(token), {x["name"] for x in mcp_server.TOOLS})
        result = self.call(token, "create_trip", {"fields": self.trip})
        self.assertTrue(result["isError"])
        self.assertIn("switched off", result["content"][0]["text"])
        self.assertEqual(self.rpc(token, "ping").status, 200)
        self.assertEqual(self.trips_made(), 1)                                    # the refused call changed nothing

    def test_a_number_needs_ids_read_and_its_own_switch(self):
        self.writes(True)
        self.ids(True)
        write_only = self.tokens(scope="read write", write=True)["access_token"]
        self.assertNotIn("add_loyalty_id", self.tool_names(write_only))           # the scope, not just the switch
        result = self.call(write_only, "add_loyalty_id", {"fields": {}})
        self.assertTrue(result["isError"])
        self.assertIn("reconnect", result["content"][0]["text"])
        both = self.tokens(scope="read write ids:read", write=True, ids=True)
        self.assertEqual(both["scope"], "read ids:read write")
        self.assertIn("add_loyalty_id", self.tool_names(both["access_token"]))
        self.ids(False)                                                           # the switch, at once
        self.assertNotIn("add_loyalty_id", self.tool_names(both["access_token"]))
        self.assertIn("create_trip", self.tool_names(both["access_token"]))
        result = self.call(both["access_token"], "add_loyalty_id", {"fields": {}})
        self.assertTrue(result["isError"])
        self.assertIn("Full ID numbers are switched off", result["content"][0]["text"])


class EndToEndTests(OAuthServer):
    """What an assistant does from its first request to a replayed refresh token."""

    def test_connect_use_refresh_replay(self):
        # What an assistant does: find the server's metadata from the 401, register, send you to approve, get tokens.
        challenge = self.rpc(None, "initialize").headers["WWW-Authenticate"]
        prm_url = challenge.split('resource_metadata="')[1].split('"')[0]
        prm = self.http("GET", prm_url).json
        asm = self.http("GET", prm["authorization_servers"][0] + "/.well-known/oauth-authorization-server").json
        reg = self.http("POST", asm["registration_endpoint"], json.dumps({"client_name": "Claude", "redirect_uris": [CALLBACK]}).encode(),
                        {"Content-Type": "application/json"}).json
        self.clients.append(reg["client_id"])
        self.writes(True)
        q = {"response_type": "code", "client_id": reg["client_id"], "redirect_uri": CALLBACK, "scope": "read write",
             "state": "s1", "code_challenge": CHALLENGE, "code_challenge_method": "S256", "resource": prm["resource"]}
        page = self.http("GET", asm["authorization_endpoint"] + "?" + urllib.parse.urlencode(q))
        self.assertIn(b"Claude wants to connect to Waypoint", page.body)
        back = self.answer(page, write=True)
        got = back.query()
        self.assertEqual((got["state"], got["iss"]), ("s1", asm["issuer"]))
        t = self.form(asm["token_endpoint"], {"grant_type": "authorization_code", "code": got["code"], "redirect_uri": CALLBACK,
                                              "code_verifier": VERIFIER, "client_id": reg["client_id"], "resource": prm["resource"]}).json
        self.assertEqual(self.rpc(t["access_token"], "initialize", {"protocolVersion": "2025-06-18"}).json["result"]["serverInfo"]["name"], "waypoint")
        self.assertIn("create_trip", self.tool_names(t["access_token"]))
        self.assertNotIn("isError", self.call(t["access_token"], "create_trip", {"fields": self.trip}))
        self.writes(False)
        self.assertTrue(self.call(t["access_token"], "create_trip", {"fields": self.trip})["isError"])
        self.writes(True)
        # Refresh: a new pair; the old refresh token is spent.
        r = self.form(asm["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": reg["client_id"]})
        self.assertEqual(r.status, 200, r.body)
        t2 = r.json
        self.assertEqual(t2["scope"], "read write")
        self.assertEqual(self.rpc(t2["access_token"], "ping").status, 200)
        # Someone replays the old one: the whole connection is revoked, the new tokens included.
        r = self.form(asm["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": reg["client_id"]})
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_grant"))
        self.assertEqual(self.rpc(t2["access_token"], "ping").status, 401)
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)
        r = self.form(asm["token_endpoint"], {"grant_type": "refresh_token", "refresh_token": t2["refresh_token"], "client_id": reg["client_id"]})
        self.assertEqual(r.json["error"], "invalid_grant")
        self.assertEqual(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id.in_(self.clients))), "refresh_reuse")


class SignInTests(OAuthServer):
    """With sign-in (OIDC): someone signed out is sent to sign in and comes back to the same consent page, a grant
    carries who approved it, and it ends when that person can no longer sign in (oidc.access_lapsed)."""
    unset = ()

    @classmethod
    def setUpClass(cls):
        cls.idp = HTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=cls.idp.serve_forever, daemon=True).start()
        cls.env = {"OIDC_ISSUER": f"http://127.0.0.1:{cls.idp.server_port}", "OIDC_CLIENT_ID": "waypoint",
                   "OIDC_CLIENT_SECRET": "s3cret", "OIDC_ALLOWED_EMAILS": "me@example.com"}
        super().setUpClass()
        os.environ["WAYPOINT_PUBLIC_URL"] = cls.base                               # (put back with the rest of the environment)
        oidc._discovery.clear()
        oidc._jwks.clear()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.idp.shutdown()
        cls.idp.server_close()
        oidc._discovery.clear()
        oidc._jwks.clear()

    def sign_in_as(self, email):
        """A Waypoint session for `email`, signed in through the test provider."""
        login = self.http("GET", "/auth/login?next=/")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(login.location).query))
        code = "c-" + tag()
        Provider.issued[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "email": email}
        done = self.http("GET", f"/auth/callback?code={code}&state={q['state']}", cookies={"waypoint_login": login.cookie("waypoint_login").value})
        return {"waypoint_session": done.cookie("waypoint_session").value}

    def test_signed_out_goes_to_sign_in_and_back(self):
        c = self.client()
        first = self.authorize(c, scope="read write")
        self.assertEqual(first.status, 302)
        path = first.location
        self.assertTrue(path.startswith("/auth/login?next="))
        back_to = urllib.parse.unquote(path[len("/auth/login?next="):])
        self.assertTrue(back_to.startswith("/oauth/authorize?"))
        login = self.http("GET", path)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(login.location).query))
        Provider.issued["c-oauth"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "email": "me@example.com"}
        done = self.http("GET", f"/auth/callback?code=c-oauth&state={q['state']}", cookies={"waypoint_login": login.cookie("waypoint_login").value})
        self.assertEqual(done.location, back_to)                                  # the whole request survived
        self.assertEqual(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(back_to).query))["state"], "xyz/+&=")
        self.session = {"waypoint_session": done.cookie("waypoint_session").value}
        page = self.http("GET", done.location, cookies=self.session)
        self.assertEqual(page.status, 200)
        self.assertIn(b"signed in as <b>me@example.com</b>", page.body)
        r = self.answer(page)
        self.assertEqual(r.status, 302)
        t = self.exchange(c, r.query()["code"]).json
        with db.session() as conn:
            self.assertEqual(conn.execute(select(OAuthGrant.sub, OAuthGrant.email)
                                          .where(OAuthGrant.client_id == c["client_id"])).fetchone()[:],
                             ("user-1", "me@example.com"))
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)       # /mcp needs no session
        # The answer must come from the person who was shown the page
        page = self.http("GET", done.location, cookies=self.session)
        self.assertEqual(page.status, 200, "the session ended between the two fetches (logged out)")
        self.assertIn(b'name="consent" value="', page.body)
        self.session = {}
        signed_out = self.answer(page)
        self.assertEqual(signed_out.status, 302)
        self.assertTrue(signed_out.location.startswith("/auth/login"))

    def test_taken_off_the_sign_in_list_ends_their_assistants(self):
        self.session = self.sign_in_as("me@example.com")
        c = self.client()
        t = self.tokens(c)
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "someone-else@example.com"}):
            r = self.rpc(t["access_token"], "ping")                               # the very next request
            self.assertEqual(r.status, 401)
            self.assertEqual(r.headers["WWW-Authenticate"], f'Bearer realm="Waypoint", resource_metadata="{self.iss}'
                                                              '/.well-known/oauth-protected-resource/mcp", error="invalid_token"')
            self.assertEqual(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id.in_(self.clients))), "user_removed")
            r = self.form("/oauth/token", {"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": c["client_id"]})
            self.assertEqual((r.status, r.json["error"]), (400, "invalid_grant"))
            self.assertNotIn("access_token", r.json)
            grants = select(OAuthGrant.id).where(OAuthGrant.client_id.in_(self.clients))
            self.assertEqual(self.mine(select(func.count()).select_from(OAuthToken).where(OAuthToken.grant_id.in_(grants))), 0)
        self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)       # back on the list: still ended (reconnect)

    def test_a_person_still_allowed_keeps_their_assistant(self):
        self.session = self.sign_in_as("me@example.com")
        t = self.tokens()
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "me@example.com,someone-else@example.com"}):
            self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)
        self.assertIsNone(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id.in_(self.clients))))

    def test_a_code_approved_before_removal_is_not_exchanged(self):
        self.session = self.sign_in_as("me@example.com")
        c = self.client()
        code = self.code(c)
        with mock.patch.dict(os.environ, {"OIDC_ALLOWED_EMAILS": "someone-else@example.com"}):
            r = self.exchange(c, code)
        self.assertEqual((r.status, r.json["error"]), (400, "invalid_grant"))
        self.assertNotIn("access_token", r.json)

    def test_with_groups_a_sign_in_that_is_too_old_ends_their_assistants(self):
        self.session = self.sign_in_as("me@example.com")
        t = self.tokens()
        groups = {"OIDC_ALLOWED_GROUPS": "household", "WAYPOINT_SESSION_DAYS": "14"}
        with mock.patch.dict(os.environ, groups):
            self.assertEqual(self.rpc(t["access_token"], "ping").status, 200)     # signed in a moment ago
            with db.session() as conn:
                conn.execute(update(User).where(User.sub == "user-1").values(last_seen=time.time() - 15 * 86400))
            try:
                self.assertEqual(self.rpc(t["access_token"], "ping").status, 401)
                self.assertEqual(self.mine(select(OAuthGrant.revoked_reason).where(OAuthGrant.client_id.in_(self.clients))), "sign_in_lapsed")
            finally:
                with db.session() as conn:
                    conn.execute(update(User).where(User.sub == "user-1").values(last_seen=time.time()))


if __name__ == "__main__":
    unittest.main()
