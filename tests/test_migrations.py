import contextlib
import os
import shutil
import unittest
from unittest import mock

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import delete, insert, select, update

from waypoint.storage import backup, db, schema, secretbox
from waypoint.storage.models import Setting, User
from tests.shared import database_path, scratch_dir


def drift(path):
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


def replay(path):
    from alembic import command
    with db.engine(path).begin() as c:
        command.upgrade(db.alembic_config(c), "head")


@contextlib.contextmanager
def migrating(path):
    with db.engine(path).connect() as c:
        if c.dialect.name == "sqlite":
            c.exec_driver_sql("PRAGMA foreign_keys=OFF")
            c.commit()
        with c.begin():
            yield c


def shape(path):
    with db.engine(path).connect() as c:
        insp = sa.inspect(c)
        out = {}
        for table in sorted(insp.get_table_names()):
            out[table] = dict(
                columns=[(col["name"], str(col["type"]), col["nullable"], str(col["default"]), col.get("autoincrement"))
                         for col in insp.get_columns(table)],
                pk=insp.get_pk_constraint(table)["constrained_columns"],
                fks=sorted((fk["name"], tuple(fk["constrained_columns"]), fk["referred_table"], tuple(fk["referred_columns"]),
                            str(fk.get("options"))) for fk in insp.get_foreign_keys(table)),
                uniques=sorted((u["name"], tuple(u["column_names"])) for u in insp.get_unique_constraints(table)),
                indexes=sorted((i["name"], tuple(i["column_names"]), bool(i["unique"])) for i in insp.get_indexes(table)))
        return out


def rows_of(path, table):
    with db.engine(path).connect() as c:
        return sorted(tuple(r) for r in c.exec_driver_sql(f"SELECT * FROM {table}"))


