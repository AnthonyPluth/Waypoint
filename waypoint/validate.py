from __future__ import annotations

import math
from datetime import date
from typing import Literal, overload

from .storage import db

TRUE = (True, 1, "1", "true", "on")
MAX_AMOUNT = 1e9


def parse_number(v, drop: str = ",$") -> float:
    if not drop:
        return db.number(v)
    s = str(v)
    for c in drop:
        s = s.replace(c, "")
    return db.number(s.strip())


def parse_external(v, drop: str = "") -> float | None:
    if v is None or v == "" or isinstance(v, bool):
        return None
    try:
        return parse_number(v, drop)
    except (TypeError, ValueError, OverflowError):
        return None


def flag(v) -> int:
    return 1 if v in TRUE else 0


def on(v) -> bool:
    return v in TRUE


class Validator:

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
        n = self.number(v, label, low, high, required=required)
        if n is not None and n != int(n):
            raise self.error(self.not_whole.format(label=label))
        return None if n is None else int(n)

    def text(self, v, label: str, limit: int, required: bool = False) -> str | None:
        s = str(v or "").strip()
        if required and not s:
            raise self.error(self.missing.format(label=label))
        if len(s) > limit:
            raise self.error(self.too_long.format(label=label, limit=limit))
        return s or None

    def file(self, v, label: str, limit: int) -> bytes:
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
        s = str(v or "").strip()
        if not s:
            if required:
                raise self.error(self.missing.format(label=label))
            return None
        try:
            return date.fromisoformat(s).isoformat()
        except ValueError:
            raise self.error(self.not_date.format(label=label)) from None
