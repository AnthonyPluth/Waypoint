from __future__ import annotations

import os
import re
import sys
import traceback
from typing import overload

_USERINFO = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^/\s@]+@", re.I)
_QUERY = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?#]*)\?[^\s#]*", re.I)
_TOKEN = re.compile(r"\b(access|public|link|processor)-(sandbox|development|production)-[0-9a-f-]{8,}", re.I)
_RAPIDAPI_HEADER = re.compile(r"(x-rapidapi-key['\"]?\s*[:=,]\s*['\"]?)[^\s'\",}]+", re.I)
SECRET_ENV = ("RAPIDAPI_KEY", "OPENROUTER_API_KEY")


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
    if not isinstance(text, str):
        return text
    return _DIGITS.sub("[number]", scrub(text))


def _database_values(text: str) -> str:
    lines = text.split("\n")
    for n, line in enumerate(lines):
        if (i := line.find("[parameters: ")) != -1:
            lines[n] = line[:i] + "[parameters: [Filtered]]"
        elif (i := line.find("Failing row contains (")) != -1:
            lines[n] = line[:i] + "Failing row contains ([Filtered])."
        elif (i := line.find("Key (")) != -1 and (j := line.find(")=(", i)) != -1:
            end = line.rfind(") ")
            lines[n] = line[:j] + ")=([Filtered])" + (line[end + 1:] if end > j else "")
    return "\n".join(lines)


def report(e: BaseException | None = None, *, values: bool = True) -> None:
    if e is None:
        e = sys.exc_info()[1]
    text = "".join(traceback.format_exception(e) if values or e is None else _types_only(e))
    print(scrub(text), file=sys.stderr, end="", flush=True)


def _chain(e: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    cur: BaseException | None = e
    while cur is not None and cur not in chain:
        chain.append(cur)
        cur = cur.__cause__ or (None if cur.__suppress_context__ else cur.__context__)
    return chain[::-1]


def _what_it_said(exc: BaseException) -> str:
    statement = getattr(exc, "statement", None)
    if type(exc).__module__.startswith("sqlalchemy") and isinstance(statement, str):
        return f"[SQL: {statement}]"
    return "[Filtered]"


def _types_only(e: BaseException) -> list[str]:
    out: list[str] = []
    for exc in _chain(e):
        if out:
            out.append("\nWhile handling the above, another exception was raised:\n\n")
        if exc.__traceback__ is not None:
            out += ["Traceback (most recent call last):\n", *traceback.format_tb(exc.__traceback__)]
        out.append(f"{type(exc).__module__}.{type(exc).__qualname__}: {_what_it_said(exc)}\n")
    return out


def log(message: str, level: str = "info", *, stderr: bool = False) -> None:
    print(message, file=sys.stderr if stderr else sys.stdout, flush=True)
