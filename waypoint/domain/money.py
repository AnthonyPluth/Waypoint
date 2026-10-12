from __future__ import annotations

import re
from dataclasses import dataclass

ZERO_DECIMALS = frozenset({"JPY", "KRW", "VND", "CLP", "ISK", "UGX", "XOF", "XAF", "XPF", "PYG", "RWF"})
THREE_DECIMALS = frozenset({"BHD", "KWD", "OMR", "JOD", "TND"})
TWO_DECIMALS = frozenset({
    "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN", "TRY", "ILS", "AED", "SAR",
    "QAR", "EGP", "ZAR", "MAD", "KES", "NGN", "INR", "LKR", "NPR", "PKR", "BDT", "THB", "MYR", "SGD", "IDR", "PHP", "TWD", "HKD", "CNY",
    "MXN", "BRL", "ARS", "COP", "PEN", "UYU", "CRC", "DOP", "JMD", "BSD", "BBD", "TTD", "UAH", "RSD", "GEL",
})
KNOWN = ZERO_DECIMALS | THREE_DECIMALS | TWO_DECIMALS
CODE = re.compile(r"[A-Z]{3}")
MAX_MINOR = 1_000_000_000


@dataclass(frozen=True)
class Price:
    amount_minor: int
    currency: str


def exponent(currency: str) -> int:
    return 0 if currency in ZERO_DECIMALS else 3 if currency in THREE_DECIMALS else 2


def valid(amount_minor: object, currency: object) -> bool:
    return (isinstance(amount_minor, int) and not isinstance(amount_minor, bool) and 0 <= amount_minor <= MAX_MINOR
            and isinstance(currency, str) and CODE.fullmatch(currency) is not None)
