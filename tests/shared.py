import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import date
from unittest import mock

PHASES: dict[str, float] = {}


@contextmanager
def phase(name):
    started = time.perf_counter()
    try:
        yield
    finally:
        PHASES[name] = PHASES.get(name, 0.0) + time.perf_counter() - started


def tag() -> str:
    return uuid.uuid4().hex[:10]


LOCK_WAIT = "200ms"
KEPT_BETWEEN_TESTS = ("alembic_version", "airports", "airlines")


def _terminate_holders(conn, name) -> None:
    from psycopg import sql
    conn.execute(sql.SQL("SELECT pg_terminate_backend(l.pid) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                         "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = {} AND l.pid <> pg_backend_pid()"
                         ).format(sql.Literal(name)))


def _with_holders_ended(conn, name, statement) -> None:
    import psycopg
    from psycopg import sql
    conn.execute(sql.SQL("SET lock_timeout = {}").format(sql.Literal(LOCK_WAIT)))
    try:
        conn.execute(statement)
    except psycopg.errors.LockNotAvailable:
        _terminate_holders(conn, name)
        conn.execute(statement)


class SchemaPool:

    def __init__(self):
        self.free: list[str] = []
        self.made = 0
        self.template = None
        self.tables: list[str] = []

    def connect(self):
        import psycopg
        return psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    def make(self, name, path) -> None:
        from waypoint.storage import db
        from psycopg import sql
        with self.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        db.TEST_SCHEMAS[path] = name
        db.init(path)

    def start(self) -> None:
        from psycopg import sql
        with self.connect() as conn:
            for (name,) in conn.execute(sql.SQL("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'p\\_%\\_%'")).fetchall():
                try:
                    os.kill(int(name.split("_")[1]), 0)
                except ProcessLookupError:
                    conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
                except (PermissionError, ValueError):
                    pass
        self.template = f"p_{os.getpid()}_template"
        self.make(self.template, "template")
        from waypoint.storage import db
        db.TEST_SCHEMAS.pop("template", None)
        with self.connect() as conn:
            self.tables = [r[0] for r in conn.execute(sql.SQL("SELECT tablename FROM pg_tables WHERE schemaname = %s ORDER BY 1"), [self.template])]

    def acquire(self, path) -> None:
        from waypoint.storage import db
        if self.template is None:
            self.start()
        if self.free:
            db.TEST_SCHEMAS[path] = self.free.pop()
            return
        self.made += 1
        self.make(f"p_{os.getpid()}_{self.made}", path)

    def release(self, path) -> None:
        from psycopg import sql
        from waypoint.storage import db
        name = db.TEST_SCHEMAS.pop(path)
        names = sql.SQL(", ").join(sql.Identifier(name, t) for t in self.tables if t != "alembic_version")
        copies = sql.SQL("; ").join(sql.SQL("INSERT INTO {} SELECT * FROM {}").format(sql.Identifier(name, t), sql.Identifier(self.template, t))
                                    for t in KEPT_BETWEEN_TESTS if t != "alembic_version")
        statement = sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE; {}").format(names, copies)
        with self.connect() as conn:
            _with_holders_ended(conn, name, statement)
        self.free.append(name)


POOL = SchemaPool()


def drop_schema(path) -> None:
    from waypoint.storage import db
    if not db.using_postgres():
        return
    from psycopg import sql
    name = db.schema_for(path)
    with phase("teardown"), POOL.connect() as conn:
        _with_holders_ended(conn, name, sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def release_database(path) -> None:
    from waypoint.storage import db
    if db.using_postgres():
        with phase("teardown"):
            POOL.release(path)


def add_database(case, path) -> str:
    from waypoint.storage import db
    later = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    with phase("schema"):
        if db.using_postgres():
            POOL.acquire(path)
            later(release_database, path)
        else:
            db.init(path)
    return path


def scratch_dir(case) -> str:
    tmp = tempfile.TemporaryDirectory()
    (case.addClassCleanup if isinstance(case, type) else case.addCleanup)(tmp.cleanup)
    return tmp.name


def database_path(case, name="waypoint.db") -> str:
    path = os.path.join(scratch_dir(case), name)
    (case.addClassCleanup if isinstance(case, type) else case.addCleanup)(drop_schema, path)
    return path


def own_database(case, **env) -> str:
    from waypoint.storage import db
    later = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    tmp = tempfile.TemporaryDirectory()
    later(tmp.cleanup)
    environ = mock.patch.dict(os.environ, {"WAYPOINT_DATA": tmp.name, **env})
    environ.start()
    later(environ.stop)
    path = os.path.join(tmp.name, "waypoint.db")
    add_database(case, path)
    opened = db.session
    session = mock.patch.object(db, "session", lambda p=None: opened(p or path))
    session.start()
    later(session.stop)
    return path


class DbCase(unittest.TestCase):

    def setUp(self):
        from waypoint.storage import db
        self.path = own_database(self)
        self.c = db.connect(self.path)
        self.addCleanup(self.c.close)


TODAY = date(2026, 9, 23)


def fetch(base, method, path, data=None, headers=None, timeout=20, follow=True):
    r = urllib.request.Request(base + path, method=method, data=data, headers=headers or {})
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        with opener.open(r, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.headers, e.read()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def serve(case, server_class=None):
    from waypoint import server
    later = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    httpd = (server_class or server.ThreadingHTTPServer)(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    later(httpd.server_close)
    later(httpd.shutdown)
    case.httpd = httpd
    return f"http://127.0.0.1:{httpd.server_port}"


class ServerCase(unittest.TestCase):
    env: dict = {}
    unset: tuple = ()
    server_class: type | None = None
    app_header = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        own_database(cls, **cls.env)
        for k in cls.unset:
            os.environ.pop(k, None)
        cls.base = serve(cls, cls.server_class)

    def req(self, method, path, body=None, headers=None, timeout=20):
        h = {"Content-Type": "application/json", **({"X-Waypoint": "1"} if self.app_header else {}), **(headers or {})}
        status, _, raw = fetch(self.base, method, path, json.dumps(body).encode() if body is not None else None, h, timeout)
        return status, json.loads(raw or b"{}")


def freeze_today(case, day=None):
    later = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    real = date
    today = day or TODAY

    class Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, real)

    class FrozenDate(real, metaclass=Meta):
        def __new__(cls, *args, **kwargs):
            return real(*args, **kwargs)

        @classmethod
        def today(cls):
            return today

    for name, mod in list(sys.modules.items()):
        if (name == "waypoint" or name.startswith(("waypoint.", "tests."))) and getattr(mod, "date", None) is real:
            patch = mock.patch.object(mod, "date", FrozenDate)
            patch.start()
            later(patch.stop)
    return today
