"""The schema comes from Alembic migrations; they must match waypoint/storage/schema.py, and each one must run both ways.
tools/fleet_checks.py checks every migration has a test here, named test_<revision>_..."""
import os
import unittest

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import insert, select

from waypoint.storage import db, schema
from waypoint.storage.models import Setting, User
from tests.shared import database_path


def drift(path):
    """Differences between the database and schema.py, as Alembic's autogenerate would see them."""
    with open(os.path.join(os.path.dirname(db.__file__), "migrations", "env.py")) as f:
        src = f.read()
    ns = {}
    exec(src[src.index("def same_type"):src.index("def skip_pk")], ns)
    with db.engine(path).connect() as c:
        diffs = compare_metadata(MigrationContext.configure(c, opts={"compare_type": ns["same_type"]}), schema.metadata)
    pk = lambda t, col: col in {c.name for c in schema.metadata.tables[t].primary_key}
    return [d for d in diffs
            if not (isinstance(d, tuple) and d[0] == "remove_table" and d[1].name == "alembic_version")
            and not (isinstance(d, list) and d[0][0] == "modify_nullable" and pk(d[0][2], d[0][3]))]


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.path = database_path(self, "m.db")

    def test_fresh_database_matches_schema(self):
        db.init(self.path)
        self.assertEqual(drift(self.path), [])
        with db.engine(self.path).connect() as c:
            head = ScriptDirectory.from_config(db.alembic_config()).get_current_head()
            self.assertEqual(c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(), head)
        db.init(self.path)   # starting again changes nothing
        self.assertEqual(drift(self.path), [])

    def test_every_migration_goes_down_and_up_again(self):
        # Each revision's downgrade undoes its upgrade: stepping down one at a time to the start and back up to the head
        # leaves the schema matching schema.py, with nothing left over on the way.
        from alembic import command
        db.init(self.path)
        revisions = [r.revision for r in ScriptDirectory.from_config(db.alembic_config()).walk_revisions()]
        with db.engine(self.path).begin() as c:
            for rev in revisions:
                with self.subTest(down_from=rev):
                    command.downgrade(db.alembic_config(c), "-1")
            self.assertEqual(set(sa.inspect(c).get_table_names()) - {"alembic_version"}, set())
            for rev in reversed(revisions):
                with self.subTest(up_to=rev):
                    command.upgrade(db.alembic_config(c), "+1")
        self.assertEqual(drift(self.path), [])

    def test_a_database_with_tables_but_no_history_is_refused(self):
        with db.engine(self.path).begin() as c:
            c.exec_driver_sql("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        with self.assertRaisesRegex(RuntimeError, "isn't one Waypoint made"):
            db.migrate(self.path)

    def test_0001_makes_the_sign_in_and_settings_tables_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(User).values(sub="s1", email="ana@example.com"))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "base")
            left = set(sa.inspect(c).get_table_names()) - {"alembic_version"}
        self.assertEqual(left, set())
        db.migrate(self.path)
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            self.assertEqual(conn.execute(select(User.sub)).scalars(), [])

    def test_0002_makes_the_mailbox_tables_and_takes_them_away(self):
        from alembic import command
        from sqlalchemy.exc import IntegrityError
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0001")
            self.assertNotIn("mailboxes", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "0002")
            tables = sa.inspect(c)
            self.assertEqual([col["name"] for col in tables.get_columns("mailboxes")],
                             ["id", "owner_sub", "address", "token", "history_id", "last_scan", "status", "last_error", "created"])
            self.assertEqual([col["name"] for col in tables.get_columns("mailbox_pending")], ["state", "owner_sub", "verifier", "created"])
        self.assertEqual(drift(self.path), [])
        row = dict(owner_sub="sub-1", address="ana@gmail.example", token="enc:v1:x", status="connected")
        with db.session(self.path) as conn:   # numbered by the database, one row for each address of a member
            conn.execute(sa.insert(schema.mailboxes).values(row))
            conn.execute(sa.insert(schema.mailboxes).values({**row, "owner_sub": "sub-2"}))
        with self.assertRaises(IntegrityError), db.session(self.path) as conn:
            conn.execute(sa.insert(schema.mailboxes).values(row))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0001")
            self.assertEqual(set(sa.inspect(c).get_table_names()) - {"alembic_version"}, {"auth_pending", "auth_sessions", "users", "settings"})
        db.migrate(self.path)
        self.assertEqual(drift(self.path), [])

    def test_processes_starting_together_take_turns_migrating(self):
        # Several copies of Waypoint (or parallel tests) starting on one empty Postgres database used to collide creating
        # alembic_version ("duplicate key value violates unique constraint pg_type_typname_nsp_index").
        import threading
        errors = []

        def start(path):
            try:
                db.migrate(path)
            except Exception as e:
                errors.append(e)
        path = database_path(self, "together.db")   # on Postgres the path only picks the test's own schema
        threads = [threading.Thread(target=start, args=(path,)) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertFalse([t for t in threads if t.is_alive()], "the migrations are stuck waiting on each other")
        self.assertEqual(errors, [])
        self.assertEqual(drift(path), [])

    @unittest.skipUnless(db.using_postgres(), "Postgres only: the lock is Postgres's")
    def test_a_tests_own_schema_migrates_without_waiting_for_another(self):
        # Each test's own schema has its own lock, so parallel tests don't all queue on one (the whole Postgres run
        # used to wait on it). Two migrations of the same schema still take turns (the test above).
        import threading
        held, free = database_path(self, "held.db"), database_path(self, "free.db")
        db.migrate(held)
        with db.engine(held).connect() as other:                            # hold held's lock, as a migration would
            other.exec_driver_sql(f"SELECT pg_advisory_xact_lock({db.SCHEMA_LOCK}, hashtext(current_schema()))")
            waiting = threading.Thread(target=db.migrate, args=(held,))
            waiting.start()
            db.migrate(free)                                                 # another schema: doesn't wait
            self.assertEqual(drift(free), [])
            waiting.join(1)
            self.assertTrue(waiting.is_alive())                             # the same schema: waits for its turn
            other.rollback()                                                  # the lock goes with the transaction
        waiting.join(30)
        self.assertFalse(waiting.is_alive())

    def test_connection_wrapper(self):
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(User).values(sub="50% off", email="a@example.com"))
            row = conn.execute(select(User.sub, User.email).where(User.sub.like("50%"))).fetchone()
            self.assertEqual((row[0], row["email"], dict(row)["sub"]), ("50% off", "a@example.com", "50% off"))
            conn.execute(insert(Setting).values(key="n", value=5))   # loose typing, as in SQLite
            self.assertEqual(db.get_setting(conn, "n"), "5")


if __name__ == "__main__":
    unittest.main()
