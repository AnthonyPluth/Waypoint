from __future__ import annotations

from typing import Literal, TypedDict

from . import chains

ALL = ("flight", "hotel", "car", "train", "cruise")
CHECKED = "2026-10-10"


class Vendor(TypedDict):
    names: tuple[str, ...]
    domains: tuple[str, ...]
    kinds: tuple[str, ...]
    url: str
    kind: Literal["app", "website"]
    checked: str
    source: str


def _app(names: tuple[str, ...], domains: tuple[str, ...], kinds: tuple[str, ...], url: str, source: str) -> Vendor:
    return {"names": names, "domains": domains, "kinds": kinds, "url": url, "kind": "app", "checked": CHECKED, "source": source}


def _site(names: tuple[str, ...], domain: str, kinds: tuple[str, ...], source: str = "the vendor's app and site files weren't seen: the vendor's home page", *, www: bool = True) -> Vendor:
    return {"names": names, "domains": (domain,), "kinds": kinds, "url": f"https://{'www.' if www else ''}{domain}/", "kind": "website", "checked": CHECKED, "source": source}


FLIGHT, HOTEL, CAR, TRAIN, CRUISE = ("flight",), ("hotel",), ("car",), ("train",), ("cruise",)
APP_ONLY_CLAIMS = "the vendor's app claims only account, check-in or parameter-driven paths, none a neutral page: the vendor's home page"

VENDORS: tuple[Vendor, ...] = (
    _app(("delta air lines", "delta"), ("delta.com",), FLIGHT, "https://www.delta.com/my-trips/search",
         "claims */my-trips/search; opened the app on the owner's iPhone"),
    _app(("united airlines", "united"), ("united.com",), FLIGHT, "https://www.united.com/en/us/manageres/mytrips",
         "claims */us/manageres/mytrips"),
    _app(("american airlines", "american"), ("aa.com",), FLIGHT, "https://www.aa.com/reservation/view/find-your-reservation",
         "claims /reservation/view/find-your-reservation"),
    _site(("southwest airlines", "southwest"), "southwest.com", FLIGHT, "the vendor's app claims only /redirect/*, which acts on parameters: the vendor's home page"),
    _site(("jetblue airways", "jetblue"), "jetblue.com", FLIGHT, "the vendor's app claims only /airware paths: the vendor's home page"),
    _site(("alaska airlines", "alaska"), "alaskaair.com", FLIGHT, "the vendor's app claims only the web check-in page, which needs parameters: the vendor's home page"),
    _app(("marriott", "marriott bonvoy"), ("marriott.com",), HOTEL, "https://www.marriott.com/", "claims / and /default.mi: the home page"),
    _site(("hilton", "hilton hotels", "hilton hotels & resorts"), "hilton.com", HOTEL,
          "the vendor's app claims /rs/hilton-honors-mobile-app/* and a deeplink_path query, which can't be confirmed without a phone: the vendor's home page"),
    _app(("hyatt", "world of hyatt"), ("hyatt.com",), HOTEL, "https://www.hyatt.com/mobile", "claims /mobile and /mobile/*"),
    _site(("ihg", "ihg hotels & resorts"), "ihg.com", HOTEL, "the vendor's app claims /redirect and wildcard hotel paths that act on parameters: the vendor's home page"),
    _app(("hertz",), ("hertz.com",), CAR, "https://www.hertz.com/homepage", "claims /homepage*"),
    _site(("avis",), "avis.com", CAR, "the vendor's app claims only /app-link/* and upsell paths: the vendor's home page"),
    _site(("budget", "budget rent a car"), "budget.com", CAR, "the vendor's app claims only /app-link/* and upsell paths: the vendor's home page"),
    _app(("enterprise", "enterprise rent-a-car", "enterprise rent a car"), ("enterprise.com",), CAR, "https://www.enterprise.com/en/home.html",
         "claims /en/home.html"),
    _app(("booking.com",), ("booking.com",), ALL, "https://www.booking.com/mybookings", "claims /mybookings"),
    _app(("expedia",), ("expedia.com",), ALL, "https://www.expedia.com/", "claims /: the home page"),
    _app(("airbnb",), ("airbnb.com",), HOTEL, "https://www.airbnb.com/trips", "claims /trips"),
    _site(("amtrak",), "amtrak.com", TRAIN, "no app claims a path on the vendor's site (no file): the vendor's home page"),
    _site(("carnival cruise line", "carnival"), "carnival.com", CRUISE, "no app claims a path on the vendor's site (no file): the vendor's home page"),
    _site(("royal caribbean", "royal caribbean international"), "royalcaribbean.com", CRUISE,
          "the vendor's app claims only account and check-in paths: the vendor's home page"),
)

