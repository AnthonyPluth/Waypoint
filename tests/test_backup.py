import gzip
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest import mock

from sqlalchemy import func, insert, select, update

from waypoint.storage import backup, db
from waypoint import server
from waypoint.storage import settings_keys as sk
from waypoint.storage.models import AuthSession, Person, Setting, User
from tests.shared import add_database, fetch, own_database, serve

db_session = db.session


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.a = own_database(self)
        self.dir = os.path.dirname(self.a)
        self.b = add_database(self, os.path.join(self.dir, "b.db"))

    def fill(self, path):
        c = db.connect(path)
        c.execute(insert(User), [{"sub": f"s{i}", "email": f"person{i}@example.com", "name": f"Person {i}",
                                  "first_name": f"P{i}", "last_seen": 1000.0 + i} for i in range(5)])
        db.set_setting(c, sk.VAPID_PRIVATE_KEY, "a-made-up-signing-key")
        db.set_setting(c, sk.LAST_BACKUP, "2026-09-01T07:00:00")
        c.execute(insert(AuthSession).values(token_hash="h", sub="s0", created=0, expires=9e9))
        c.commit()
        return c

    def test_round_trip(self):
        src = self.fill(self.a)
        raw = backup.dump(src)
        data = backup.load(raw)
        self.assertEqual(data["format"], "waypoint-backup")
        self.assertNotIn("auth_sessions", data["tables"])          # sessions don't travel
        self.assertNotIn("auth_pending", data["tables"])
        stored = dict(data["tables"]["settings"]["rows"])
        self.assertTrue(stored[sk.VAPID_PRIVATE_KEY].startswith("enc:v1:"))   # a secret stays encrypted in the file
        dst = db.connect(self.b)
        dst.execute(insert(User).values(sub="old", email="old@example.com"))   # replaced, not merged
        counts = backup.restore(dst, data)
        dst.commit()
        self.assertEqual(counts["users"], 5)
        self.assertEqual(sorted(r[0] for r in dst.execute(select(User.sub))), [f"s{i}" for i in range(5)])
        self.assertEqual(db.get_setting(dst, sk.VAPID_PRIVATE_KEY), "a-made-up-signing-key")
        self.assertEqual(dst.execute(select(func.count()).select_from(AuthSession)).scalar(), 0)
        src.close(); dst.close()

    def awkward(self, c):
        """Rows with values a restore must put back exactly as they were."""
        c.execute(insert(User).values(sub="a:1|’", email="o'brien+tag@example.com", name="Ünïcödé 🐶 %s :name \\ back\nslash",
                                      first_name="", last_seen=-0.0))
        c.execute(insert(User).values(sub="z", email=None, name="Line one\nline two\ttab " + "x" * 5000, last_seen=1e-9))
        c.execute(insert(Person).values(display_name="Zoë O’Brien-Ünï 🐶", first_name="", legal_name="  Zoë  \"Z\" O'Brien\n",
                                        aliases='["O\'BRIEN/ZOE MS", "OBRIEN/ZOE🐶 MS", ""]', user_sub="a:1|’"))
        c.execute(insert(Person).values(display_name="Grandpa Ño %s \\ 50%", first_name=None, legal_name=None, aliases=None))
        c.execute(insert(Setting).values(key="%_LIKE_%", value='{"json": "inside", "n": 0.1}'))
        c.execute(insert(Setting).values(key="empty", value=""))
        db.set_setting(c, sk.VAPID_PRIVATE_KEY, "secret ’ 🐶")

    def rows_of(self, c):
        return {t: sorted(map(tuple, p["rows"]), key=repr) for t, p in backup.export(c)["tables"].items()}

    def test_round_trip_keeps_awkward_values(self):
        src = db.connect(self.a)
        self.awkward(src)
        src.commit()
        data = backup.load(backup.dump(src))
        self.assertEqual(data["revision"], backup.head())   # made at this version's revision: restored as it is
        dst = db.connect(self.b)
        backup.restore(dst, data)
        dst.commit()
        exported = self.rows_of(dst)
        want = self.rows_of(src)
        # The secret is encrypted again on the way out (a new token each time): compare what it decrypts to.
        for rows in (exported, want):
            rows["settings"] = [(k, secretbox_plain(v) if k == sk.VAPID_PRIVATE_KEY else v) for k, v in rows["settings"]]
        self.assertEqual(exported, want)
        self.assertEqual(db.get_setting(dst, sk.VAPID_PRIVATE_KEY), "secret ’ 🐶")
        src.close(); dst.close()

    def test_people_come_back_exactly_with_their_links(self):
        src = db.connect(self.a)
        self.awkward(src)
        src.commit()
        dst = db.connect(self.b)
        backup.restore(dst, backup.load(backup.dump(src)))
        dst.commit()
        want = sorted((p.display_name, p.first_name, p.legal_name, p.aliases, p.user_sub) for p in src.orm.scalars(select(Person)))
        got = sorted((p.display_name, p.first_name, p.legal_name, p.aliases, p.user_sub) for p in dst.orm.scalars(select(Person)))
        self.assertEqual(len(want), 2)
        self.assertEqual(got, want)
        src.close(); dst.close()

    def test_a_backup_through_the_migrations_from_the_first_revision(self):
        # A backup made at an older revision is brought up to date in a scratch database first. With one migration so
        # far that's 0001 to itself; this keeps the path working for the migrations to come.
        src = self.fill(self.a)
        data = backup.load(backup.dump(src))
        data["revision"] = "0001"
        dst = db.connect(self.b)
        with mock.patch.object(backup, "head", return_value="not-this-one"):   # take the scratch-database path
            backup.restore(dst, data)
        dst.commit()
        self.assertEqual(self.rows_of(dst)["users"], self.rows_of(src)["users"])
        if db.using_postgres():   # the database it was brought up to date in is gone, never committed
            self.assertEqual(dst.sa.exec_driver_sql("SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'waypoint_restore_%%'").scalar(), 0)
        src.close(); dst.close()

    def test_a_backup_from_a_newer_version_is_refused(self):
        src = self.fill(self.a)
        data = backup.load(backup.dump(src))
        for change in ({"revision": "0999"}, {"version": backup.VERSION + 1}):
            with self.subTest(change=change):
                newer = {**data, **change}
                with self.assertRaisesRegex(ValueError, "newer version of Waypoint"):
                    backup.load(gzip.compress(json.dumps(newer).encode()))
        dst = db.connect(self.b)
        dst.execute(insert(User).values(sub="kept"))
        with self.assertRaisesRegex(ValueError, "newer version of Waypoint"):
            backup.restore(dst, {**data, "revision": "0999"})
        self.assertEqual([r[0] for r in dst.execute(select(User.sub))], ["kept"])   # nothing touched
        for bad in (5, ["0001"], None):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "isn't a Waypoint backup"):
                backup.load(json.dumps({**data, "revision": bad}).encode())
        src.close(); dst.close()

    def test_a_backup_without_a_revision_is_refused(self):
        src = self.fill(self.a)
        data = backup.load(backup.dump(src))
        del data["revision"]
        with self.assertRaisesRegex(ValueError, "isn't a Waypoint backup"):
            backup.load(json.dumps(data).encode())
        src.close()

    def test_rejects_other_files(self):
        for raw in (b"hello", gzip.compress(b'{"format": "something-else"}'),
                    json.dumps({"format": "waypoint-backup", "version": 99, "tables": {}}).encode(),
                    json.dumps({"format": "runway-backup", "version": 2, "revision": "0001", "tables": {}}).encode()):
            with self.subTest(raw=raw[:30]), self.assertRaises(ValueError):
                backup.load(raw)

    def test_a_column_from_the_future_is_left_out(self):
        src = self.fill(self.a)
        data = backup.load(backup.dump(src))
        t = data["tables"]["users"]
        t["columns"].append("column_from_the_future"); [r.append(1) for r in t["rows"]]
        dst = db.connect(self.b)
        backup.restore(dst, data)
        self.assertEqual(dst.execute(select(func.count()).select_from(User)).scalar(), 5)
        src.close(); dst.close()

    def test_a_column_only_the_database_has_travels(self):
        src = self.fill(self.a)
        src.sa.exec_driver_sql("ALTER TABLE users ADD COLUMN legacy_note TEXT")   # not in the schema: SQL on the raw connection
        src.sa.exec_driver_sql("UPDATE users SET legacy_note='kept' WHERE sub='s0'")
        data = backup.load(backup.dump(src))
        self.assertIn("legacy_note", data["tables"]["users"]["columns"])
        dst = db.connect(self.b)
        dst.sa.exec_driver_sql("ALTER TABLE users ADD COLUMN legacy_note TEXT")
        backup.restore(dst, data)
        self.assertEqual(dst.sa.exec_driver_sql("SELECT sub, legacy_note FROM users WHERE sub='s0'").fetchall(), [("s0", "kept")])
        src.close(); dst.close()

    def test_restore_all_holds_off_background_jobs(self):
        lock = threading.Lock()
        with mock.patch.object(db, "session", lambda p=None: db_session(p or self.b)):
            data = backup.load(backup.dump(self.fill(self.a)))
            with lock, self.assertRaises(backup.Busy):
                backup.restore_all(data, locks=(threading.Lock(), lock), directory=self.dir)
            with db.session() as c:
                self.assertEqual(c.execute(select(func.count()).select_from(User)).scalar(), 0)   # nothing restored
            done = backup.restore_all(data, locks=(lock,), directory=self.dir)
            self.assertFalse(lock.locked())
            self.assertEqual((done["counts"]["users"], done["safety_copy"], done["unreadable_secrets"]),
                             (5, None, []))   # nothing was here to keep a copy of

    def test_every_secret_has_a_label(self):
        self.assertEqual(set(backup.SECRET_LABELS), set(sk.SECRETS))
        self.assertEqual(backup.unreadable_summary([sk.VAPID_PRIVATE_KEY]), backup.SECRET_LABELS[sk.VAPID_PRIVATE_KEY])
        self.assertEqual(backup.unreadable_summary([]), "")

    def test_preview_says_what_a_backup_holds(self):
        src = self.fill(self.a)
        data = backup.load(backup.dump(src))
        data["tables"]["table_from_the_future"] = {"columns": ["x"], "rows": [[1], [2]]}   # not counted: it isn't restored
        p = backup.preview(data)
        self.assertEqual((p["source"], p["version"]), ("postgres" if db.using_postgres() else "sqlite", backup.VERSION))
        self.assertEqual((p["revision"], p["created"]), (backup.head(), data["created"]))
        self.assertEqual({k: p["counts"][k] for k in backup.SUMMARY}, {"users": 5})
        self.assertEqual(p["counts"]["total"], sum(len(t["rows"]) for n, t in data["tables"].items() if n != "table_from_the_future"))
        self.assertEqual(backup.counts(src), p["counts"])                    # the live database, counted the same way
        self.assertEqual(backup.counts(db.connect(self.b))["users"], 0)
        src.close()

    def test_safety_copy_keeps_what_was_here(self):
        out = os.path.join(self.dir, "copies")
        os.mkdir(out)
        empty = db.connect(self.b)
        self.assertIsNone(backup.safety_copy(empty, out))                    # nothing to keep
        self.assertEqual(os.listdir(out), [])
        src = self.fill(self.a)
        path = backup.safety_copy(src, out)
        assert path is not None
        self.assertEqual(os.path.dirname(path), out)
        self.assertRegex(os.path.basename(path), r"^waypoint-before-restore-\d{4}-\d\d-\d\d-\d{6}\.json\.gz$")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)         # it holds your data: private
        with open(path, "rb") as f:
            kept = backup.load(f.read())
        self.assertEqual(len(kept["tables"]["users"]["rows"]), 5)
        backup.restore(empty, kept)                                          # and it restores like any backup
        self.assertEqual(empty.execute(select(func.count()).select_from(User)).fetchone()[0], 5)
        src.close(); empty.close()


