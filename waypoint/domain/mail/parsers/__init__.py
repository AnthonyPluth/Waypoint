"""Vendor parsers: senders whose booking emails carry no schema.org markup (or not enough of it) are read from their
text. A parser is a pure function from a message's HTML and plain text to the bookings in it (`Parsed`): no I/O, no logging,
nothing kept of the text (AGENTS.md, "Email stays on the server"). It is keyed by the sender's domain here, and `extract.read`
runs it when the markup gave no booking. A parser also reads the vendor's change and cancellation emails: a cancellation
comes out as a booking with status "cancelled", and a change as the booking with its new times, which the merge in
`trips.merge_email_segment` marks changed (and leaves any field a person edited alone).

A new parser is a module here (`<vendor>.py` with a `parse`), an entry in `PARSERS` and synthetic fixtures in
`tests/fixtures/mail/<vendor>/` (`booking.eml`, `change.eml`, `cancellation.eml`), read by `tests/test_mail_parser_<vendor>.py`;
`tools/fleet_checks.py` fails without them. Fixtures are invented: made-up names, codes and numbers, real airport codes."""
from __future__ import annotations

from collections.abc import Callable

from ..booking import Parsed
from . import southwest


Parser = Callable[[str, str], Parsed]

# Sender domain -> parser; a subdomain of the key (luv.southwest.com) is the same sender.
PARSERS: dict[str, Parser] = {
    "southwest.com": southwest.parse,
}


def for_sender(domain: str | None) -> Parser | None:
    """The parser for a message from this sender domain, if there is one."""
    if not domain:
        return None
    for key, parser in PARSERS.items():
        if domain == key or domain.endswith("." + key):
            return parser
    return None
