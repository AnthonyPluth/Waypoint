from __future__ import annotations

import gzip
import json
import os
import threading
import uuid
import zlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from alembic import command
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Connection as SAConnection
from sqlalchemy import Column, MetaData, column, create_engine, delete, false, func, insert, inspect, select, table
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateColumn

from . import db, schema, secretbox
from .. import monitoring
from . import settings_keys as sk
from .models import LoyaltyId, Mailbox, Setting

FORMAT = "waypoint-backup"
VERSION = 1
SKIP = {"auth_sessions", "auth_pending", "mailbox_pending", "airports", "airlines", "flight_status", "brand_logos", "push_devices", "calendar_feeds",
        "reminders_sent", "oauth_clients", "oauth_grants", "oauth_codes", "oauth_tokens", "oauth_consents"}
ASSISTANT_TABLES = ("oauth_tokens", "oauth_codes", "oauth_consents", "oauth_grants", "oauth_clients")
NEWER = "That backup is from a newer version of Waypoint. Update Waypoint first."


def tables() -> list[str]:
    return [t.name for t in schema.metadata.sorted_tables if t.name not in SKIP]


def table_columns(conn, table: str) -> list[str]:
    return [c["name"] for c in inspect(conn.sa).get_columns(table)]


def _table(name: str, cols: list[str]):
    t = schema.metadata.tables[name]
    return t if all(c in t.c for c in cols) else table(name, *(column(c) for c in cols))


def _secret_columns(table: str, cols: list[str]):
    if table == "settings" and "key" in cols and "value" in cols:
        k, v = cols.index("key"), cols.index("value")
        return lambda row: [v] if row[k] in secretbox.SECRET_SETTINGS else []
    if table in secretbox.SECRET_COLUMNS:
        found = [cols.index(c) for c in secretbox.SECRET_COLUMNS[table] if c in cols]
        if found:
            return lambda row: found
    return None


def _convert(table: str, cols: list[str], rows: list[list], fn) -> list[list]:
    which = _secret_columns(table, cols)
    if not which:
        return rows
    for row in rows:
        for i in which(row):
            row[i] = fn(row[i])
    return rows


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(db.alembic_config())


def head() -> str:
    return str(_scripts().get_current_head())


def revision(sa_conn) -> str | None:
    if not inspect(sa_conn).has_table("alembic_version"):
        return None
    return sa_conn.execute(select(column("version_num")).select_from(table("alembic_version"))).scalar()


def export(conn) -> dict:
    have = set(inspect(conn.sa).get_table_names())
    out: dict[str, Any] = {"format": FORMAT, "version": VERSION, "revision": revision(conn.sa),
                           "created": datetime.now().isoformat(timespec="seconds"),
                           "source": "postgres" if conn.postgres else "sqlite", "tables": {}}
    for t in tables():
        if t not in have:
            continue
        cols = table_columns(conn, t)
        src = _table(t, cols)
        rows = [list(r) for r in conn.execute(select(*(src.c[c] for c in cols)))]
        out["tables"][t] = {"columns": cols, "rows": _convert(t, cols, rows, secretbox.encrypt)}
    return out


def dump(conn) -> bytes:
    return gzip.compress(json.dumps(export(conn), separators=(",", ":"), default=str).encode(), compresslevel=6)


MAX_UNPACKED = 256 * 1024 * 1024


def _gunzip(raw: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw, MAX_UNPACKED + 1)
    if len(out) > MAX_UNPACKED:
        raise ValueError("That backup is too large to restore.")
    if not d.eof:
        raise ValueError("That file isn't a Waypoint backup.")
    return out


def _check_revision(data: dict) -> None:
    rev = data.get("revision")
    if not isinstance(rev, str):
        raise ValueError("That file isn't a Waypoint backup.")
    try:
        known = _scripts().get_revision(rev) is not None
    except CommandError:
        known = False
    if not known:
        raise ValueError(NEWER)


def load(raw: bytes) -> dict:
    try:
        if raw[:2] == b"\x1f\x8b":
            raw = _gunzip(raw)
    except zlib.error as e:
        raise ValueError("That file isn't a Waypoint backup.") from e
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise ValueError("That file isn't a Waypoint backup.") from e
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("tables"), dict):
        raise ValueError("That file isn't a Waypoint backup.")
    if not isinstance(data.get("version", 0), int):
        raise ValueError("That file isn't a Waypoint backup.")
    if data.get("version", 0) > VERSION:
        raise ValueError(NEWER)
    _check_revision(data)
    return data


SUMMARY = ("users",)


def _summary_counts(rows: dict[str, int]) -> dict[str, int]:
    return {**{t: rows.get(t, 0) for t in SUMMARY}, "total": sum(rows.values())}


