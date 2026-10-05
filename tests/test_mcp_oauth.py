"""OAuth for the MCP endpoint, as functions over a database connection (waypoint/server/mcp_oauth.py): the HTTP side is
in tests/test_mcp_oauth_http.py. The grant types, PKCE, rotation and replay revocation, revocation, expiry of apps nobody
approved, and a grant ending when its approver can no longer sign in (oidc.access_lapsed) are held here."""
import base64
import hashlib
import json
import os
import time
import unittest
from unittest import mock

from sqlalchemy import delete, func, insert, select, update

from waypoint.storage import db
from waypoint.server import mcp_access, mcp_oauth
from tests.shared import add_database, database_path
from waypoint.server.mcp_oauth import OAuthError, PageError, RedirectError
from waypoint.storage.models import OAuthClient, OAuthCode, OAuthConsent, OAuthGrant, OAuthToken, User

ISS = "https://waypoint.example.com"
RES = ISS + "/mcp"
TABLES = (OAuthClient, OAuthGrant, OAuthCode, OAuthToken, OAuthConsent)


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


VERIFIER = "v" * 50
CHALLENGE = challenge(VERIFIER)


def clear(conn):
    for t in TABLES:
        conn.execute(delete(t))


class Db(unittest.TestCase):
    """A database of its own (on Postgres, its own schema), so these tests may clear the OAuth tables and count their rows
    while other test modules run alongside."""
    @classmethod
    def setUpClass(cls):
        cls.path = add_database(cls, database_path(cls, "oauth.db"))

    def setUp(self):
        self.conn = db.connect(self.path)
        clear(self.conn)

    def tearDown(self):
        clear(self.conn)
        self.conn.commit()
        self.conn.close()

    def count(self, model, *where):
        return self.conn.execute(select(func.count()).select_from(model).where(*where)).fetchone()[0]

    def client(self, **meta):
        return mcp_oauth.register(self.conn, {"client_name": "Claude", "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"], **meta})

    def request(self, client, **over):
        q = {"response_type": "code", "client_id": client["client_id"], "redirect_uri": client["redirect_uris"][0],
             "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "st", **over}
        return mcp_oauth.check_authorize(self.conn, {k: [v] for k, v in q.items() if v is not None}, ISS)

    def code(self, client, scope=frozenset({"read"}), now=None, **over):
        req = self.request(client, **over)
        return mcp_oauth.approve(self.conn, req.params(), scope, "sub-1", "me@example.com", now), req

    def tokens(self, client, scope=frozenset({"read"}), now=None):
        code, req = self.code(client, scope, now)
        c = mcp_oauth.get_client(self.conn, client["client_id"])
        return mcp_oauth.token(self.conn, c, {"grant_type": "authorization_code", "code": code, "redirect_uri": req.redirect_uri,
                                              "code_verifier": VERIFIER}, ISS, now)


class IssuerTests(unittest.TestCase):
    """The address OAuth is served at (WAYPOINT_PUBLIC_URL, or a home address) and the two metadata documents."""
    def issuer(self, host, public=None):
        env = {"WAYPOINT_PUBLIC_URL": public} if public is not None else {}
        with mock.patch.dict(os.environ, env):
            if public is None:
                os.environ.pop("WAYPOINT_PUBLIC_URL", None)
            return mcp_oauth.issuer(host)

    def test_public_url_wins_over_the_host(self):
        self.assertEqual(self.issuer("evil.example", "https://waypoint.example.com/"), "https://waypoint.example.com")
        self.assertEqual(self.issuer("127.0.0.1:8765", "https://waypoint.example.com"), "https://waypoint.example.com")
        self.assertEqual(self.issuer("x", "http://nas.local:8765"), "http://nas.local:8765")
        self.assertIsNone(self.issuer("127.0.0.1", "http://waypoint.example.com"))
        for odd in ('https://waypoint.example.com/"x', "https://waypoint.example.com/a b", "https://user@waypoint.example.com", "ftp://x.example"):
            with self.subTest(public=odd):
                self.assertIsNone(self.issuer("127.0.0.1", odd))

    def test_without_it_only_a_home_address(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "nas.local", "[::1]:8765", "192.168.1.5", "homeserver"):
            with self.subTest(host=host):
                self.assertEqual(self.issuer(host), "http://" + host)
        for host in ("waypoint.example.com", "8.8.8.8", "", None, '127.0.0.1:87"65', "127.0.0.1 x", "127.0.0.1:99999999"):
            with self.subTest(host=host):
                self.assertIsNone(self.issuer(host))

    def test_metadata(self):
        self.assertEqual(mcp_oauth.protected_resource_metadata(ISS), {
            "resource": RES, "authorization_servers": [ISS], "scopes_supported": ["read", "write"],
            "bearer_methods_supported": ["header"]})
        m = mcp_oauth.authorization_server_metadata(ISS)
        self.assertEqual((m["issuer"], m["authorization_endpoint"], m["token_endpoint"], m["registration_endpoint"], m["revocation_endpoint"]),
                         (ISS, ISS + "/oauth/authorize", ISS + "/oauth/token", ISS + "/oauth/register", ISS + "/oauth/revoke"))
        self.assertEqual(m["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(m["response_types_supported"], ["code"])
        self.assertEqual(m["grant_types_supported"], ["authorization_code", "refresh_token"])
        self.assertEqual(m["token_endpoint_auth_methods_supported"], ["none", "client_secret_post", "client_secret_basic"])


class ValueTests(unittest.TestCase):
    """The checks on what an app sends: redirect URIs, scopes, resource, PKCE and what the consent page says each opt-in allows."""
    def test_redirect_uris(self):
        for ok in ("https://claude.ai/api/mcp/auth_callback", "https://x.example:8443/cb?a=1", "http://127.0.0.1:33418/callback",
                   "http://localhost/cb", "http://[::1]:5000/cb"):
            with self.subTest(uri=ok):
                self.assertEqual(mcp_oauth.check_redirect_uri(ok), ok)
        for bad in ("cursor://anysphere.cursor-retrieval/oauth", "com.example.app:/cb", "http://example.com/cb", "http://192.168.1.2/cb",
                    "https://claude.ai/cb#frag", "https://user:pw@claude.ai/cb", "https://user@claude.ai/cb", "javascript:alert(1)",
                    "https:///nohost", "https://exa mple.com/", "https://claude.ai/\ncb", "https://claude.ai:x/cb", "", None, 5,
                    "https://claude.ai/" + "a" * 2000, "https://clаude.ai/cb", "https://claude.ai\\@evil.com/", "data:text/html,x",
                    "http://127.0.0.1.evil.com/cb", "https://evil.com\"/cb"):
            with self.subTest(uri=bad), self.assertRaises(OAuthError) as e:
                mcp_oauth.check_redirect_uri(bad)
            self.assertEqual(e.exception.error, "invalid_redirect_uri")

    def test_redirect_matching(self):
        reg = ["https://claude.ai/cb", "http://127.0.0.1:1234/callback"]
        self.assertTrue(mcp_oauth.redirect_matches(reg, "https://claude.ai/cb"))
        self.assertTrue(mcp_oauth.redirect_matches(reg, "http://127.0.0.1:5555/callback"))
        self.assertTrue(mcp_oauth.redirect_matches(reg, "http://127.0.0.1/callback"))
        for bad in ("https://claude.ai/cb/", "https://claude.ai/cb?x=1", "https://claude.ai:443/cb", "https://CLAUDE.ai/cb",
                    "http://localhost:1234/callback", "http://127.0.0.1:1234/callback/x", "http://127.0.0.1:1234/callback#x",
                    "https://127.0.0.1:1234/callback", None, ""):
            with self.subTest(uri=bad):
                self.assertFalse(mcp_oauth.redirect_matches(reg, bad))

    def test_what_the_consent_page_says_each_opt_in_allows(self):
        self.assertEqual(set(mcp_oauth.CONSENT), {"write"})   # nothing opens full ID numbers to an assistant
        label, note, off = mcp_oauth.CONSENT["write"]
        self.assertEqual(label, "Change trips")
        for words in ("Add, change and remove trips, bookings, travellers, people and guests, and the distance unit",
                      "Never mailboxes", "AI settings, backups, loyalty numbers, sign-in or these assistant settings"):
            self.assertIn(words, note)
        self.assertIn("Let assistants change trips", off)

    def test_scopes(self):
        self.assertEqual(mcp_oauth.parse_scope(None), {"read"})
        self.assertEqual(mcp_oauth.parse_scope(""), {"read"})
        self.assertEqual(mcp_oauth.parse_scope("write"), {"read", "write"})
        self.assertEqual(mcp_oauth.scope_text(mcp_oauth.parse_scope("write read")), "read write")
        for bad in ("writes", "write:all", "read admin", "openid", "ids:read", "read ids:read", "churning:write", "categorize:write", 5):
            with self.subTest(scope=bad), self.assertRaises(OAuthError) as e:
                mcp_oauth.parse_scope(bad)
            self.assertEqual(e.exception.error, "invalid_scope")

    def test_resource(self):
        mcp_oauth.check_resource(None, RES)
        mcp_oauth.check_resource(RES + "/", RES)
        for bad in ("https://waypoint.example.com", "https://other.example/mcp", RES + "/x", 5):
            with self.subTest(res=bad), self.assertRaises(OAuthError) as e:
                mcp_oauth.check_resource(bad, RES)
            self.assertEqual(e.exception.error, "invalid_target")

    def test_pkce(self):
        self.assertTrue(mcp_oauth.pkce_ok(VERIFIER, CHALLENGE))
        self.assertFalse(mcp_oauth.pkce_ok("w" * 50, CHALLENGE))
        self.assertFalse(mcp_oauth.pkce_ok("short", challenge("short")))
        self.assertFalse(mcp_oauth.pkce_ok(None, CHALLENGE))

    def test_with_params_keeps_the_query(self):
        self.assertEqual(mcp_oauth.with_params("https://a.example/cb?x=1", {"code": "c", "state": "a b&c", "none": None}),
                         "https://a.example/cb?x=1&code=c&state=a+b%26c")


class RegistrationTests(Db):
    """Dynamic client registration: what's saved, what's refused, and the cap on apps nobody has approved."""
    def test_a_public_client(self):
        out = self.client()
        self.assertTrue(out["client_id"].startswith("wpc_"))
        self.assertEqual((out["token_endpoint_auth_method"], out["grant_types"], out["response_types"], out["client_name"]),
                         ("none", ["authorization_code", "refresh_token"], ["code"], "Claude"))
        self.assertNotIn("client_secret", out)
        self.assertNotIn("registration_access_token", out)
        row = self.conn.execute(select(OAuthClient)).fetchone()
        self.assertEqual((row["kind"], row["metadata_url"], row["secret_hash"]), ("dcr", None, None))

    def test_a_confidential_client_gets_a_secret_kept_as_a_hash(self):
        out = self.client(token_endpoint_auth_method="client_secret_post")
        self.assertEqual(out["client_secret_expires_at"], 0)
        stored = self.conn.execute(select(OAuthClient.secret_hash)).fetchone()[0]
        self.assertEqual(stored, hashlib.sha256(out["client_secret"].encode()).hexdigest())

    def test_refusals(self):
        for meta, error in (({"redirect_uris": []}, "invalid_redirect_uri"),
                            ({"redirect_uris": "https://a.example/cb"}, "invalid_redirect_uri"),
                            ({"redirect_uris": [f"https://a.example/{i}" for i in range(11)]}, "invalid_redirect_uri"),
                            ({"redirect_uris": ["myapp://cb"]}, "invalid_redirect_uri"),
                            ({"client_name": "x" * 101}, "invalid_client_metadata"),
                            ({"client_name": "bad\nname"}, "invalid_client_metadata"),
                            ({"client_name": 5}, "invalid_client_metadata"),
                            ({"token_endpoint_auth_method": "private_key_jwt"}, "invalid_client_metadata"),
                            ({"grant_types": ["client_credentials"]}, "invalid_client_metadata"),
                            ({"grant_types": ["refresh_token"]}, "invalid_client_metadata"),
                            ({"response_types": ["token"]}, "invalid_client_metadata"),
                            ({"scope": "admin"}, "invalid_client_metadata")):
            with self.subTest(meta=meta), self.assertRaises(OAuthError) as e:
                self.client(**meta)
            self.assertEqual(e.exception.error, error)
        with self.assertRaises(OAuthError):
            mcp_oauth.register(self.conn, ["not", "an", "object"])
        with self.assertRaises(OAuthError):
            mcp_oauth.register(self.conn, {"client_name": "no redirect uris"})
        self.assertEqual(self.count(OAuthClient), 0)

    def test_ids_read_is_not_a_scope_to_register_for(self):
        with self.assertRaises(OAuthError) as e:
            self.client(scope="read ids:read")
        self.assertEqual(e.exception.error, "invalid_client_metadata")
        self.assertEqual(self.count(OAuthClient), 0)

    def test_at_most_fifty_unapproved_apps_at_once(self):
        first = mcp_oauth.register(self.conn, {"redirect_uris": ["https://a.example/cb"]}, now=1000)
        approved = mcp_oauth.register(self.conn, {"redirect_uris": ["https://b.example/cb"]}, now=1001)
        gid = self.conn.execute(insert(OAuthGrant).values(client_id=approved["client_id"], scope="read", resource=RES,
                                                          created=1001)).lastrowid
        self.conn.execute(insert(OAuthToken).values(token_hash="h", kind="refresh", grant_id=gid, created=1001, expires=9e12))
        burst = 1000 + mcp_oauth.CONSENT_TTL + 10
        for i in range(60):
            mcp_oauth.register(self.conn, {"redirect_uris": ["https://c.example/cb"]}, now=burst + i / 100)
        self.assertEqual(self.count(OAuthClient), 62)
        self.assertIsNotNone(mcp_oauth.get_client(self.conn, first["client_id"]))
        later = burst + mcp_oauth.CONSENT_TTL + 10
        mcp_oauth.register(self.conn, {"redirect_uris": ["https://d.example/cb"]}, now=later)
        self.assertEqual(self.count(OAuthClient), 51)
        self.assertIsNone(mcp_oauth.get_client(self.conn, first["client_id"]))
        self.assertIsNotNone(mcp_oauth.get_client(self.conn, approved["client_id"]))
        with mock.patch.object(mcp_oauth, "MAX_UNCONSENTED_ALL", 70):
            for i in range(30):
                mcp_oauth.register(self.conn, {"redirect_uris": ["https://e.example/cb"]}, now=later + 1 + i / 100)
        self.assertEqual(self.count(OAuthClient), 71)


class ClientAuthTests(Db):
    """How an app proves who it is on /oauth/token and /oauth/revoke, the way it registered."""
    def auth(self, form, header=None):
        return mcp_oauth.authenticate_client(self.conn, form, header)

    def basic(self, cid, secret):
        return "Basic " + base64.b64encode(f"{cid}:{secret}".encode()).decode()

    def test_public_client(self):
        c = self.client()
        self.assertEqual(self.auth({"client_id": c["client_id"]})["id"], c["client_id"])
        for form, header in (({}, None), ({"client_id": "wpc_nope"}, None), ({"client_id": "other"}, None),
                             ({"client_id": c["client_id"], "client_secret": "x"}, None)):
            with self.subTest(form=form), self.assertRaises(OAuthError) as e:
                self.auth(form, header)
            self.assertEqual((e.exception.error, e.exception.status), ("invalid_client", 401))

    def test_secret_post_and_basic(self):
        post = self.client(token_endpoint_auth_method="client_secret_post")
        basic = self.client(token_endpoint_auth_method="client_secret_basic")
        self.assertTrue(self.auth({"client_id": post["client_id"], "client_secret": post["client_secret"]}))
        self.assertTrue(self.auth({}, self.basic(basic["client_id"], basic["client_secret"])))
        self.assertTrue(self.auth({"client_id": basic["client_id"]}, self.basic(basic["client_id"], basic["client_secret"])))
        for form, header in (({"client_id": post["client_id"], "client_secret": "wrong"}, None),
                             ({"client_id": post["client_id"]}, None),
                             ({}, self.basic(post["client_id"], post["client_secret"])),
                             ({"client_id": basic["client_id"], "client_secret": basic["client_secret"]}, None),
                             ({}, self.basic(basic["client_id"], "wrong")),
                             ({"client_id": post["client_id"]}, self.basic(basic["client_id"], basic["client_secret"])),
                             ({}, "Basic !!!"), ({}, "Basic " + base64.b64encode(b"no-colon").decode())):
            with self.subTest(form=form, header=header), self.assertRaises(OAuthError) as e:
                self.auth(form, header)
            self.assertEqual(e.exception.status, 401)
        with self.assertRaises(OAuthError) as e:
            self.auth({"client_secret": basic["client_secret"]}, self.basic(basic["client_id"], basic["client_secret"]))
        self.assertEqual(e.exception.error, "invalid_request")


class AuthorizeTests(Db):
    """The authorization request, and the consent form's token (kept once, for ten minutes)."""
    def test_a_good_request(self):
        c = self.client()
        req = self.request(c, scope="write", resource=RES + "/")
        self.assertEqual((req.client_id, req.scope, req.state, req.resource), (c["client_id"], {"read", "write"}, "st", RES))

    def test_the_app_and_its_redirect_must_be_known_or_nothing_is_sent_back(self):
        c = self.client()
        for over in ({"client_id": "wpc_unknown"}, {"client_id": None}, {"redirect_uri": "https://evil.example/cb"},
                     {"redirect_uri": None}, {"redirect_uri": "https://claude.ai/api/mcp/auth_callback/"}):
            with self.subTest(over=over), self.assertRaises(PageError):
                self.request(c, **over)
        with self.assertRaises(PageError):
            mcp_oauth.check_authorize(self.conn, {"client_id": [c["client_id"]] * 2}, ISS)

    def test_other_mistakes_go_back_to_the_app(self):
        c = self.client()
        for over, error in (({"response_type": "token"}, "unsupported_response_type"), ({"code_challenge_method": None}, "invalid_request"),
                            ({"code_challenge_method": "plain"}, "invalid_request"), ({"code_challenge": None}, "invalid_request"),
                            ({"code_challenge": "short"}, "invalid_request"), ({"scope": "admin"}, "invalid_scope"), ({"scope": "read ids:read"}, "invalid_scope"),
                            ({"resource": "https://other.example/mcp"}, "invalid_target")):
            with self.subTest(over=over), self.assertRaises(RedirectError) as e:
                self.request(c, **over)
            self.assertEqual((e.exception.error, e.exception.redirect_uri, e.exception.state), (error, c["redirect_uris"][0], "st"))

    def test_consent_is_taken_once_and_expires(self):
        token = mcp_oauth.start_consent(self.conn, {"a": 1}, now=1000)
        self.assertNotIn(token, json.dumps([dict(r) for r in self.conn.execute(select(OAuthConsent))]))
        self.assertIsNone(mcp_oauth.take_consent(self.conn, token + "x", now=1001))
        self.assertEqual(mcp_oauth.take_consent(self.conn, token, now=1001), {"a": 1})
        self.assertIsNone(mcp_oauth.take_consent(self.conn, token, now=1001))
        old = mcp_oauth.start_consent(self.conn, {"a": 1}, now=1000)
        self.assertIsNone(mcp_oauth.take_consent(self.conn, old, now=1000 + mcp_oauth.CONSENT_TTL + 1))
        self.assertIsNone(mcp_oauth.take_consent(self.conn, None))


class TokenTests(Db):
    """Codes, tokens, refresh rotation and its replay revocation, expiry, use being noted and revocation."""
    def exchange(self, client_id, the_code, **over):
        form = {"grant_type": "authorization_code", "code": the_code, "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
                "code_verifier": VERIFIER, **over}
        return mcp_oauth.token(self.conn, mcp_oauth.get_client(self.conn, client_id), {k: v for k, v in form.items() if v is not None}, ISS)

    def test_code_for_tokens(self):
        c = self.client()
        code, _ = self.code(c, frozenset({"read", "write"}))
        self.assertTrue(code.startswith("wpo_"))
        out = self.exchange(c["client_id"], code, resource=RES)
        self.assertEqual((out["token_type"], out["expires_in"], out["scope"]), ("Bearer", 3600, "read write"))
        self.assertTrue(out["access_token"].startswith("wpa_") and out["refresh_token"].startswith("wpr_"))
        stored = json.dumps([list(r) for r in self.conn.execute(select(OAuthToken))] + [list(r) for r in self.conn.execute(select(OAuthCode))])
        for secret in (out["access_token"], out["refresh_token"], code):
            self.assertNotIn(secret, stored)
        access = mcp_access.resolve_bearer(self.conn, "Bearer " + out["access_token"], RES)
        self.assertEqual((access.scopes, access.sub, access.email), ({"read", "write"}, "sub-1", "me@example.com"))

    def test_code_refusals(self):
        c = self.client()
        other = self.client()
        for over in ({"code_verifier": "w" * 50}, {"redirect_uri": "https://claude.ai/other"}, {"code": "wpo_nope"},
                     {"resource": "https://other.example/mcp"}):
            with self.subTest(over=over):
                code, _ = self.code(c)
                with self.assertRaises(OAuthError) as e:
                    self.exchange(c["client_id"], code, **over)
                self.assertIn(e.exception.error, ("invalid_grant", "invalid_target"))
        code, _ = self.code(c)
        with self.assertRaises(OAuthError) as e:
            self.exchange(other["client_id"], code)
        self.assertEqual(e.exception.error, "invalid_grant")
        code, _ = self.code(c)
        with self.assertRaises(OAuthError) as e:
            self.exchange(c["client_id"], code, code_verifier=None)
        self.assertEqual(e.exception.error, "invalid_request")
        with self.assertRaises(OAuthError) as e:
            self.exchange(c["client_id"], code, grant_type="password")
        self.assertEqual(e.exception.error, "unsupported_grant_type")

    def test_an_expired_code(self):
        c = self.client()
        code, _ = self.code(c, now=time.time() - mcp_oauth.CODE_TTL - 5)
        with self.assertRaises(OAuthError) as e:
            self.exchange(c["client_id"], code)
        self.assertEqual(e.exception.error, "invalid_grant")

    def test_a_code_used_twice_revokes_its_grant(self):
        c = self.client()
        code, _ = self.code(c)
        out = self.exchange(c["client_id"], code)
        with self.assertRaises(OAuthError) as e:
            self.exchange(c["client_id"], code)
        self.assertEqual(e.exception.error, "invalid_grant")
        self.assertEqual(self.conn.execute(select(OAuthGrant.revoked_reason)).fetchone()[0], "code_reuse")
        self.assertIsNone(mcp_access.resolve_bearer(self.conn, "Bearer " + out["access_token"], RES))

    def refresh(self, client_id, token, **over):
        return mcp_oauth.token(self.conn, mcp_oauth.get_client(self.conn, client_id),
                               {"grant_type": "refresh_token", "refresh_token": token, **over}, ISS)

    def test_refresh_rotates_and_a_replay_revokes_everything(self):
        c = self.client()
        first = self.tokens(c)
        second = self.refresh(c["client_id"], first["refresh_token"])
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.assertEqual(second["scope"], "read")
        third = self.refresh(c["client_id"], second["refresh_token"])
        self.assertIsNotNone(mcp_access.resolve_bearer(self.conn, "Bearer " + third["access_token"], RES))
        with self.assertRaises(OAuthError) as e:
            self.refresh(c["client_id"], first["refresh_token"])
        self.assertEqual(e.exception.error, "invalid_grant")
        self.assertEqual(self.conn.execute(select(OAuthGrant.revoked_reason)).fetchone()[0], "refresh_reuse")
        self.assertIsNone(mcp_access.resolve_bearer(self.conn, "Bearer " + third["access_token"], RES))
        with self.assertRaises(OAuthError):
            self.refresh(c["client_id"], third["refresh_token"])

    def test_refresh_refusals(self):
        c, other = self.client(), self.client()
        out = self.tokens(c)
        for client_id, over in ((other["client_id"], {}), (c["client_id"], {"scope": "write"}),
                                (c["client_id"], {"resource": "https://other.example/mcp"}), (c["client_id"], {"refresh_token": "wpr_nope"}),
                                (c["client_id"], {"refresh_token": out["access_token"]})):
            with self.subTest(over=over), self.assertRaises(OAuthError):
                self.refresh(client_id, out["refresh_token"], **over)
        with self.assertRaises(OAuthError) as e:                                  # ids:read is no scope at all
            self.refresh(c["client_id"], out["refresh_token"], scope="read ids:read")
        self.assertEqual(e.exception.error, "invalid_scope")
        again = self.refresh(c["client_id"], out["refresh_token"], scope="read")
        self.conn.execute(update(OAuthToken)
                          .where(OAuthToken.consumed.is_(None), OAuthToken.kind == "refresh").values(expires=1))
        with self.assertRaises(OAuthError) as e:
            self.refresh(c["client_id"], again["refresh_token"])
        self.assertEqual(e.exception.error, "invalid_grant")

    def test_access_tokens_expire_and_belong_to_one_resource(self):
        c = self.client()
        out = self.tokens(c)
        bearer = "Bearer " + out["access_token"]
        self.assertIsNotNone(mcp_access.resolve_bearer(self.conn, bearer, RES))
        self.assertIsNotNone(mcp_access.resolve_bearer(self.conn, "bearer  " + out["access_token"], RES))
        for auth, res in ((bearer, "https://other.example/mcp"), (bearer, None), (out["access_token"], RES), ("Bearer " + out["refresh_token"], RES),
                          (bearer + "x", RES), (None, RES), ("Bearer wpm_x", RES)):
            with self.subTest(auth=auth, res=res):
                self.assertIsNone(mcp_access.resolve_bearer(self.conn, auth, res))
        self.conn.execute(update(OAuthToken).where(OAuthToken.kind == "access").values(expires=1))
        self.assertIsNone(mcp_access.resolve_bearer(self.conn, bearer, RES))

    def test_use_is_noted(self):
        c = self.client()
        out = self.tokens(c)
        mcp_access.resolve_bearer(self.conn, "Bearer " + out["access_token"], RES)
        self.assertIsNotNone(self.conn.execute(select(OAuthGrant.last_used)).fetchone()[0])
        self.assertIsNotNone(self.conn.execute(select(OAuthClient.last_used)).fetchone()[0])

    def test_revoke(self):
        c, other = self.client(), self.client()
        out = self.tokens(c)
        client = mcp_oauth.get_client(self.conn, c["client_id"])
        mcp_oauth.revoke(self.conn, mcp_oauth.get_client(self.conn, other["client_id"]), out["refresh_token"])
        mcp_oauth.revoke(self.conn, client, "wpr_unknown")
        mcp_oauth.revoke(self.conn, client, None)
        self.assertIsNotNone(mcp_access.resolve_bearer(self.conn, "Bearer " + out["access_token"], RES))
        mcp_oauth.revoke(self.conn, client, out["refresh_token"])
        self.assertIsNone(mcp_access.resolve_bearer(self.conn, "Bearer " + out["access_token"], RES))
        self.assertEqual(self.conn.execute(select(OAuthGrant.revoked_reason)).fetchone()[0], "revoked_by_client")
        self.assertEqual(self.count(OAuthToken), 0)
        self.assertEqual(mcp_oauth.connections(self.conn), [])

    def test_connections(self):
        c = self.client()
        self.tokens(c, frozenset({"read", "write"}))
        self.code(c)
        got = mcp_oauth.connections(self.conn)
        self.assertEqual([(g["client"], g["who"], g["scope"]) for g in got], [("Claude", "me@example.com", ["read", "write"])])
        self.assertTrue(mcp_oauth.revoke_grant(self.conn, got[0]["id"], "revoked_in_settings"))
        self.assertFalse(mcp_oauth.revoke_grant(self.conn, got[0]["id"], "revoked_in_settings"))
        self.assertEqual(mcp_oauth.connections(self.conn), [])


OIDC = {"OIDC_ISSUER": "https://id.example.com", "OIDC_CLIENT_ID": "waypoint"}
OIDC_RULES = ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_ALLOWED_EMAILS", "OIDC_ALLOWED_GROUPS", "OIDC_ALLOW_ANY_USER",
              "OIDC_TRUST_UNVERIFIED_EMAIL", "WAYPOINT_SESSION_DAYS")


def sign_in(**env):
    """Waypoint's sign-in rules as these environment variables say (the rest unset)."""
    patch = mock.patch.dict(os.environ, env)
    patch.start()
    for k in OIDC_RULES:
        if k not in env:
            os.environ.pop(k, None)
    return patch


class ApproverTests(Db):
    """An approval lasts only as long as its approver may sign in (mcp_oauth.cut_off_reason, by oidc.still_allowed)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(sign_in(**OIDC, OIDC_ALLOWED_EMAILS="me@example.com,partner@example.com").stop)

    def connect(self, sub, email, scope=frozenset({"read"}), now=None):
        c = self.client()
        req = self.request(c)
        code = mcp_oauth.approve(self.conn, req.params(), scope, sub, email, now)
        return c, mcp_oauth.token(self.conn, mcp_oauth.get_client(self.conn, c["client_id"]),
                                  {"grant_type": "authorization_code", "code": code, "redirect_uri": req.redirect_uri,
                                   "code_verifier": VERIFIER}, ISS, now)

    def works(self, out):
        return mcp_access.resolve_bearer(self.conn, "Bearer " + out["access_token"], RES) is not None

    def reason(self, client):
        return self.conn.execute(select(OAuthGrant.revoked_reason)
                                 .where(OAuthGrant.client_id == client["client_id"])).fetchone()[0]

    def tokens_of(self, client):
        return self.count(OAuthToken, OAuthToken.grant_id.in_(select(OAuthGrant.id).where(OAuthGrant.client_id == client["client_id"])))

    def test_taken_off_the_email_list_ends_their_assistants_and_no_one_elses(self):
        mine, mine_out = self.connect("sub-me", "me@example.com")
        theirs, theirs_out = self.connect("sub-partner", "partner@example.com")
        self.assertTrue(self.works(mine_out) and self.works(theirs_out))
        os.environ["OIDC_ALLOWED_EMAILS"] = "partner@example.com"
        self.assertFalse(self.works(mine_out))
        self.assertEqual(self.reason(mine), "user_removed")
        self.assertTrue(self.works(theirs_out))
        self.assertIsNone(self.reason(theirs))
        with self.assertRaises(OAuthError) as e:
            mcp_oauth.token(self.conn, mcp_oauth.get_client(self.conn, mine["client_id"]),
                            {"grant_type": "refresh_token", "refresh_token": mine_out["refresh_token"]}, ISS)
        self.assertEqual(e.exception.error, "invalid_grant")
        self.assertEqual(self.tokens_of(mine), 0)
        self.assertEqual([c["who"] for c in mcp_oauth.connections(self.conn)], ["partner@example.com"])
        os.environ["OIDC_ALLOWED_EMAILS"] = "me@example.com,partner@example.com"
        self.assertFalse(self.works(mine_out))

    def test_refresh_is_refused_even_before_the_next_request(self):
        mine, out = self.connect("sub-me", "me@example.com")
        os.environ["OIDC_ALLOWED_EMAILS"] = "partner@example.com"
        with self.assertRaises(OAuthError) as e:
            mcp_oauth._refresh(self.conn, mcp_oauth.get_client(self.conn, mine["client_id"]),
                               {"refresh_token": out["refresh_token"]}, RES, time.time())
        self.assertEqual(e.exception.error, "invalid_grant")
        self.assertEqual((self.reason(mine), self.tokens_of(mine)), ("user_removed", 0))

    def test_a_code_approved_before_removal_is_not_exchanged(self):
        c = self.client()
        req = self.request(c)
        code = mcp_oauth.approve(self.conn, req.params(), frozenset({"read"}), "sub-me", "me@example.com")
        os.environ["OIDC_ALLOWED_EMAILS"] = "partner@example.com"
        with self.assertRaises(OAuthError) as e:
            mcp_oauth._exchange_code(self.conn, mcp_oauth.get_client(self.conn, c["client_id"]),
                                     {"code": code, "redirect_uri": req.redirect_uri, "code_verifier": VERIFIER}, RES, time.time())
        self.assertEqual(e.exception.error, "invalid_grant")
        self.assertEqual(self.reason(c), "user_removed")

    def test_settings_stops_listing_a_removed_persons_assistant_even_unused(self):
        self.connect("sub-me", "me@example.com")
        self.assertEqual(len(mcp_oauth.connections(self.conn)), 1)
        os.environ["OIDC_ALLOWED_EMAILS"] = "partner@example.com"
        self.assertEqual(mcp_oauth.connections(self.conn), [])
        self.assertEqual(self.count(OAuthGrant, OAuthGrant.revoked_reason == "user_removed"), 1)

    def test_without_sign_in_grants_keep_working(self):
        self.addCleanup(sign_in().stop)
        c, out = self.connect(None, None)
        self.assertTrue(self.works(out))
        mcp_oauth.housekeeping(self.conn)
        self.assertTrue(self.works(out))
        self.assertIsNone(self.reason(c))

    def test_an_approval_from_before_sign_in_was_set_up_ends_with_it(self):
        self.addCleanup(sign_in().stop)
        c, out = self.connect(None, None)
        self.addCleanup(sign_in(**OIDC, OIDC_ALLOWED_EMAILS="me@example.com").stop)
        self.assertFalse(self.works(out))
        self.assertEqual(self.reason(c), "user_removed")

    def test_anyone_allowed_means_nobody_is_cut_off(self):
        self.addCleanup(sign_in(**OIDC, OIDC_ALLOW_ANY_USER="1").stop)
        _c, out = self.connect("sub-x", "stranger@example.com")
        self.assertTrue(self.works(out))

    def test_with_groups_an_approval_lasts_as_long_as_a_sign_in(self):
        self.addCleanup(sign_in(**OIDC, OIDC_ALLOWED_GROUPS="household", WAYPOINT_SESSION_DAYS="14").stop)
        now = time.time()
        for sub in ("recent", "lapsed", "gone"):
            self.conn.execute(insert(User).values(sub=sub, email=sub + "@example.com", last_seen=now - 60))
        outs = {sub: self.connect(sub, sub + "@example.com") for sub in ("recent", "lapsed", "gone")}
        self.assertTrue(all(self.works(out) for _c, out in outs.values()))
        self.conn.execute(update(User).where(User.sub == "recent").values(last_seen=now - 13 * 86400))
        self.conn.execute(update(User).where(User.sub == "lapsed").values(last_seen=now - 15 * 86400))
        self.conn.execute(delete(User).where(User.sub == "gone"))
        self.assertTrue(self.works(outs["recent"][1]))
        self.assertFalse(self.works(outs["lapsed"][1]))
        self.assertFalse(self.works(outs["gone"][1]))
        self.assertEqual([self.reason(outs[s][0]) for s in ("recent", "lapsed", "gone")], [None, "sign_in_lapsed", "sign_in_lapsed"])
        with self.assertRaises(OAuthError):
            self.connect("lapsed", "lapsed@example.com")


class HousekeepingTests(Db):
    """What housekeeping keeps and what it deletes (apps nobody approved after a day, spent tokens, old codes)."""
    def test_what_is_kept_and_what_goes(self):
        now = 10_000_000.0
        day = 86400
        live = mcp_oauth.register(self.conn, {"redirect_uris": ["https://a.example/cb"]}, now=now - 100 * day)
        self.tokens(live, now=now - 700)
        fresh = mcp_oauth.register(self.conn, {"redirect_uris": ["https://b.example/cb"]}, now=now - 60)
        waiting = mcp_oauth.register(self.conn, {"redirect_uris": ["https://c.example/cb"]}, now=now - 20 * 3600)
        stale = mcp_oauth.register(self.conn, {"redirect_uris": ["https://c.example/cb"]}, now=now - 25 * 3600)
        unused_code, _ = self.code(fresh, now=now - 3600)
        mcp_oauth.start_consent(self.conn, {}, now=now - 3600)
        mcp_oauth.start_consent(self.conn, {}, now=now - 60)
        spent = self.tokens(mcp_oauth.register(self.conn, {"redirect_uris": ["https://d.example/cb"]}, now=now - 100 * day), now=now - 40 * day)
        del spent, unused_code
        mcp_oauth.housekeeping(self.conn, now)
        ids = {r[0] for r in self.conn.execute(select(OAuthClient.id))}
        self.assertIn(live["client_id"], ids)
        self.assertIn(fresh["client_id"], ids)
        self.assertIn(waiting["client_id"], ids)
        self.assertNotIn(stale["client_id"], ids)
        self.assertEqual(self.count(OAuthCode), 0)
        self.assertEqual(self.count(OAuthConsent), 1)
        self.assertEqual(self.count(OAuthGrant), 2)
        self.assertEqual(self.count(OAuthToken), 3)
        self.assertEqual(self.count(OAuthToken, OAuthToken.kind == "access"), 1)


if __name__ == "__main__":
    unittest.main()
