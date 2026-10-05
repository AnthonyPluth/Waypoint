"""db.is_busy: a database error that only means something else was writing (so try again), on SQLite and Postgres."""
import os
import sqlite3
import tempfile
import unittest

import psycopg.errors
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from waypoint.storage import db


def wrapped(orig: BaseException) -> OperationalError:
    """The driver's error as SQLAlchemy raises it."""
    return OperationalError("UPDATE account SET balance=?", {}, orig)


def write_lock(dbapi_conn) -> None:
    """Take SQLite's write lock on a plain sqlite3 connection, as a sync's write does."""
    dbapi_conn.execute("BEGIN IMMEDIATE")


class BusyTests(unittest.TestCase):
    def test_sqlite_locked_is_busy(self):
        for text in ("database is locked", "database table is locked", "database table is locked: account"):
            with self.subTest(text=text):
                self.assertTrue(db.is_busy(wrapped(sqlite3.OperationalError(text))))
                self.assertTrue(db.is_busy(sqlite3.OperationalError(text)))

    def test_sqlite_by_its_error_name(self):
        e = sqlite3.OperationalError("something else")
        e.sqlite_errorname = "SQLITE_BUSY_SNAPSHOT"
        self.assertTrue(db.is_busy(wrapped(e)))

    def test_a_real_sqlite_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "x.db")
            a, b = sqlite3.connect(path, timeout=0), sqlite3.connect(path, timeout=0)
            try:
                write_lock(a)
                with self.assertRaises(sqlite3.OperationalError) as caught:
                    write_lock(b)
                self.assertTrue(db.is_busy(caught.exception))
            finally:
                a.close()
                b.close()

    def test_other_sqlite_errors_are_not(self):
        for text in ("no such table: account", "disk I/O error", "the database is locked up tight"):
            with self.subTest(text=text):
                self.assertFalse(db.is_busy(wrapped(sqlite3.OperationalError(text))))

    def test_postgres_lock_timeout_deadlock_and_serialization_failure(self):
        for cls in (psycopg.errors.LockNotAvailable, psycopg.errors.DeadlockDetected, psycopg.errors.SerializationFailure):
            with self.subTest(error=cls.__name__):
                self.assertTrue(db.is_busy(wrapped(cls("could not obtain lock"))))
                self.assertTrue(db.is_busy(cls("x")))

    @unittest.skipUnless(db.using_postgres(), "needs Postgres (DATABASE_URL)")
    def test_a_real_postgres_lock_timeout(self):
        key = 0x7E57B05
        with db.engine().connect() as a, db.engine().connect() as b:
            a.execute(select(func.pg_advisory_xact_lock(key)))
            b.execute(select(func.set_config("lock_timeout", "50ms", False)))
            with self.assertRaises(OperationalError) as caught:
                b.execute(select(func.pg_advisory_xact_lock(key)))
            self.assertTrue(db.is_busy(caught.exception))
            a.rollback()

    def test_other_postgres_errors_are_not(self):
        for e in (psycopg.errors.QueryCanceled("canceling statement"), psycopg.errors.UndefinedColumn("column locked"),
                  psycopg.errors.UniqueViolation("database is locked")):
            with self.subTest(error=type(e).__name__):
                self.assertFalse(db.is_busy(wrapped(e)))
        self.assertFalse(db.is_busy(IntegrityError("INSERT", {}, psycopg.errors.UniqueViolation("dup"))))

    def test_anything_else_is_not(self):
        self.assertFalse(db.is_busy(ValueError("database is locked")))
        self.assertFalse(db.is_busy(KeyError("locked")))


if __name__ == "__main__":
    unittest.main()
