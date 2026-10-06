import json
import unittest
import urllib.error
import urllib.request

from waypoint import server
from tests.shared import ServerCase, fetch

NETWORK: set[str] = set()


class RouteTests(ServerCase):
    def raw(self, method, path, body=None):
        status, _, data = fetch(self.base, method, path, json.dumps(body).encode() if body is not None else None,
                                {"X-Waypoint": "1", "Content-Type": "application/json"})
        return status, data

    def test_no_route_fails_with_a_server_error(self):
        for method, pattern, *_ in server.ROUTES:
            if pattern in NETWORK:
                continue
            for rid in ("1", "a|0", "nope"):
                path = pattern.replace("{id}", urllib.request.quote(rid, safe=""))
                with self.subTest(method=method, path=path):
                    status, body = self.raw(method, path, None if method == "GET" else {})
                    self.assertNotEqual(status, 500, f"{method} {path}: {body[:300]!r}")
                if "{id}" not in pattern:
                    break


def _noop(*_a):
    return {}


SAMPLE = [
    ("GET", "/api/trips", _noop),
    ("POST", "/api/trips/new", _noop),
    ("GET", "/api/trips/deleted", _noop),
    ("GET", "/api/trips/{id}", _noop),
    ("POST", "/api/trips/{id}", _noop),
    ("POST", "/api/trips/{id}/segments/{id}/remove", _noop),
]


class TableTests(unittest.TestCase):

    @staticmethod
    def scan(routes, method, path):
        parts = path.strip("/").split("/")
        for m, pattern, *_ in routes:
            want = pattern.strip("/").split("/")
            if (method is None or m == method) and len(want) == len(parts) \
                    and all(w == "{id}" or w == p for w, p in zip(want, parts, strict=True)):
                return pattern
        return None

    def test_every_route_is_found_as_a_scan_would(self):
        for routes in (server.ROUTES, SAMPLE):
            table = server.routes.Table(routes)
            for method, pattern, *_ in routes:
                for rid in ("7", "a%7C0", "new", "deleted"):
                    path = pattern.replace("{id}", rid)
                    for m in (method, None):
                        with self.subTest(method=m, path=path):
                            found = table.match(m, path)
                            self.assertEqual(found.route.pattern if found else None, self.scan(routes, m, path))

    def test_ids_and_order(self):
        table = server.routes.Table(SAMPLE)
        found = table.match("POST", "/api/trips/a%7C0/segments/2026-09-01/remove")
        self.assertEqual((found.route.pattern, found.params), ("/api/trips/{id}/segments/{id}/remove", ["a|0", "2026-09-01"]))
        self.assertEqual(table.match("POST", "/api/trips/new").route.pattern, "/api/trips/new")
        self.assertEqual(table.match("GET", "/api/trips/deleted").route.pattern, "/api/trips/deleted")
        self.assertEqual(table.match("GET", "/api/trips/").route.pattern, "/api/trips")
        self.assertIsNone(table.match("DELETE", "/api/trips"))
        self.assertIsNone(table.match("GET", "/api/nothing/here"))


if __name__ == "__main__":
    unittest.main()