def with_next_migration(case, probe="9001"):
    source = os.path.join(os.path.dirname(db.__file__), "migrations")
    root = os.path.join(scratch_dir(case), "migrations")
    os.makedirs(root)
    for name in ("env.py", "script.py.mako"):
        shutil.copy(os.path.join(source, name), root)
    for name in ("airports.tsv.gz", "airlines.tsv.gz"):
        shutil.copy(os.path.join(os.path.dirname(source), name), os.path.dirname(root))
    shutil.copytree(os.path.join(source, "versions"), os.path.join(root, "versions"), ignore=shutil.ignore_patterns("__pycache__"))
    head = ScriptDirectory.from_config(db.alembic_config()).get_current_head()
    with open(os.path.join(root, "versions", f"{probe}_probe.py"), "w") as f:
        f.write(f"import sqlalchemy as sa\nfrom alembic import op\n\nrevision = {probe!r}\ndown_revision = {head!r}\n"
                "branch_labels = None\ndepends_on = None\n\n\ndef upgrade() -> None:\n"
                "    op.add_column('settings', sa.Column('probe', sa.Text()))\n\n\ndef downgrade() -> None:\n"
                "    op.drop_column('settings', 'probe')\n")
    real = db.alembic_config

    def config(connection=None):
        cfg = real(connection)
        cfg.set_main_option("script_location", root)
        return cfg
    patch = mock.patch.object(db, "alembic_config", config)
    patch.start()
    case.addCleanup(patch.stop)
    return probe


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.path = database_path(self, "m.db")

    def test_fresh_database_matches_schema(self):
        db.init(self.path)
        self.assertEqual(drift(self.path), [])
        with db.engine(self.path).connect() as c:
            head = ScriptDirectory.from_config(db.alembic_config()).get_current_head()
            self.assertEqual(c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(), head)
        db.init(self.path)
        self.assertEqual(drift(self.path), [])

    def test_a_new_database_is_made_in_one_step_and_equals_one_made_by_running_the_migrations(self):
        made = database_path(self, "replayed.db")
        replay(made)
        db.init(self.path)
        self.assertEqual(drift(self.path), [])
        self.assertEqual(shape(self.path), shape(made))
        for table in ("airports", "airlines", "alembic_version"):
            with self.subTest(table=table):
                self.assertEqual(rows_of(self.path, table), rows_of(made, table))
        self.assertGreater(len(rows_of(self.path, "airports")), 5000)
        self.assertGreater(len(rows_of(self.path, "airlines")), 500)

    def test_the_first_start_makes_the_schema_in_one_step_and_the_second_does_nothing_more(self):
        from alembic import command
        with mock.patch.object(command, "upgrade", wraps=command.upgrade) as upgrade, \
                mock.patch.object(schema.metadata, "create_all", wraps=schema.metadata.create_all) as create_all:
            db.init(self.path)
            self.assertEqual((create_all.call_count, upgrade.call_count), (1, 0))
            head = ScriptDirectory.from_config(db.alembic_config()).get_current_head()
            self.assertEqual(rows_of(self.path, "alembic_version"), [(head,)])
            with db.session(self.path) as conn:
                conn.execute(insert(User).values(sub="s1", email="ana@example.com"))
            before = shape(self.path)
            db.init(self.path)
            self.assertEqual(create_all.call_count, 1)
            self.assertEqual(shape(self.path), before)
            self.assertEqual(rows_of(self.path, "alembic_version"), [(head,)])
            self.assertEqual([r[0] for r in rows_of(self.path, "users")], ["s1"])

    def test_a_database_the_migrations_made_starts_with_nothing_to_do_and_keeps_its_rows(self):
        from alembic import command
        replay(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(User).values(sub="s1", email="ana@example.com"))
            conn.execute(insert(schema.trips).values(id=1, name="Trip", auto=True))
        head = ScriptDirectory.from_config(db.alembic_config()).get_current_head()
        before = (shape(self.path), rows_of(self.path, "users"), rows_of(self.path, "trips"), rows_of(self.path, "airports"))
        with mock.patch.object(schema.metadata, "create_all") as create_all, \
                mock.patch.object(command, "upgrade", wraps=command.upgrade) as upgrade:
            db.init(self.path)
        create_all.assert_not_called()
        self.assertEqual(upgrade.call_count, 1)
        self.assertEqual((shape(self.path), rows_of(self.path, "users"), rows_of(self.path, "trips"), rows_of(self.path, "airports")), before)
        self.assertEqual(rows_of(self.path, "alembic_version"), [(head,)])
        self.assertEqual(drift(self.path), [])

    def test_a_migration_added_later_upgrades_a_database_of_either_kind(self):
        fresh, replayed = database_path(self, "fresh.db"), database_path(self, "replayed.db")
        db.init(fresh)
        replay(replayed)
        for path in (fresh, replayed):
            with db.session(path) as conn:
                conn.execute(insert(Setting).values(key="kept", value="yes"))
        probe = with_next_migration(self)
        for path in (fresh, replayed):
            with self.subTest(path=os.path.basename(path)):
                db.init(path)
                with db.engine(path).connect() as c:
                    self.assertIn("probe", {col["name"] for col in sa.inspect(c).get_columns("settings")})
                self.assertEqual(rows_of(path, "alembic_version"), [(probe,)])
                self.assertEqual([r[:2] for r in rows_of(path, "settings")], [("kept", "yes")])
                db.init(path)
                self.assertEqual(rows_of(path, "alembic_version"), [(probe,)])

    def test_every_migration_goes_down_and_up_again(self):
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

    def test_a_database_last_used_before_the_squash_is_refused_with_a_plain_message_and_left_as_it_was(self):
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(User).values(sub="s1", email="ana@example.com"))
        for old in ("0001", "0033"):
            with db.engine(self.path).begin() as c:
                c.exec_driver_sql(f"UPDATE alembic_version SET version_num = '{old}'")
            before = (shape(self.path), rows_of(self.path, "users"))
            with self.subTest(revision=old):
                with self.assertRaisesRegex(RuntimeError, "before its database migrations were squashed into one") as raised:
                    db.migrate(self.path)
                self.assertIn("last release before the squash", str(raised.exception))
                self.assertNotIn("Can't locate", str(raised.exception))
                self.assertEqual((shape(self.path), rows_of(self.path, "users")), before)
                self.assertEqual(rows_of(self.path, "alembic_version"), [(old,)])

    def test_0034_is_the_baseline_that_makes_every_table_and_the_reference_rows_and_takes_them_away(self):
        from alembic import command
        replay(self.path)
        self.assertEqual(drift(self.path), [])
        self.assertEqual({name for name in shape(self.path)} - {"alembic_version"}, set(schema.metadata.tables))
        self.assertGreater(len(rows_of(self.path, "airports")), 5000)
        self.assertGreater(len(rows_of(self.path, "airlines")), 500)
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "base")
            self.assertEqual(set(sa.inspect(c).get_table_names()) - {"alembic_version"}, set())
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])

    def test_0035_keeps_only_the_final_flight_statuses_and_leaves_the_times_of_the_last_checks(self):
        from alembic import command
        old_status = sa.table("flight_status", *(sa.column(n) for n in ("flight_number", "date", "state", "dep_gate", "fetched_at", "attempted_at")))
        with db.engine(self.path).begin() as c:
            command.upgrade(db.alembic_config(c), "0034")
            for number, state, fetched, attempted in (("EX1", "landed", 10.0, 10.0), ("EX2", "cancelled", 20.0, None), ("EX3", "diverted", 30.0, 31.0),
                                                      ("EX4", "delayed", 40.0, 45.0), ("EX5", "scheduled", 50.0, None), ("EX6", "departed", 60.0, 55.0),
                                                      ("EX7", "unknown", 0.0, 70.0), ("EX8", "unknown", 0.0, None)):
                c.execute(old_status.insert().values(flight_number=number, date="2026-11-20", state=state, dep_gate="B24",
                                                     fetched_at=fetched, attempted_at=attempted))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        self.assertEqual([(r[0], r[1], r[2]) for r in rows_of(self.path, "flight_status")],
                         [("EX1", "2026-11-20", "landed"), ("EX2", "2026-11-20", "cancelled"), ("EX3", "2026-11-20", "diverted")])
        self.assertNotIn("attempted_at", [col[0] for col in shape(self.path)["flight_status"]["columns"]])
        self.assertEqual(rows_of(self.path, "flight_checks"),
                         [("EX4", "2026-11-20", 45.0), ("EX5", "2026-11-20", 50.0), ("EX6", "2026-11-20", 60.0), ("EX7", "2026-11-20", 70.0)])
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0034")
        self.assertEqual(len(rows_of(self.path, "flight_status")), 3)
        self.assertIn("attempted_at", [col[0] for col in shape(self.path)["flight_status"]["columns"]])

    def test_0036_removes_retired_logo_credentials_on_upgrade_and_backup_restore(self):
        from alembic import command
        with mock.patch.dict(os.environ, {"WAYPOINT_SECRET_KEY": "synthetic-key-for-retired-logo-migration"}):
            settings = {"logodev_token": "fictional-token", "logodev_secret": secretbox.encrypt("fictional-secret"),
                        "logodev_last_error": "fictional-error", "distance_unit": "km"}
        with db.engine(self.path).begin() as c:
            command.upgrade(db.alembic_config(c), "0035")
            c.execute(insert(Setting), [{"key": key, "value": value} for key, value in settings.items()])
        with db.session(self.path) as conn:
            old = backup.export(conn)
        db.init(self.path)
        self.assertEqual(rows_of(self.path, "settings"), [("distance_unit", "km")])
        self.assertEqual(drift(self.path), [])
        with db.session(self.path) as conn:
            backup.restore(conn, old)
            self.assertEqual(backup.export(conn)["tables"]["settings"]["rows"], [["distance_unit", "km"]])
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0035")
        db.init(self.path)
        self.assertEqual(rows_of(self.path, "settings"), [("distance_unit", "km")])

    def test_0037_adds_the_review_reminder_choice_on_for_everyone_who_already_chose_and_takes_it_away(self):
        from alembic import command
        with db.engine(self.path).begin() as c:
            command.upgrade(db.alembic_config(c), "0036")
            old = sa.table("reminder_prefs", sa.column("owner_sub"), sa.column("check_in"), sa.column("day_of"))
            c.execute(old.insert(), [{"owner_sub": "sub-a", "check_in": True, "day_of": False}, {"owner_sub": "sub-b", "check_in": False, "day_of": True}])
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        self.assertEqual(sorted(rows_of(self.path, "reminder_prefs")), [("sub-a", True, False, True), ("sub-b", False, True, True)])
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0036")
        self.assertEqual(sorted(rows_of(self.path, "reminder_prefs")), [("sub-a", True, False), ("sub-b", False, True)])
        self.assertNotIn("review", [col[0] for col in shape(self.path)["reminder_prefs"]["columns"]])

    def test_0038_photos_adds_the_three_tables_and_takes_them_away(self):
        from alembic import command
        with db.engine(self.path).begin() as c:
            command.upgrade(db.alembic_config(c), "0037")
        self.assertFalse({"photo_sources", "photos", "photo_trip_syncs"} & set(shape(self.path)))
        db.init(self.path)
        self.assertEqual(drift(self.path), [])
        tables = shape(self.path)
        self.assertEqual(tables["photo_sources"]["uniques"], [("uq_photo_sources_person_url_user", ("person_id", "url", "immich_user_id"))])
        self.assertEqual(tables["photos"]["uniques"], [("uq_photos_source_asset", ("source_id", "asset_id"))])
        self.assertEqual([i[0] for i in tables["photos"]["indexes"] if not i[2]], ["ix_photos_segment_id", "ix_photos_source_id_taken_utc", "ix_photos_trip_id"])
        self.assertEqual(tables["photo_trip_syncs"]["pk"], ["source_id", "trip_id"])
        ondelete = {(t, fk[0]): fk[4] for t in ("photo_sources", "photos", "photo_trip_syncs") for fk in tables[t]["fks"]}
        self.assertIn("CASCADE", ondelete[("photo_sources", "fk_photo_sources_person_id")])
        self.assertIn("CASCADE", ondelete[("photos", "fk_photos_source_id")])
        self.assertIn("SET NULL", ondelete[("photos", "fk_photos_trip_id")])
        self.assertIn("SET NULL", ondelete[("photos", "fk_photos_segment_id")])
        self.assertIn("CASCADE", ondelete[("photo_trip_syncs", "fk_photo_trip_syncs_source_id")])
        self.assertIn("CASCADE", ondelete[("photo_trip_syncs", "fk_photo_trip_syncs_trip_id")])
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0037")
        self.assertFalse({"photo_sources", "photos", "photo_trip_syncs"} & set(shape(self.path)))

    def test_0039_turns_hidden_photos_into_one_exclusion_each_and_its_downgrade_widens_nothing(self):
        from alembic import command
        old_photos = sa.table("photos", *(sa.column(n) for n in ("id", "source_id", "asset_id", "asset_updated", "kind", "taken_utc", "taken_local", "trip_id", "match", "hidden", "seen")))
        syncs = sa.table("photo_trip_syncs", *(sa.column(n) for n in ("source_id", "trip_id", "window_start", "window_end")))

        def photo(c, id, source, asset, trip, hidden=False):
            c.execute(old_photos.insert().values(id=id, source_id=source, asset_id=asset, asset_updated="t", kind="image", taken_utc="2026-01-01T00:00:00Z",
                                                 taken_local="2026-01-01T00:00", trip_id=trip, match="time", hidden=hidden, seen=1.0))
        with migrating(self.path) as c:
            command.upgrade(db.alembic_config(c), "0038")
            c.execute(insert(schema.people), [{"id": 1, "display_name": "One"}, {"id": 2, "display_name": "Two"}])
            c.execute(insert(schema.trips), [{"id": n, "name": f"Trip {n}", "auto": True} for n in (1, 2, 3)])
            c.execute(insert(schema.photo_sources), [{"id": s, "person_id": p, "owner_sub": "sub-x", "url": f"https://photos{s}.example", "immich_user_id": "u",
                                                      "api_key": "enc:v1:x", "status": "ok", "created": 1.0} for s, p in ((1, 1), (2, 1), (3, 2))])
            photo(c, 1, 1, "twice", 1, hidden=True)
            photo(c, 2, 2, "twice", 1, hidden=True)
            photo(c, 3, 3, "theirs", 1, hidden=True)
            photo(c, 4, 1, "shown", 1)
            photo(c, 5, 1, "unplaced", None, hidden=True)
            c.execute(syncs.insert().values(source_id=1, trip_id=1, window_start="a", window_end="b"))
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        self.assertEqual(shape(self.path)["photo_sources"]["uniques"], [("uq_photo_sources_person_url_user", ("person_id", "url", "immich_user_id"))])
        with db.session(self.path) as conn:
            conn.execute(insert(schema.photo_sources), [{"id": s, "person_id": 1, "owner_sub": "sub-x", "url": "https://two-accounts.example", "immich_user_id": u,
                                                         "api_key": "enc:v1:x", "status": "ok", "created": 1.0} for s, u in ((8, "first-user"), (9, "second-user"))])
        self.assertEqual([r[:3] for r in rows_of(self.path, "photo_exclusions")], [(1, "twice", 1), (2, "theirs", 1)])
        self.assertTrue(all(r[3] > 0 for r in rows_of(self.path, "photo_exclusions")))
        self.assertEqual((rows_of(self.path, "photos"), rows_of(self.path, "photo_trip_syncs")), ([], []))
        tables = shape(self.path)
        self.assertNotIn("hidden", [col[0] for col in tables["photos"]["columns"]])
        self.assertIn("ask_again", [col[0] for col in tables["photo_grants"]["columns"]])
        self.assertIn("was_trip_id", [col[0] for col in tables["photo_exclusions"]["columns"]])
        self.assertIn("SET NULL", {fk[0]: fk[4] for fk in tables["photo_exclusions"]["fks"]}["fk_photo_exclusions_was_trip_id"])
        self.assertEqual((tables["photo_grants"]["pk"], tables["photo_exclusions"]["pk"], tables["photo_sharing_prefs"]["pk"]),
                         (["person_id", "trip_id"], ["person_id", "asset_id", "trip_id"], ["person_id"]))
        self.assertEqual([i[0] for i in tables["photo_grants"]["indexes"] if not i[2]], ["ix_photo_grants_trip_id"])
        self.assertEqual([i[0] for i in tables["photo_exclusions"]["indexes"] if not i[2]], ["ix_photo_exclusions_trip_id"])
        for table in ("photo_grants", "photo_exclusions", "photo_sharing_prefs"):
            for fk in tables[table]["fks"]:
                if fk[0] != "fk_photo_exclusions_was_trip_id":
                    self.assertIn("CASCADE", fk[4], (table, fk[0]))
        with db.session(self.path) as conn:
            conn.execute(insert(schema.trips), [{"id": 4, "name": "Trip 4", "auto": True}, {"id": 5, "name": "Trip 5", "auto": True}])
            conn.execute(update(schema.trips).where(schema.trips.c.id == 1).values(booked_by=2))
            conn.execute(insert(schema.trip_people), [{"trip_id": t, "person_id": p} for t, p in ((1, 1), (2, 1), (3, 2), (5, 1))])
            conn.execute(insert(schema.photo_grants), [{"person_id": p, "trip_id": t, "scope": scope, "revoked": revoked, "changed": 1.0, "granted_by": "sub-x"}
                                                       for p, t, scope, revoked in ((1, 1, "trip", None), (1, 2, "only_me", None), (2, 1, "trip", 2.0), (2, 3, "trip", None), (2, 4, "trip", None),
                                                                                    (1, 5, "trip", None))])
            conn.execute(insert(schema.photo_exclusions).values(person_id=1, asset_id="removed", trip_id=1, created=3.0))
            conn.execute(insert(schema.photo_exclusions).values(person_id=1, asset_id="elsewhere", trip_id=2, created=3.0))
            conn.execute(insert(schema.photo_sharing_prefs).values(person_id=1, default_scope="trip", share_all=True, set_by="sub-x", share_all_since=4.0, steward_sub=None))
            rows = [(1, 1, "shown", 1), (2, 1, "removed", 1), (3, 2, "elsewhere", 1), (4, 1, "mine", 2), (5, 1, "unplaced", None),
                    (6, 3, "stopped", 1), (7, 3, "ok", 3), (8, 3, "ungranted", 2), (9, 3, "left", 4), (10, 1, "members_only", 5)]
            conn.execute(insert(schema.photos), [{"id": id, "source_id": source, "asset_id": asset, "asset_updated": "t", "kind": "image", "taken_utc": "2026-01-01T00:00:00Z",
                                                  "taken_local": "2026-01-01T00:00", "trip_id": trip, "match": "time", "seen": 1.0} for id, source, asset, trip in rows])
            conn.execute(insert(schema.photo_trip_syncs).values(source_id=1, trip_id=1, window_start="a", window_end="b"))
        with migrating(self.path) as c:
            command.downgrade(db.alembic_config(c), "0038")
        self.assertFalse({"photo_grants", "photo_exclusions", "photo_sharing_prefs"} & set(shape(self.path)))
        self.assertEqual(shape(self.path)["photo_sources"]["uniques"], [("uq_photo_sources_person_url", ("person_id", "url"))])
        self.assertEqual([r[0] for r in rows_of(self.path, "photo_sources") if r[3] == "https://two-accounts.example"], [8])
        self.assertIn("hidden", [col[0] for col in shape(self.path)["photos"]["columns"]])
        self.assertEqual((rows_of(self.path, "photos"), rows_of(self.path, "photo_trip_syncs")), ([], []))
        with migrating(self.path) as c:
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        self.assertEqual(rows_of(self.path, "photo_exclusions"), [])

    def test_0040_pages_photo_syncs_by_capture_time_and_restarts_a_traversal_in_progress(self):
        from alembic import command
        old = sa.table("photo_trip_syncs", *(sa.column(n) for n in ("source_id", "trip_id", "window_start", "window_end", "cursor", "resume_page", "fetch_started")))
        with db.engine(self.path).begin() as c:
            command.upgrade(db.alembic_config(c), "0039")
            c.execute(insert(schema.people).values(id=1, display_name="One"))
            c.execute(insert(schema.trips), [{"id": 1, "name": "Trip 1", "auto": True}, {"id": 2, "name": "Trip 2", "auto": True}])
            c.execute(insert(schema.photo_sources).values(id=1, person_id=1, owner_sub="sub-x", url="https://photos.example", immich_user_id="u",
                                                         api_key="enc:v1:x", status="ok", created=1.0))
            c.execute(old.insert(), [{"source_id": 1, "trip_id": 1, "window_start": "a", "window_end": "b", "cursor": "c1", "resume_page": None, "fetch_started": None},
                                     {"source_id": 1, "trip_id": 2, "window_start": "a", "window_end": "b", "cursor": None, "resume_page": 3, "fetch_started": "f"}])
            command.upgrade(db.alembic_config(c), "head")
        self.assertEqual(drift(self.path), [])
        self.assertEqual([r[:7] for r in rows_of(self.path, "photo_trip_syncs")], [(1, 1, "a", "b", "c1", None, None), (1, 2, "a", "b", None, None, None)])
        with db.engine(self.path).begin() as c:
            command.downgrade(db.alembic_config(c), "0039")
            names = [r[1] for r in c.exec_driver_sql("PRAGMA table_info(photo_trip_syncs)")]
        self.assertIn("resume_page", names)
        self.assertFalse({"resume_after", "inputs"} & set(names))
        self.assertEqual([(r[names.index("cursor")], r[names.index("resume_page")]) for r in rows_of(self.path, "photo_trip_syncs")], [("c1", None), (None, None)])

    def test_a_photo_source_takes_its_photos_and_syncs_with_it_and_a_trip_only_unmatches_its_photos(self):
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(schema.people).values(id=1, display_name="Person"))
            conn.execute(insert(schema.trips).values(id=1, name="Trip", auto=True))
            conn.execute(insert(schema.photo_sources).values(id=1, person_id=1, owner_sub="local", url="https://photos.example.com",
                                                             immich_user_id="u", api_key="enc:v1:x", status="ok", created=1.0))
            conn.execute(insert(schema.photos).values(id=1, source_id=1, asset_id="a", asset_updated="t", kind="image", taken_utc="2026-01-01T00:00:00Z",
                                                      taken_local="2026-01-01T00:00", trip_id=1, match="time", seen=1.0))
            conn.execute(insert(schema.photo_trip_syncs).values(source_id=1, trip_id=1, window_start="a", window_end="b"))
            conn.execute(insert(schema.photo_grants).values(person_id=1, trip_id=1, scope="trip", changed=1.0, granted_by="sub-a"))
            conn.execute(insert(schema.photo_exclusions).values(person_id=1, asset_id="b", trip_id=1, created=1.0))
            conn.execute(insert(schema.trips).values(id=2, name="Other", auto=True))
            conn.execute(insert(schema.photo_exclusions).values(person_id=1, asset_id="c", trip_id=2, created=1.0, was_trip_id=1))
            conn.execute(insert(schema.photo_sharing_prefs).values(person_id=1, default_scope="only_me", share_all=False, steward_sub="sub-b"))
            conn.execute(delete(schema.trips).where(schema.trips.c.id == 1))
            self.assertIsNone(conn.execute(select(schema.photos.c.trip_id)).scalar())
            self.assertEqual(conn.execute(select(schema.photo_exclusions.c.asset_id, schema.photo_exclusions.c.was_trip_id)).fetchall(), [("c", None)])
            conn.execute(delete(schema.photo_exclusions))
            for table in ("photo_trip_syncs", "photo_grants", "photo_exclusions"):
                self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.metadata.tables[table])).scalar(), 0, table)
            self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.photo_sharing_prefs)).scalar(), 1)
            conn.execute(delete(schema.people).where(schema.people.c.id == 1))
            for table in ("photo_sources", "photos", "photo_sharing_prefs"):
                self.assertEqual(conn.execute(select(sa.func.count()).select_from(schema.metadata.tables[table])).scalar(), 0, table)

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
        import threading
        errors = []

        def start(path):
            try:
                db.migrate(path)
            except Exception as e:
                errors.append(e)
        path = database_path(self, "together.db")
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
        import threading
        held, free = database_path(self, "held.db"), database_path(self, "free.db")
        db.migrate(held)
        with db.engine(held).connect() as other:
            other.exec_driver_sql(f"SELECT pg_advisory_xact_lock({db.SCHEMA_LOCK}, hashtext(current_schema()))")
            waiting = threading.Thread(target=db.migrate, args=(held,))
            waiting.start()
            db.migrate(free)
            self.assertEqual(drift(free), [])
            waiting.join(1)
            self.assertTrue(waiting.is_alive())
            other.rollback()
        waiting.join(30)
        self.assertFalse(waiting.is_alive())

    def test_connection_wrapper(self):
        db.init(self.path)
        with db.session(self.path) as conn:
            conn.execute(insert(User).values(sub="50% off", email="a@example.com"))
            row = conn.execute(select(User.sub, User.email).where(User.sub.like("50%"))).fetchone()
            self.assertEqual((row[0], row["email"], dict(row)["sub"]), ("50% off", "a@example.com", "50% off"))
            conn.execute(insert(Setting).values(key="n", value=5))
            self.assertEqual(db.get_setting(conn, "n"), "5")


if __name__ == "__main__":
    unittest.main()
