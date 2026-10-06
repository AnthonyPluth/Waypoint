from __future__ import annotations

import re

CHAINS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Marriott", ("marriott", "westin", "sheraton", "w hotel", "w hotels", "ritz carlton", "courtyard by marriott", "courtyard marriott", "residence inn", "fairfield inn",
                  "fairfield by", "springhill", "aloft", "element by", "renaissance", "st regis", "le meridien", "autograph collection",
                  "towneplace", "moxy hotel", "moxy hotels", "ac hotel", "four points", "gaylord", "luxury collection", "edition hotel", "delta hotels",
                  "protea", "tribute portfolio", "design hotels", "bonvoy")),
    ("Hilton", ("hilton", "hampton inn", "hampton by", "doubletree", "embassy suites", "homewood suites", "home2", "conrad", "waldorf astoria",
                "curio collection", "tapestry collection", "canopy by", "tru by", "motto by", "lxr hotels", "signia by hilton", "spark by")),
    ("Hyatt", ("hyatt", "andaz", "thompson hotel", "alila", "miraval", "caption by", "destination hotels", "joie de vivre", "jdv by")),
    ("IHG", ("holiday inn", "crowne plaza", "intercontinental", "kimpton", "staybridge", "candlewood", "hotel indigo", "even hotels",
             "voco", "regent hotel", "six senses", "avid hotel", "atwell suites", "ihg", "vignette collection", "garner hotel")),
    ("Wyndham", ("wyndham", "ramada", "days inn", "super 8", "la quinta", "baymont", "microtel", "howard johnson", "travelodge",
                 "wingate", "hawthorn suites", "tryp by", "dolce hotels", "trademark collection", "registry collection")),
    ("Choice Hotels", ("comfort inn", "comfort suites", "quality inn", "clarion", "sleep inn", "econo lodge", "rodeway", "ascend hotel",
                       "cambria hotel", "mainstay suites", "suburban extended", "woodspring", "choice hotels")),
    ("Best Western", ("best western", "surestay", "glo by", "vib by", "aiden by")),
    ("Accor", ("accor", "novotel", "ibis", "sofitel", "pullman", "fairmont", "raffles", "swissotel", "mercure", "mgallery", "mama shelter",
               "grand mercure", "movenpick", "banyan tree", "25hours", "so sofitel")),
    ("Radisson", ("radisson", "park inn", "park plaza", "country inn suites", "arc hotel")),
    ("Four Seasons", ("four seasons",)),
    ("Mandarin Oriental", ("mandarin oriental",)),
    ("Omni", ("omni hotel", "omni resort")),
    ("Loews", ("loews",)),
    ("Langham", ("langham", "cordis", "eaton hotel")),
    ("Shangri-La", ("shangri la", "kerry hotel", "jen hotel")),
    ("Motel 6", ("motel 6", "studio 6")),
    ("Red Roof", ("red roof",)),
    ("Extended Stay", ("extended stay america",)),
    ("Drury", ("drury inn", "drury plaza")),
)
BOOKING_SITES = ("capital one travel", "expedia", "hotels com", "booking com", "priceline", "hotwire", "agoda", "kayak", "orbitz",
                 "travelocity", "trip com", "costco travel", "american express travel", "amex travel", "chase travel", "cheaptickets",
                 "trivago", "hopper", "ebookers", "lastminute", "getaroom", "tripadvisor", "points com", "rocketmiles", "fine hotels")
PLATFORMS = {"airbnb": "Airbnb", "vrbo": "VRBO", "homeaway": "VRBO"}
VIA = re.compile(r"\s*[(\[]\s*(?:booked\s+)?(?:via|through|with|by)\b[^)\]]*[)\]]\s*", re.IGNORECASE)


def _words(text: str | None) -> str:
    return " " + re.sub(r"[^a-z0-9+]+", " ", (text or "").casefold().replace("é", "e").replace("’", "")).strip() + " "


def _mentions(text: str, phrases: tuple[str, ...]) -> bool:
    return any(f" {_words(p).strip()} " in text for p in phrases)


def clean(name: str | None) -> str | None:
    cleaned = VIA.sub(" ", name or "").strip(" ,;-–")
    return " ".join(cleaned.split()) or None


def hotel_chain(provider: str | None, hotel: str | None) -> str | None:
    provider = clean(provider)
    for text in (_words(hotel), _words(provider)):
        for chain, phrases in CHAINS:
            if _mentions(text, phrases):
                return chain
    if not provider:
        return None
    named = _words(provider)
    for key, label in PLATFORMS.items():
        if f" {key} " in named:
            return label
    if _mentions(named, BOOKING_SITES) or named.strip() == _words(hotel).strip():
        return None
    return provider
