"""For tests that share one database with tests in other processes (on Postgres every test module uses the same schema
unless it passes its own path, and CI runs the modules in parallel with unittest-parallel).

A test that writes settings, or runs something that does (a mail scan, a request through the server), takes a database
of its own with own_database(), so nothing it writes reaches another module's test. Everything else a test makes, it
should find and remove by its own names and ids, never by clearing a table.
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import date
from unittest import mock


def tag() -> str:
    """A name no other test (or run) uses."""
    return uuid.uuid4().hex[:10]


def drop_schema(path) -> None:
    """On Postgres, drop the schema db.init(path) made for this path (db.py names it from the path); SQLite has nothing
    to drop: the file goes with its directory."""
    from waypoint.storage import db
    if not db.using_postgres():
        return
    import psycopg
    from psycopg import sql
    name = "t_" + hashlib.sha1(path.encode(), usedforsecurity=False).hexdigest()[:12]   # as db._postgres_engine names it
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        # A connection the test left open (a transaction never ended) holds locks that would make the drop wait forever.
        conn.execute(sql.SQL("SELECT pg_terminate_backend(l.pid) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                             "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = {} AND l.pid <> pg_backend_pid()"
                             ).format(sql.Literal(name)))
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def add_database(case, path) -> str:
    """db.init(path), and (in setUp, or setUpClass with the class) drop its schema on Postgres when the test is cleaned
    up, so nothing a run makes stays in the database. own_database does this for its own; a test that needs a second
    database (a restore target, an old schema to migrate) makes it with this. Returns the path."""
    from waypoint.storage import db
    db.init(path)
    (case.addClassCleanup if isinstance(case, type) else case.addCleanup)(drop_schema, path)
    return path


def scratch_dir(case) -> str:
    """A directory removed when the test (or class) is cleaned up."""
    tmp = tempfile.TemporaryDirectory()
    (case.addClassCleanup if isinstance(case, type) else case.addCleanup)(tmp.cleanup)
    return tmp.name


def database_path(case, name="waypoint.db") -> str:
    """The path of a database a test makes itself (db.init, db.migrate, or tables made by hand), in a directory of its
    own, with its schema dropped on Postgres and the directory removed when the test is cleaned up. Nothing is created
    yet, and db.session() isn't pointed at it (own_database does that)."""
    path = os.path.join(scratch_dir(case), name)
    (case.addClassCleanup if isinstance(case, type) else case.addCleanup)(drop_schema, path)
    return path


def own_database(case, **env) -> str:
    """In setUp (or a test): a database for this test alone, with db.session() pointed at it and WAYPOINT_DATA (plus any
    other environment variables given) set, all undone when the test is cleaned up. On Postgres its schema is named
    after its path. Returns the path, for db.connect().

    In setUpClass (pass the class): the same for every test in the class, undone after tearDownClass. db.session() is
    patched for the whole process, so a server a class starts on a thread uses it too: start the server after this, and
    stop it in tearDownClass (class cleanups run after that)."""
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
    """A test with a database of its own (own_database) and a connection to it, self.c."""

    def setUp(self):
        from waypoint.storage import db
        self.path = own_database(self)
        self.c = db.connect(self.path)
        self.addCleanup(self.c.close)


TODAY = date(2026, 9, 23)


def fetch(base, method, path, data=None, headers=None, timeout=20, follow=True):
    """One request to a server: (status, headers, body bytes). An error status (4xx, 5xx) comes back the same way, not
    as an exception. follow=False doesn't follow a redirect (the 3xx is returned)."""
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
    """In setUp (or setUpClass, with the class): a Waypoint server on a thread of its own, stopped when the test (or class)
    is cleaned up. Returns its base URL (http://127.0.0.1:PORT). Call own_database() first: the server uses whichever
    database db.session() points at, and the class cleanups run last first, so the server stops before the database goes."""
    from waypoint import server
    later = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    httpd = (server_class or server.ThreadingHTTPServer)(("127.0.0.1", 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    later(httpd.server_close)
    later(httpd.shutdown)           # (runs first)
    case.httpd = httpd
    return f"http://127.0.0.1:{httpd.server_port}"


class ServerCase(unittest.TestCase):
    """A real Waypoint on a thread, on a database of its own for the whole class (own_database, so on Postgres its own
    schema), and req() to call it. Set `env` for environment variables the class needs (put back afterwards), and
    `unset` for ones that must not be set (WAYPOINT_PUBLIC_URL, say); `server_class` picks the HTTP server."""
    env: dict = {}
    unset: tuple = ()
    server_class: type | None = None
    app_header = True       # send X-Waypoint: 1, as the web app does, unless a request says otherwise

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        own_database(cls, **cls.env)    # undone after the server has stopped
        for k in cls.unset:
            os.environ.pop(k, None)
        cls.base = serve(cls, cls.server_class)

    def req(self, method, path, body=None, headers=None, timeout=20):
        """(status, parsed JSON) of a call with a JSON body (an empty response is {})."""
        h = {"Content-Type": "application/json", **({"X-Waypoint": "1"} if self.app_header else {}), **(headers or {})}
        status, _, raw = fetch(self.base, method, path, json.dumps(body).encode() if body is not None else None, h, timeout)
        return status, json.loads(raw or b"{}")


def freeze_today(case, day=None):
    """In setUp (or setUpClass, with the class): date.today() is `day` (shared.TODAY by default) in Waypoint's modules and
    the tests', so a test doesn't depend on the day it runs. (datetime.now() isn't frozen, and a module that imports
    date inside a function isn't either.) Undone when the test (or class) is cleaned up."""
    later = case.addClassCleanup if isinstance(case, type) else case.addCleanup
    real = date
    today = day or TODAY

    class Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, real)

    class FrozenDate(real, metaclass=Meta):
        def __new__(cls, *args, **kwargs):
            return real(*args, **kwargs)        # a real date, so nothing downstream sees a subclass

        @classmethod
        def today(cls):
            return today

    for name, mod in list(sys.modules.items()):
        if (name == "waypoint" or name.startswith(("waypoint.", "tests."))) and getattr(mod, "date", None) is real:
            patch = mock.patch.object(mod, "date", FrozenDate)
            patch.start()
            later(patch.stop)
    return today
