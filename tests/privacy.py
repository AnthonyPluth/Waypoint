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
