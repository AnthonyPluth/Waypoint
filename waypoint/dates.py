from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta


def parse_day(s: str) -> date:
    return date.fromisoformat(s[:10])


def clamp_day(year: int, month: int, day: int) -> date:
    return date(year, month, 1) + relativedelta(day=day)


def month_end(d: date) -> date:
    return clamp_day(d.year, d.month, 31)


def add_months(d: date, n: int, day: int | None = None) -> date:
    return date(d.year, d.month, 1) + relativedelta(months=n, day=day or d.day)


def month_start(d: date, n: int = 0) -> date:
    return date(d.year, d.month, 1) + relativedelta(months=n)


def next_after(d: date, day: int) -> date:
    this_month = clamp_day(d.year, d.month, day)
    return this_month if this_month > d else add_months(this_month, 1, day)


def days_in_month(d: date) -> int:
    return month_end(d).day


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


def month_key(d: date) -> str:
    return f"{d:%Y-%m}"


def key_start(key: str) -> date:
    y, m = (int(x) for x in key.split("-"))
    return date(y, m, 1)


def next_month_key(key: str) -> str:
    return month_key(month_start(key_start(key), 1))


def month_keys(last: date, months: int) -> list[str]:
    return [month_key(month_start(last, i - months + 1)) for i in range(months)]
