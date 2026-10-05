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
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

from sqlalchemy import select, update

from waypoint.storage import db
from waypoint import monitoring, oidc, server
from waypoint.storage.models import AuthPending, AuthSession, User
from tests.shared import NoRedirect, own_database

N = 0xf0e468c25263ab5b85ed863374cc64adae8284623519e21e7cbf01e2554656a58f8f69140ff8e701322655b598044841a7839a25b81c3737ee8141ee25ba7e6a46706540e49f61b7a321ad1e53d9bf44770558691d32aafb0edb49104ad0e9cc29074e856c22d864d285dbad96d228fb509f00b7d065ba0188d8c511efaee63001347fbe9939df1497b5efaf2e0d54626c6d1b3152397d3737b0e35141e1e58da75badd4f9897236e4d4c9b35ec9a0037c19152f1f7dc2cea916100588f76fd5ad4668da24e037339e9d34ab75ba37b91037a62ba7800df275f48651e231f021d7eb1c48006b016c1daff8d6d40a7446a8209b9666a85e5c04b999c38b3003a1
D = 0xcea925b6903831aa331bb32631eda7f1d8e4dfede0e073bcf40869f5627315a2b3a6b4df2154c7d99ecc847b660f466e0ce83a3661dcd30288fb1b34d3e94acaa1e38afa4128fb0c304793dd90d21de4feb6f742366a618541199f74faba7fd946d99de39901cbe3b338635e6925a342f7c7713640f304c08c466bcb177554c3f024ea80a55aa110bd895aff210a164ecf7844e674ba9120f510f4b148d42e67136c701859afeb76c4526520b920afb22c594cee4c49098a9f5c150fffc6b709f9e4f14a4983fe079214de100fc0952b6a4dc0454c8fd6dec1f4748d59590a0aa048842308f7c31b07e53900cf55ebb68350d0e26cc69cbf83b88fb55f88b69
E = 65537


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign(claims: dict, kid="k1", key_d=D) -> str:
    head = b64(json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}).encode())
    body = b64(json.dumps(claims).encode())
    digest = hashlib.sha256(f"{head}.{body}".encode()).digest()
    size = (N.bit_length() + 7) // 8
    em = b"\x00\x01" + b"\xff" * (size - 3 - 19 - 32) + b"\x00" + bytes.fromhex("3031300d060960864801650304020105000420") + digest
    sig = pow(int.from_bytes(em, "big"), key_d, N).to_bytes(size, "big")
    return f"{head}.{body}.{b64(sig)}"


