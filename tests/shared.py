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
    return uuid.uuid4().hex[:10]


def drop_schema(path) -> None:
    from waypoint.storage import db
    if not db.using_postgres():
        return
    import psycopg
    from psycopg import sql
    name = "t_" + hashlib.sha256(path.encode()).hexdigest()[:12]
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(sql.SQL("SELECT pg_terminate_backend(l.pid) FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
                             "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = {} AND l.pid <> pg_backend_pid()"
                             ).format(sql.Literal(name)))
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def add_database(case, path) -> str:
    from waypoint.storage import db
    db.init(path)
    (case.addClassCleanup if isinstance(case, type) else case.addCleanup)(drop_schema, path)
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
