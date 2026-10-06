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
from typing import Any
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def data_dir() -> str:
    d = os.environ.get("WAYPOINT_DATA") or os.path.join(ROOT, "data")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def db_path() -> str:
    return os.path.join(data_dir(), "waypoint.db")


def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def using_postgres() -> bool:
    return bool(database_url())


def engine_url(path: str | None = None) -> str:
    url = database_url()
    if url:
        return re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", url)
    return f"sqlite:///{path or db_path()}"


def describe() -> str:
    if using_postgres():
        u = urlsplit(database_url() or "")
        return f"Postgres {u.hostname or 'local'}{':' + str(u.port) if u.port else ''}/{u.path.lstrip('/')}"
    return db_path()


_engines: dict[tuple, Engine] = {}
_engines_lock = threading.Lock()


def engine(path: str | None = None) -> Engine:
    key = (engine_url(path), path if using_postgres() else None)
    with _engines_lock:
        if key not in _engines:
            _engines[key] = _postgres_engine(key[0], path) if using_postgres() else _sqlite_engine(key[0])
        return _engines[key]


def _sqlite_engine(url: str) -> Engine:
    eng = create_engine(url, poolclass=NullPool, connect_args={"timeout": 30, "check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _setup(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.create_function("lower", 1, _lower, deterministic=True)
    return eng


def _lower(v):
    if v is None or isinstance(v, bytes):
        return v
    return str(v).lower()


def _postgres_engine(url: str, path: str | None) -> Engine:
    from psycopg.adapt import Dumper

    class Untyped(Dumper):
        oid = 0

        def dump(self, obj):
            if isinstance(obj, bool):
                return b"1" if obj else b"0"
            return str(obj).encode()

    test_schema = None if path is None else "t_" + hashlib.sha256(path.encode()).hexdigest()[:12]
    eng = (create_engine(url, poolclass=NullPool) if test_schema
           else create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=60))

    @event.listens_for(eng, "connect")
    def _setup(dbapi_conn, _record):
        for t in (str, int, float, bool):
            dbapi_conn.adapters.register_dumper(t, Untyped)
        if test_schema:
            dbapi_conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{test_schema}"')   # nosemgrep: waypoint-sql-from-string -- a test schema's name, which DDL can't bind
            dbapi_conn.execute(f'SET search_path TO "{test_schema}"')   # nosemgrep: waypoint-sql-from-string -- a test schema's name, which DDL can't bind
            dbapi_conn.commit()
    return eng


class Row(tuple):
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

    def fetchone(self) -> Any:
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

    def scalar(self) -> Any:
        row = self.fetchone()
        return row[0] if row is not None else None

    def scalars(self) -> list:
        return [r[0] for r in self.fetchall()]


class Connection:

    def __init__(self, sa_conn):
        self.sa = sa_conn
        self.postgres = sa_conn.dialect.name == "postgresql"
        self._orm: Session | None = None

    @property
    def orm(self) -> Session:
        if self._orm is None:
            self._orm = Session(bind=self.sa, join_transaction_mode="rollback_only", expire_on_commit=False,
                                autoflush=True)
        return self._orm

    def _before(self) -> None:
        if self._orm is not None:
            self._orm.flush()

    def _after_write(self) -> None:
        if self._orm is not None and self._orm.identity_map:
            self._orm.expire_all()

    def execute(self, stmt, params=None) -> Result:
        if isinstance(stmt, str):
            raise TypeError("SQL text isn't supported; build a statement (docs/src/content/docs/contributing/orm.md)")
        if isinstance(params, list) and not params:
            return Result(rows=[])
        self._before()
        res = self.sa.execute(stmt, params) if params is not None else self.sa.execute(stmt)
        lastrowid = None
        ctx = getattr(res, "context", None)
        if ctx is not None and ctx.isinsert and not ctx.executemany:
            try:
                pk = res.inserted_primary_key
                lastrowid = pk[0] if pk is not None and len(pk) == 1 else None
            except InvalidRequestError:
                lastrowid = None
        if getattr(stmt, "is_dml", False):
            self._after_write()
        return Result(res, lastrowid)

    def commit(self) -> None:
        if self._orm is not None:
            self._orm.commit()
        self.sa.commit()

    def rollback(self) -> None:
        if self._orm is not None:
            self._orm.rollback()
        self.sa.rollback()

    def close(self) -> None:
        if self._orm is not None:
            self._orm.close()
            self._orm = None
        self.sa.close()


BUSY_SQLSTATES = frozenset({"55P03", "40P01", "40001"})


def is_busy(e: BaseException) -> bool:
    orig = getattr(e, "orig", None) or e
    state = getattr(orig, "sqlstate", None)
    if state is not None:
        return state in BUSY_SQLSTATES
    if isinstance(orig, sqlite3.OperationalError):
        name = getattr(orig, "sqlite_errorname", None) or ""
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


def dialect_insert(conn: Connection, entity):
    return (pg_dialect if conn.postgres else sqlite_dialect).insert(entity)


def upsert(conn: Connection, entity, values: dict | list[dict], key: list[str], update=None) -> Result:
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
    many = isinstance(values, list)
    if many and not values:
        return Result(rows=[])
    stmt = dialect_insert(conn, entity)
    if not many:
        stmt = stmt.values(values)
    return conn.execute(stmt.on_conflict_do_nothing(index_elements=key), values if many else None)


def alembic_config(connection=None):
    ini = os.path.join(ROOT, "alembic.ini")
    cfg = Config(ini) if os.path.exists(ini) else Config()
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


MIGRATE_LOCK = 0x57415950
SCHEMA_LOCK = 0x5741


_sqlite_migrating = threading.Lock()


@contextmanager
def _sqlite_turn(path: str | None):
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
    with _sqlite_turn(path), engine(path).connect() as sa_conn:
        sqlite = sa_conn.dialect.name == "sqlite"
        if sqlite:
            sa_conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            sa_conn.commit()
        with sa_conn.begin():
            if not sqlite:
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
                if broken:
                    raise RuntimeError(f"Migrating the database left rows in {', '.join(broken)} that refer to rows that "
                                       "aren't there.")


def init(path: str | None = None) -> None:
    migrate(path)
    if not using_postgres():
        private_files(path or db_path())
    with session(path) as conn:
        secretbox.encrypt_stored(conn)


def private_files(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        with contextlib.suppress(OSError):
            os.chmod(path + suffix, 0o600)


MAX_NUMBER = 1e12


def number(value) -> float:
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
    keys = list(dict.fromkeys(keys))
    found = dict(conn.execute(select(Setting.key, Setting.value).where(Setting.key.in_(keys))).fetchall()) if keys else {}
    out: dict[str, str | None] = {}
    for key in keys:
        value = found.get(key)
        if value is not None and key in secretbox.SECRET_SETTINGS:
            try:
                value = secretbox.decrypt(value)
            except secretbox.SecretError as e:
                monitoring.log(f"Warning: {key}: {e}", "warning")
                value = None
        out[key] = value
    return out


def set_setting(conn, key: str, value: str | None) -> None:
    if value is not None and key in secretbox.SECRET_SETTINGS:
        value = secretbox.encrypt(value)
    upsert(conn, Setting, {"key": key, "value": value}, key=["key"])


def rows(cur) -> list[dict]:
    if hasattr(cur, "mappings"):
        return [dict(m) for m in cur.mappings()]
    return [dict(r) for r in cur.fetchall()]


def as_dict(obj) -> dict:
    return {a.key: getattr(obj, a.key) for a in inspect(obj).mapper.column_attrs}
