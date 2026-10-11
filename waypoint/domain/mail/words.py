from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    name: str
    months: tuple[tuple[str, ...], ...]
    departure: tuple[str, ...]
    arrival: tuple[str, ...]
    origin: tuple[str, ...]
    destination: tuple[str, ...]
    confirmation: tuple[str, ...]
    cancel: tuple[str, ...]
    booked: tuple[str, ...]


ENGLISH = Language(
    "English",
    (("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"), ("july", "jul"),
     ("august", "aug"), ("september", "sept", "sep"), ("october", "oct"), ("november", "nov"), ("december", "dec")),
    ("departs", "departure", "departing", "depart", "leaves", "leaving"),
    ("arrives", "arrival", "arriving", "arrive"),
    ("from", "origin"),
    ("to", "destination"),
    ("confirmation code", "confirmation number", "confirmation no.", "confirmation no", "confirmation #", "booking reference",
     "booking code", "booking number", "reservation code", "reservation number", "reservation no.", "reservation no", "reservation #",
     "record locator", "pnr"),
    ("cancel", "refund", "penalt", "no-show", "no show"),
    ("booked on", "booking date", "date booked", "issued", "purchased", "purchase date", "order date", "sent on"),
)
FRENCH = Language(
    "French",
    (("janvier", "janv"), ("février", "févr", "fév"), ("mars",), ("avril", "avr"), ("mai",), ("juin",), ("juillet", "juil"),
     ("août", "aout"), ("septembre", "sept"), ("octobre", "oct"), ("novembre", "nov"), ("décembre", "déc")),
    ("départ", "depart", "décollage"),
    ("arrivée", "arrivee"),
    ("de", "origine"),
    ("vers", "à", "destination"),
    ("numéro de réservation", "référence de réservation", "code de réservation", "numéro de confirmation", "référence", "dossier"),
    ("annul", "rembours", "pénalit", "penalit"),
    ("réservé le", "reserve le", "date de réservation", "émis le", "acheté le"),
)
GERMAN = Language(
    "German",
    (("januar", "jan", "jän"), ("februar", "feb"), ("märz", "mär", "mrz"), ("april", "apr"), ("mai",), ("juni", "jun"), ("juli", "jul"),
     ("august", "aug"), ("september", "sept", "sep"), ("oktober", "okt"), ("november", "nov"), ("dezember", "dez")),
    ("abflug", "abreise", "abfahrt"),
    ("ankunft", "landung"),
    ("von", "herkunft"),
    ("nach", "ziel"),
    ("buchungscode", "buchungsnummer", "buchungsreferenz", "reservierungsnummer", "reservierungscode", "bestätigungsnummer"),
    ("storn", "erstatt", "rückerstattung", "no-show"),
    ("gebucht am", "buchungsdatum", "ausgestellt am", "bestelldatum"),
)
SPANISH = Language(
    "Spanish",
    (("enero", "ene"), ("febrero", "feb"), ("marzo", "mar"), ("abril", "abr"), ("mayo", "may"), ("junio", "jun"), ("julio", "jul"),
     ("agosto", "ago"), ("septiembre", "setiembre", "sept", "sep"), ("octubre", "oct"), ("noviembre", "nov"), ("diciembre", "dic")),
    ("salida", "sale"),
    ("llegada", "llega"),
    ("desde", "origen"),
    ("hasta", "destino"),
    ("código de reserva", "codigo de reserva", "número de reserva", "numero de reserva", "referencia de reserva", "localizador",
     "código de confirmación"),
    ("cancel", "anul", "reembolso", "penaliz"),
    ("reservado el", "fecha de reserva", "emitido el", "comprado el"),
)
JAPANESE = Language(
    "Japanese",
    (),
    ("出発", "発"),
    ("到着", "着"),
    ("出発地",),
    ("到着地", "目的地"),
    ("予約番号", "確認番号", "予約ID", "予約コード"),
    ("キャンセル", "払い戻し", "取消"),
    ("予約日", "購入日", "発行日"),
)
LANGUAGES = (ENGLISH, FRENCH, GERMAN, SPANISH, JAPANESE)


def _joined(pick: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(w for lang in LANGUAGES for w in getattr(lang, pick)))


def _pattern(words: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)), re.IGNORECASE)


DEPARTURE = _pattern(_joined("departure"))
ARRIVAL = _pattern(_joined("arrival"))
BOOKED = _pattern(_joined("booked"))
CANCEL = _pattern(_joined("cancel"))
CONFIRMATION = _joined("confirmation")
ORIGIN = _joined("origin")
DESTINATION = _joined("destination")
FULL_MONTHS: dict[str, int] = {}
for lang in LANGUAGES:
    for number, spellings in enumerate(lang.months, 1):
        for spelling in spellings:
            FULL_MONTHS.setdefault(spelling, number)
ENGLISH_PREFIX = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
