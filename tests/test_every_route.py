"""Rules every API route follows, checked for each one in the route table, so a new route is held to them the moment it
is added (AGENTS.md, "Waypoint's promises" and "Conventions"): it needs sign-in, a change needs the app's header and
its own site, its reply has a type in the API contract, and its feature has a docs page."""
import json
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from waypoint import oidc, server
from tests.shared import ServerCase, fetch

ROOT = Path(__file__).resolve().parent.parent
OPENAPI = json.loads((ROOT / "docs/openapi.json").read_text())
FEATURE_MAP = json.loads((ROOT / "docs/feature-map.json").read_text())

# Routes whose reply isn't JSON, so the API contract can't type it. Only downloads belong here; a new one says why.
NOT_JSON = {
    "GET /api/backup": "a .json.gz file to keep",
}


def address(pattern: str) -> str:
    """An address the route answers, with each {id} filled in."""
    return pattern.replace("{id}", urllib.parse.quote("a|1", safe=""))


def every_route():
    return [(m, p) for m, p, *_ in server.ROUTES]


class SignedOutTests(ServerCase):
    """With sign-in on, every route answers 401 to someone who isn't signed in, and runs nothing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patch = mock.patch.object(oidc, "enabled", return_value=True)
        patch.start()
        cls.addClassCleanup(patch.stop)

    def test_every_route_needs_sign_in(self):
        for method, pattern in every_route():
            with self.subTest(route=f"{method} {pattern}"):
                handler = mock.Mock(side_effect=AssertionError("ran while signed out"))
                with mock.patch.object(server.routes, "dispatch", handler):
                    status, body = self.req(method, address(pattern), None if method == "GET" else {})
                self.assertEqual(status, 401)
                self.assertEqual(body["login"], "/auth/login")
                handler.assert_not_called()


class ChangeTests(ServerCase):
    """Every route that changes something refuses a request without the web app's header, or from another site."""

    def test_changes_need_the_app_header_and_this_site(self):
        changes = [(m, p) for m, p in every_route() if m != "GET"]
        self.assertTrue(changes)
        for method, pattern in changes:
            for headers in ({"X-Waypoint": "0"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"},
                            {"Origin": "null"}):
                with self.subTest(route=f"{method} {pattern}", headers=headers):
                    handler = mock.Mock(side_effect=AssertionError("ran without the checks"))
                    h = {"X-Waypoint": "1", "Content-Type": "application/json", **headers}
                    with mock.patch.object(server.routes, "dispatch", handler):
                        status, _, _ = fetch(self.base, method, address(pattern), b"{}", h)
                    self.assertEqual(status, 403)
                    handler.assert_not_called()


class ContractTests(unittest.TestCase):
    def test_every_json_route_is_in_the_contract(self):
        typed = {f"{m.upper()} {'/'.join('{id}' if s.startswith('{') else s for s in p.split('/'))}"
                 for p, ops in OPENAPI["paths"].items() for m in ops}
        routes = {f"{m} {p}" for m, p in every_route()}
        self.assertEqual(sorted(routes - typed - set(NOT_JSON)), [],
                         "give these routes' handlers reply types from waypoint/server/contract.py, then `make api-contract`")
        self.assertEqual(sorted(set(NOT_JSON) - routes), [], "NOT_JSON lists a route that's gone")
        self.assertEqual(sorted(set(NOT_JSON) & typed), [], "NOT_JSON lists a route the contract types")


class DocsTests(unittest.TestCase):
    def test_every_route_has_a_docs_page(self):
        missing = [f"{r['method']} {r['path']}" for r in FEATURE_MAP["routes"] if not r["docs"]]
        self.assertEqual(missing, [], "describe these routes' feature in docs/src/content/docs/ and map their area in "
                                      "tools/feature_map.py's AREA_DOCS, then `make feature-map`")


if __name__ == "__main__":
    unittest.main()