class Provider(BaseHTTPRequestHandler):
    """A tiny OIDC provider: discovery, keys, and a token endpoint that hands out whatever the test queued."""
    issued = {}
    last_token_request = {}

    def log_message(self, *a):
        pass

    def reply(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        base = f"http://127.0.0.1:{self.server.server_port}"
        if self.path == "/.well-known/openid-configuration":
            return self.reply({"issuer": base, "authorization_endpoint": base + "/authorize", "token_endpoint": base + "/token",
                               "jwks_uri": base + "/jwks", "userinfo_endpoint": base + "/userinfo", "end_session_endpoint": base + "/logout",
                               "token_endpoint_auth_methods_supported": ["client_secret_basic"]})
        if self.path == "/jwks":
            return self.reply({"keys": [{"kty": "RSA", "kid": "k1", "use": "sig", "alg": "RS256",
                                         "n": b64(N.to_bytes(256, "big")), "e": b64(E.to_bytes(3, "big"))}]})
        self.reply({}, 404)

    def do_POST(self):
        form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        Provider.last_token_request = {"form": form, "auth": self.headers.get("Authorization")}
        base = f"http://127.0.0.1:{self.server.server_port}"
        grant = Provider.issued.pop(form.get("code"), None)
        if not grant:
            return self.reply({"error": "invalid_grant"}, 400)
        if b64(hashlib.sha256(form["code_verifier"].encode()).digest()) != grant["challenge"]:
            return self.reply({"error": "invalid_grant", "error_description": "PKCE"}, 400)
        now = int(time.time())
        claims = {"iss": base, "aud": grant.get("aud", "waypoint"), "sub": "user-1", "email": grant["email"], "email_verified": True,
                  "name": "Alex", "nonce": grant["nonce"], "iat": now, "exp": now + 300, "groups": grant.get("groups", [])}
        tok = sign(claims)
        if grant.get("tamper"):
            h, _b, s = tok.split(".")
            claims["email"] = "attacker@example.com"
            tok = f"{h}.{b64(json.dumps(claims).encode())}.{s}"
        self.reply({"access_token": "at", "token_type": "Bearer", "id_token": tok})


class OIDCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idp = HTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=cls.idp.serve_forever, daemon=True).start()
        own_database(cls, OIDC_ISSUER=f"http://127.0.0.1:{cls.idp.server_port}", OIDC_CLIENT_ID="waypoint",
                     OIDC_CLIENT_SECRET="s3cret", OIDC_ALLOWED_EMAILS="me@example.com", OIDC_ALLOWED_GROUPS="finance")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"
        os.environ["WAYPOINT_PUBLIC_URL"] = cls.base
        oidc._discovery.clear(); oidc._jwks.clear()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.idp.shutdown()

    def req(self, path, cookies=None, method="GET", headers=None):
        r = urllib.request.Request(self.base + path, method=method, headers=headers or {})
        if cookies:
            r.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
        opener = urllib.request.build_opener(NoRedirect)
        try:
            resp = opener.open(r, timeout=10)
        except urllib.error.HTTPError as e:
            resp = e
        set_cookies = {}
        for h in resp.headers.get_all("Set-Cookie") or []:
            k, v = h.split(";")[0].split("=", 1)
            set_cookies[k] = v
        return resp.status if hasattr(resp, "status") else resp.code, resp.headers.get("Location"), set_cookies, resp.read()

    def sign_in(self, email="me@example.com", groups=None, tamper=False, aud="waypoint", same_browser=True):
        status, loc, ck, _ = self.req("/auth/login?next=/%23upcoming")
        self.assertEqual(status, 302)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))
        self.assertEqual((q["client_id"], q["code_challenge_method"], q["redirect_uri"]), ("waypoint", "S256", self.base + "/auth/callback"))
        code = os.urandom(8).hex()
        Provider.issued[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "email": email,
                                 "groups": groups or [], "tamper": tamper, "aud": aud}
        cookies = {"waypoint_login": ck["waypoint_login"]} if same_browser else {}
        return self.req(f"/auth/callback?code={code}&state={q['state']}", cookies)

    def test_signed_out_requests_go_to_login(self):
        status, loc, _, _ = self.req("/")
        self.assertEqual((status, loc), (302, "/auth/login?next=%2F"))
        status, _, _, body = self.req("/api/state")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["login"], "/auth/login")
        status, loc, _, _ = self.req("/plaid/oauth?oauth_state_id=abc-123")
        self.assertEqual((status, loc), (302, "/auth/login?next=%2Fplaid%2Foauth%3Foauth_state_id%3Dabc-123"))
        self.assertEqual(self.req("/page.css")[0], 200)
        self.assertEqual(self.req("/healthz")[0], 200)

    def test_full_sign_in_and_sign_out(self):
        status, loc, ck, _ = self.sign_in()
        self.assertEqual((status, loc), (302, "/#upcoming"))
        self.assertTrue(Provider.last_token_request["auth"].startswith("Basic "))
        session = {"waypoint_session": ck["waypoint_session"]}
        status, _, _, body = self.req("/api/state", session)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["user"]["email"], "me@example.com")
        with db.session() as conn:
            self.assertIn("Alex", conn.execute(select(User.first_name)).scalars())   # remembered as one of the household
            self.assertIsNone(conn.execute(select(AuthSession.token_hash)
                                           .where(AuthSession.token_hash == ck["waypoint_session"])).fetchone())
        self.assertEqual(self.req("/auth/logout", session)[0], 405)
        self.assertEqual(self.req("/auth/logout", session, "POST")[0], 403)
        self.assertEqual(self.req("/auth/logout", session, "POST", {"X-Waypoint": "1", "Origin": "https://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/state", session)[0], 200)
        status, _, ck2, body = self.req("/auth/logout", session, "POST", {"X-Waypoint": "1"})
        loc = json.loads(body)["redirect"]
        self.assertTrue(loc.startswith(f"http://127.0.0.1:{self.idp.server_port}/logout?"))
        self.assertIn("id_token_hint", loc)
        self.assertEqual(ck2.get("waypoint_session"), "")
        self.assertEqual(self.req("/api/state", session)[0], 401)

    def test_group_membership_is_enough(self):
        status, _loc, ck, _ = self.sign_in(email="partner@example.com", groups=["Finance"])
        self.assertEqual(status, 302)
        self.assertIn("waypoint_session", ck)

    def test_rejections(self):
        for kwargs, words in (({"email": "stranger@example.com"}, "isn’t allowed".encode()),
                              ({"tamper": True}, b"signature"),
                              ({"aud": "some-other-app"}, b"different app"),
                              ({"same_browser": False}, b"didn")):
            status, _, ck, body = self.sign_in(**kwargs)
            self.assertEqual(status, 403, kwargs)
            self.assertIn(words, body, kwargs)
            self.assertNotIn("waypoint_session", {k: v for k, v in ck.items() if v})

    def test_a_refusal_names_who_in_the_log_but_never_in_what_is_sent(self):
        who = "canary-stranger@example.com"
        with mock.patch.object(monitoring, "send_log") as sent, mock.patch("builtins.print") as printed:
            status, _, _, _ = self.sign_in(email=who)
        self.assertEqual(status, 403)
        lines = [" ".join(str(a) for a in c.args) for c in printed.call_args_list]
        self.assertTrue(any(who in line and "OIDC_ALLOWED_EMAILS" in line for line in lines), lines)   # the operator's fix
        reported = [str(c.args[0]) for c in sent.call_args_list]
        self.assertIn("[sign-in] refused an account that isn't on the allow-list", reported)
        self.assertFalse([r for r in reported if who in r], reported)

    def test_someone_not_allowed_is_told_so_and_offered_another_account(self):
        status, _, _, body = self.sign_in(email="stranger@example.com")
        self.assertEqual(status, 403)
        page = body.decode()
        self.assertIn("Not authorized", page)
        self.assertIn("stranger@example.com isn’t allowed to use this Waypoint. Ask whoever runs it to add you", page)
        self.assertNotIn("OIDC_", page)
        self.assertIn('href="/auth/login?prompt=select_account"', page)
        self.assertIn("Sign out of 127.0.0.1", page)
        self.assertIn(f"http://127.0.0.1:{self.idp.server_port}/logout?client_id=waypoint", page)
        status, loc, _, _ = self.req("/auth/login?prompt=select_account")
        self.assertEqual(status, 302)
        self.assertEqual(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))["prompt"], "select_account")
        _, loc, _, _ = self.req("/auth/login?prompt=none")
        self.assertNotIn("prompt", dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query)))

    def test_refused_changes_say_why(self):
        _, _, ck, _ = self.sign_in()
        session = {"waypoint_session": ck["waypoint_session"]}
        status, _, _, body = self.req("/api/categories", session, "POST", {"X-Waypoint": "1", "Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertIn("WAYPOINT_PUBLIC_URL and WAYPOINT_ALLOWED_HOSTS", json.loads(body)["error"])
        status, _, _, body = self.req("/api/categories", session, "POST")
        self.assertEqual(status, 403)
        self.assertIn("X-Waypoint header", json.loads(body)["error"])
        status, _, _, body = self.req("/auth/logout", session)
        self.assertEqual(status, 405)
        self.assertIn(b"use the Sign out button in Waypoint", body)

    def test_a_session_in_use_is_renewed_with_the_same_cookie(self):
        _, _, ck, _ = self.sign_in()
        token = ck["waypoint_session"]
        session = {"waypoint_session": token}
        self.assertNotIn("waypoint_session", self.req("/api/state", session)[2])
        with db.session() as conn:
            conn.execute(update(AuthSession).where(AuthSession.token_hash == oidc._hash(token))
                         .values(expires=time.time() + 86400))
        r = urllib.request.Request(self.base + "/api/state", headers={"Cookie": f"waypoint_session={token}"})
        with urllib.request.urlopen(r, timeout=10) as resp:
            cookies = resp.headers.get_all("Set-Cookie")
        self.assertEqual(len(cookies), 1)
        value, *attrs = cookies[0].split("; ")
        self.assertEqual(value, f"waypoint_session={token}")
        max_age = int(next(a for a in attrs if a.startswith("Max-Age="))[len("Max-Age="):])
        self.assertAlmostEqual(max_age, 14 * 86400, delta=10)
        self.assertEqual([a for a in attrs if not a.startswith("Max-Age=")], ["Path=/", "HttpOnly", "SameSite=Lax"])
        self.assertNotIn("waypoint_session", self.req("/api/state", session)[2])
        self.assertNotIn("waypoint_session", self.req("/", session)[2])

    def test_login_state_cannot_be_replayed(self):
        _status, loc, ck, _ = self.req("/auth/login")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(loc).query))
        Provider.issued["c1"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "email": "me@example.com"}
        self.assertEqual(self.req(f"/auth/callback?code=c1&state={q['state']}", {"waypoint_login": ck["waypoint_login"]})[0], 302)
        Provider.issued["c2"] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "email": "me@example.com"}
        self.assertEqual(self.req(f"/auth/callback?code=c2&state={q['state']}", {"waypoint_login": ck["waypoint_login"]})[0], 403)

    def test_expired_session(self):
        _, _, ck, _ = self.sign_in()
        with db.session() as conn:
            conn.execute(update(AuthSession).values(expires=time.time() - 1))
        self.assertEqual(self.req("/api/state", {"waypoint_session": ck["waypoint_session"]})[0], 401)

    def test_open_redirect_blocked(self):
        with db.session() as conn:
            _, state = oidc.start_login(conn, "//evil.com/x")
            self.assertEqual(conn.execute(select(AuthPending.next)
                                          .where(AuthPending.state == state)).fetchone()[0], "/")


