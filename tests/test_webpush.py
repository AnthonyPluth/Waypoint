import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import http_ece
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from waypoint.providers import webpush as w
from tests.shared import DbCase


def receiver():
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, w.b64u(pub), os.urandom(16)


def decrypt(body: bytes, key, auth: bytes) -> dict:
    return json.loads(http_ece.decrypt(body, private_key=key, auth_secret=auth, version="aes128gcm"))


class PushService(BaseHTTPRequestHandler):
    received = []
    status = 201

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        PushService.received.append((self.path, self.headers, body))
        self.send_response(PushService.status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class WebPushTests(DbCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
        cls.srv = HTTPServer(("127.0.0.1", 0), PushService)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_key_is_made_once_and_kept(self):
        _v1, pub1 = w.vapid_keys(self.c)
        _v2, pub2 = w.vapid_keys(self.c)
        self.assertEqual(pub1, pub2)
        self.assertEqual(len(w.unb64u(pub1)), 65)
        self.assertTrue(w.valid_public_key(pub1))
        self.assertFalse(w.valid_public_key(w.b64u(b"\x04" + bytes(64))))

    def test_send_encrypts_and_signs(self):
        key, p256dh, auth = receiver()
        sub = {"endpoint": f"http://127.0.0.1:{self.srv.server_port}/push/abc", "p256dh": p256dh, "auth": w.b64u(auth)}
        vapid, pub = w.vapid_keys(self.c)
        PushService.received.clear()
        self.assertEqual(w.send(sub, {"title": "Hi", "body": "$1,234.56"}, vapid, "mailto:a@b.c"), 201)
        path, headers, body = PushService.received[-1]
        self.assertEqual((path, headers["Content-Encoding"], headers["TTL"], headers["Urgency"]),
                         ("/push/abc", "aes128gcm", "86400", "normal"))
        self.assertEqual(decrypt(body, key, auth), {"title": "Hi", "body": "$1,234.56"})
        auth_header = headers["Authorization"]
        token = auth_header.split("t=")[1].split(",")[0].strip()
        self.assertIn(f"k={pub}", auth_header)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), w.unb64u(pub))
        claims = jwt.decode(token, public, algorithms=["ES256"], audience=f"http://127.0.0.1:{self.srv.server_port}")
        self.assertEqual(claims["sub"], "mailto:a@b.c")

    def test_gone(self):
        _key, p256dh, auth = receiver()
        sub = {"endpoint": f"http://127.0.0.1:{self.srv.server_port}/push/x", "p256dh": p256dh, "auth": w.b64u(auth)}
        vapid, _ = w.vapid_keys(self.c)
        PushService.status = 410
        try:
            with self.assertRaises(w.Gone):
                w.send(sub, {"title": "x"}, vapid, "mailto:a@b.c")
        finally:
            PushService.status = 201


if __name__ == "__main__":
    unittest.main()
