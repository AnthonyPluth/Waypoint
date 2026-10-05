"""Backups that work across databases: one gzip'd JSON file with every table's rows.

Use it to move Waypoint (Mac -> server, SQLite -> Postgres) or just to keep a copy. It includes your settings and the
secrets among them: those stay encrypted in the file, as they are in the database (waypoint/storage/secretbox.py), so a
backup on its own doesn't give them away. Restoring on a machine with the same
WAYPOINT_SECRET_KEY (or a copy of secret.key) reads them again; under another key they can't be read (the restore says
which): set the key the backup was made with as WAYPOINT_SECRET_KEY_OLD for one start, and they're re-encrypted with the
current one, or enter them again in Settings. Sign-in sessions aren't included, so you sign in again after
restoring.

A backup records the schema it was made with (its Alembic revision). Restoring one made by an older version loads its
rows into a database of their own at that revision, runs the migrations since over them (so what they change in the
data, a setting moved say, is changed in the backup's data too) and then copies the result in. That database is a
throwaway: in memory on SQLite, and on Postgres a schema made inside a transaction that's rolled back. A backup from a
newer version than this one is refused, and so is one that doesn't record its revision (every Waypoint backup does).
"""
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
# Sign-ins (and Gmail connections still at Google) don't travel: sign in again after a restore. Nor do the airports: they're
# reference data every database is given by its migrations, and no row refers to them. The flight status cache is refetched.
# Devices belong to the browsers that made them and feeds to the addresses that were handed out: both are set up again after
# a restore (what was already sent isn't sent twice, but a restored database may be on another day's flights).
SKIP = {"auth_sessions", "auth_pending", "mailbox_pending", "airports", "flight_status", "push_devices", "calendar_feeds",
        "reminders_sent"}
NEWER = "That backup is from a newer version of Waypoint. Update Waypoint first."


def tables() -> list[str]:
    return [t.name for t in schema.metadata.sorted_tables if t.name not in SKIP]


def table_columns(conn, table: str) -> list[str]:
    return [c["name"] for c in inspect(conn.sa).get_columns(table)]


def _table(name: str, cols: list[str]):
    """The table (schema.py's), for statements on these columns. The database is migrated to match schema.py, but a
    column only the database has (one from long ago) still goes along, as with SQL naming it: then a bare table()."""
    t = schema.metadata.tables[name]
    return t if all(c in t.c for c in cols) else table(name, *(column(c) for c in cols))


def _secret_columns(table: str, cols: list[str]):
    """Which values in a row are stored encrypted: returns a test (row -> list of column indexes)."""
    if table == "settings" and "key" in cols and "value" in cols:
        k, v = cols.index("key"), cols.index("value")
        return lambda row: [v] if row[k] in secretbox.SECRET_SETTINGS else []
    if table in secretbox.SECRET_COLUMNS and secretbox.SECRET_COLUMNS[table] in cols:
        i = cols.index(secretbox.SECRET_COLUMNS[table])
        return lambda row: [i]
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
    """The revision this version of Waypoint migrates databases to."""
    return str(_scripts().get_current_head())


def revision(sa_conn) -> str | None:
    """The revision a database is at (None: not one Alembic has migrated)."""
    if not inspect(sa_conn).has_table("alembic_version"):
        return None
    return sa_conn.execute(select(column("version_num")).select_from(table("alembic_version"))).scalar()


def export(conn) -> dict:
    """Secrets are written as they're stored, encrypted (a value saved by a version before encryption is encrypted on
    the way out), so the file holds nothing readable without the key. Works at any revision (a migration saves a copy
    before it removes anything): a table the database doesn't have yet is left out."""
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


MAX_UNPACKED = 256 * 1024 * 1024   # a real backup unpacks to far less; a crafted one could be many GB (held in memory)


def _gunzip(raw: bytes) -> bytes:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(raw, MAX_UNPACKED + 1)
    if len(out) > MAX_UNPACKED:
        raise ValueError("That backup is too large to restore.")
    if not d.eof:
        raise ValueError("That file isn't a Waypoint backup.")
    return out


def _check_revision(data: dict) -> None:
    """A backup's revision must be one this version knows; one it doesn't is from a newer version."""
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


SUMMARY = ("users",)   # what a person recognises their data by (trips, once there are any)


def _summary_counts(rows: dict[str, int]) -> dict[str, int]:
    return {**{t: rows.get(t, 0) for t in SUMMARY}, "total": sum(rows.values())}