def preview(data: dict) -> dict:
    known = set(tables())
    rows = {t: len(p.get("rows") or []) for t, p in data["tables"].items() if t in known and isinstance(p, dict)}
    return {"created": data.get("created"), "source": data.get("source"), "version": data.get("version", 0),
            "revision": data.get("revision"), "counts": _summary_counts(rows)}


def counts(conn) -> dict[str, int]:
    return _summary_counts({t: conn.execute(select(func.count()).select_from(schema.metadata.tables[t])).scalar() or 0
                            for t in tables()})


def save_copy(conn, name: str, directory: str | None = None) -> str:
    directory = directory or db.data_dir()
    stamp = datetime.now().strftime('%Y-%m-%d-%H%M%S')
    data = dump(conn)
    n = 1
    while True:
        path = os.path.join(directory, f"{name}-{stamp}{f'-{n}' if n > 1 else ''}.json.gz")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            n += 1
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def safety_copy(conn, directory: str | None = None) -> str | None:
    if not counts(conn)["total"]:
        return None
    return save_copy(conn, "waypoint-before-restore", directory)


def unreadable_secrets(conn) -> list[str]:
    out = []
    for r in conn.execute(select(Setting.key, Setting.value).where(Setting.key.in_(sorted(secretbox.SECRET_SETTINGS)))
                          .order_by(Setting.key)).fetchall():
        try:
            secretbox.decrypt(r["value"])
        except secretbox.SecretError:
            out.append(r["key"])
    if any(not _readable(token) for token in conn.execute(select(Mailbox.token)).scalars()):
        out.append(MAILBOXES)
    if any(not _readable(number) for number in conn.execute(select(LoyaltyId.number)).scalars()):
        out.append(LOYALTY)
    return out


def _readable(token: str) -> bool:
    try:
        secretbox.decrypt(token)
    except secretbox.SecretError:
        return False
    return True


MAILBOXES = "mailboxes"
MAILBOXES_LABEL = "Gmail connections (connect them again in Settings)"
LOYALTY = "loyalty_ids"
LOYALTY_LABEL = "loyalty numbers (enter them again on People)"

SECRET_LABELS = {
    sk.VAPID_PRIVATE_KEY: "notifications' signing key (devices sign up for notifications again)",
    sk.AI_OPENROUTER_KEY: "OpenRouter key (enter it again in Settings → AI)",
    sk.LOGODEV_TOKEN: "Logo.dev publishable key (enter it again in Settings → Brand logos)",
    sk.LOGODEV_SECRET: "Logo.dev secret key (enter it again in Settings → Brand logos)",
}


def unreadable_summary(unreadable: list[str]) -> str:
    labels = {**SECRET_LABELS, MAILBOXES: MAILBOXES_LABEL, LOYALTY: LOYALTY_LABEL}
    return ", ".join(dict.fromkeys(label for key, label in labels.items() if key in unreadable))


Rows = dict[str, tuple[list[str], list[list]]]


@contextmanager
def _scratch(conn) -> Iterator[SAConnection]:
    if not conn.postgres:
        eng = create_engine("sqlite://", poolclass=StaticPool)
        try:
            with eng.connect() as sc, sc.begin():
                yield sc
        finally:
            eng.dispose()
        return
    with conn.sa.engine.connect() as sc:
        trans = sc.begin()
        try:
            name = f"waypoint_restore_{uuid.uuid4().hex[:12]}"
            sc.exec_driver_sql(f'CREATE SCHEMA "{name}"')   # nosemgrep: waypoint-sql-from-string -- a name made here, which DDL can't bind
            sc.exec_driver_sql(f'SET LOCAL search_path TO "{name}"')   # nosemgrep: waypoint-sql-from-string -- a name made here, which DDL can't bind
            yield sc
        finally:
            trans.rollback()


def _migrate(sc: SAConnection, to: str) -> None:
    cfg = db.alembic_config(sc)
    cfg.attributes["restoring"] = True
    command.upgrade(cfg, to)


