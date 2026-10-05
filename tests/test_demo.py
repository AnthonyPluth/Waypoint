"""waypoint/domain/demo.py: `run.py demo` fills an empty database (make verify relies on it), and says how many rows it
added."""
from datetime import date

from sqlalchemy import MetaData, func, select

from waypoint.domain import demo, trips
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
        self.assertEqual(len([t for t in found if (t["end_date"] or "") < day]), 1)
        self.assertEqual(len([t for t in found if (t["start_date"] or "") <= day <= (t["end_date"] or "")]), 1)
        self.assertEqual(len([t for t in found if (t["start_date"] or "") > day]), 3)   # (one of them read from an email)
        self.assertTrue(all(t["segments"] for t in found))

    def test_has_a_past_trip_one_in_progress_and_some_to_come(self):
        self.check_dates(date(2026, 10, 5))

    def test_keeps_its_trips_around_today_across_a_year_end(self):
        self.check_dates(date(2026, 12, 30))
