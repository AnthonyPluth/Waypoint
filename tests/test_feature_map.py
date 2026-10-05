"""tools/feature_map.py: how it matches addresses, and that the committed feature map is current."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("feature_map", ROOT / "tools" / "feature_map.py")
assert _spec and _spec.loader
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)


def table(*routes):
    return [{"method": m, "path": p, "handler": "h", "file": "f.py", "parts": fm.segments(p)} for m, p in routes]


class Matching(unittest.TestCase):
    def setUp(self):
        self.rs = table(("POST", "/api/things/bulk"), ("POST", "/api/things/{id}"), ("GET", "/api/things/{id}"))

    def paths(self, method, path):
        return [(r["method"], r["path"]) for r in fm.answers(self.rs, method, path)]

    def test_first_route_wins_for_a_literal_as_the_router_does(self):
        self.assertEqual(self.paths("POST", "/api/things/bulk"), [("POST", "/api/things/bulk")])
        self.assertEqual(self.paths("POST", "/api/things/7"), [("POST", "/api/things/{id}")])

    def test_a_dynamic_segment_only_matches_an_id(self):
        self.assertEqual(self.paths("POST", "/api/things/${x}"), [("POST", "/api/things/{id}")])

    def test_no_method_means_every_method(self):
        self.assertEqual(self.paths(None, "/api/things/7"), [("POST", "/api/things/{id}"), ("GET", "/api/things/{id}")])

    def test_a_different_shape_matches_nothing(self):
        self.assertEqual(self.paths("GET", "/api/things"), [])

    def test_a_call_s_method_is_read_from_the_call(self):
        text = 'await api("/api/x", { method: "post", body: { a: (1) } }); api("/api/y")'
        self.assertEqual(fm.call_method(text, text.index("api(")), "POST")
        self.assertEqual(fm.call_method(text, text.rindex("api(")), "GET")
        dynamic = 'api("/api/x", { method })'
        self.assertIsNone(fm.call_method(dynamic, 0))


class Committed(unittest.TestCase):
    def test_the_map_lists_every_route_and_is_current(self):
        built = fm.build()
        self.assertEqual([(r["method"], r["path"]) for r in built["routes"]],
                         [(r["method"], r["path"]) for r in fm.routes()])
        self.assertEqual(fm.JSON_OUT.read_text(), fm.render_json(built), "run `make feature-map`")

    def test_the_allow_list_has_only_untested_routes(self):
        untested = {f"{r['method']} {r['path']}" for r in fm.build()["routes"] if not r["tests"]}
        self.assertEqual(fm.read_allowlist() - untested, set(), "delete the lines of routes that now have a test")
        self.assertEqual(untested - fm.read_allowlist(), set(), "a route needs a test")


if __name__ == "__main__":
    unittest.main()
