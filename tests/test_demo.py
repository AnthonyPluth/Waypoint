"""waypoint/domain/demo.py: `run.py demo` fills an empty database without error (make verify relies on it)."""
from waypoint.domain import demo
from tests.shared import DbCase


class DemoTests(DbCase):
    def test_seeds_an_empty_database(self):
        self.assertGreaterEqual(demo.seed(self.c), 0)
