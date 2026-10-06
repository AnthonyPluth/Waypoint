import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("coverage_floor", ROOT / "tools" / "coverage_floor.py")
assert _spec and _spec.loader
cf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cf)


def report(total, **files):
    return {"totals": {"percent_covered": total},
            "files": {name: {"summary": {"percent_covered": pct, "num_statements": n}} for name, (pct, n) in files.items()}}


class FloorTests(unittest.TestCase):
    def test_at_the_floor_passes(self):
        self.assertEqual(cf.problems(report(cf.TOTAL, **{"waypoint/domain/trips.py": (cf.EACH, 40)})), [])

    def test_too_little_overall(self):
        self.assertIn("the floor is", cf.problems(report(cf.TOTAL - 0.1))[0])

    def test_one_module_where_features_live(self):
        found = cf.problems(report(99, **{"waypoint/providers/gmail.py": (60, 100), "waypoint/oidc.py": (60, 100),
                                          "waypoint/server/api/trips.py": (cf.EACH - 1, 10)}))
        self.assertEqual(len(found), 2)
        self.assertTrue(found[0].startswith("waypoint/providers/gmail.py"))
        self.assertTrue(found[1].startswith("waypoint/server/api/trips.py"))

    def test_an_empty_module_needs_nothing(self):
        self.assertEqual(cf.problems(report(99, **{"waypoint/domain/__init__.py": (0, 0)})), [])


if __name__ == "__main__":
    unittest.main()
