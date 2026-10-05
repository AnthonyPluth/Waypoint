"""Waypoint's database: SQLite (a file in WAYPOINT_DATA) by default, or Postgres when DATABASE_URL is set.

SQLAlchemy provides the engine for both, and Alembic keeps the schema (waypoint/storage/schema.py) up to date: migrations run
when Waypoint starts. The rest of Waypoint queries through the small Connection wrapper here, which works the same on
either database (rows read by name or position, `lastrowid`, ...): with SQLAlchemy statements built from the ORM
models in waypoint/storage/models.py (docs/src/content/docs/contributing/orm.md), or through its ORM Session (`conn.orm`). SQL
text isn't taken: a statement is compiled for whichever database the connection is on.
"""
from __future__ import annotations

import fcntl
import hashlib
import contextlib
import math
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.dialects import postgresql as pg_dialect
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from .. import monitoring
from . import secretbox
from .models import Setting

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the repository: waypoint/storage/db.py is two folders down

def data_dir() -> str:
    d = os.environ.get("WAYPOINT_DATA") or os.path.join(ROOT, "data")
    os.makedirs(d, mode=0o700, exist_ok=True)   # the database and (without WAYPOINT_SECRET_KEY) its key: Waypoint's user only
    return d


def db_path() -> str:
    return os.path.join(data_dir(), "waypoint.db")


def database_url() -> str | None:
    """Postgres connection string, if Waypoint should use Postgres instead of its SQLite file."""
    return os.environ.get("DATABASE_URL") or None


def using_postgres() -> bool:
    return bool(database_url())


def engine_url(path: str | None = None) -> str:
    url = database_url()
    if url:   # postgres://... and postgresql://... both mean "Postgres through psycopg 3"
        return re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", url)
    return f"sqlite:///{path or db_path()}"


def describe() -> str:
    if using_postgres():
        u = urlsplit(database_url() or "")
        return f"Postgres {u.hostname or 'local'}{':' + str(u.port) if u.port else ''}/{u.path.lstrip('/')}"
    return db_path()


# ------------------------------------------------------------------------------------------------ engines

_engines: dict[tuple, Engine] = {}
_engines_lock = threading.Lock()


def engine(path: str | None = None) -> Engine:
    """One engine per database. On Postgres, a path (only ever passed by tests) picks a schema of its own, so each
    test gets an empty database."""
    key = (engine_url(path), path if using_postgres() else None)
    with _engines_lock:
        if key not in _engines:
            _engines[key] = _postgres_engine(key[0], path) if using_postgres() else _sqlite_engine(key[0])
        return _engines[key]