class TokenChecks(unittest.TestCase):
    """verify_id_token on its own, with an EC-signed provider (ES256) and the claims that must be right."""

    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        import jwt as pyjwt
        self.jwt = pyjwt
        self.key = ec.generate_private_key(ec.SECP256R1())
        jwk = json.loads(pyjwt.algorithms.ECAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": "ec1", "use": "sig", "alg": "ES256"})
        self.jwks = {"keys": [jwk]}
        os.environ.update({"OIDC_ISSUER": "https://id.example.com/", "OIDC_CLIENT_ID": "waypoint", "OIDC_CLIENT_SECRET": ""})
        oidc._jwks.clear()
        self.orig = oidc._get_json
        oidc._get_json = lambda url, headers=None: self.jwks
        self.d = {"jwks_uri": "https://id.example.com/jwks", "token_endpoint": "https://id.example.com/token"}

    def tearDown(self):
        oidc._get_json = self.orig
        oidc._jwks.clear()
        for k in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
            os.environ.pop(k, None)

    def token(self, **over):
        now = int(time.time())
        claims = {"iss": "https://id.example.com", "aud": "waypoint", "sub": "u1", "nonce": "n1", "iat": now, "exp": now + 300, **over}
        return self.jwt.encode(claims, self.key, algorithm="ES256", headers={"kid": "ec1"})

    def test_good_and_bad_tokens(self):
        self.assertEqual(oidc.verify_id_token(self.token(), "n1", self.d)["sub"], "u1")
        now = int(time.time())
        for over, words in (({"exp": now - 600}, "expired"), ({"iat": now + 3600}, "future"), ({"nonce": "other"}, "this sign-in"),
                            ({"iss": "https://evil.example.com"}, "different issuer"), ({"aud": "other"}, "different app")):
            with self.assertRaises(oidc.OIDCError) as e:
                oidc.verify_id_token(self.token(**over), "n1", self.d)
            self.assertIn(words, str(e.exception), over)
        unsigned = self.jwt.encode({"sub": "u1"}, None, algorithm="none")
        with self.assertRaises(oidc.OIDCError):
            oidc.verify_id_token(unsigned, "n1", self.d)
        from cryptography.hazmat.primitives.asymmetric import ec
        other = self.jwt.encode({"iss": "https://id.example.com", "aud": "waypoint", "sub": "u1", "nonce": "n1", "iat": now, "exp": now + 300},
                                ec.generate_private_key(ec.SECP256R1()), algorithm="ES256", headers={"kid": "ec1"})
        with self.assertRaises(oidc.OIDCError) as e:
            oidc.verify_id_token(other, "n1", self.d)
        self.assertIn("signature", str(e.exception))


class ConfigTests(unittest.TestCase):
    def test_hosts(self):
        ok = ["localhost:8765", "127.0.0.1:8765", "[::1]:8765", "192.168.1.50:8765", "10.0.0.9", "100.101.102.103:8765",
              "nas.local:8765", "homeserver:8765", "box.tail1234.ts.net"]
        for h in ok:
            self.assertTrue(server.host_allowed(h), h)
        for h in ["evil.com", "rebind.attacker.net:8765", "8.8.8.8:8765", ""]:
            self.assertFalse(server.host_allowed(h), h)

    def test_needs_sign_in_on_the_network(self):
        for k in ("OIDC_ISSUER", "WAYPOINT_ALLOW_NO_AUTH"):
            os.environ.pop(k, None)
        with self.assertRaises(SystemExit):
            server.serve(host="0.0.0.0", port=0)
        os.environ["OIDC_ISSUER"] = "https://auth.example.com"
        try:
            with self.assertRaises(SystemExit) as cm:
                server.serve(host="0.0.0.0", port=0)
            self.assertIn("OIDC_ALLOWED_EMAILS", str(cm.exception))
        finally:
            os.environ.pop("OIDC_ISSUER", None)
