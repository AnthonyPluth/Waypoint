"""A check for AGENTS.md's privacy promises: run code with made-up "canary" values in it (an email body, a traveller's
name, a confirmation code, a loyalty number), then fail if any of them turns up in the clear anywhere Waypoint keeps or
sends things: what it printed, Python's logging, what it sent to another service (every request goes through
waypoint/tls.py's urlopen), or any table of the database.

    with no_leaks(self, "CANARY-BODY-7Q2X", "CANARY-KTN-98765432", database=self.path):
        scan.run(conn, mailbox, today=TODAY)

Encrypted values don't count as leaks (secretbox's tokens never contain the plaintext). Use values that can't occur by
chance, and one per kind of thing, so a failure says which one escaped and where. A test that sends a canary on purpose
(to the AI, when the household turned it on) checks that request itself and passes `sent_ok=True`."""
from __future__ import annotations

import contextlib
import io
import logging
import urllib.request
from collections.abc import Iterator
from unittest import mock

from sqlalchemy import MetaData, select

from waypoint import tls
from waypoint.storage import db


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


def _request_text(req, data) -> str:
    """Everything a request would send: its address, headers and body."""
    if isinstance(req, urllib.request.Request):
        data = req.data if data is None else data
        parts = [req.full_url, *(f"{k}: {v}" for k, v in req.header_items())]
    else:
        parts = [str(req)]
    if isinstance(data, bytes):
        parts.append(data.decode("utf-8", "replace"))
    elif data is not None:
        parts.append(str(data))
    return "\n".join(parts)


@contextlib.contextmanager
def no_leaks(case, *canaries: str, database: str | None = None, sent_ok: bool = False) -> Iterator[None]:
    """Run the block with stdout, stderr, Python's logging and every outbound request (tls.urlopen, still made)
    captured; afterwards fail `case` naming every place a canary turned up. `database`: a database path to search too
    (own_database's)."""
    assert canaries and all(len(k) >= 8 for k in canaries), "use canaries long enough not to match by chance"
    out, err, logged = io.StringIO(), io.StringIO(), io.StringIO()
    sent: list[str] = []
    real_urlopen = tls.urlopen

    def recording_urlopen(req, *args, **kwargs):
        sent.append(_request_text(req, kwargs.get("data")))
        return real_urlopen(req, *args, **kwargs)

    handler = logging.StreamHandler(logged)
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        with mock.patch.object(tls, "urlopen", recording_urlopen), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            yield
    finally:
        root.removeHandler(handler)
    places = {"what was printed": out.getvalue(), "stderr": err.getvalue(), "Python's logging": logged.getvalue()}
    if not sent_ok:
        places["what was sent to another service"] = "\n".join(sent)
    leaks = [f"{k} in {where}" for where, text in places.items() for k in canaries if k in text]
    if database:
        leaks += found_in_database(database, canaries)
    case.assertEqual(leaks, [], "private values escaped (AGENTS.md, \"Waypoint's promises\")")