def _sqlite_engine(url: str) -> Engine:
    # A fresh connection per request, as before; SQLite connections are cheap and this keeps locks short.
    eng = create_engine(url, poolclass=NullPool, connect_args={"timeout": 30, "check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _setup(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        # SQLite's own lower() leaves anything past ASCII as it is ("É" stays "É"); Postgres's lowers every letter. So a
        # search for "é" found "CAFÉ" on one and not the other: Python's lower() takes its place, on every connection.
        dbapi_conn.create_function("lower", 1, _lower, deterministic=True)
    return eng


def _lower(v):
    """SQLite's lower(), for every letter: NULL stays NULL, a number becomes its text as SQLite's does."""
    if v is None or isinstance(v, bytes):
        return v
    return str(v).lower()


def _postgres_engine(url: str, path: str | None) -> Engine:
    from psycopg.adapt import Dumper   # the Postgres driver: only loaded when DATABASE_URL is set

    class Untyped(Dumper):
        """Send values as "unknown" so Postgres fits them to the column, as SQLite's loose typing would
        (a Python int into a TEXT column, '5' compared with an INTEGER, ...)."""
        oid = 0

        def dump(self, obj):
            if isinstance(obj, bool):
                return b"1" if obj else b"0"
            return str(obj).encode()

    # Only a short, stable name for a test's schema, not a secret; changing the hash would orphan existing test schemas.
    test_schema = None if path is None else "t_" + hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest()[:12]
    # Tests make an engine per database; they don't keep connections open, so they don't run Postgres out of them.
    eng = (create_engine(url, poolclass=NullPool) if test_schema
           else create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=60))   # up to 64 requests plus syncs at once

    @event.listens_for(eng, "connect")
    def _setup(dbapi_conn, _record):
        for t in (str, int, float, bool):
            dbapi_conn.adapters.register_dumper(t, Untyped)
        if test_schema:
            dbapi_conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{test_schema}"')   # nosemgrep: waypoint-sql-from-string -- a test schema's name, which DDL can't bind
            dbapi_conn.execute(f'SET search_path TO "{test_schema}"')   # nosemgrep: waypoint-sql-from-string -- a test schema's name, which DDL can't bind
            dbapi_conn.commit()
    return eng


# ------------------------------------------------------------------------------------------------ connections

class Row(tuple):
    """A result row, read by name (row["id"]) or position (row[0]); dict(row) works too."""
    __slots__ = ()
    _idx: dict = {}

    def __getitem__(self, k):
        if isinstance(k, str):
            return tuple.__getitem__(self, self._idx[k])
        return tuple.__getitem__(self, k)

    def keys(self):
        return list(self._idx)


class Result:
    def __init__(self, res=None, lastrowid=None, rows=None):
        self._res, self.lastrowid = res, lastrowid
        self._make = None
        if res is not None and res.returns_rows:
            cls = type("Row", (Row,), {"__slots__": (), "_idx": {k: i for i, k in enumerate(res.keys())}})
            self._make = cls
        self._rows = rows

    @property
    def rowcount(self) -> int:
        return self._res.rowcount if self._res is not None else 0

    def fetchone(self):
        if self._rows is not None:
            return self._rows.pop(0) if self._rows else None
        if self._make is None:
            return None
        r = self._res.fetchone()
        return self._make(r) if r is not None else None

    def fetchall(self) -> list:
        if self._rows is not None:
            out, self._rows = self._rows, []
            return out
        if self._make is None:
            return []
        return [self._make(r) for r in self._res.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    def scalar(self):
        """The first column of the first row, or None if there are no rows (`SELECT COUNT(*) ...` -> the count)."""
        row = self.fetchone()
        return row[0] if row is not None else None

    def scalars(self) -> list:
        """The first column of every row."""
        return [r[0] for r in self.fetchall()]


class Connection:
    """A database connection and its open transaction: one per request or sync, never shared between threads.

    `execute()` takes a SQLAlchemy statement (`select(Account.id).where(...)`, `update(Asset)...`; see
    docs/src/content/docs/contributing/orm.md). `orm` is an ORM Session on this same connection and transaction, for
    loading and changing model objects. Either way, `commit()` commits everything so far (and is what code calls before
    a slow network request, so the write lock isn't held through it); `rollback()` undoes it. `sa` is the SQLAlchemy
    connection underneath.
    """

    def __init__(self, sa_conn):
        self.sa = sa_conn
        self.postgres = sa_conn.dialect.name == "postgresql"
        self._orm: Session | None = None

    @property
    def orm(self) -> Session:
        """An ORM Session sharing this connection and its transaction, made on first use.

        If the connection is already in a transaction, the Session joins it ("rollback_only": its commit() doesn't
        commit the connection's transaction; a rollback does roll it back); otherwise it begins the transaction itself.
        Either way, only Connection.commit()/rollback() should end it: they flush the Session and commit or roll back
        both together. Objects stay readable after a commit (expire_on_commit=False)."""
        if self._orm is None:
            self._orm = Session(bind=self.sa, join_transaction_mode="rollback_only", expire_on_commit=False,
                                autoflush=True)
        return self._orm

    def _before(self) -> None:
        # A statement run here doesn't go through the Session: write out its pending changes first, so it sees them.
        if self._orm is not None:
            self._orm.flush()

    def _after_write(self) -> None:
        # ... and objects the Session already loaded may be out of date after an UPDATE or DELETE run here.
        if self._orm is not None and self._orm.identity_map:
            self._orm.expire_all()

    def execute(self, stmt, params=None) -> Result:
        """Run a SQLAlchemy statement (params: a dict, or a list of dicts for many rows)."""
        if isinstance(stmt, str):
            raise TypeError("SQL text isn't supported; build a statement (docs/src/content/docs/contributing/orm.md)")
        if isinstance(params, list) and not params:   # no rows: nothing to do (not one row of defaults)
            return Result(rows=[])
        self._before()
        res = self.sa.execute(stmt, params) if params is not None else self.sa.execute(stmt)
        lastrowid = None
        ctx = getattr(res, "context", None)
        if ctx is not None and ctx.isinsert and not ctx.executemany:
            try:
                pk = res.inserted_primary_key
                lastrowid = pk[0] if pk is not None and len(pk) == 1 else None
            except InvalidRequestError:   # e.g. an INSERT ... SELECT: there's no one new row
                lastrowid = None
        if getattr(stmt, "is_dml", False):
            self._after_write()
        return Result(res, lastrowid)

    def commit(self) -> None:
        if self._orm is not None:
            self._orm.commit()   # flushes; commits the transaction if the Session began it, else leaves that to us
        self.sa.commit()         # nothing to do if the Session just committed it

    def rollback(self) -> None:
        if self._orm is not None:
            self._orm.rollback()
        self.sa.rollback()

    def close(self) -> None:
        if self._orm is not None:
            self._orm.close()
            self._orm = None
        self.sa.close()


# Postgres's SQLSTATEs for "another transaction is in the way, try again": lock_not_available (a lock_timeout ran out),
# deadlock_detected and serialization_failure (this transaction was the one rolled back).
BUSY_SQLSTATES = frozenset({"55P03", "40P01", "40001"})


def is_busy(e: BaseException) -> bool:
    """Whether a database error means only that something else was writing at the time (a sync, say), so the same
    request is worth trying again in a moment: SQLite's "database is locked" (SQLITE_BUSY, SQLITE_LOCKED), or one of
    Postgres's BUSY_SQLSTATES. Takes SQLAlchemy's error or the driver's own."""
    orig = getattr(e, "orig", None) or e
    state = getattr(orig, "sqlstate", None)
    if state is not None:   # psycopg's errors carry their SQLSTATE
        return state in BUSY_SQLSTATES
    if isinstance(orig, sqlite3.OperationalError):
        name = getattr(orig, "sqlite_errorname", None) or ""   # (not on one made by hand, as in the tests)
        return name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")) or str(orig).startswith(("database is locked", "database table is locked"))
    return False


def connect(path: str | None = None) -> Connection:
    return Connection(engine(path).connect())


@contextmanager
def session(path: str | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ------------------------------------------------------------------------------------------------ SQL helpers
# Portable pieces for SQLAlchemy statements (docs/src/content/docs/contributing/orm.md): each works the same on SQLite
# and Postgres.

def dialect_insert(conn: Connection, entity):
    """An INSERT for this connection's database that can take .on_conflict_do_update()/.on_conflict_do_nothing()
    (SQLite and Postgres both have ON CONFLICT, but SQLAlchemy builds it with each one's own insert())."""
    return (pg_dialect if conn.postgres else sqlite_dialect).insert(entity)


def upsert(conn: Connection, entity, values: dict | list[dict], key: list[str], update=None) -> Result:
    """INSERT ... ON CONFLICT(key) DO UPDATE SET col=excluded.col, for one row (a dict of column name -> value) or
    many (a list of dicts, all with the same keys).

    `update` picks what a conflict changes: None = every column given except the key; a list of column names; or a
    function taking the would-be row (`excluded`) and returning {column name: expression}, for anything else
    (`lambda ex: {"value": func.coalesce(ex.value, Asset.value)}`). Nothing to update means ON CONFLICT DO NOTHING."""
    many = isinstance(values, list)
    if many and not values:
        return Result(rows=[])
    stmt = dialect_insert(conn, entity)
    if not many:
        stmt = stmt.values(values)
    cols = values[0] if many else values
    if callable(update):
        set_ = update(stmt.excluded)
    else:
        set_ = {c: stmt.excluded[c] for c in (update if update is not None else [c for c in cols if c not in key])}
    stmt = stmt.on_conflict_do_update(index_elements=key, set_=set_) if set_ else stmt.on_conflict_do_nothing(index_elements=key)
    return conn.execute(stmt, values if many else None)


def insert_ignore(conn: Connection, entity, values: dict | list[dict], key: list[str] | None = None) -> Result:
    """INSERT ... ON CONFLICT DO NOTHING: rows already there (by `key`, or by any unique constraint) are left alone."""
    many = isinstance(values, list)
    if many and not values:
        return Result(rows=[])
    stmt = dialect_insert(conn, entity)
    if not many:
        stmt = stmt.values(values)
    return conn.execute(stmt.on_conflict_do_nothing(index_elements=key), values if many else None)


# ------------------------------------------------------------------------------------------------ schema

def alembic_config(connection=None):
    ini = os.path.join(ROOT, "alembic.ini")
    cfg = Config(ini) if os.path.exists(ini) else Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


MIGRATE_LOCK = 0x57415950      # "WAYP": Postgres advisory lock key, held while one process migrates
SCHEMA_LOCK = 0x5741          # "WA": with the schema's hash, the lock for migrating a test's own schema


_sqlite_migrating = threading.Lock()


@contextmanager
def _sqlite_turn(path: str | None):
    """On SQLite, migrations take turns too: a lock file beside the database (other processes) and a lock in this one
    (other threads; a file lock is per process). SQLite's own locking only starts at a transaction's first write, after
    each of them has seen an empty database and set out to create the same tables."""
    if using_postgres():
        yield
        return
    target = path or db_path()
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    with _sqlite_migrating, open(target + ".migrate-lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def migrate(path: str | None = None) -> None:
    """Bring the database's schema up to date. Processes starting together (several copies of Waypoint, or the tests
    running in parallel) take turns: the others wait for the first to finish, then find nothing left to do. On Postgres
    a test's own schema (a path) is a database of its own, so it has a lock of its own: tests migrating different
    schemas don't queue behind each other, while two migrating the same one still take turns."""
    with _sqlite_turn(path), engine(path).connect() as sa_conn:
        sqlite = sa_conn.dialect.name == "sqlite"
        if sqlite:
            # SQLite changes a table by making it again (Alembic's batch mode): with foreign keys on, dropping the old
            # copy would take every row referring to it along (ON DELETE CASCADE). So they're off while migrating (set
            # before a transaction starts: inside one it does nothing), and checked afterwards.
            sa_conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            sa_conn.commit()
        with sa_conn.begin():
            if not sqlite:   # the lock is released when this transaction ends
                if path is None:
                    sa_conn.exec_driver_sql(f"SELECT pg_advisory_xact_lock({MIGRATE_LOCK})")   # nosemgrep: waypoint-sql-from-string -- an integer constant
                else:
                    sa_conn.exec_driver_sql(f"SELECT pg_advisory_xact_lock({SCHEMA_LOCK}, hashtext(current_schema()))")   # nosemgrep: waypoint-sql-from-string -- integer constants
            tables = set(inspect(sa_conn).get_table_names())
            cfg = alembic_config(sa_conn)
            if tables and "alembic_version" not in tables:
                raise RuntimeError("The database has tables but no migration history: it isn't one Waypoint made.")
            command.upgrade(cfg, "head")
            if sqlite:
                broken = sorted({r[0] for r in sa_conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()})
                if broken:   # the migrations left a row referring to one that isn't there (table names only: no data)
                    raise RuntimeError(f"Migrating the database left rows in {', '.join(broken)} that refer to rows that "
                                       "aren't there.")


def init(path: str | None = None) -> None:
    migrate(path)
    if not using_postgres():
        private_files(path or db_path())
    with session(path) as conn:
        secretbox.encrypt_stored(conn)   # secrets saved under an older key


def private_files(path: str) -> None:
    """The SQLite database (and its journal files, which SQLite makes with the same mode) readable by Waypoint's user
    only: it's created with the process's umask, usually readable by everyone on the machine."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            os.chmod(path + suffix, 0o600)


MAX_NUMBER = 1e12   # more than any amount, price or count here; a sum of bigger ones overflows to inf


def number(value) -> float:
    """float(), for a number someone typed or sent: "nan" and "inf" are refused (float() takes them, and one saved
    would spoil every sum it's in, or stop the sync that uses it), and so is anything past MAX_NUMBER (a product of
    two such overflows to inf just the same, and inf isn't JSON)."""
    n = float(value)
    if math.isnan(n) or n in (float("inf"), float("-inf")):
        raise ValueError(f"{value!r} isn't a number")
    if abs(n) > MAX_NUMBER:
        raise ValueError(f"{value!r} is too large")
    return n


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    value = get_settings(conn, [key])[key]
    return value if value is not None else default


def get_settings(conn, keys) -> dict[str, str | None]:
    """Several settings in one query: {key: get_setting's value for it (None when it isn't set)}."""
    keys = list(dict.fromkeys(keys))
    found = dict(conn.execute(select(Setting.key, Setting.value).where(Setting.key.in_(keys))).fetchall()) if keys else {}
    out: dict[str, str | None] = {}
    for key in keys:
        value = found.get(key)
        if value is not None and key in secretbox.SECRET_SETTINGS:
            try:
                value = secretbox.decrypt(value)
            except secretbox.SecretError as e:   # the key changed: behave as if it was never entered, and say why
                monitoring.log(f"Warning: {key}: {e}", "warning")
                value = None
        out[key] = value
    return out


def set_setting(conn, key: str, value: str | None) -> None:
    if value is not None and key in secretbox.SECRET_SETTINGS:
        value = secretbox.encrypt(value)   # secrets are stored encrypted (waypoint/storage/secretbox.py)
    upsert(conn, Setting, {"key": key, "value": value}, key=["key"])


def rows(cur) -> list[dict]:
    """Every row of a result as a dict (column name -> value), from Connection.execute() or a Session's execute()."""
    if hasattr(cur, "mappings"):   # a SQLAlchemy Result (conn.orm.execute(...))
        return [dict(m) for m in cur.mappings()]
    return [dict(r) for r in cur.fetchall()]


def as_dict(obj) -> dict:
    """A model object's columns as a dict, in the table's order: what `SELECT *` gave as a row."""
    return {a.key: getattr(obj, a.key) for a in inspect(obj).mapper.column_attrs}
