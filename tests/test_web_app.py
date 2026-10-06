import mimetypes
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from waypoint import server
from tests.shared import ServerCase, scratch_dir

PAGE = b'<!doctype html><head><script type="module" crossorigin src="/assets/index-abc.js"></script></head><div id="app"></div>'


def built_app(static: str) -> None:
    os.makedirs(os.path.join(static, "app", "assets"), exist_ok=True)
    with open(os.path.join(static, "app", "index.html"), "wb") as f:
        f.write(PAGE)
    with open(os.path.join(static, "app", "assets", "index-abc.js"), "wb") as f:
        f.write(b"console.log(1)")


def serving(static: str):
    app = os.path.join(static, "app")
    return mock.patch.multiple(server.static, STATIC=static, APP_DIR=app, APP_INDEX=os.path.join(app, "index.html"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class WebAppTests(ServerCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.static = os.path.join(scratch_dir(cls), "static")
        built_app(cls.static)
        with open(os.path.join(cls.static, "sw.js"), "wb") as f:
            f.write(b"// service worker")

    def get(self, path, static=None):
        with serving(static or self.static):
            try:
                with urllib.request.build_opener(NoRedirect).open(self.base + path, timeout=10) as r:
                    return r.status, r.headers, r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.headers, e.read()

    def test_page_gets_a_nonce_and_the_policy(self):
        for path in ("/", "/plaid/oauth", "/anything"):
            with self.subTest(path=path):
                status, headers, body = self.get(path)
                self.assertEqual(status, 200)
                csp = headers["Content-Security-Policy"]
                nonce = csp.split("'nonce-")[1].split("'")[0]
                self.assertIn(f'<script nonce="{nonce}" type="module"'.encode(), body)
                self.assertIn("object-src 'none'", csp)
                self.assertEqual(headers["Cache-Control"], "no-store")

    def test_old_address_leads_to_the_app(self):
        for path in ("/next", "/next/", "/next/assets/index-abc.js"):
            with self.subTest(path=path):
                status, headers, _ = self.get(path)
                self.assertEqual((status, headers["Location"]), (302, "/"))

    def test_built_files_are_kept_for_good(self):
        status, headers, body = self.get("/assets/index-abc.js")
        self.assertEqual((status, body), (200, b"console.log(1)"))
        self.assertIn("immutable", headers["Cache-Control"])
        status, headers, body = self.get("/sw.js")
        self.assertEqual((status, body), (200, b"// service worker"))
        self.assertNotIn("immutable", headers.get("Cache-Control") or "")

    def test_never_outside_static(self):
        status, _, body = self.get("/../../server.py")
        self.assertNotIn(b"def serve", body)
        self.assertEqual(status, 200)

    def test_not_built(self):
        with tempfile.TemporaryDirectory() as empty:
            status, _, body = self.get("/", static=empty)
        self.assertEqual(status, 404)
        self.assertIn(b"npm run build", body)


class ContentTypeTests(unittest.TestCase):

    @staticmethod
    def guessed(path: str) -> str:
        for t, ext in (("image/svg+xml", ".svg"), ("font/woff2", ".woff2"), ("application/manifest+json", ".webmanifest")):
            mimetypes.add_type(t, ext)
        return mimetypes.guess_type(path)[0] or "application/octet-stream"

    def test_every_shipped_file(self):
        shipped = [os.path.join(d, f) for d, _dirs, files in os.walk(server.static.STATIC) for f in files]
        self.assertTrue(any(f.endswith(".woff2") for f in shipped))
        built = ["index.html", "assets/index-abc.js", "assets/index-abc.css", "assets/logo-abc.svg", "assets/a.png", "favicon.ico",
                 "assets/x.json", "assets/x.js.map", "robots.txt", "assets/font.woff", "assets/m.mjs", "assets/w.wasm",
                 "assets/p.jpg", "assets/p.webp", "assets/p.gif", "assets/f.ttf", "sitemap.xml"]
        for path in shipped + built:
            with self.subTest(path=path):
                self.assertEqual(server.static.content_type(path), self.guessed(path))

    def test_anything_else_is_octet_stream(self):
        for path in ("/x.exe", "/x", "/x.unknown", "/evil.html\r\nSet-Cookie: a=b"):
            self.assertEqual(server.static.content_type(path), "application/octet-stream")
        self.assertEqual(server.static.content_type("/LOGO.SVG"), "image/svg+xml")

    def test_a_header_value_never_holds_a_line_break(self):
        from waypoint.server.common import header_value
        self.assertEqual(header_value("text/html"), "text/html")
        for bad in ("a\r\nSet-Cookie: x=1", "a\nb", "a\rb"):
            with self.subTest(v=bad), self.assertRaises(ValueError):
                header_value(bad)


if __name__ == "__main__":
    unittest.main()