TAIL: tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...] = (
    (("spirit airlines", "spirit"), "spirit.com", FLIGHT), (("frontier airlines", "frontier"), "flyfrontier.com", FLIGHT),
    (("hawaiian airlines", "hawaiian"), "hawaiianairlines.com", FLIGHT), (("air canada",), "aircanada.com", FLIGHT),
    (("westjet",), "westjet.com", FLIGHT), (("british airways",), "britishairways.com", FLIGHT),
    (("virgin atlantic",), "virginatlantic.com", FLIGHT), (("lufthansa",), "lufthansa.com", FLIGHT),
    (("swiss", "swiss international air lines"), "swiss.com", FLIGHT), (("air france",), "airfrance.com", FLIGHT),
    (("klm", "klm royal dutch airlines"), "klm.com", FLIGHT), (("iberia",), "iberia.com", FLIGHT),
    (("finnair",), "finnair.com", FLIGHT), (("ryanair",), "ryanair.com", FLIGHT), (("easyjet",), "easyjet.com", FLIGHT),
    (("turkish airlines",), "turkishairlines.com", FLIGHT), (("emirates",), "emirates.com", FLIGHT),
    (("qatar airways",), "qatarairways.com", FLIGHT), (("etihad", "etihad airways"), "etihad.com", FLIGHT),
    (("singapore airlines",), "singaporeair.com", FLIGHT), (("cathay pacific",), "cathaypacific.com", FLIGHT),
    (("all nippon airways", "ana"), "ana.co.jp", FLIGHT), (("japan airlines", "jal"), "jal.co.jp", FLIGHT),
    (("qantas",), "qantas.com", FLIGHT), (("air new zealand",), "airnewzealand.com", FLIGHT),
    (("wyndham", "wyndham hotels & resorts"), "wyndhamhotels.com", HOTEL), (("accor",), "accor.com", HOTEL),
    (("choice hotels",), "choicehotels.com", HOTEL), (("best western",), "bestwestern.com", HOTEL),
    (("radisson",), "radissonhotels.com", HOTEL), (("sixt",), "sixt.com", CAR), (("national", "national car rental"), "nationalcar.com", CAR),
    (("alamo", "alamo rent a car"), "alamo.com", CAR), (("eurostar",), "eurostar.com", TRAIN), (("trainline",), "trainline.com", TRAIN),
    (("sncf connect", "sncf"), "sncf-connect.com", TRAIN), (("rail europe",), "raileurope.com", TRAIN),
    (("hotels.com",), "hotels.com", ALL), (("vrbo",), "vrbo.com", HOTEL), (("kayak",), "kayak.com", ALL), (("priceline",), "priceline.com", ALL),
    (("orbitz",), "orbitz.com", ALL), (("travelocity",), "travelocity.com", ALL), (("agoda",), "agoda.com", ALL), (("trip.com",), "trip.com", ALL),
    (("chase travel",), "chasetravel.com", ALL), (("capital one travel",), "capitalonetravel.com", ALL), (("perk",), "perk.com", ALL),
    (("travelbank",), "travelbank.com", ALL), (("amex travel", "american express travel"), "amextravel.com", ALL), (("navan",), "navan.com", ALL),
    (("tripactions",), "tripactions.com", ALL), (("egencia",), "egencia.com", ALL), (("costco travel",), "costcotravel.com", ALL),
    (("cheapoair",), "cheapoair.com", ALL), (("onetravel",), "onetravel.com", ALL), (("hopper",), "hopper.com", ALL),
    (("celebrity cruises", "celebrity"), "celebritycruises.com", CRUISE), (("norwegian cruise line", "ncl"), "ncl.com", CRUISE),
    (("princess cruises", "princess"), "princess.com", CRUISE), (("holland america line", "holland america"), "hollandamerica.com", CRUISE),
    (("msc cruises", "msc"), "msccruises.com", CRUISE), (("virgin voyages",), "virginvoyages.com", CRUISE),
    (("viking", "viking cruises"), "vikingcruises.com", CRUISE), (("disney cruise line",), "disneycruise.com", CRUISE),
    (("cunard",), "cunard.com", CRUISE), (("seabourn",), "seabourn.com", CRUISE), (("azamara",), "azamara.com", CRUISE),
    (("oceania cruises",), "oceaniacruises.com", CRUISE), (("regent seven seas cruises", "regent seven seas"), "rssc.com", CRUISE),
    (("silversea", "silversea cruises"), "silversea.com", CRUISE), (("windstar cruises", "windstar"), "windstarcruises.com", CRUISE),
    (("ponant",), "ponant.com", CRUISE), (("lindblad expeditions", "lindblad"), "lindblad.com", CRUISE),
    (("costa cruises", "costa"), "costacruises.com", CRUISE), (("avalon waterways",), "avalonwaterways.com", CRUISE),
    (("uniworld", "uniworld boutique river cruises"), "uniworld.com", CRUISE), (("amawaterways", "ama waterways"), "amawaterways.com", CRUISE),
    (("vacations to go",), "vacationstogo.com", CRUISE),
)
ALIASED_DOMAINS = {"familyvacations-disneycruise.com": "disneycruise.com", "airnz.co.nz": "airnewzealand.com"}

ALL_VENDORS: tuple[Vendor, ...] = VENDORS + tuple(_site(names, domain, kinds, www=False) for names, domain, kinds in TAIL)
BY_NAME: dict[str, Vendor] = {name: v for v in ALL_VENDORS for name in v["names"]}
BY_DOMAIN: dict[str, Vendor] = {d: v for v in ALL_VENDORS for d in v["domains"]}
for _alias, _domain in ALIASED_DOMAINS.items():
    BY_DOMAIN.setdefault(_alias, BY_DOMAIN[_domain])


def vendor_for(kind: str, provider: str | None, place: str | None = None) -> Vendor | None:
    name = " ".join((provider or "").casefold().split())
    found = BY_NAME.get(name)
    if found is None and kind == "hotel":
        chain = chains.hotel_chain(provider, place)
        found = BY_NAME.get(" ".join((chain or "").casefold().split()))
    return found if found is not None and kind in found["kinds"] else None
