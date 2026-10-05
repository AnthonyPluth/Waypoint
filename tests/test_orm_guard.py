"""Waypoint queries with SQLAlchemy statements built from waypoint/storage/models.py (docs/src/content/docs/contributing/orm.md),
and db.Connection.execute() doesn't take SQL text. This finds any SQL text passed to `execute()`/`executemany()` in
waypoint/ and tests/ and fails if there is some, so a query in text doesn't come back (in a code path the tests don't
run, or in a test).

What counts as SQL text: a string, f-string, string concatenation or formatting (`"..." + x`, `"..." % x`,
`"...".format()`, `", ".join()`), or a variable assigned one in the same function, as the first argument. Also any
SQLAlchemy `text(...)` without a `# raw SQL: <why>` comment on its line or the line above: text() is allowed only for
SQL that can't be written with SQLAlchemy, and must say why. Not counted: waypoint/storage/migrations (history, written once),
the driver-level SQL on a raw DB-API connection (`dbapi_conn.execute("PRAGMA ...")` in db.py's engine setup, or a
test's own sqlite3 connection named dbapi_conn), and `exec_driver_sql()` on a SQLAlchemy connection (db.py's schema
upgrade, and tests that set up older schemas).
"""
import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNED = ("waypoint", "tests")
SKIPPED_DIRS = {"migrations", "static", "fixtures", "__pycache__"}
EXEMPT_RECEIVERS = {"dbapi_conn"}


def _is_sql_text(node, string_names: set[str]) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        return _is_sql_text(node.left, string_names) or _is_sql_text(node.right, string_names)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("format", "join"):
        return _is_sql_text(node.func.value, string_names)
    if isinstance(node, ast.IfExp):
        return _is_sql_text(node.body, string_names) or _is_sql_text(node.orelse, string_names)
    if isinstance(node, ast.Name):
        return node.id in string_names
    return False


def _string_names(fn) -> set[str]:
    """Names assigned SQL text anywhere in a function (or module)."""
    names: set[str] = set()
    for _ in range(2):
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and _is_sql_text(n.value, names):
                names.update(t.id for t in n.targets if isinstance(t, ast.Name))
            elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and _is_sql_text(n.value, names):
                names.add(n.target.id)
    return names


def _sqlalchemy_names(tree) -> tuple[set[str], set[str]]:
    """The names SQLAlchemy's text() goes by in this module (`from sqlalchemy import text`), and the names the
    sqlalchemy package does (`import sqlalchemy as sa`, for `sa.text`). Another function called text isn't it."""
    texts, modules = set(), set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "sqlalchemy":
            texts.update(a.asname or a.name for a in n.names if a.name == "text")
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] == "sqlalchemy":
                    modules.add(a.asname or "sqlalchemy")
    return texts, modules


def count(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    lines = src.splitlines()
    texts, modules = _sqlalchemy_names(tree)
    scopes = {id(tree): _string_names(tree)}
    parents = {}
    for p in ast.walk(tree):
        for ch in ast.iter_child_nodes(p):
            parents[id(ch)] = p
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes[id(ch)] = _string_names(ch)

    def names_for(node) -> set[str]:
        p = parents.get(id(node))
        while p is not None and id(p) not in scopes:
            p = parents.get(id(p))
        return scopes[id(p) if p is not None else id(tree)]

    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr in ("execute", "executemany") and node.args:
            if isinstance(f.value, ast.Name) and f.value.id in EXEMPT_RECEIVERS:
                continue
            if _is_sql_text(node.args[0], names_for(node)):
                n += 1
        elif (isinstance(f, ast.Name) and f.id in texts) or (isinstance(f, ast.Attribute) and f.attr == "text"
                                                            and isinstance(f.value, ast.Name) and f.value.id in modules):
            around = " ".join(lines[max(0, node.lineno - 2):node.lineno])
            parent = parents.get(id(node))
            if isinstance(parent, ast.keyword) and parent.arg == "server_default":
                continue
            if "# raw SQL:" not in around:
                n += 1
    return n


def counts() -> dict[str, int]:
    """SQL text found, by module (only modules with some)."""
    out = {}
    for top in SCANNED:
        for d, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = sorted(x for x in dirs if x not in SKIPPED_DIRS)
            for fn in sorted(files):
                if fn.endswith(".py"):
                    p = os.path.join(d, fn)
                    c = count(p)
                    if c:
                        out[os.path.relpath(p, ROOT).replace(os.sep, "/")] = c
    return dict(sorted(out.items()))


class OrmGuardTests(unittest.TestCase):
    def test_no_sql_text(self):
        self.assertEqual(counts(), {}, "SQL text passed to execute() (module: how many). Write the query with SQLAlchemy "
                                       "and the models instead: see docs/src/content/docs/contributing/orm.md.")

    def test_counter(self):
        src = '''
import sqlalchemy as sa
from sqlalchemy import text


def f(conn, x):
    conn.execute("SELECT 1")
    conn.execute(f"SELECT {x}")
    conn.execute("SELECT " + x)
    q = "SELECT 1"
    q += " WHERE 1"
    conn.execute(q, ())
    conn.executemany("INSERT INTO t VALUES (?)", [])
    conn.execute(select(T))
    stmt = select(T)
    conn.execute(stmt)
    dbapi_conn.execute("PRAGMA foreign_keys=ON")
    conn.sa.exec_driver_sql("PRAGMA busy_timeout=1000")
    text("SELECT 2")
    sa.text("SELECT 3")
    # raw SQL: a window function SQLAlchemy can express, but not readably
    text("SELECT 4")
'''
        own = '''
def text(r):   # a test's own helper, not SQLAlchemy's
    return r["text"]


text({"text": "SELECT 5"})
'''
        import tempfile
        for code, want in ((src, 7), (own, 0)):
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
                f.write(code)
            try:
                self.assertEqual(count(f.name), want)
            finally:
                os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