def secretbox_plain(value):
    from waypoint.storage import secretbox
    return secretbox.decrypt(value)


class BackupServerTests(unittest.TestCase):
    """POST /api/backup/inspect, and the copy POST /api/restore keeps of what it replaces. A restore replaces the whole
    database, so the test has one of its own."""
    HEADERS = {"X-Waypoint": "1", "Content-Type": "application/octet-stream"}

    def setUp(self):
        self.data = os.path.dirname(own_database(self))   # WAYPOINT_DATA, where the safety copy goes
        self.base = serve(self, server.Server)

    def post(self, path, body):
        status, _, raw = fetch(self.base, "POST", path, body, self.HEADERS, timeout=10)
        return status, json.loads(raw)

    def get(self, path, method="GET"):
        status, _, raw = fetch(self.base, method, path, timeout=10)
        return status, raw

    def test_downloading_a_backup_records_when(self):
        self.assertIsNone(json.loads(self.get("/api/state")[1])["last_backup"])   # never downloaded
        self.assertEqual(self.get("/api/backup", "HEAD")[0], 200)
        self.assertIsNone(json.loads(self.get("/api/state")[1])["last_backup"])   # a HEAD isn't a download
        before = datetime.now().replace(microsecond=0)
        code, raw = self.get("/api/backup")
        self.assertEqual(code, 200)
        self.assertIn("tables", backup.load(raw))
        stamp = None
        for _ in range(50):   # recorded once the file has been sent, so just after the client has it
            with db.session() as c:
                stamp = db.get_setting(c, sk.LAST_BACKUP)
            if stamp:
                break
            time.sleep(0.05)
        self.assertLessEqual(before, datetime.fromisoformat(stamp))           # the machine's local time, no offset stored
        got = json.loads(self.get("/api/state")[1])["last_backup"]
        self.assertTrue(got.startswith(stamp))                                 # sent with its UTC offset
        self.assertEqual(datetime.fromisoformat(got).replace(tzinfo=None), datetime.fromisoformat(stamp))

    def test_inspect_then_restore_keeps_a_copy(self):
        with db.session() as c:
            c.execute(insert(User).values(sub="test:bk", email="bk@example.com"))
        with db.session() as c:
            raw, here = backup.dump(c), backup.counts(c)
        code, got = self.post("/api/backup/inspect", raw)
        self.assertEqual(code, 200)
        self.assertEqual(got["counts"], here)                                # this backup is of what's here
        self.assertEqual(got["current"], here)
        self.assertIn(got["database"], ("sqlite", "postgres"))
        self.assertEqual(self.post("/api/backup/inspect", b"hello"), (400, {"error": "That file isn't a Waypoint backup."}))
        self.assertEqual(self.post("/api/backup/inspect", b""), (400, {"error": "Choose a backup file (up to 200 MB)."}))
        self.assertFalse([f for f in os.listdir(self.data) if f.startswith("waypoint-before-restore-")])   # inspecting changes nothing

        with db.session() as c:
            c.execute(update(User).where(User.sub == "test:bk").values(email="changed@example.com"))
        code, got = self.post("/api/restore", raw)
        self.assertEqual(code, 200)
        self.assertEqual((got["ok"], got["counts"]["users"], got["unreadable_secrets"]), (True, 1, []))
        path = got["safety_copy"]
        self.assertEqual(os.path.dirname(path), self.data)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        with open(path, "rb") as f:
            self.assertEqual(backup.preview(backup.load(f.read()))["counts"], here)
        with db.session() as c:
            self.assertEqual(c.execute(select(User.email).where(User.sub == "test:bk")).scalar(), "bk@example.com")


    def test_a_restore_that_fails_says_why_and_changes_nothing(self):
        with db.session() as c:
            c.execute(insert(User).values(sub="test:kept", email="kept@example.com"))
            raw = backup.dump(c)
        self.assertEqual(self.post("/api/restore", b""), (400, {"error": "Choose a backup file (up to 200 MB)."}))
        self.assertEqual(self.post("/api/restore", b"hello"), (400, {"error": "That file isn't a Waypoint backup."}))
        busy = sqlite3.OperationalError("database is locked")
        for raised, status, says in ((ValueError("That backup can't be read."), 400, "That backup can't be read."),
                                     (OSError(28, "No space left on device"), 500, "Couldn’t save a copy of what’s here first (No space left on device), so nothing was restored."),
                                     (busy, 503, "Waypoint is busy saving something else. Try the restore again in a few seconds.")):
            with self.subTest(raised=raised), mock.patch.object(backup, "restore_all", side_effect=raised):
                self.assertEqual(self.post("/api/restore", raw), (status, {"error": says}))
        with mock.patch.object(backup, "restore_all", side_effect=RuntimeError("a bug")):
            status, body = self.post("/api/restore", raw)
        self.assertEqual(status, 500)
        self.assertNotIn("a bug", body["error"])
        with db.session() as c:
            self.assertEqual(c.execute(select(User.email).where(User.sub == "test:kept")).scalar(), "kept@example.com")


