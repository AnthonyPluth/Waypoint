import contextlib
import unittest

import sqlalchemy as sa
from sqlalchemy import insert, select

from tests import shared
from waypoint.storage import db, schema


@unittest.skipUnless(db.using_postgres(), "Postgres only: the SQLite tests each get a file of their own")
class PooledSchemaTests(unittest.TestCase):

    def lease(self, path):
        shared.POOL.acquire(path)
        self.addCleanup(lambda: path in db.TEST_SCHEMAS and shared.POOL.release(path))
        return db.TEST_SCHEMAS[path]

    def test_a_schema_comes_back_empty_with_its_numbers_started_over_and_its_reference_rows_whole(self):
        first = self.lease("/pool/a.db")
        with db.session("/pool/a.db") as conn:
            conn.execute(insert(schema.trips).values(name="Left behind", auto=True))
            conn.execute(insert(schema.users).values(sub="s1"))
            conn.execute(sa.delete(schema.airports).where(schema.airports.c.code == "JFK"))
            conn.execute(sa.update(schema.airlines).where(schema.airlines.c.code == "AA").values(name="Changed"))
            conn.execute(insert(schema.airlines).values(code="ZZZ", name="Extra"))
        shared.POOL.release("/pool/a.db")
        second = self.lease("/pool/b.db")
        self.assertEqual(second, first)
        with db.session("/pool/b.db") as conn:
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.trips)).scalar(), 0)
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.users)).scalar(), 0)
            conn.execute(insert(schema.trips).values(name="Fresh", auto=True))
            self.assertEqual(conn.execute(select(schema.trips.c.id)).scalar(), 1)
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.airports).where(schema.airports.c.code == "JFK")).scalar(), 1)
            self.assertNotEqual(conn.execute(select(schema.airlines.c.name).where(schema.airlines.c.code == "AA")).scalar(), "Changed")
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.airlines).where(schema.airlines.c.code == "ZZZ")).scalar(), 0)
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(sa.table("alembic_version"))).scalar(), 1)

    def test_two_databases_held_at_once_do_not_share_rows(self):
        a, b = self.lease("/pool/one.db"), self.lease("/pool/two.db")
        self.assertNotEqual(a, b)
        with db.session("/pool/one.db") as conn:
            conn.execute(insert(schema.users).values(sub="only-in-one"))
        with db.session("/pool/two.db") as conn:
            self.assertEqual(list(conn.execute(select(schema.users.c.sub)).scalars()), [])
            conn.execute(insert(schema.users).values(sub="only-in-two"))
        with db.session("/pool/one.db") as conn:
            self.assertEqual(list(conn.execute(select(schema.users.c.sub)).scalars()), ["only-in-one"])
        with db.session("/pool/two.db") as conn:
            self.assertEqual(list(conn.execute(select(schema.users.c.sub)).scalars()), ["only-in-two"])

    def test_a_connection_left_open_does_not_stop_a_schema_being_given_back(self):
        path = "/pool/open.db"
        self.lease(path)
        left_open = db.engine(path).connect()

        def close():
            with contextlib.suppress(sa.exc.OperationalError):
                left_open.close()
        self.addCleanup(close)
        left_open.execute(select(schema.users.c.sub)).fetchall()
        shared.POOL.release(path)
        again = self.lease("/pool/after.db")
        with db.session("/pool/after.db") as conn:
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.users)).scalar(), 0)
        self.assertTrue(again)


if __name__ == "__main__":
    unittest.main()
