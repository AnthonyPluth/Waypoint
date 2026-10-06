from __future__ import annotations

from collections.abc import Iterable
from datetime import date

SENDERS = (
    "aa.com", "delta.com", "united.com", "southwest.com", "jetblue.com", "alaskaair.com", "spirit.com", "flyfrontier.com",
    "hawaiianairlines.com", "aircanada.com", "westjet.com", "britishairways.com", "virginatlantic.com", "lufthansa.com",
    "swiss.com", "airfrance.com", "klm.com", "iberia.com", "finnair.com", "ryanair.com", "easyjet.com", "turkishairlines.com",
    "emirates.com", "qatarairways.com", "etihad.com", "singaporeair.com", "cathaypacific.com", "ana.co.jp", "jal.co.jp",
    "qantas.com", "airnewzealand.com", "airnz.co.nz",
    "marriott.com", "hilton.com", "hyatt.com", "ihg.com", "wyndhamhotels.com", "accor.com", "choicehotels.com",
    "bestwestern.com", "radissonhotels.com",
    "hertz.com", "avis.com", "budget.com", "enterprise.com", "nationalcar.com", "alamo.com", "sixt.com",
    "amtrak.com", "eurostar.com", "trainline.com", "sncf-connect.com", "raileurope.com",
    "booking.com", "expedia.com", "hotels.com", "airbnb.com", "vrbo.com", "kayak.com", "priceline.com", "orbitz.com",
    "travelocity.com", "agoda.com", "trip.com",
)
WORDS = ("confirmation", "itinerary", "reservation", "e-ticket", "booking")
LOOKBACK_MONTHS = 18


def build(since: date, ignored: Iterable[str] = ()) -> str:
    senders = " OR ".join(SENDERS)
    words = " OR ".join(f'"{w}"' if "-" in w else w for w in WORDS)
    skipped = "".join(f" -from:{d}" for d in sorted(set(ignored)))
    return f"from:({senders}) ({words}) -category:promotions{skipped} after:{since:%Y/%m/%d}"
