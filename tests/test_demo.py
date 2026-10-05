"""waypoint/domain/demo.py: `run.py demo` fills an empty database (make verify relies on it), and says how many rows it
added."""
from datetime import UTC, date, datetime

from sqlalchemy import MetaData, func, select

from waypoint.domain import demo, stats, trips
from waypoint.domain.visibility import Viewer
from tests.shared import DbCase


class DemoTests(DbCase):
    def rows(self) -> int:
        meta = MetaData()
        meta.reflect(self.c.sa)
        return sum(self.c.sa.execute(select(func.count()).select_from(t)).scalar() or 0
                   for t in meta.sorted_tables if t.name != "alembic_version")

    def test_says_how_many_rows_it_added(self):
        before = self.rows()
        added = demo.seed(self.c)
        self.assertEqual(self.rows() - before, added)

    def check_dates(self, today: date) -> None:
        demo.seed(self.c, today)
        found = trips.listing(self.c, Viewer(None, household=True))
        day = today.isoformat()
        self.assertEqual(len([t for t in found if (t["end_date"] or "") < day]), 3)   # (two of them older, for Stats' years)
        self.assertEqual(len([t for t in found if (t["start_date"] or "") <= day <= (t["end_date"] or "")]), 1)
        self.assertEqual(len([t for t in found if (t["start_date"] or "") > day]), 3)   # (one of them read from an email)
        self.assertTrue(all(t["segments"] for t in found))

    def test_has_a_past_trip_one_in_progress_and_some_to_come(self):
        self.check_dates(date(2026, 10, 5))

    def test_keeps_its_trips_around_today_across_a_year_end(self):
        self.check_dates(date(2026, 12, 30))

    def test_stats_has_something_in_every_section_and_more_than_one_year(self):
        demo.seed(self.c, date(2026, 10, 5))
        got = stats.compute(self.c, Viewer(None, household=True), None, None, datetime(2026, 10, 5, 12, tzinfo=UTC))
        assert got is not None
        f = got["flights"]
        self.assertGreaterEqual(len(got["years"]), 3)
        for name in ("airports", "airlines", "countries", "routes", "cabins"):
            self.assertGreater(len(f[name]), 2, name)
        self.assertTrue(f["top_seat"] and f["longest"] and f["shortest"] and f["busiest_month"])
        self.assertTrue(f["seat_positions"]["window"] and f["seat_positions"]["aisle"])
        self.assertTrue(got["stays"]["chains"] and got["stays"]["nights"] and got["cars"]["companies"] and got["cars"]["days"])
