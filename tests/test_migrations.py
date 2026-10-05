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
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
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

    def test_0003_makes_people_from_the_users_who_signed_in_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0002")
            self.assertNotIn("people", sa.inspect(c).get_table_names())
            c.execute(insert(User), [
                {"sub": "b", "email": "bo@example.com", "name": "Bo Example", "first_name": "Bo"},
                {"sub": "a", "email": "ana@example.com", "name": None, "first_name": "Ana"},
                {"sub": "c", "email": None, "name": " ", "first_name": None}])
            command.upgrade(db.alembic_config(c), "0003")
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            made = [tuple(r) for r in conn.execute(select(schema.people.c.display_name, schema.people.c.first_name,
                                                          schema.people.c.user_sub).order_by(schema.people.c.user_sub))]
            self.assertEqual(made, [("ana@example.com", "Ana", "a"), ("Bo Example", "Bo", "b"), ("c", None, "c")])
            with self.assertRaises(sa.exc.IntegrityError):   # one person to a login
                conn.execute(insert(schema.people).values(display_name="Again", user_sub="a"))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0002")
            self.assertNotIn("people", sa.inspect(c).get_table_names())
            self.assertEqual(c.execute(select(User.sub)).scalars().all().__len__(), 3)   # the users stay

    def test_0004_makes_the_loyalty_table_and_takes_it_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0003")
            self.assertNotIn("loyalty_ids", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "0004")
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            conn.execute(insert(schema.people).values(id=7, display_name="Mia"))
            row = dict(person_id=7, kind="airline", program="Other", number="enc:v1:x")
            conn.execute(insert(schema.loyalty_ids).values(**row))
            with self.assertRaises(sa.exc.IntegrityError):   # a membership belongs to someone
                conn.execute(insert(schema.loyalty_ids).values(**{**row, "person_id": 8}))
        with db.session(self.path) as conn:   # and goes with them
            conn.execute(sa.delete(schema.people).where(schema.people.c.id == 7))
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.loyalty_ids)).scalar(), 0)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0003")
            self.assertNotIn("loyalty_ids", sa.inspect(c).get_table_names())
            self.assertIn("people", sa.inspect(c).get_table_names())

    def test_0005_makes_trips_with_the_airports_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0004")
            self.assertEqual(set(sa.inspect(c).get_table_names()) & {"airports", "trips", "segments", "segment_travelers"}, set())
            c.execute(insert(schema.people).values(id=1, display_name="Jane Doe"))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            zones = dict(conn.execute(select(schema.airports.c.code, schema.airports.c.zone)
                                      .where(schema.airports.c.code.in_(["AKL", "LAX", "LHR"]))).fetchall())
            self.assertEqual(zones, {"AKL": "Pacific/Auckland", "LAX": "America/Los_Angeles", "LHR": "Europe/London"})
            self.assertGreater(conn.execute(sa.select(sa.func.count()).select_from(schema.airports)).scalar(), 5000)
            conn.execute(insert(schema.trips).values(id=1, name="Spring", auto=True, booked_by=1))
            conn.execute(insert(schema.segments).values(
                id=1, trip_id=1, kind="flight", status="confirmed", start_local="2026-03-01T22:15:00",
                start_zone="Pacific/Auckland", end_local="2026-03-01T15:10:00", end_zone="America/Los_Angeles",
                source="manual", booked_by=1))
            conn.execute(insert(schema.segment_travelers).values(segment_id=1, person_id=1))
            conn.execute(insert(schema.segment_travelers).values(segment_id=1, name="DOE/GUEST MR"))
            conn.execute(sa.delete(schema.people).where(schema.people.c.id == 1))   # takes the person's own row, lets go of the booking
            self.assertEqual(conn.execute(select(schema.trips.c.booked_by)).scalar(), None)
            self.assertEqual(conn.execute(select(schema.segments.c.booked_by)).scalar(), None)
            self.assertEqual(conn.execute(select(schema.segment_travelers.c.name)).scalars(), ["DOE/GUEST MR"])
            conn.execute(sa.delete(schema.trips))   # a trip takes its segments, and they their travellers
            self.assertEqual(conn.execute(sa.select(sa.func.count()).select_from(schema.segments)).scalar(), 0)
            self.assertEqual(conn.execute(sa.select(sa.func.count()).select_from(schema.segment_travelers)).scalar(), 0)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0004")
            self.assertEqual(set(sa.inspect(c).get_table_names()) & {"airports", "trips", "segments", "segment_travelers"}, set())
            self.assertIn("people", sa.inspect(c).get_table_names())
            self.assertIn("loyalty_ids", sa.inspect(c).get_table_names())

    def test_0006_makes_the_flight_status_cache_and_takes_it_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0005")
            self.assertNotIn("flight_status", sa.inspect(c).get_table_names())
            self.assertIn("trips", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "0006")
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            row = dict(flight_number="EX101", date="2026-11-20", state="delayed", fetched_at=1.0)
            conn.execute(insert(schema.flight_status).values(**row))
            conn.execute(insert(schema.flight_status).values(**{**row, "date": "2026-11-21"}))   # one a day, for each flight number
        for values in (row,   # a flight and date have one answer
                       dict(flight_number="EX9", date="2026-11-20", state="landed")):   # which always says when it came
            with self.assertRaises(sa.exc.IntegrityError), db.session(self.path) as conn:   # (each in a session of its own: Postgres ends a transaction at an error)
                conn.execute(insert(schema.flight_status).values(**values))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0005")
            self.assertNotIn("flight_status", sa.inspect(c).get_table_names())
            self.assertIn("trips", sa.inspect(c).get_table_names())

    def test_0007_makes_the_scan_tables_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        scan_tables = {"scanned_messages", "review_items", "ignored_senders"}
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0006")
            self.assertEqual(set(sa.inspect(c).get_table_names()) & scan_tables, set())
            self.assertNotIn("scan_error", {col["name"] for col in sa.inspect(c).get_columns("mailboxes")})
            c.execute(insert(schema.mailboxes).values(id=1, owner_sub="u", address="a@gmail.example", token="enc:v1:x", status="connected"))
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            self.assertIsNone(conn.execute(select(schema.mailboxes.c.scan_error)).scalar())   # a mailbox from before has no scan error
            conn.execute(insert(schema.scanned_messages).values(mailbox_id=1, message_id="m1", outcome="booking", scanned=1.0))
            conn.execute(insert(schema.review_items).values(mailbox_id=1, message_id="m2", sender_domain="air.example",
                                                            reason="no_markup", created=1.0))
            conn.execute(insert(schema.ignored_senders).values(mailbox_id=1, domain="air.example"))
        with self.assertRaises(sa.exc.IntegrityError), db.session(self.path) as conn:   # a message is recorded once per mailbox
            conn.execute(insert(schema.scanned_messages).values(mailbox_id=1, message_id="m1", outcome="booking", scanned=2.0))
        with self.assertRaises(sa.exc.IntegrityError), db.session(self.path) as conn:   # and belongs to a mailbox
            conn.execute(insert(schema.review_items).values(mailbox_id=9, message_id="m3", sender_domain="x.example",
                                                            reason="no_markup", created=1.0))
        with db.session(self.path) as conn:   # disconnecting a mailbox takes what its scans kept
            conn.execute(sa.delete(schema.mailboxes))
            for t in (schema.scanned_messages, schema.review_items, schema.ignored_senders):
                self.assertEqual(conn.execute(select(sa.func.count()).select_from(t)).scalar(), 0)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0006")
            self.assertEqual(set(sa.inspect(c).get_table_names()) & scan_tables, set())
            self.assertNotIn("scan_error", {col["name"] for col in sa.inspect(c).get_columns("mailboxes")})
            self.assertIn("mailboxes", sa.inspect(c).get_table_names())

    def test_0008_makes_the_reminder_and_feed_tables_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        tables = {"push_devices", "reminder_prefs", "reminders_sent", "calendar_feeds"}
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0007")
            self.assertEqual(set(sa.inspect(c).get_table_names()) & tables, set())
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            conn.execute(insert(schema.push_devices).values(owner_sub="u", endpoint="https://push.example.com/a", p256dh="k",
                                                            auth="a", created=1.0))
            conn.execute(insert(schema.reminder_prefs).values(owner_sub="u", check_in=True, day_of=False))
            conn.execute(insert(schema.reminders_sent).values(owner_sub="u", kind="check_in", ref="1@2026-11-20T19:00", sent=1.0))
            conn.execute(insert(schema.calendar_feeds).values(owner_sub="u", key_hash="h1", created=1.0))
        for table, values in ((schema.push_devices, dict(owner_sub="v", endpoint="https://push.example.com/a", p256dh="k", auth="a", created=2.0)),
                              (schema.reminder_prefs, dict(owner_sub="u", check_in=True, day_of=True)),   # one choice per member
                              (schema.reminders_sent, dict(owner_sub="u", kind="check_in", ref="1@2026-11-20T19:00", sent=2.0)),
                              (schema.calendar_feeds, dict(owner_sub="u", key_hash="h2", created=2.0)),   # one feed per member
                              (schema.calendar_feeds, dict(owner_sub="w", key_hash="h1", created=2.0))):   # and one key per feed
            with self.assertRaises(sa.exc.IntegrityError), db.session(self.path) as conn:   # (each in a session of its own: Postgres ends a transaction at an error)
                conn.execute(insert(table).values(**values))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0007")
            self.assertEqual(set(sa.inspect(c).get_table_names()) & tables, set())
            self.assertIn("scanned_messages", sa.inspect(c).get_table_names())

    def test_0009_adds_the_ai_suggestion_columns_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0008")
            self.assertNotIn("suggestion", {col["name"] for col in sa.inspect(c).get_columns("review_items")})
            c.execute(insert(schema.mailboxes).values(id=1, owner_sub="u", address="a@gmail.example", token="enc:v1:x", status="connected"))
            c.execute(insert(schema.review_items).values(mailbox_id=1, message_id="m1", sender_domain="air.example",
                                                         reason="no_markup", created=1.0))
            command.upgrade(db.alembic_config(c), "0009")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # an item from before has no suggestion and no error
            row = conn.execute(select(schema.review_items.c.suggestion, schema.review_items.c.suggestion_error)).fetchone()
            self.assertEqual((row[0], row[1]), (None, None))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0008")
            names = {col["name"] for col in sa.inspect(c).get_columns("review_items")}
            self.assertNotIn("suggestion", names)
            self.assertNotIn("suggestion_error", names)
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.review_items)).scalar(), 1)

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
