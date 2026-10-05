"""The ORM session layer (waypoint/storage/db.py): statements run with Connection.execute() and the ORM Session share the
Connection's transaction, results read as rows did, and the portable helpers (upsert, insert_ignore) give the rows they
should."""
import unittest

from sqlalchemy import func, insert, select, update

from waypoint.storage import db, schema
from waypoint.storage.models import Setting, User
from tests.shared import DbCase


class SessionLayerTests(DbCase):
    def others_see(self, stmt):
        with db.session(self.path) as other:
            return other.execute(stmt).fetchall()

    def test_statement_results_read_like_legacy_rows(self):
        self.c.execute(insert(User).values(sub="s1", email="ana@example.com", name="Ana Example"))
        row = self.c.execute(select(User.sub, User.name.label("n"))).fetchone()
        self.assertEqual((row[0], row["sub"], row["n"], dict(row)), ("s1", "s1", "Ana Example", {"sub": "s1", "n": "Ana Example"}))
        self.assertEqual(db.rows(self.c.execute(select(User.sub))), [{"sub": "s1"}])
        self.assertEqual(db.rows(self.c.orm.execute(select(User.sub))), [{"sub": "s1"}])
        whole = db.rows(self.c.execute(select(User)))[0]
        self.assertEqual(list(whole), [c.name for c in schema.users.c])
        self.assertEqual((whole["sub"], whole["email"], whole["first_name"]), ("s1", "ana@example.com", None))
        self.assertEqual(db.as_dict(self.c.orm.get(User, "s1")), whole)
        self.assertRaisesRegex(TypeError, "SQL text isn't supported", self.c.execute, "SELECT * FROM users")

    def test_rowcount_and_scalars(self):
        self.c.execute(insert(Setting), [])
        self.c.execute(insert(Setting), [{"key": "a", "value": "1"}, {"key": "b", "value": "2"}])
        self.assertEqual(self.c.execute(update(Setting).where(Setting.key == "a").values(value="3")).rowcount, 1)
        self.assertEqual(self.c.execute(select(func.count()).select_from(Setting)).scalar(), 2)
        self.assertEqual(self.c.execute(select(Setting.value).order_by(Setting.key)).scalars(), ["3", "2"])
        self.assertIsNone(self.c.execute(select(Setting.value).where(Setting.key == "none")).scalar())

    def test_orm_and_statements_share_one_transaction(self):
        self.c.execute(insert(Setting).values(key="a", value="1"))
        self.c.orm.add(User(sub="s1", name="Ana Example"))
        self.assertEqual(self.c.execute(select(User.name)).fetchone()[0], "Ana Example")
        self.assertEqual(self.others_see(select(User)), [])
        self.c.commit()
        self.assertEqual(len(self.others_see(select(User))), 1)
        self.assertEqual(len(self.others_see(select(Setting))), 1)

    def test_rollback_undoes_both(self):
        self.c.execute(insert(Setting).values(key="a", value="1"))
        self.c.orm.add(User(sub="s1"))
        self.c.orm.flush()
        self.c.rollback()
        self.assertEqual(self.c.execute(select(func.count()).select_from(Setting)).fetchone()[0], 0)
        self.assertEqual(self.c.execute(select(func.count()).select_from(User)).fetchone()[0], 0)
        with self.assertRaises(RuntimeError), db.session(self.path) as conn:
            conn.orm.add(User(sub="s2"))
            conn.execute(insert(Setting).values(key="b", value="2"))
            raise RuntimeError
        self.assertEqual(self.others_see(select(User)) + self.others_see(select(Setting)), [])

    def test_statement_writes_refresh_loaded_objects(self):
        self.c.orm.add(User(sub="s1", last_seen=1.0))
        self.c.orm.flush()
        ana = self.c.orm.get(User, "s1")
        self.c.execute(update(User).where(User.sub == "s1").values(last_seen=2))
        self.assertEqual(ana.last_seen, 2.0)
        self.c.execute(update(User).where(User.sub == "s1").values(last_seen=User.last_seen + 1))
        self.assertEqual(ana.last_seen, 3.0)

    def test_upsert_and_insert_ignore(self):
        db.upsert(self.c, Setting, {"key": "k", "value": "1"}, key=["key"])
        db.upsert(self.c, Setting, {"key": "k", "value": "2"}, key=["key"])
        self.assertEqual(db.get_setting(self.c, "k"), "2")
        db.upsert(self.c, Setting, [{"key": "k", "value": "3"}, {"key": "j", "value": "4"}], key=["key"])
        self.assertEqual(db.rows(self.c.execute(select(Setting).where(Setting.key.in_(["j", "k"])).order_by(Setting.key))),
                         [{"key": "j", "value": "4"}, {"key": "k", "value": "3"}])
        db.upsert(self.c, Setting, {"key": "k", "value": "5"}, key=["key"], update=[])
        self.assertEqual(db.get_setting(self.c, "k"), "3")
        db.upsert(self.c, Setting, {"key": "k", "value": "x"}, key=["key"],
                  update=lambda ex: {"value": Setting.value + ex.value})
        self.assertEqual(db.get_setting(self.c, "k"), "3x")
        db.insert_ignore(self.c, Setting, {"key": "k", "value": "y"})
        db.insert_ignore(self.c, User, [{"sub": "s1", "name": "Ana"}] * 2, key=["sub"])
        self.assertEqual(db.get_setting(self.c, "k"), "3x")
        self.assertEqual(self.c.execute(select(func.count()).select_from(User)).fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
