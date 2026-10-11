from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from . import query

Decision = Literal["read", "skip"]
CATEGORY_SIGNALS = frozenset({"CATEGORY_RESERVATIONS", "CATEGORY_PURCHASES"})
TRAVEL = (
    re.compile(r"\bflights?\b", re.IGNORECASE),
    re.compile(r"itinerar", re.IGNORECASE),
    re.compile(r"e-?tickets?", re.IGNORECASE),
    re.compile(r"boarding pass", re.IGNORECASE),
    re.compile(r"check-?in\b|チェックイン", re.IGNORECASE),
    re.compile(r"check-out|check-?out (?:time|date)|checkout (?:time|date)|チェックアウト", re.IGNORECASE),
    re.compile(r"your stay|宿泊", re.IGNORECASE),
    re.compile(r"\bhotels?\b", re.IGNORECASE),
    re.compile(r"your room|room (?:type|reservation)|\b\d+ rooms?\b", re.IGNORECASE),
    re.compile(r"cruise|sailing", re.IGNORECASE),
    re.compile(r"rental car|car rental|car hire|pick-?up (?:location|date|time)", re.IGNORECASE),
    re.compile(r"\btrain\b", re.IGNORECASE),
    re.compile(r"trip is|your trip", re.IGNORECASE),
)
PLACE = re.compile(r"\b(?:inn|resort|lodge|lodging|suites?|villa|apartment|cabin|guest ?house|motel|b&b|bnb)\b", re.IGNORECASE)
RESERVATION_NUMBER = re.compile(r"reservation (?:number|no\b|#)", re.IGNORECASE)
GENERIC = re.compile(r"confirm|book(?:ed|ing)|reserv|予約|確認", re.IGNORECASE)
RETAIL = re.compile(r"\border(?:s|ed)?\b|shipped|shipment|out for delivery|\bdelivered\b|tracking (?:number|id)|your package|\breturns?\b|refund|receipt|invoice|(?:thanks|thank you) for your purchase", re.IGNORECASE)
SENDER_NAME = re.compile(r"hotels?|resorts?|\binn\b|lodge|lodging|suites|motel|airlines?|airways|\bair\b|cruises?|\brail|travel|stays?|vacations?|hostel", re.IGNORECASE)
CHANGES = re.compile(r"modif|amend|cancel|rebook|\bchang(?:e|ed|es)\b.{0,40}(?:reservation|booking|stay|trip|itinerary|flight)|(?:reservation|booking|stay|trip|itinerary|flight)\b.{0,30}\bchang(?:e|ed|es)\b", re.IGNORECASE)
CODE = re.compile(r"(?:one[- ]time|verification|security|login|log-in|sign[- ]?in|authentication|access)\s+(?:code|passcode|pin)|\botp\b|your (?:code|passcode) is|passcode", re.IGNORECASE)
MAILING = re.compile(r"newsletter|weekly digest|monthly digest|\bdeals?\b|\bsale\b|\d+% off|membership (?:offer|renewal|reminder|statement)|points statement|rewards? (?:offer|statement)|special offer|exclusive offer", re.IGNORECASE)
AUTO_REPLY = re.compile(r"(?:we(?:'ve| have)?|i(?:'ve| have)?) received your (?:message|request|inquiry|enquiry|email)|auto[- ]?reply|automatic reply|out of office|thank you for contacting|thanks for contacting", re.IGNORECASE)
REPLY = re.compile(r"^\s*re\s*:", re.IGNORECASE)


@dataclass(frozen=True)
class Head:
    subject: str
    sender_domain: str | None
    snippet: str
    labels: frozenset[str]
    sender_name: str = ""


def sender_in(domain: str | None, domains: tuple[str, ...]) -> bool:
    return bool(domain) and any(domain == d or (domain or "").endswith("." + d) for d in domains)


def travel_words(text: str) -> int:
    found = sum(1 for word in TRAVEL if word.search(text))
    return found + (1 if RESERVATION_NUMBER.search(text) and PLACE.search(text) else 0)


def _named(head: Head) -> bool:
    return bool(SENDER_NAME.search(head.sender_name))


def _categorised(head: Head) -> bool:
    text = f"{head.subject} {head.snippet}"
    return bool(head.labels & CATEGORY_SIGNALS) and bool(GENERIC.search(text)) and not RETAIL.search(text)


def strong(head: Head) -> bool:
    return sender_in(head.sender_domain, query.SENDERS) or travel_words(f"{head.subject} {head.snippet}") >= 2 or _categorised(head)


def shopping(head: Head) -> bool:
    if sender_in(head.sender_domain, query.SENDERS) or sender_in(head.sender_domain, query.BANK_SENDERS):
        return False
    if sender_in(head.sender_domain, query.RETAIL_SENDERS):
        return True
    text = f"{head.subject} {head.snippet}"
    return bool(RETAIL.search(text)) and not travel_words(text) and not _named(head)


def decide(head: Head) -> Decision:
    text = f"{head.subject} {head.snippet}"
    changes = bool(CHANGES.search(head.subject))
    known = sender_in(head.sender_domain, query.SENDERS)
    words = travel_words(text)
    if not changes and (CODE.search(text) or AUTO_REPLY.search(text) or (not known and (REPLY.match(head.subject) or (MAILING.search(head.subject) and not (travel_words(head.subject) or GENERIC.search(head.subject)))))):
        return "skip"
    if sender_in(head.sender_domain, query.BANK_SENDERS):
        return "read" if any(w in head.subject.lower() for w in query.BANK_SUBJECT_WORDS) else "skip"
    if known:
        return "read"
    if sender_in(head.sender_domain, query.RETAIL_SENDERS):
        return "skip"
    if words or _categorised(head) or (_named(head) and (GENERIC.search(text) or RETAIL.search(text))) or (changes and GENERIC.search(text) and not RETAIL.search(text)):
        return "read"
    return "skip"
