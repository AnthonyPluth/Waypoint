import unittest
import urllib.error
import urllib.request

from tests.shared import ServerCase


class ServerTests(ServerCase):
    def test_state_and_static(self):
        code, st = self.req("GET", "/api/state")
        self.assertEqual(code, 200)
        self.assertEqual(st["user"], {"name": None, "email": None, "local": True})
        with urllib.request.urlopen(self.base + "/manifest.webmanifest") as resp:
            self.assertIn(b"Waypoint", resp.read())
            self.assertEqual(resp.headers["Content-Type"].split(";")[0], "application/manifest+json")
        with urllib.request.urlopen(self.base + "/sw.js") as resp:
            self.assertEqual(resp.headers["Content-Type"].split(";")[0], "text/javascript")

    def test_csrf_header_required(self):
        code, _ = self.req("POST", "/api/restore", {}, headers={"X-Waypoint": "0"})
        self.assertEqual(code, 403)

    def test_foreign_host_rejected(self):
        r = urllib.request.Request(self.base + "/api/state", headers={"Host": "evil.example"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r)
        self.assertEqual(cm.exception.code, 403)

    def test_an_address_no_route_answers_is_a_404(self):
        self.assertEqual(self.req("GET", "/api/transactions"), (404, {"error": "Not found"}))
        self.assertEqual(self.req("POST", "/api/state", {}), (404, {"error": "Not found"}))


if __name__ == "__main__":
    unittest.main()
