"""Checking what someone typed or sent: numbers, amounts of money, whole numbers, short texts, days and on/off
flags; and numbers in other systems' replies (parse_external).

Each module that takes input keeps its own error class and wording, so a Validator is made with both; the checks
themselves are shared. A number is db.number's (which refuses nan, inf and anything past db.MAX_NUMBER), after dropping
only the characters asked for (a pasted "$1,234.50"), and isn't rounded. An amount of money (a transaction's, a bill's,
a budget's, a filter's) is a number of at most MAX_AMOUNT either way, rounded to the cent when that's asked for.

The API (waypoint/server/api/) checks everything a request sends with these before using it, so a value that can't be
read is a 400 saying which one, and anything else that goes wrong in a handler is a bug (a 500, reported).
"""
from __future__ import annotations

import math
from datetime import date
from typing import Literal, overload

from .storage import db

TRUE = (True, 1, "1", "true", "on")
# The most one amount of money can be, either way: far more than any transaction, bill or budget, and small enough that
# adding up a lifetime of them stays exact to the cent. Other numbers (prices, share counts, a home's value) are
# db.number's, up to db.MAX_NUMBER.
MAX_AMOUNT = 1e9


def parse_number(v, drop: str = ",$") -> float:
    """v as a number. drop: characters removed first (from str(v), then stripped), so True is "True" and refused.
    drop="" passes v to db.number as it is (None is a TypeError, True is 1.0). Raises TypeError or ValueError like
    db.number."""
    if not drop:
        return db.number(v)
    s = str(v)
    for c in drop:
        s = s.replace(c, "")
    return db.number(s.strip())


def parse_external(v, drop: str = "") -> float | None:
    """A number in another system's reply (a bank's, a broker's, a store's), or None when it isn't one: left out,
    empty, not a number, or one db.number refuses ("nan", "inf", past MAX_NUMBER), so a bad value is dropped instead of
    saved into amounts and balances. A true or false isn't a number either. drop as in parse_number."""
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return parse_number(v, drop)
    except (TypeError, ValueError, OverflowError):   # OverflowError: a whole number too big for a float
        return None


def flag(v) -> int:
    """1 for a checkbox or switch that's on (True, 1, "1", "true", "on"), else 0: "false", "0", "no" and anything else
    are off (unlike bool(), which takes any text but "" as on)."""
    return 1 if v in TRUE else 0


def on(v) -> bool:
    """flag(v), as True or False."""
    return v in TRUE


class Validator:
    """The shared checks, raising `error` with a module's own messages. Templates are str.format()ted with label (and
    low and high, or limit). Left out or empty (None or ""), a value is None, or the `missing` error when required."""

    def __init__(self, error: type[Exception], *, drop: str = ",$",
                 missing: str = "Enter the {label}",
                 not_number: str = "The {label} must be a number",
                 out_of_range: str = "The {label} must be between {low:g} and {high:g}",
                 not_whole: str = "The {label} must be a whole number",
                 too_long: str = "The {label} is too long (at most {limit} characters)",
                 not_date: str = "The {label} must be a date (YYYY-MM-DD)",
                 too_large: str = "The {label} is too large",
                 empty_file: str = "The {label} is empty",
                 file_too_large: str = "The {label} is larger than {limit}"):
        self.error = error
        self.drop = drop
        self.missing = missing
        self.not_number = not_number
        self.out_of_range = out_of_range
        self.not_whole = not_whole
        self.too_long = too_long
        self.not_date = not_date
        self.too_large = too_large
        self.empty_file = empty_file
        self.file_too_large = file_too_large

    @overload
    def number(self, v, label: str, low: float = ..., high: float = ..., *, required: Literal[True]) -> float: ...
    @overload
    def number(self, v, label: str, low: float = ..., high: float = ..., *, required: bool = ...) -> float | None: ...

    def number(self, v, label: str, low: float = -math.inf, high: float = math.inf, *,
               required: bool = False) -> float | None:
        """A number from low to high (both included)."""
        if v in (None, ""):
            if required:
                raise self.error(self.missing.format(label=label))
            return None
        try:
            n = parse_number(v, self.drop)
        except (TypeError, ValueError):
            raise self.error(self.not_number.format(label=label)) from None
        if not low <= n <= high:
            raise self.error(self.out_of_range.format(label=label, low=low, high=high))
        return n

    @overload
    def amount(self, v, label: str, *, cents: bool = ..., required: Literal[True]) -> float: ...
    @overload
    def amount(self, v, label: str, *, cents: bool = ..., required: bool = ...) -> float | None: ...

    def amount(self, v, label: str, *, cents: bool = True, required: bool = False) -> float | None:
        """An amount of money, signed, of less than MAX_AMOUNT either way; rounded to the cent unless cents=False. True
        and False aren't amounts, whatever `drop` is."""
        if isinstance(v, bool):
            raise self.error(self.not_number.format(label=label))
        n = self.number(v, label, required=required)
        if n is None:
            return None
        if abs(n) >= MAX_AMOUNT:
            raise self.error(self.too_large.format(label=label))
        return round(n, 2) if cents else n

    @overload
    def integer(self, v, label: str, low: int, high: int, *, required: Literal[True]) -> int: ...
    @overload
    def integer(self, v, label: str, low: int, high: int, *, required: bool = ...) -> int | None: ...

    def integer(self, v, label: str, low: int, high: int, *, required: bool = False) -> int | None:
        """A whole number from low to high: 3 and "3.0" are 3, 3.5 is refused (not rounded)."""
        n = self.number(v, label, low, high, required=required)
        if n is not None and n != int(n):
            raise self.error(self.not_whole.format(label=label))
        return None if n is None else int(n)

    def text(self, v, label: str, limit: int, required: bool = False) -> str | None:
        """A text of at most limit characters, without the spaces around it; None when there's nothing."""
        s = str(v or "").strip()
        if required and not s:
            raise self.error(self.missing.format(label=label))
        if len(s) > limit:
            raise self.error(self.too_long.format(label=label, limit=limit))
        return s or None

    def file(self, v, label: str, limit: int) -> bytes:
        """An uploaded file's bytes, at most `limit` of them and not none (the `limit` shown in the message in MB)."""
        if not isinstance(v, bytes | bytearray) or not v.strip():
            raise self.error(self.empty_file.format(label=label))
        if len(v) > limit:
            raise self.error(self.file_too_large.format(label=label, limit=f"{limit // (1024 * 1024)} MB"))
        return bytes(v)

    @overload
    def day(self, v, label: str, required: Literal[True]) -> str: ...
    @overload
    def day(self, v, label: str, required: bool = ...) -> str | None: ...

    def day(self, v, label: str, required: bool = False) -> str | None:
        """A day as YYYY-MM-DD; None when there's nothing."""
        s = str(v or "").strip()
        if not s:
            if required:
                raise self.error(self.missing.format(label=label))
            return None
        try:
            return date.fromisoformat(s).isoformat()
        except ValueError:
            raise self.error(self.not_date.format(label=label)) from None