def _upgraded(conn, data: dict) -> Rows:
    rev: str = data["revision"]
    with _scratch(conn) as sc:
        _migrate(sc, rev)
        then = MetaData()
        then.reflect(sc)
        order = [t for t in then.sorted_tables if t.name != "alembic_version"]
        for t in reversed(order):
            sc.execute(delete(t))
        target = inspect(conn.sa)
        given: Rows = {}
        for t in order:
            payload = data["tables"].get(t.name)
            if not isinstance(payload, dict):
                continue
            there = set(t.c.keys())
            if target.has_table(t.name):
                for c in target.get_columns(t.name):
                    if c["name"] in payload["columns"] and c["name"] not in there:
                        ddl = CreateColumn(Column(c["name"], c["type"])).compile(dialect=sc.dialect)
                        sc.exec_driver_sql(f'ALTER TABLE "{t.name}" ADD COLUMN {ddl}')   # nosemgrep: waypoint-sql-from-string -- the model's own table and column names, which DDL can't bind
                        there.add(c["name"])
            cols = [c for c in payload["columns"] if c in there]
            keep = [payload["columns"].index(c) for c in cols]
            given[t.name] = (cols, _convert(t.name, cols, [[r[i] for i in keep] for r in payload["rows"]], secretbox.encrypt))
        _prune(given, then)
        if sc.dialect.name == "postgresql":
            sc.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")
        for t in order:
            cols, rows = given.get(t.name, ([], []))
            if rows and cols:
                sc.execute(insert(table(t.name, *(column(c) for c in cols))), [dict(zip(cols, r, strict=True)) for r in rows])
        if sc.dialect.name == "postgresql":
            sc.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
        _migrate(sc, "head")
        insp = inspect(sc)
        out: Rows = {}
        for name in tables():
            if not insp.has_table(name):
                continue
            cols = [c["name"] for c in insp.get_columns(name)]
            got: list[Any] = list(sc.execute(select(*(column(c) for c in cols)).select_from(table(name))))
            out[name] = (cols, [list(row) for row in got])
        return out


def _as_given(data: dict) -> Rows:
    known = set(tables())
    return {t: (list(p["columns"]), [list(r) for r in p["rows"]]) for t, p in data["tables"].items()
            if t in known and isinstance(p, dict)}


def _prune(rows: Rows, meta: MetaData) -> dict[str, int]:
    gone: dict[str, int] = {}
    for t in meta.sorted_tables:
        if t.name not in rows:
            continue
        cols, data = rows[t.name]
        for fk in sorted(t.foreign_keys, key=lambda f: f.parent.name):
            if fk.parent.name not in cols:
                continue
            parent = fk.column.table.name
            pcols, prows = rows.get(parent, ([], []))
            if parent == t.name:
                pcols, prows = cols, data
            if fk.column.name not in pcols:
                continue
            j, i = pcols.index(fk.column.name), cols.index(fk.parent.name)
            there = {r[j] for r in prows}
            if fk.ondelete == "CASCADE" or not fk.parent.nullable:
                kept = [r for r in data if r[i] is None or r[i] in there]
                if len(kept) < len(data):
                    gone[t.name] = gone.get(t.name, 0) + len(data) - len(kept)
                data = kept
            else:
                for r in data:
                    if r[i] is not None and r[i] not in there:
                        r[i] = None
        rows[t.name] = (cols, data)
    return gone


def restore(conn, data: dict) -> dict:
    _check_revision(data)
    rows = _as_given(data) if data.get("revision") == head() else _upgraded(conn, data)
    for t, n in sorted(_prune(rows, schema.metadata).items()):
        monitoring.log(f"Restore: left out {n} row{'s' if n != 1 else ''} of {t} referring to something the backup doesn't have.",
                       "warning")
    for t in reversed(tables()):
        conn.execute(delete(schema.metadata.tables[t]))
    for t in ASSISTANT_TABLES:
        conn.execute(delete(schema.metadata.tables[t]))
    conn.sa.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED" if conn.postgres else "PRAGMA defer_foreign_keys = ON")
    out = {}
    for t in tables():
        if t not in rows:
            continue
        have = table_columns(conn, t)
        given, data_rows = rows[t]
        cols = [c for c in given if c in have]
        keep = [given.index(c) for c in cols]
        restored = _convert(t, cols, [[r[i] for i in keep] for r in data_rows], secretbox.encrypt)
        if restored and cols:
            conn.execute(insert(_table(t, cols)), [dict(zip(cols, r, strict=True)) for r in restored])
        out[t] = len(restored)
    if conn.postgres:
        for t in sorted(schema.AUTO_ID):
            last = select(func.max(schema.metadata.tables[t].c.id)).scalar_subquery()
            conn.execute(select(func.setval(func.pg_get_serial_sequence(t, "id"), func.coalesce(last, 0) + 1, false())))
    return out


class Busy(RuntimeError):
    pass


def restore_all(data: dict, locks: Sequence[threading.Lock] = (), directory: str | None = None) -> dict:
    held: list[threading.Lock] = []
    try:
        for lock in locks:
            if not lock.acquire(blocking=False):
                raise Busy("Waypoint is busy in the background. Restore once it has finished.")
            held.append(lock)
        with db.session() as conn:
            copy = safety_copy(conn, directory)
            restored = restore(conn, data)
            unreadable = unreadable_secrets(conn)
    finally:
        for lock in held:
            lock.release()
    return {"counts": restored, "safety_copy": copy, "unreadable_secrets": unreadable}