class RestoreCommandTests(unittest.TestCase):
    """python run.py restore: the same restore as the web's (a copy first, what can't be read)."""

    def run_py(self, data_dir, *args, stdin=None):
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}   # a SQLite database of its own
        env.update(WAYPOINT_DATA=data_dir, WAYPOINT_SECRET_KEY="k" * 40)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run([sys.executable, os.path.join(root, "run.py"), *args], env=env, input=stdin, capture_output=True,
                              text=True, timeout=120, cwd=root)

    def test_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = os.path.join(tmp, "src"), os.path.join(tmp, "dst")
            os.mkdir(src); os.mkdir(dst)
            made = self.run_py(src, "demo")
            self.assertEqual(made.returncode, 0, made.stderr)
            out = os.path.join(tmp, "b.json.gz")
            self.assertEqual(self.run_py(src, "backup", out).returncode, 0)
            with open(out, "rb") as f:
                data = backup.load(f.read())
            data["tables"]["users"]["rows"].append(["s-cli", "cli@example.com", "Cli Example", "Cli", 1.0])
            full = os.path.join(tmp, "full.json.gz")
            with open(full, "wb") as f:
                f.write(gzip.compress(json.dumps(data, default=str).encode()))

            r = self.run_py(dst, "restore", full, stdin="no\n")
            self.assertEqual(r.returncode, 1)
            self.assertIn("Nothing changed.", r.stderr)
            self.assertIn("Stop Waypoint first", r.stdout)

            r = self.run_py(dst, "restore", full, "--yes")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Restored", r.stdout)
            self.assertNotIn("A copy of what was here", r.stdout)        # an empty database: nothing to keep

            r = self.run_py(dst, "restore", full, "--yes")                # again, over what's there now
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("A copy of what was here before is at " + dst, r.stdout)
            self.assertTrue([f for f in os.listdir(dst) if f.startswith("waypoint-before-restore-")])
            self.assertNotIn("can't be read", r.stdout)

            # A secret this key can't read (made under another): named as Settings has it, never its value.
            data["tables"]["settings"]["rows"].append([sk.VAPID_PRIVATE_KEY, "enc:v1:not-this-key-sekrit"])
            locked = os.path.join(tmp, "locked.json.gz")
            with open(locked, "wb") as f:
                f.write(gzip.compress(json.dumps(data, default=str).encode()))
            r = self.run_py(dst, "restore", locked, "--yes")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("These can't be read with this Waypoint's secret key: "
                          f"{backup.SECRET_LABELS[sk.VAPID_PRIVATE_KEY]}.", r.stdout)
            self.assertNotIn("sekrit", r.stdout + r.stderr)
            self.assertNotIn(sk.VAPID_PRIVATE_KEY, r.stdout)

            data["revision"] = "0999"
            with open(full, "wb") as f:
                f.write(gzip.compress(json.dumps(data, default=str).encode()))
            r = self.run_py(dst, "restore", full, "--yes")
            self.assertEqual(r.returncode, 1)
            self.assertIn("newer version of Waypoint", r.stderr)


if __name__ == "__main__":
    unittest.main()
