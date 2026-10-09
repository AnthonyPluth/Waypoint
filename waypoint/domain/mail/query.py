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
    "chasetravel.com", "capitalonetravel.com", "perk.com", "travelbank.com", "amextravel.com", "navan.com", "tripactions.com",
    "egencia.com", "costcotravel.com", "cheapoair.com", "onetravel.com", "hopper.com",
    "carnival.com", "royalcaribbean.com", "celebritycruises.com", "ncl.com", "princess.com", "hollandamerica.com", "msccruises.com",
    "virginvoyages.com", "vikingcruises.com", "disneycruise.com", "familyvacations-disneycruise.com", "cunard.com", "seabourn.com", "azamara.com", "oceaniacruises.com",
    "rssc.com", "silversea.com", "windstarcruises.com", "ponant.com", "lindblad.com", "costacruises.com", "avalonwaterways.com",
    "uniworld.com", "amawaterways.com", "vacationstogo.com",
)
BANK_SENDERS = ("chase.com", "capitalone.com", "americanexpress.com", "aexp.com")
BANK_SUBJECT_WORDS = ("travel", "trip", "flight", "hotel", "cruise", "itinerary", "e-ticket")
WORDS = ("confirmation", "itinerary", "reservation", "e-ticket", "booking", "cruise", "sailing")
LOOKBACK_MONTHS = 18


def build(since: date, ignored: Iterable[str] = ()) -> str:
    senders = " OR ".join(SENDERS)
    banks = " OR ".join(BANK_SENDERS)
    words = _any(WORDS)
    subject = _any(BANK_SUBJECT_WORDS)
    skipped = "".join(f" -from:{d}" for d in sorted(set(ignored)))
    return (f"((from:({senders}) ({words})) OR (from:({banks}) subject:({subject}) ({words}))) "
            f"-category:promotions{skipped} after:{since:%Y/%m/%d}")


def _any(words: Iterable[str]) -> str:
    return " OR ".join(f'"{w}"' if "-" in w else w for w in words)
