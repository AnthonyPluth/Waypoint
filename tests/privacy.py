"""A check for AGENTS.md's privacy promises: run code with made-up "canary" values in it (an email body, a traveller's
name, a confirmation code, a loyalty number), then fail if any of them turns up in the clear anywhere Waypoint keeps or
sends things: what it printed, Python's logging, what it sent to Sentry (with reporting on), or any table of the
database.

    with no_leaks(self, "CANARY-BODY-7Q2X", "CANARY-KTN-98765432", database=self.path):
        scan.run(conn, mailbox, today=TODAY)

Encrypted values don't count as leaks (secretbox's tokens never contain the plaintext). Use values that can't occur by
chance, and one per kind of thing, so a failure says which one escaped and where."""
from __future__ import annotations

import contextlib
import io
import logging
import os
from collections.abc import Iterator
from unittest import mock

import sentry_sdk
from sqlalchemy import MetaData, select

from waypoint import monitoring
from waypoint.storage import db

DSN = "https://publickey@o123.ingest.us.sentry.io/456"


class _Capture(sentry_sdk.transport.Transport):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sent: list[str] = []

    def capture_envelope(self, envelope):
        self.sent += [i.payload.get_bytes().decode("utf-8", "replace") for i in envelope.items]


def found_in_database(path: str, canaries: tuple[str, ...]) -> list[str]:
    """Each canary found in the clear in a table of the database at `path`, as 'canary in table.column'."""
    out = []
    meta = MetaData()
    with db.engine(path).connect() as c:
        meta.reflect(c)
        for table in meta.sorted_tables:
            for row in c.execute(select(table)).mappings():
                for column, value in row.items():
                    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
                    out += [f"{k} in {table.name}.{column}" for k in canaries if k in text]
    return sorted(set(out))


@contextlib.contextmanager
def no_leaks(case, *canaries: str, database: str | None = None) -> Iterator[None]:
    """Run the block with stdout, stderr, Python's logging and Sentry (reporting on, sent nowhere) captured; afterwards
    fail `case` naming every place a canary turned up. `database`: a database path to search too (own_database's)."""
    assert canaries and all(len(k) >= 8 for k in canaries), "use canaries long enough not to match by chance"
    out, err = io.StringIO(), io.StringIO()
    logged = io.StringIO()
    handler = logging.StreamHandler(logged)
    root = logging.getLogger()
    root.addHandler(handler)
    with mock.patch.dict(os.environ, {"SENTRY_DSN": DSN}), contextlib.redirect_stdout(io.StringIO()):
        monitoring.init()
    transport = _Capture()
    sentry_sdk.get_client().transport = transport
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            yield
        sentry_sdk.flush()
    finally:
        root.removeHandler(handler)
        sentry_sdk.get_client().close()
        sentry_sdk.init(dsn=None)
        monitoring._enabled = False
    places = {"what was printed": out.getvalue(), "stderr": err.getvalue(), "Python's logging": logged.getvalue(),
              "what was sent to Sentry": "\n".join(transport.sent)}
    leaks = [f"{k} in {where}" for where, text in places.items() for k in canaries if k in text]
    if database:
        leaks += found_in_database(database, canaries)
    case.assertEqual(leaks, [], "private values escaped (AGENTS.md, \"Waypoint's promises\")")
