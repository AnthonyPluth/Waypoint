"""The schema comes from Alembic migrations; they must match waypoint/storage/schema.py, and each one must run both ways.
tools/fleet_checks.py checks every migration has a test here, named test_<revision>_..."""
import os
import unittest

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, insert, select

from waypoint.storage import db, schema
from waypoint.storage.models import Setting, User
from tests.shared import database_path


def json_list(raw):
    import json
    return json.loads(raw)


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
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
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

    def test_0010_seeds_the_airlines_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0009")
            self.assertNotIn("airlines", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "0010")
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            a = schema.airlines.c
            found = {code: (name, icao, country) for code, name, icao, country in conn.execute(select(a.code, a.name, a.icao, a.country)).fetchall()}
            self.assertEqual(found["NZ"], ("Air New Zealand", "ANZ", "New Zealand"))
            self.assertGreater(len(found), 900)
        with self.assertRaises(sa.exc.IntegrityError), db.session(self.path) as conn:   # a code is one airline
            conn.execute(insert(schema.airlines).values(code="NZ", name="Another"))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0009")
            self.assertNotIn("airlines", sa.inspect(c).get_table_names())
            self.assertIn("scanned_messages", sa.inspect(c).get_table_names())

    def test_0012_makes_the_recipients_table_and_merges_the_duplicate_segments(self):
        from alembic import command
        db.init(self.path)
        seg = dict(kind="flight", status="confirmed", provider="American Airlines", start_zone="America/New_York",
                   end_zone="Europe/London", origin="JFK", destination="LHR", source="email", locked_fields=None, manage_url=None)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0011")
            self.assertNotIn("segment_recipients", sa.inspect(c).get_table_names())
            for i, name in ((1, "Jane"), (2, "Sam"), (3, "Mia")):
                c.execute(insert(schema.people).values(id=i, display_name=name))
            for i, booker in ((1, 1), (2, 2)):
                c.execute(insert(schema.trips).values(id=i, name=f"Trip {i}", auto=True, booked_by=booker))
            c.execute(insert(schema.segments), [
                # the oldest, on Jane's trip; a copy from Sam's mailbox on his own trip, the same flight written another way,
                # cancelled and with an edit of its own; and a copy on Jane's trip changed by hand.
                {**seg, "id": 1, "trip_id": 1, "booked_by": 1, "confirmation": "ZQ4PXD", "start_local": "2026-06-01T19:00",
                 "end_local": "2026-06-02T07:10", "details": '{"flight_number": "AA 4001", "seat": "12A"}', "locked_fields": '["seat"]'},
                {**seg, "id": 2, "trip_id": 2, "booked_by": 2, "confirmation": "zq4pxd ", "provider": "American Airlines Inc.",
                 "start_local": "2026-06-01T19:00", "end_local": "2026-06-02T07:10", "status": "cancelled",
                 "details": '{"flight_number": "AA04001", "seat": "30D"}', "locked_fields": '["manage_url", "seat"]',
                 "manage_url": "https://example.com/manage/mine"},
                {**seg, "id": 3, "trip_id": 1, "booked_by": 1, "confirmation": "ZQ4PXD", "start_local": "2026-06-01T19:00",
                 "end_local": "2026-06-02T07:10", "details": '{"flight_number": "AA 4001"}'},
                # not duplicates: another code on the same flight, the same code on another flight, and one with no code
                {**seg, "id": 4, "trip_id": 1, "booked_by": 1, "confirmation": "QW9ERT", "start_local": "2026-06-01T19:00",
                 "end_local": "2026-06-02T07:10", "details": '{"flight_number": "AA 4001"}'},
                {**seg, "id": 5, "trip_id": 1, "booked_by": 1, "confirmation": "ZQ4PXD", "start_local": "2026-06-01T19:00",
                 "end_local": "2026-06-02T07:10", "details": '{"flight_number": "AA 4002"}'},
                {**seg, "id": 6, "trip_id": 1, "booked_by": 1, "confirmation": None, "start_local": "2026-06-01T19:00",
                 "end_local": "2026-06-02T07:10", "details": '{"flight_number": "AA 4001"}'}])
            c.execute(insert(schema.segment_travelers), [
                {"segment_id": 1, "person_id": 1, "name": None}, {"segment_id": 2, "person_id": 1, "name": None}, {"segment_id": 2, "person_id": 3, "name": None},
                {"segment_id": 2, "person_id": None, "name": "ROE/ALEX MR"}, {"segment_id": 3, "person_id": None, "name": "Roe/Alex Mr"},
                {"segment_id": 1, "person_id": None, "name": "roe/alex mr"}])
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            kept = {r["id"]: r for r in db.rows(conn.execute(select(schema.segments).order_by(schema.segments.c.id)))}
            self.assertEqual(set(kept), {1, 4, 5, 6})   # the oldest of each leg stays
            one = kept[1]
            self.assertEqual((one["trip_id"], one["booked_by"], one["provider"], one["status"]), (1, 1, "American Airlines", "cancelled"))
            self.assertEqual(one["details"], '{"flight_number": "AA 4001", "seat": "12A"}')   # (the oldest's seat: both locked it)
            self.assertEqual(json_list(one["locked_fields"]), ["manage_url", "seat"])          # (the other's edit is kept and locked)
            self.assertEqual(one["manage_url"], "https://example.com/manage/mine")
            travelers = db.rows(conn.execute(select(schema.segment_travelers).order_by(schema.segment_travelers.c.id)))
            on = sorted((t["person_id"] or 0, (t["name"] or "").casefold()) for t in travelers if t["segment_id"] == 1)
            self.assertEqual(on, [(0, "roe/alex mr"), (1, ""), (3, "")])   # (everyone once)
            self.assertEqual([t for t in travelers if t["segment_id"] in (2, 3)], [])
            # Sam booked the copy on his own trip, which is now empty and goes; he still sees the booking as a recipient.
            self.assertEqual([t["id"] for t in db.rows(conn.execute(select(schema.trips)))], [1])
            self.assertEqual([(r["segment_id"], r["person_id"]) for r in db.rows(conn.execute(select(schema.segment_recipients)))], [(1, 2)])
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0011")
            self.assertNotIn("segment_recipients", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "head")
        with db.session(self.path) as conn:   # (up again on what's left: nothing more to merge, and the table is empty)
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.segment_recipients)).scalar(), 0)
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.segments)).scalar(), 4)
        with self.assertRaises(sa.exc.IntegrityError), db.session(self.path) as conn:
            conn.execute(insert(schema.segment_recipients).values(segment_id=1, person_id=2))
            conn.execute(insert(schema.segment_recipients).values(segment_id=1, person_id=2))   # (once each)

    def test_0011_adds_the_check_times_flag_to_segments_and_takes_it_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0010")
            self.assertNotIn("check_times", {col["name"] for col in sa.inspect(c).get_columns("segments")})
            c.execute(insert(schema.trips).values(id=1, name="Trip", auto=True))
            c.execute(insert(schema.segments).values(trip_id=1, kind="flight", status="confirmed", start_local="2026-12-04T09:00",
                                                     start_zone="America/Chicago", end_local="2026-12-04T11:10", end_zone="America/Denver",
                                                     origin="ORD", destination="DEN", source="email"))
            command.upgrade(db.alembic_config(c), "head")   # the later migrations too: the schema as a whole matches schema.py
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # a segment from before has no note to check
            self.assertEqual(conn.execute(select(schema.segments.c.check_times)).scalar(), False)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0010")
            self.assertNotIn("check_times", {col["name"] for col in sa.inspect(c).get_columns("segments")})
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.segments)).scalar(), 1)

    def test_0013_adds_the_claim_columns_to_people_and_takes_them_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0012")
            self.assertNotIn("links", {col["name"] for col in sa.inspect(c).get_columns("people")})
            c.execute(insert(schema.people).values(display_name="Mia Doe"))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # someone from before has no links and hasn't turned the suggestion down
            row = conn.execute(select(schema.people.c.links, schema.people.c.claim_dismissed)).fetchone()
            self.assertEqual((row[0], row[1]), (None, None))
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0012")
            names = {col["name"] for col in sa.inspect(c).get_columns("people")}
            self.assertEqual(names & {"links", "claim_dismissed"}, set())
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.people)).scalar(), 1)

    def test_0014_adds_the_assistant_tables_and_takes_them_away(self):
        from alembic import command
        tables = {"oauth_clients", "oauth_grants", "oauth_codes", "oauth_tokens", "oauth_consents"}
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            self.assertEqual(tables - set(sa.inspect(c).get_table_names()), set())
            command.downgrade(db.alembic_config(c), "0013")
            self.assertEqual(tables & set(sa.inspect(c).get_table_names()), set())
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # an upgraded database has nobody connected, and the switches are off
            for table in tables:
                self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.metadata.tables[table])).scalar(), 0)
            self.assertIsNone(db.get_setting(conn, "mcp_allow_ids"))
            self.assertIsNone(db.get_setting(conn, "mcp_allow_writes"))

    def test_0015_adds_the_ports_table_and_takes_it_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            self.assertIn("segment_ports", sa.inspect(c).get_table_names())
            command.downgrade(db.alembic_config(c), "0014")
            self.assertNotIn("segment_ports", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])

    def test_0016_adds_the_brand_logos_table_and_takes_it_away(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            self.assertIn("brand_logos", sa.inspect(c).get_table_names())
            command.downgrade(db.alembic_config(c), "0015")
            self.assertNotIn("brand_logos", sa.inspect(c).get_table_names())
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])

    def test_a_cruises_ports_go_with_the_cruise(self):
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(schema.trips).values(id=1, name="Trip", auto=True))
            conn.execute(insert(schema.segments).values(
                id=1, trip_id=1, kind="cruise", status="confirmed", start_local="2026-03-01T17:00", start_zone="America/New_York",
                end_local="2026-03-08T07:00", end_zone="America/New_York", source="manual"))
            conn.execute(insert(schema.segment_ports).values(segment_id=1, position=0, name="Nassau", zone="America/Nassau"))
            conn.execute(delete(schema.segments).where(schema.segments.c.id == 1))
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.segment_ports)).scalar(), 0)

    def test_0017_adds_the_sharing_switch_to_mailboxes_off_and_takes_it_away_without_losing_a_review_item(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0016")
            self.assertNotIn("share_review", {col["name"] for col in sa.inspect(c).get_columns("mailboxes")})
            c.execute(insert(schema.mailboxes).values(id=1, owner_sub="u", address="a@gmail.example", token="t", status="connected"))
            c.execute(insert(schema.review_items).values(mailbox_id=1, message_id="m", sender_domain="x.example", reason="no_markup", created=1.0))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # a mailbox from before shares nothing
            self.assertEqual(conn.execute(select(schema.mailboxes.c.share_review)).scalar(), False)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0016")
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.review_items)).scalar(), 1)   # (the cascade took nothing)

    def test_0018_adds_a_seat_to_each_traveller_empty_and_takes_it_away_keeping_the_travellers(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0017")
            self.assertNotIn("seat", {col["name"] for col in sa.inspect(c).get_columns("segment_travelers")})
            c.execute(insert(schema.trips).values(id=1, name="Trip", auto=True))
            c.execute(insert(schema.segments).values(id=1, trip_id=1, kind="flight", status="confirmed", start_local="2026-03-01T10:00",
                                                     start_zone="America/New_York", end_local="2026-03-01T12:00", end_zone="America/New_York", source="manual"))
            c.execute(insert(schema.segment_travelers).values(segment_id=1, name="DOE/JANE MS"))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # a traveller from before has no seat of their own
            self.assertIsNone(conn.execute(select(schema.segment_travelers.c.seat)).scalar())
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0017")
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.segment_travelers)).scalar(), 1)

    def test_0019_adds_where_a_logo_came_from_marks_the_ones_from_before_logodev_and_asks_again(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0018")
            self.assertNotIn("source", {col["name"] for col in sa.inspect(c).get_columns("brand_logos")})
            c.execute(insert(schema.brand_logos).values(key="harbour hotels", name="Harbour Hotels", logo=b"png", logo_type="image/png", checked="2026-10-01T00:00:00"))
            c.execute(insert(schema.brand_logos).values(key="nowhere air", name="Nowhere Air", checked="2026-10-01T00:00:00"))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            rows = {r[0]: r[1:] for r in conn.execute(select(schema.brand_logos.c.key, schema.brand_logos.c.source, schema.brand_logos.c.checked))}
            self.assertEqual(rows, {"harbour hotels": ("logodev", None), "nowhere air": (None, None)})   # (a brand with no logo has no source)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0018")
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.brand_logos)).scalar(), 2)

    def test_0020_drops_the_tier_from_memberships_and_clears_an_expiry_that_an_airline_hotel_or_car_one_had(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0019")
            self.assertIn("tier", {col["name"] for col in sa.inspect(c).get_columns("loyalty_ids")})
            c.execute(insert(schema.people).values(id=1, display_name="Pat"))
            old_loyalty_ids = sa.table("loyalty_ids", *(sa.column(n) for n in ("person_id", "kind", "program", "number", "tier", "expiry")))   # (as it was)
            for kind, program, expiry in (("airline", "Other", "2029-01-31"), ("hotel", "Other", "2029-01-31"), ("car", "Other", "2029-01-31"),
                                          ("known_traveler", "Global Entry", "2029-03-31"), ("redress", "DHS TRIP", "2030-01-01")):
                c.execute(insert(old_loyalty_ids).values(person_id=1, kind=kind, program=program, number="n", tier="Gold", expiry=expiry))
            command.upgrade(db.alembic_config(c), "head")
            self.assertNotIn("tier", {col["name"] for col in sa.inspect(c).get_columns("loyalty_ids")})
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:   # only the numbers that expire keep their date
            got = dict(conn.execute(select(schema.loyalty_ids.c.kind, schema.loyalty_ids.c.expiry)).fetchall())
            self.assertEqual(got, {"airline": None, "hotel": None, "car": None, "known_traveler": "2029-03-31", "redress": "2030-01-01"})
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0019")
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.loyalty_ids)).scalar(), 5)   # (no row lost)
            command.upgrade(db.alembic_config(c), "head")

    def test_0021_adds_the_tables_that_keep_messages_and_takes_them_away_leaving_everything_else(self):
        from alembic import command
        db.init(self.path)
        with db.engine(self.path).begin() as c:
            self.assertTrue({"stored_messages", "segment_messages"} <= set(sa.inspect(c).get_table_names()))
            c.execute(insert(schema.mailboxes).values(id=1, owner_sub="u", address="a@gmail.example", token="t", status="connected"))
            c.execute(insert(schema.review_items).values(mailbox_id=1, message_id="m", sender_domain="x.example", reason="no_markup", created=1.0))
            command.downgrade(db.alembic_config(c), "0020")
            self.assertFalse({"stored_messages", "segment_messages"} & set(sa.inspect(c).get_table_names()))
            self.assertEqual(c.execute(select(sa.func.count()).select_from(schema.review_items)).scalar(), 1)   # (the item stays; its message was a copy)
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])

    def test_a_grant_takes_its_codes_and_tokens_with_it_and_a_client_its_grants(self):
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(schema.oauth_clients).values(id="wpc_x", redirect_uris="[]", auth_method="none", created=1.0))
            conn.execute(insert(schema.oauth_grants).values(id=1, client_id="wpc_x", scope="read", resource="http://h/mcp", created=1.0))
            conn.execute(insert(schema.oauth_tokens).values(token_hash="t", kind="access", grant_id=1, created=1.0, expires=2.0))
            conn.execute(insert(schema.oauth_codes).values(code_hash="c", client_id="wpc_x", grant_id=1, redirect_uri="u",
                                                           code_challenge="x", resource="r", created=1.0))
            conn.execute(delete(schema.oauth_clients).where(schema.oauth_clients.c.id == "wpc_x"))
            for table in ("oauth_grants", "oauth_tokens", "oauth_codes"):
                self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.metadata.tables[table])).scalar(), 0, table)

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
