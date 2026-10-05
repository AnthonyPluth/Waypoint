"""Waypoint's log: errors and notes printed for whoever runs it (`docker logs`, the terminal). Nothing is sent anywhere
else; Waypoint has no error-reporting service.

Waypoint holds mailbox access and your travel, so what it logs about an error is only what it takes to find the bug:
the error's type and where it was raised, a database error's SQL (never the values bound to it), and the request's
method and route. Credentials in addresses, query strings and token-like strings are blanked wherever they turn up
(scrub), and a handler's failure is logged without what the exception says (report(values=False)), which may quote what
the request sent.
"""
from __future__ import annotations

import os
import re
import sys
import traceback
from typing import overload

# Secrets that can appear in an error's text: user:password@ in an address, a query string, and long bearer-style tokens.
_USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@", re.I)
_QUERY = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?#]*)\?[^\s#]*", re.I)
_TOKEN = re.compile(r"\b(access|public|link|processor)-(sandbox|development|production)-[0-9a-f-]{8,}", re.I)
_RAPIDAPI_HEADER = re.compile(r"(x-rapidapi-key['\"]?\s*[:=,]\s*['\"]?)[^\s'\",}]+", re.I)
# Keys that live in the environment: wherever one turns up in a text (an error that quoted the request), it's blanked.
SECRET_ENV = ("RAPIDAPI_KEY",)


def scrub(text):
    if not isinstance(text, str):
        return text
    text = _USERINFO.sub(r"\1[Filtered]@", text)
    text = _QUERY.sub(r"\1?[Filtered]", text)
    text = _database_values(text)
    text = _RAPIDAPI_HEADER.sub(r"\1[Filtered]", text)
    for name in SECRET_ENV:
        secret = (os.environ.get(name) or "").strip()
        if len(secret) >= 8:
            text = text.replace(secret, "[Filtered]")
    return _TOKEN.sub("[Filtered]", text)


_DIGITS = re.compile(r"\d{5,}")


@overload
def public_text(text: str) -> str: ...
@overload
def public_text(text: None) -> None: ...
def public_text(text: str | None) -> str | None:
    """What another service said (an airline's or Google's message, an API's error), made safe to keep and
    show: scrub(), and any run of five or more digits blanked, in case a message names an account or card number."""
    if not isinstance(text, str):
        return text
    return _DIGITS.sub("[number]", scrub(text))


def _database_values(text: str) -> str:
    """A database error's text names the row it was writing: SQLAlchemy's "[parameters: ...]", and Postgres's "Failing row
    contains (...)" and "Key (...)=(...) already exists". Blank the values and keep the rest (the SQL helps). Plain string
    scans, a line at a time: a regex here could take quadratic time on text that repeats one of the markers."""
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if (i := line.find("[parameters: ")) != -1:
            lines[n] = line[:i] + "[parameters: [Filtered]]"
        elif (i := line.find("Failing row contains (")) != -1:
            lines[n] = line[:i] + "Failing row contains ([Filtered])."
        elif (i := line.find("Key (")) != -1 and (j := line.find(")=(", i)) != -1:
            end = line.rfind(") ")   # before "already exists", "is not present in table ..." and the like
            lines[n] = line[:j] + ")=([Filtered])" + (line[end + 1:] if end > j else "")
    return "\n".join(lines)


def report(e: BaseException | None = None, *, values: bool = True) -> None:
    """Log an error that was caught (the current one, or `e`).

    values=False: what each exception says is left out (only its type, and where it was raised, are kept), for an error
    whose text may quote what was being read: a request's handler failing ("invalid literal for int(): 'Acme'", a
    KeyError's key, a database driver's "Key (payee)=(Acme) already exists"). A database error keeps its SQL, which helps
    and holds no values (they're bound to it)."""
    # Scrubbed: a database error's text names the row it was writing.
    if e is None:
        e = sys.exc_info()[1]
    text = "".join(traceback.format_exception(e) if values or e is None else _types_only(e))
    print(scrub(text), file=sys.stderr, end="", flush=True)


def _chain(e: BaseException) -> list[BaseException]:
    """e and the exceptions it was raised from or while handling, the first of them first (as a traceback shows them)."""
    chain: list[BaseException] = []
    cur: BaseException | None = e
    while cur is not None and cur not in chain:
        chain.append(cur)
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    return chain[::-1]


def _what_it_said(exc: BaseException) -> str:
    """What report(values=False) keeps of an exception's text: a database error's SQL, else nothing."""
    statement = getattr(exc, "statement", None)
    if type(exc).__module__.startswith("sqlalchemy") and isinstance(statement, str):
        return f"[SQL: {statement}]"
    return "[Filtered]"


def _types_only(e: BaseException) -> list[str]:
    """e's traceback (and those of the exceptions it was raised from), each exception's text as _what_it_said."""
    out: list[str] = []
    for exc in _chain(e):
        if out:
            out.append("\nWhile handling the above, another exception was raised:\n\n")
        if exc.__traceback__ is not None:
            out += ["Traceback (most recent call last):\n", *traceback.format_tb(exc.__traceback__)]
        out.append(f"{type(exc).__module__}.{type(exc).__qualname__}: {_what_it_said(exc)}\n")
    return out


def log(message: str, level: str = "info", *, stderr: bool = False) -> None:
    """Print a line to Waypoint's log, to stderr when `stderr`. `level` (info, warning, error) says what kind of line it
    is, for whoever reads the call."""
    print(message, file=sys.stderr if stderr else sys.stdout, flush=True)
