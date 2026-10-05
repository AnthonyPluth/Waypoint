"""Calendar arithmetic shared by the forecast, churning, reports and the rest: months that don't all have the same days,
and the "YYYY-MM" month keys the reports and budgets group by.

A day of the month that a month doesn't have becomes that month's last day (the 31st in February is the 28th, or the
29th in a leap year), the way issuers, lenders and vesting schedules count it.
"""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta


def parse_day(s: str) -> date:
    """The date at the start of an ISO date or timestamp ("2026-09-23", "2026-09-23T10:00:00"). Raises ValueError on
    anything else."""
    return date.fromisoformat(s[:10])


def clamp_day(year: int, month: int, day: int) -> date:
    """That day of the month, or the month's last day if it's shorter (Feb 31 -> Feb 28)."""
    return date(year, month, 1) + relativedelta(day=day)


def month_end(d: date) -> date:
    """The last day of d's month."""
    return clamp_day(d.year, d.month, 31)


def add_months(d: date, n: int, day: int | None = None) -> date:
    """`n` months after d (before it when n is below zero), on d's day of the month or `day`, either clamped to the
    month's last day (Jan 31 + 1 month -> Feb 28)."""
    return date(d.year, d.month, 1) + relativedelta(months=n, day=day or d.day)


def month_start(d: date, n: int = 0) -> date:
    """The 1st of the month `n` months after d's (before it when n is below zero)."""
    return date(d.year, d.month, 1) + relativedelta(months=n)


def next_after(d: date, day: int) -> date:
    """First date strictly after d whose day-of-month is `day` (clamped)."""
    this_month = clamp_day(d.year, d.month, day)
    return this_month if this_month > d else add_months(this_month, 1, day)


def days_in_month(d: date) -> int:
    """How many days d's month has."""
    return month_end(d).day


def months_between(a: date, b: date) -> int:
    """How many calendar months b's month is after a's (negative before it), whatever the days: 2026-01-31 to
    2026-03-01 is 2."""
    return (b.year - a.year) * 12 + b.month - a.month


def month_key(d: date) -> str:
    """d's month as "YYYY-MM"."""
    return f"{d:%Y-%m}"


def key_start(key: str) -> date:
    """The 1st of a "YYYY-MM" month."""
    y, m = (int(x) for x in key.split("-"))
    return date(y, m, 1)


def next_month_key(key: str) -> str:
    """The "YYYY-MM" month after this one ("2026-12" -> "2027-01")."""
    return month_key(month_start(key_start(key), 1))


def month_keys(last: date, months: int) -> list[str]:
    """The `months` months ("2026-09") ending with last's, oldest first."""
    return [month_key(month_start(last, i - months + 1)) for i in range(months)]
