from __future__ import annotations

import re
from datetime import date, time, timedelta

from . import when
from .booking import Booking, Parsed, Passenger
from .parsers._text import lines

MAX_NIGHTS = 60
CHECK_IN = time(15, 0)
CHECK_OUT = time(11, 0)
LABELS: dict[str, tuple[str, ...]] = {
    "checkin": ("check-in date", "check in date", "check-in", "check in", "checkin", "arrival date", "arrival", "チェックイン日", "チェックイン"),
    "checkout": ("check-out date", "check out date", "check-out", "check out", "checkout", "departure date", "departure", "チェックアウト日", "チェックアウト"),
    "property": ("hotel name", "property name", "property", "hotel", "accommodation", "宿泊施設名", "宿泊施設", "施設名", "ホテル名", "宿泊先"),
    "address": ("address", "住所", "所在地"),
    "confirmation": ("reservation number", "reservation no.", "reservation no", "reservation #", "reservation code", "confirmation number",
                     "confirmation no.", "confirmation no", "confirmation #", "confirmation code", "booking number", "booking reference",
                     "予約番号", "確認番号", "予約ID"),
    "nights": ("number of nights", "length of stay", "nights", "泊数", "宿泊数"),
    "guest": ("guest name", "guest", "宿泊者名", "宿泊者", "ご利用者名"),
}
CANCEL = re.compile(r"cancel|refund|penalt|no[- ]show|キャンセル|払い戻し|取消", re.IGNORECASE)
NIGHTS = re.compile(r"(\d{1,3})\s*(?:nights?|泊)", re.IGNORECASE)
CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{3,24}")
Sources = tuple[tuple[str, str], ...]


class Unreadable(Exception):
    pass


FREE = {"property", "address", "guest"}


def _find(rows: list[str], key: str) -> tuple[str, str] | None:
    for n, row in enumerate(rows):
        if CANCEL.search(row):
            continue
        for label in LABELS[key]:
            if not row.lower().startswith(label.lower()):
                continue
            after = row[len(label):]
            if label.isascii() and after[:1].isalnum():
                continue
            colon = after.lstrip().startswith((":", "：", "#"))
            rest = after.lstrip(" :：#.-").strip()
            if rest and key in FREE and not colon:
                continue
            if not rest and n + 1 < len(rows) and not CANCEL.search(rows[n + 1]):
                following = rows[n + 1]
                if not any(following.lower().startswith(w.lower()) for ws in LABELS.values() for w in ws):
                    rest = following
            if rest:
                return label, rest
    return None


def read(html: str, text: str) -> tuple[Parsed, str | None]:
    rows = lines(html, text)
    try:
        return Parsed((_booking(rows),)), None
    except Unreadable as e:
        return Parsed(), str(e)


def parse(html: str, text: str) -> Parsed:
    return read(html, text)[0]


def _booking(rows: list[str]) -> Booking:
    found = {key: hit for key in LABELS if (hit := _find(rows, key)) is not None}
    if "checkin" not in found:
        raise Unreadable("")
    if "property" not in found:
        raise Unreadable("no hotel name found")
    name = found["property"][1][:100]
    first = when.find_date(found["checkin"][1])
    if first is None:
        raise Unreadable("check-in isn't a date")
    sources: dict[str, str] = {"origin": found["property"][0], "start_local": found["checkin"][0]}
    at_in = when.find_time(found["checkin"][1])
    last: date | None = None
    at_out: time | None = None
    if "checkout" in found:
        last = when.find_date(found["checkout"][1])
        at_out = when.find_time(found["checkout"][1])
        if last is None:
            raise Unreadable("check-out isn't a date")
        sources["end_local"] = found["checkout"][0]
    elif "nights" in found and (n := NIGHTS.search(found["nights"][1]) or re.fullmatch(r"(\d{1,3})", found["nights"][1].strip())):
        last = first + timedelta(days=int(n[1]))
        sources["end_local"] = found["nights"][0]
    elif n := next((m for r in rows if not CANCEL.search(r) and (m := NIGHTS.search(r))), None):
        last = first + timedelta(days=int(n[1]))
        sources["end_local"] = "nights"
    if last is None:
        raise Unreadable("no check-out date found")
    if last <= first:
        raise Unreadable("check-out isn't after check-in")
    if (last - first).days > MAX_NIGHTS:
        raise Unreadable(f"stay is longer than {MAX_NIGHTS} nights")
    code = None
    if "confirmation" in found:
        m = CODE.search(found["confirmation"][1])
        code = m[0].upper() if m else None
        if code:
            sources["confirmation"] = found["confirmation"][0]
    address = found["address"][1][:300] if "address" in found else None
    if address:
        sources["address"] = found["address"][0]
    guest = found["guest"][1][:80] if "guest" in found else None
    details = tuple((k, v) for k, v in (("address", address), ("time_unknown", "yes" if at_in is None or at_out is None else None)) if v)
    return Booking("hotel", "confirmed", code, name, when.stamp(first, at_in, CHECK_IN), when.stamp(last, at_out, CHECK_OUT), name, None, details=details,
                   passengers=(Passenger(guest),) if guest else (), generic=tuple(sources.items()))
