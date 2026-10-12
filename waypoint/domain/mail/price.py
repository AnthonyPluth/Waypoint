from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from typing import Any

from .. import money
from .booking import Booking

SYMBOLS = {"US$": "USD", "CA$": "CAD", "C$": "CAD", "AU$": "AUD", "A$": "AUD", "NZ$": "NZD", "HK$": "HKD", "S$": "SGD", "MX$": "MXN",
           "R$": "BRL", "CN¥": "CNY", "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "₩": "KRW"}
SIGNS = "|".join(re.escape(s) for s in sorted(SYMBOLS, key=len, reverse=True))
CODES = "|".join(sorted(money.KNOWN))
CURRENCY = rf"(?:{SIGNS}|(?<![A-Za-z])(?:{CODES})(?![A-Za-z]))"
NUMBER = r"(?<![\d.,])(?:\d{1,3}(?:[,. \u00a0\u202f'’]\d{3})+(?:[.,]\d{1,3})?|\d+(?:[.,]\d{1,3})?)(?!\d|[.,]\d)"
MONEY = re.compile(rf"(?:(?P<pre>{CURRENCY})\s?(?P<a>{NUMBER})(?:\s?(?P<after>{CURRENCY}))?|(?P<b>{NUMBER})\s?(?P<post>{CURRENCY}))")
HINTED = re.compile(rf"(?P<label>[^\d]*?)\s*\((?P<code>{CURRENCY})\)\s*[:：\-–—]?\s*(?P<num>{NUMBER})\s*")
GROUPED_SPACES = re.compile(r"\d{1,3}(?:[ ']\d{3})+(?:[.,]\d{1,3})?")
GROUPED = {",": re.compile(r"\d{1,3}(?:,\d{3})+"), ".": re.compile(r"\d{1,3}(?:\.\d{3})+")}
LABEL = re.compile(
    r"(?:(?:grand|order|booking|reservation|trip|final|estimated|rental|stay)\s+)?total"
    r"(?:\s+(?:amount|price|cost|charges?|charged|paid|due|fare|payment|for\s+(?:your\s+)?(?:stay|trip|rental|booking|reservation|room|flights?|cruise)))?"
    r"(?:\s+(?:amount|charged|paid))?(?:\s+(?:incl\.?|including|inc\.?)\s+(?:all\s+)?(?:taxes|tax|fees)(?:\s*(?:and|&|,)\s*(?:taxes|fees))?)?"
    r"|amount\s+(?:charged|paid|due)|amount\s+you\s+paid")
BRACKET = re.compile(r"\s*[(\[][^)\]]{0,40}[)\]]")
EDGE = " \t:：-–—|•*·"
NOT_A_TOTAL = re.compile(r"^\s*(?:per\s|/\s?|a\s+night|nightly|each|avg|average|pts|points|miles)", re.IGNORECASE)
NEGATIVE = "-−("


def _number(text: str, currency: str) -> Decimal | None:
    t = text.replace("\u00a0", " ").replace("\u202f", " ").replace("’", "'")
    if re.search(r"[ ']", t):
        if GROUPED_SPACES.fullmatch(t) is None:
            return None
        t = re.sub(r"[ ']", "", t)
    last = max(t.rfind("."), t.rfind(","))
    if last == -1:
        whole, fraction = t, ""
    else:
        sep, head, tail = t[last], t[:last], t[last + 1:]
        other = "," if sep == "." else "."
        if other in head:
            if GROUPED[other].fullmatch(head) is None or (len(tail) == 3 and money.exponent(currency) != 3):
                return None
            whole, fraction = head.replace(other, ""), tail
        elif sep in head:
            if GROUPED[sep].fullmatch(t) is None:
                return None
            whole, fraction = t.replace(sep, ""), ""
        elif len(tail) == 3 and money.exponent(currency) != 3:
            if not 1 <= len(head) <= 3:
                return None
            whole, fraction = head + tail, ""
        else:
            whole, fraction = head, tail
    if not whole.isdigit() or (fraction and not fraction.isdigit()) or len(fraction) > money.exponent(currency):
        return None
    return Decimal(f"{whole}.{fraction}" if fraction else whole)


def _price(amount: Decimal | None, currency: str) -> money.Price | None:
    if amount is None or amount <= 0:
        return None
    minor = amount.scaleb(money.exponent(currency))
    if minor != minor.to_integral_value() or minor > money.MAX_MINOR:
        return None
    return money.Price(int(minor), currency)


def _currency(*tokens: str | None) -> str | None:
    codes = {t for t in tokens if t and t not in SYMBOLS}
    signs = {SYMBOLS[t] for t in tokens if t and t in SYMBOLS}
    if len(codes) > 1:
        return None
    if codes:
        return next(iter(codes))
    return next(iter(signs)) if len(signs) == 1 else None


def _moneys(line: str) -> list[tuple[money.Price | None, int, int]]:
    out: list[tuple[money.Price | None, int, int]] = []
    for m in MONEY.finditer(line):
        if m["a"] is not None:
            number, first, second = m["a"], m["pre"], m["after"]
        else:
            number, first, second = m["b"], None, m["post"]
        currency = _currency(first, second)
        out.append((_price(_number(number, currency), currency) if currency else None, m.start(), m.end()))
    return out


def _label(text: str) -> bool:
    plain = BRACKET.sub("", text.replace("’", "'").strip(EDGE)).strip(EDGE).lower()
    return LABEL.fullmatch(re.sub(r"\s+", " ", plain)) is not None


def _in_line(line: str) -> money.Price | None:
    found = _moneys(line)
    if not found:
        hinted = HINTED.fullmatch(line.strip())
        if hinted is None or not _label(hinted["label"]):
            return None
        currency = _currency(hinted["code"])
        return _price(_number(hinted["num"], currency), currency) if currency else None
    price, start, _ = found[0]
    if not _label(line[:start]) or price is None or (start and line[start - 1] in NEGATIVE) or NOT_A_TOTAL.match(line[found[0][2]:]):
        return None
    return price if all(p == price for p, *_ in found) else None


def _alone(line: str) -> money.Price | None:
    found = _moneys(line.strip())
    return found[0][0] if len(found) == 1 and found[0][1] == 0 and found[0][2] == len(line.strip()) else None


def read(text: str) -> money.Price | None:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    found: set[money.Price] = set()
    for n, line in enumerate(lines):
        price = _in_line(line)
        if price is None and n + 1 < len(lines) and not _moneys(line) and _label(line):
            price = _alone(lines[n + 1])
        if price is not None:
            found.add(price)
    return next(iter(found)) if len(found) == 1 else None


def structured(total: Any, currency: Any) -> money.Price | None:
    if not isinstance(currency, str) or money.CODE.fullmatch(currency.strip().upper()) is None:
        return None
    code = currency.strip().upper()
    if isinstance(total, bool):
        return None
    if isinstance(total, (int, float)):
        try:
            return _price(Decimal(str(total)), code)
        except InvalidOperation:
            return None
    if isinstance(total, str):
        plain = re.sub(rf"\s*{CURRENCY}\s*", "", total.strip())
        return _price(_number(plain, code), code) if plain else None
    return None


def printed(text: str, cost: money.Price) -> bool:
    signs = [sign for sign, code in SYMBOLS.items() if code == cost.currency]
    if not (re.search(rf"(?<![A-Za-z]){cost.currency}(?![A-Za-z])", text) or any(sign in text for sign in signs)):
        return False
    return any(_price(_number(m[0], cost.currency), cost.currency) == cost for m in re.finditer(NUMBER, text))


def _earliest(bookings: Iterable[Booking]) -> Booking:
    return min(bookings, key=lambda b: b.start)


def assign(bookings: Sequence[Booking], text: str) -> list[Booking]:
    live = [replace(b, price=None) if b.status == "cancelled" else b for b in bookings]
    coded: dict[str, list[Booking]] = {}
    for b in live:
        if b.confirmation and b.price is not None:
            coded.setdefault(b.confirmation, []).append(b)
    drop: set[int] = set()
    for same in coded.values():
        if len(same) > 1 and len({b.price for b in same}) == 1:
            drop.update(id(b) for b in same if b is not _earliest(same))
    live = [replace(b, price=None) if id(b) in drop else b for b in live]
    open_ = [b for b in live if b.status != "cancelled"]
    if not open_ or any(b.price is not None for b in live):
        return live
    one_booking = len(open_) == 1 or (open_[0].confirmation is not None and len({b.confirmation for b in open_}) == 1)
    total = read(text) if one_booking else None
    if total is None:
        return live
    first = _earliest(open_)
    return [replace(b, price=total) if b is first else b for b in live]