def preview(data: dict) -> dict:
    """What a loaded backup holds, shown before restoring it: when and where it was made, and how many rows (the tables
    you'd recognise, and all rows in the tables this version restores)."""
    known = set(tables())
    rows = {t: len(p.get("rows") or []) for t, p in data["tables"].items() if t in known and isinstance(p, dict)}
    return {"created": data.get("created"), "source": data.get("source"), "version": data.get("version", 0),
            "revision": data.get("revision"), "counts": _summary_counts(rows)}


def counts(conn) -> dict[str, int]:
    """The same counts for the database as it is now: what a restore would replace."""
    return _summary_counts({t: conn.execute(select(func.count()).select_from(schema.metadata.tables[t])).scalar() or 0
                            for t in tables()})


def save_copy(conn, name: str, directory: str | None = None) -> str:
    """Everything in the database, as a backup, in `directory` (the data directory) as <name>-<time>.json.gz, private
    to Waypoint's user. Returns the file's path."""
    directory = directory or db.data_dir()
    stamp = datetime.now().strftime('%Y-%m-%d-%H%M%S')
    data = dump(conn)
    n = 1
    while True:   # another copy made the same second (two restores in a row) gets -2, -3, ...
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
    """Before a restore replaces everything: a backup of what's here now, saved next to the database (the data
    directory) as waypoint-before-restore-<time>.json.gz. None when there's nothing to keep (the database is empty).
    Returns the file's path."""
    if not counts(conn)["total"]:
        return None
    return save_copy(conn, "waypoint-before-restore", directory)


def unreadable_secrets(conn) -> list[str]:
    """The settings that hold a secret this Waypoint's key can't read (a backup from a machine with another key): what
    to enter again in Settings, by name."""
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


MAILBOXES = "mailboxes"   # not a setting: the Gmail connections' refresh tokens
MAILBOXES_LABEL = "Gmail connections (connect them again in Settings)"
LOYALTY = "loyalty_ids"   # not a setting: the loyalty and Known Traveler numbers
LOYALTY_LABEL = "loyalty numbers (enter them again on People)"

# What each secret is called where it's entered again (Settings), for saying which ones a restore couldn't read.
SECRET_LABELS = {
    sk.VAPID_PRIVATE_KEY: "notifications' signing key (devices sign up for notifications again)",
}


def unreadable_summary(unreadable: list[str]) -> str:
    """unreadable_secrets() for people: each setting by its name in Settings. Only these fixed labels are said, never
    anything read from the rows."""
    labels = {**SECRET_LABELS, MAILBOXES: MAILBOXES_LABEL, LOYALTY: LOYALTY_LABEL}
    return ", ".join(dict.fromkeys(label for key, label in labels.items() if key in unreadable))


# ------------------------------------------------------------------------------------------------ restoring

Rows = dict[str, tuple[list[str], list[list]]]   # table -> (columns, rows)


@contextmanager
def _scratch(conn) -> Iterator[SAConnection]:
    """An empty database to bring a backup up to date in, on the same kind of database as this one (the migrations
    are written for each), thrown away afterwards: on SQLite one in memory; on Postgres a schema of its own, made in a
    transaction that's rolled back, so nothing of it is ever committed."""
    if not conn.postgres:
        eng = create_engine("sqlite://", poolclass=StaticPool)   # foreign keys off, as while migrating (db.migrate)
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
    cfg.attributes["restoring"] = True   # the backup is the copy: a migration that saves one before it removes anything needn't
    command.upgrade(cfg, to)


