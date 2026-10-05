"""What a scan asks Gmail for: a search built from the senders bookings come from and the words they carry, so mail that
doesn't match is never downloaded (AGENTS.md, "Email stays on the server")."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date

# Sender domains of airlines, hotel groups, rental companies, railways and booking sites (Gmail's `from:` also matches their
# subdomains, such as mail.delta.com). A booking from anywhere else isn't looked for.
SENDERS = (
    # airlines
    "aa.com", "delta.com", "united.com", "southwest.com", "jetblue.com", "alaskaair.com", "spirit.com", "flyfrontier.com",
    "hawaiianairlines.com", "aircanada.com", "westjet.com", "britishairways.com", "virginatlantic.com", "lufthansa.com",
    "swiss.com", "airfrance.com", "klm.com", "iberia.com", "finnair.com", "ryanair.com", "easyjet.com", "turkishairlines.com",
    "emirates.com", "qatarairways.com", "etihad.com", "singaporeair.com", "cathaypacific.com", "ana.co.jp", "jal.co.jp",
    "qantas.com", "airnewzealand.com", "airnz.co.nz",
    # hotels
    "marriott.com", "hilton.com", "hyatt.com", "ihg.com", "wyndhamhotels.com", "accor.com", "choicehotels.com",
    "bestwestern.com", "radissonhotels.com",
    # rental cars
    "hertz.com", "avis.com", "budget.com", "enterprise.com", "nationalcar.com", "alamo.com", "sixt.com",
    # trains
    "amtrak.com", "eurostar.com", "trainline.com", "sncf-connect.com", "raileurope.com",
    # booking sites
    "booking.com", "expedia.com", "hotels.com", "airbnb.com", "vrbo.com", "kayak.com", "priceline.com", "orbitz.com",
    "travelocity.com", "agoda.com", "trip.com",
)
# What a booking's email says somewhere (in its subject or text).
WORDS = ("confirmation", "itinerary", "reservation", "e-ticket", "booking")
LOOKBACK_MONTHS = 18   # how far back a mailbox's first scan reads


def build(since: date, ignored: Iterable[str] = ()) -> str:
    """The Gmail search for messages since a day: from a known sender (and not from one the person chose to ignore), with a
    confirmation word, leaving out Gmail's Promotions."""
    senders = " OR ".join(SENDERS)
    words = " OR ".join(f'"{w}"' if "-" in w else w for w in WORDS)
    skipped = "".join(f" -from:{d}" for d in sorted(set(ignored)))
    return f"from:({senders}) ({words}) -category:promotions{skipped} after:{since:%Y/%m/%d}"
