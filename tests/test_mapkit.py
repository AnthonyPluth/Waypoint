import base64
import json
import os
import tempfile
import unittest
from unittest import mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from tests.privacy import no_leaks
from tests.shared import ServerCase
from waypoint import es256, server
from waypoint.domain import maps
from waypoint.providers import mapkit
from waypoint.server import handler

KEY_ID = "MAPKEY1234"
TEAM_ID = "TEAMID5678"
SITE = "https://waypoint.example.test"
PRIVATE = ec.generate_private_key(ec.SECP256R1())


def pem_of(key) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


PEM = pem_of(PRIVATE)
SECRET_LINE = PEM.decode().splitlines()[1]


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def parts(token: str) -> tuple[dict, dict, bytes, bytes]:
    head, claims, signature = token.split(".")
    return json.loads(unb64(head)), json.loads(unb64(claims)), unb64(signature), f"{head}.{claims}".encode()


def verifies(token: str, public) -> bool:
    _, _, signature, signed = parts(token)
    try:
        public.verify(encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")), signed, ec.ECDSA(hashes.SHA256()))
    except Exception:
        return False
    return True


class Keys(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder.name
        self.path = self.write("AuthKey.p8", PEM)

    def write(self, name: str, data: bytes) -> str:
        path = os.path.join(self.folder, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def configure(self, **changes):
        env = {maps.FLAG_ENV: "on", maps.KEY_FILE_ENV: self.path, maps.KEY_ID_ENV: KEY_ID, maps.TEAM_ID_ENV: TEAM_ID, maps.PUBLIC_URL_ENV: SITE, **changes}
        patch = mock.patch.dict(os.environ, {k: v for k, v in env.items() if v is not None})
        patch.start()
        self.addCleanup(patch.stop)
        for name in {k for k, v in env.items() if v is None}:
            os.environ.pop(name, None)


class SigningTests(Keys):
    def test_a_token_is_an_es256_jwt_with_the_claims_apple_asks_for(self):
        token, expires = mapkit.sign(mapkit.Credentials(PEM, KEY_ID, TEAM_ID), SITE, 1_700_000_000.9)
        header, claims, _, _ = parts(token)
        self.assertEqual(header, {"alg": "ES256", "kid": KEY_ID, "typ": "JWT"})
        self.assertEqual(claims, {"iss": TEAM_ID, "iat": 1_700_000_000, "exp": 1_700_000_000 + 1800, "origin": SITE})
        self.assertEqual(expires, claims["exp"])
        self.assertTrue(verifies(token, PRIVATE.public_key()))
        self.assertFalse(verifies(token, ec.generate_private_key(ec.SECP256R1()).public_key()))

    def test_a_token_lives_thirty_minutes(self):
        self.assertEqual(mapkit.TOKEN_LIFETIME, 1800)

    def test_a_key_that_isnt_elliptic_is_refused(self):
        with self.assertRaises(ValueError):
            mapkit.sign(mapkit.Credentials(pem_of(rsa.generate_private_key(65537, 2048)), KEY_ID, TEAM_ID), SITE, 1.0)

    def test_the_shared_signer_matches_what_apns_sends(self):
        token = es256.sign_jwt(PRIVATE, {"alg": "ES256", "kid": KEY_ID}, {"iss": TEAM_ID, "iat": 5})
        self.assertTrue(verifies(token, PRIVATE.public_key()))


class ConfigurationTests(Keys):
    def test_it_is_off_unless_the_flag_and_a_working_key_and_an_address_are_all_there(self):
        self.configure()
        self.assertTrue(maps.enabled())
        for name, changes in {
            "flag off": {maps.FLAG_ENV: "off"}, "flag false": {maps.FLAG_ENV: "false"}, "flag zero": {maps.FLAG_ENV: "0"}, "flag no": {maps.FLAG_ENV: " No "},
            "no key file": {maps.KEY_FILE_ENV: None}, "missing file": {maps.KEY_FILE_ENV: os.path.join(self.folder, "gone.p8")},
            "a folder": {maps.KEY_FILE_ENV: self.folder}, "no key id": {maps.KEY_ID_ENV: None}, "short key id": {maps.KEY_ID_ENV: "ABC"},
            "lowercase key id": {maps.KEY_ID_ENV: "abcdefghij"}, "no team id": {maps.TEAM_ID_ENV: None}, "long team id": {maps.TEAM_ID_ENV: "A" * 11},
            "no public address": {maps.PUBLIC_URL_ENV: None}, "address with no scheme": {maps.PUBLIC_URL_ENV: "waypoint.example.test"},
            "ftp address": {maps.PUBLIC_URL_ENV: "ftp://waypoint.example.test"},
        }.items():
            with self.subTest(name):
                self.configure(**changes)
                self.assertFalse(maps.enabled())
                self.assertIsNone(maps.issue(1.0))
            self.configure()

    def test_the_flag_is_on_unless_it_is_turned_off(self):
        for given in (None, "", "on", "true", "1", "yes", "anything"):
            with self.subTest(given):
                self.configure(**{maps.FLAG_ENV: given})
                self.assertTrue(maps.flag_on())
                self.assertTrue(maps.enabled())
        for given in ("off", "OFF", "false", "0", "no"):
            with self.subTest(given):
                self.configure(**{maps.FLAG_ENV: given})
                self.assertFalse(maps.flag_on())

    def test_with_the_flag_left_on_and_no_key_nothing_is_active(self):
        self.configure(**{maps.FLAG_ENV: None, maps.KEY_FILE_ENV: None, maps.KEY_ID_ENV: None, maps.TEAM_ID_ENV: None})
        self.assertTrue(maps.flag_on())
        self.assertFalse(maps.enabled())
        self.assertIsNone(maps.issue(1.0))

    def test_a_key_file_that_isnt_a_p256_key_is_off(self):
        for name, data in {"garbage": b"not a key", "empty": b"", "rsa": pem_of(rsa.generate_private_key(65537, 2048)),
                           "p384": pem_of(ec.generate_private_key(ec.SECP384R1()))}.items():
            with self.subTest(name):
                self.configure(**{maps.KEY_FILE_ENV: self.write(f"{name}.p8", data)})
                self.assertFalse(maps.enabled())
                self.assertIsNone(maps.issue(1.0))

    def test_a_replaced_key_file_is_read_again(self):
        self.configure()
        self.assertTrue(maps.enabled())
        other = ec.generate_private_key(ec.SECP256R1())
        self.write("AuthKey.p8", pem_of(other))
        os.utime(self.path, ns=(1, 2_000_000_000))
        issued = maps.issue(10.0)
        assert issued
        self.assertTrue(verifies(issued.token, other.public_key()))
        self.assertFalse(verifies(issued.token, PRIVATE.public_key()))

    def test_the_origin_is_the_address_without_a_path(self):
        for given, want in {"https://waypoint.example.test": SITE, "https://waypoint.example.test/": SITE, "https://waypoint.example.test/app/x?y=1": SITE,
                            "http://192.168.1.5:8080/": "http://192.168.1.5:8080"}.items():
            with self.subTest(given):
                self.configure(**{maps.PUBLIC_URL_ENV: given})
                self.assertEqual(maps.origin(), want)

    def test_the_token_carries_the_origin_and_the_script_address(self):
        self.configure()
        issued = maps.issue(1_700_000_000)
        assert issued
        self.assertEqual(parts(issued.token)[1]["origin"], SITE)
        self.assertEqual(issued.script, mapkit.SCRIPT_URL)
        self.assertEqual(issued.expires, 1_700_001_800)


class PolicyTests(Keys):
    def test_the_policy_is_unchanged_unless_it_is_enabled(self):
        plain = handler.content_security_policy("N")
        for name, changes in {"flag off": {maps.FLAG_ENV: "off"}, "no key": {maps.KEY_FILE_ENV: None}, "flag unset and no key": {maps.FLAG_ENV: None, maps.KEY_FILE_ENV: None}}.items():
            with self.subTest(name):
                self.configure(**changes)
                self.assertEqual(handler.content_security_policy("N"), plain)
        self.assertNotIn("apple", plain)
        self.assertIn("img-src 'self' data:;", plain)
        self.assertIn("connect-src 'self';", plain)
        self.assertIn("worker-src 'self';", plain)

    def test_the_policy_names_apples_hosts_only_when_enabled(self):
        self.configure()
        csp = handler.content_security_policy("N")
        self.assertIn("script-src 'nonce-N' 'strict-dynamic' 'self' https://cdn.apple-mapkit.com;", csp)
        self.assertIn("img-src 'self' data: https://*.apple-mapkit.com blob:;", csp)
        self.assertIn("connect-src 'self' https://*.apple-mapkit.com;", csp)
        self.assertIn("worker-src 'self' blob:;", csp)
        for directive in ("default-src 'self'", "frame-src 'none'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'", "style-src 'self' 'unsafe-inline'"):
            self.assertIn(directive, csp)


class TokenRouteTests(ServerCase, Keys):
    def setUp(self):
        Keys.setUp(self)

    def token(self, path="/api/mapkit/token"):
        return self.req("GET", path)

    def test_it_answers_off_when_the_flag_is_off_even_with_a_key(self):
        self.configure(**{maps.FLAG_ENV: "off"})
        self.assertEqual(self.token(), (200, {"enabled": False}))

    def test_it_answers_off_by_default_when_there_is_no_key(self):
        self.configure(**{maps.FLAG_ENV: None, maps.KEY_FILE_ENV: None, maps.KEY_ID_ENV: None, maps.TEAM_ID_ENV: None})
        self.assertEqual(self.token(), (200, {"enabled": False}))

    def test_it_signs_by_default_when_a_key_is_configured_and_the_flag_is_not_mentioned(self):
        self.configure(**{maps.FLAG_ENV: None})
        status, body = self.token()
        self.assertEqual((status, body["enabled"]), (200, True))

    def test_it_answers_off_when_the_key_is_missing_or_wrong(self):
        for changes in ({maps.KEY_FILE_ENV: None}, {maps.KEY_FILE_ENV: os.path.join(self.folder, "gone.p8")}, {maps.KEY_ID_ENV: "x"},
                        {maps.PUBLIC_URL_ENV: None}, {maps.KEY_FILE_ENV: self.write("junk.p8", b"junk " + SECRET_LINE.encode())}):
            with self.subTest(changes):
                self.configure(**changes)
                status, body = self.token()
                self.assertEqual((status, body), (200, {"enabled": False}))

    def test_it_signs_a_short_token_for_this_site(self):
        self.configure()
        status, body = self.token()
        self.assertEqual(status, 200)
        self.assertEqual(sorted(body), ["enabled", "expires", "script", "token"])
        self.assertTrue(body["enabled"])
        header, claims, _, _ = parts(body["token"])
        self.assertEqual(sorted(claims), ["exp", "iat", "iss", "origin"])
        self.assertEqual((header["kid"], claims["iss"], claims["origin"]), (KEY_ID, TEAM_ID, SITE))
        self.assertEqual(claims["exp"] - claims["iat"], 1800)
        self.assertEqual(body["expires"], claims["exp"])
        self.assertEqual(body["script"], mapkit.SCRIPT_URL)
        self.assertTrue(verifies(body["token"], PRIVATE.public_key()))

    def test_the_reply_never_carries_the_key_or_a_trip(self):
        self.configure()
        _, body = self.token("/api/mapkit/token?trip=1&segment=2&near=39.7,-104.9")
        text = json.dumps(body)
        for secret in (SECRET_LINE, "PRIVATE KEY", self.path):
            self.assertNotIn(secret, text)
        self.assertEqual(sorted(parts(body["token"])[1]), ["exp", "iat", "iss", "origin"])

    def test_it_is_not_cached(self):
        self.configure()
        from tests.shared import fetch
        _, headers, _ = fetch(self.base, "GET", "/api/mapkit/token", None, {"X-Waypoint": "1"})
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_the_key_and_the_token_are_never_logged_or_sent_on(self):
        self.configure()
        sealed = "TOKEN.CANARY.0123456789abcdef"
        with no_leaks(self, SECRET_LINE, sealed, self.path, KEY_ID, TEAM_ID):
            with mock.patch.object(mapkit, "sign", return_value=(sealed, 5)):
                status, body = self.token()
            self.configure(**{maps.KEY_FILE_ENV: self.write("junk.p8", SECRET_LINE.encode() + b"\n")})
            self.token()
            self.configure(**{maps.KEY_FILE_ENV: os.path.join(self.folder, "gone.p8")})
            self.token()
        self.assertEqual((status, body["token"]), (200, sealed))

    def test_an_assistant_cant_reach_it(self):
        from waypoint.server import mcp_access, mcp_http
        self.assertTrue(mcp_access.blocked("/api/mapkit/token"))
        self.assertIsNone(mcp_http.needs("GET", "/api/mapkit/token"))

    def test_the_route_is_registered_once_and_only_for_get(self):
        found = [(m, p) for m, p, *_ in server.ROUTES if "mapkit" in p]
        self.assertEqual(found, [("GET", "/api/mapkit/token")])


if __name__ == "__main__":
    unittest.main()
