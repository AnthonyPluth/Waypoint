"""waypoint/domain/demo.py: `run.py demo` fills an empty database (make verify relies on it), and says how many rows it
added."""
from sqlalchemy import MetaData, func, select

from waypoint.domain import demo
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
