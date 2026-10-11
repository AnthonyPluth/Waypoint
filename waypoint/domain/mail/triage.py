from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from . import query

Decision = Literal["read", "skip"]
CATEGORY_SIGNALS = frozenset({"CATEGORY_RESERVATIONS", "CATEGORY_PURCHASES"})
BOOKING = re.compile(r"confirm|itinerar|reserv|e-?ticket|book(?:ed|ing)|cruise|sailing|check-?in|check-?out|your stay|hotel|boarding pass|trip is|宿泊|予約|確認", re.IGNORECASE)
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


def sender_in(domain: str | None, domains: tuple[str, ...]) -> bool:
    return bool(domain) and any(domain == d or (domain or "").endswith("." + d) for d in domains)


def decide(head: Head) -> Decision:
    text = f"{head.subject} {head.snippet}"
    changes = bool(CHANGES.search(head.subject))
    known = sender_in(head.sender_domain, query.SENDERS)
    if not changes and (CODE.search(text) or AUTO_REPLY.search(text) or (not known and (REPLY.match(head.subject) or (MAILING.search(head.subject) and not BOOKING.search(head.subject))))):
        return "skip"
    if sender_in(head.sender_domain, query.BANK_SENDERS):
        return "read" if any(w in head.subject.lower() for w in query.BANK_SUBJECT_WORDS) else "skip"
    if known or head.labels & CATEGORY_SIGNALS or BOOKING.search(text):
        return "read"
    return "skip"