def _upgraded(conn, data: dict) -> Rows:
    """The backup's rows as they'd be had its database been migrated to this version's schema."""
    rev: str = data["revision"]   # (load checked it's one this version knows)
    with _scratch(conn) as sc:
        _migrate(sc, rev)
        then = MetaData()
        then.reflect(sc)
        order = [t for t in then.sorted_tables if t.name != "alembic_version"]
        for t in reversed(order):
            sc.execute(delete(t))   # anything a migration put there: the backup's rows replace it
        target = inspect(conn.sa)
        given: Rows = {}
        for t in order:
            payload = data["tables"].get(t.name)
            if not isinstance(payload, dict):
                continue
            there = set(t.c.keys())
            # A column only the backup's database had (one from long ago) comes along if this database has it too.
            if target.has_table(t.name):
                for c in target.get_columns(t.name):
                    if c["name"] in payload["columns"] and c["name"] not in there:
                        ddl = CreateColumn(Column(c["name"], c["type"])).compile(dialect=sc.dialect)
                        sc.exec_driver_sql(f'ALTER TABLE "{t.name}" ADD COLUMN {ddl}')   # nosemgrep: waypoint-sql-from-string -- the model's own table and column names, which DDL can't bind
                        there.add(c["name"])
            cols = [c for c in payload["columns"] if c in there]
            keep = [payload["columns"].index(c) for c in cols]
            given[t.name] = (cols, _convert(t.name, cols, [[r[i] for i in keep] for r in payload["rows"]], secretbox.encrypt))
        _prune(given, then)   # at a revision with foreign keys, a row they'd refuse (the migrations do the rest)
        if sc.dialect.name == "postgresql":
            sc.exec_driver_sql("SET CONSTRAINTS ALL DEFERRED")   # rows referring to later ones of their own table
        for t in order:
            cols, rows = given.get(t.name, ([], []))
            if rows and cols:
                sc.execute(insert(table(t.name, *(column(c) for c in cols))), [dict(zip(cols, r, strict=True)) for r in rows])
        if sc.dialect.name == "postgresql":
            sc.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")   # checked now: a migration can't change a table with checks pending
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
    """A backup made at this version's revision: its rows as they are."""
    known = set(tables())
    return {t: (list(p["columns"]), [list(r) for r in p["rows"]]) for t, p in data["tables"].items()
            if t in known and isinstance(p, dict)}


def _prune(rows: Rows, meta: MetaData) -> dict[str, int]:
    """Rows that refer to one the backup doesn't have (a foreign key in `meta` that couldn't hold): the row goes, or
    lets go, as removing what it refers to would do (ON DELETE CASCADE or SET NULL). Returns how many went, by table."""
    gone: dict[str, int] = {}
    for t in meta.sorted_tables:   # what a row refers to is checked (and pruned) before the row
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
    """Replace everything with the backup's contents (in one transaction). Returns rows restored per table. Secrets
    the backup holds encrypted are kept as they are (see unreadable_secrets for the ones this key can't read); a
    plaintext one from an old backup is encrypted."""
    _check_revision(data)
    rows = _as_given(data) if data.get("revision") == head() else _upgraded(conn, data)
    for t, n in sorted(_prune(rows, schema.metadata).items()):   # counts only: never what the rows held
        monitoring.log(f"Restore: left out {n} row{'s' if n != 1 else ''} of {t} referring to something the backup doesn't have.",
                       "warning")
    for t in reversed(tables()):
        conn.execute(delete(schema.metadata.tables[t]))
    # Rows can refer to rows of their own table restored after them: checked when the restore commits, not row by row.
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
    if conn.postgres:   # auto-numbered ids continue after the restored ones
        for t in sorted(schema.AUTO_ID):
            last = select(func.max(schema.metadata.tables[t].c.id)).scalar_subquery()
            conn.execute(select(func.setval(func.pg_get_serial_sequence(t, "id"), func.coalesce(last, 0) + 1, false())))
    return out


class Busy(RuntimeError):
    """Something in the background (a mail scan) is writing: a restore now would mix its rows in with the backup's."""


def restore_all(data: dict, locks: Sequence[threading.Lock] = (), directory: str | None = None) -> dict:
    """Restore a loaded backup, the whole way, for the web and the command line alike: hold `locks` (the server's sync
    background jobs' locks: Busy if one is taken), save a copy of what's here first (safety_copy), replace everything with the backup
    (restore), and see which of its secrets this Waypoint's key can't read. Returns what to tell the person: rows restored
    per table (counts), the copy's path (safety_copy), those secrets (unreadable_secrets) and a warning (or None).
    Raises ValueError for a backup that can't be restored, OSError when the copy can't be saved (nothing is restored
    then), and the database's errors as they are."""
    held: list[threading.Lock] = []
    try:
        for lock in locks:
            if not lock.acquire(blocking=False):
                raise Busy("Waypoint is busy in the background. Restore once it has finished.")
            held.append(lock)
        with db.session() as conn:
            copy = safety_copy(conn, directory)   # what's here now, in case the backup was the wrong one
            restored = restore(conn, data)
            unreadable = unreadable_secrets(conn)   # from a machine with another key: entered again
    finally:
        for lock in held:
            lock.release()
    return {"counts": restored, "safety_copy": copy, "unreadable_secrets": unreadable}
