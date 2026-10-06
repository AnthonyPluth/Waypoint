"""Hotel sub-brand logos from Wikidata and Wikimedia Commons: the one module that talks to them.

Logo.dev has a logo per website, so Hyatt Regency, Hyatt Place and the rest of a hotel group's brands rarely have one of their
own there. Wikidata does know most of them (an item for the brand, with its logo file on Commons). A request carries a brand's
name (never a traveller, a date, a confirmation code or the rest of a hotel's name, AGENTS.md, "Email stays on the server") and
nothing that identifies the household; neither service needs a key.

What comes back is kept only if it is a small PNG, JPEG, WebP or GIF (never SVG, which can carry scripts: Commons draws an SVG as a
PNG of the width asked for). A redirect is followed only within Wikimedia's own image hosts. Which brands to ask about, and keeping
what comes back, is waypoint/domain/logos.py.
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import IO, Any

from .. import tls

TIMEOUT = 10
MAX_LOGO = 256 * 1024
MAX_JSON = 2 * 1024 * 1024
WIDTH = 256   # pixels: shown at 24–48, so sharp on a dense screen
TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
IMAGE_HOSTS = frozenset({"commons.wikimedia.org", "upload.wikimedia.org"})
USER_AGENT = "Waypoint (https://github.com/AnthonyPluth/Waypoint; self-hosted travel app)"   # (Wikimedia asks for one that says who)
CANDIDATES = 10   # items looked at for a name
SERVICE_ERRORS = frozenset({"ratelimited", "maxlag", "readonly", "internal_api_error_DBConnectionError"})   # (an API error that is the service's)
NOT_A_BRAND = ("building", "skyscraper", "airport", "hotel in ", "hotel located", "resort in ", "stadium", "station")


@dataclass(frozen=True)
class Hosts:
    """The services' addresses. Tests point them at a fake one (and allow its plain http)."""
    wikidata: str = "https://www.wikidata.org/w/api.php"
    files: str = "https://commons.wikimedia.org/wiki/Special:FilePath"
    allow_http: bool = False


HOSTS = Hosts()


class Unavailable(Exception):
    """Wikidata or Commons couldn't be reached or was too busy: the service, not one brand's logo, is the trouble, so a round
    stops asking. The message is fixed text, safe to show and log. (A brand whose file is no good is just None: no logo.)"""


class _Redirects(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only to Wikimedia's image hosts (or the host the request went to)."""
    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        host = urllib.parse.urlsplit(newurl).hostname
        if host not in IMAGE_HOSTS and host != urllib.parse.urlsplit(req.full_url).hostname:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, limit: int, accept: str, file: bool = False) -> tuple[bytes, str]:
    """A file Commons won't give (any 4xx but "too many requests") is raised as FileNotFoundError, as that file's problem."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with tls.urlopen(req, timeout=TIMEOUT, allow_http=HOSTS.allow_http, handlers=(_Redirects(),)) as resp:
            return resp.read(limit + 1), (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 404 or (file and 400 <= e.code < 500 and e.code != 429):
            raise FileNotFoundError from None
        raise Unavailable("Wikimedia is busy or refused the request" if e.code == 429 else f"Wikimedia answered HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError):
        raise Unavailable("Wikimedia couldn't be reached") from None


def _api(**params: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    try:
        data, _ = _open(f"{HOSTS.wikidata}?{query}", MAX_JSON, "application/json")
        found = json.loads(data) if len(data) <= MAX_JSON else None
    except FileNotFoundError:
        found = None
    except ValueError:
        found = None
    if not isinstance(found, dict):
        raise Unavailable("Wikidata answered with something that isn't what was asked for")
    if "error" in found:   # busy or read-only: the service; any other error is this one question's, which has no answer
        if str((found["error"] or {}).get("code") if isinstance(found["error"], dict) else "") in SERVICE_ERRORS:
            raise Unavailable("Wikidata is busy or read-only")
        return {}
    return found


# ------------------------------------------------------------------------------------------------ matching

_DROP = re.compile(r"\b(the|hotel|hotels|resort|resorts|and|company|group|inc|llc|ltd|restaurants)\b")
_BY = re.compile(r"\bby [a-z0-9 ]+$")


def norm(name: str | None) -> str:
    """A brand's name for comparing: no case, accents or punctuation, no "by Marriott" or "Hotels & Resorts"."""
    text = unicodedata.normalize("NFKD", (name or "").lower().replace("&", " and ")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = _BY.sub("", text)
    return " ".join(_DROP.sub(" ", text).split())


def same_brand(name: str, label: str | None) -> bool:
    """Whether a Wikidata item's label is this brand: the same name give or take "Hotels", "by Marriott" and punctuation. Not a
    longer one ("Holiday Inn" is not "Holiday Inn Express"), so a brand's logo is never another brand's."""
    a, b = norm(name), norm(label)
    return len(a) >= 2 and a == b


# ------------------------------------------------------------------------------------------------ asking

def _logo_file(claims: Any) -> str | None:
    """The logo image of an item (property P154): the preferred one, else the newest."""
    best: tuple[int, str] | None = None
    for claim in claims if isinstance(claims, list) else []:
        value = (((claim or {}).get("mainsnak") or {}).get("datavalue") or {}).get("value")
        rank = (claim or {}).get("rank")
        if isinstance(value, str) and value and rank != "deprecated":
            score = 1 if rank == "preferred" else 0
            if best is None or score >= best[0]:   # (>=: of equals, the one listed last, the newest)
                best = (score, value)
    return best[1] if best else None


def _label(entity: dict[str, Any]) -> str:
    label = (entity.get("labels") or {}).get("en") or {}
    return str(label.get("value") or "")


def find_logo(name: str) -> tuple[bytes, str] | None:
    """The logo of a hotel brand by its name, as (image, content type); None when Wikidata has no item for exactly that brand
    with a logo on Commons that is a small image. Raises Unavailable when the service couldn't be asked, so that is never taken
    for "no such brand"."""
    words = " ".join((name or "").split())
    if len(norm(words)) < 2:
        return None
    hits = _api(action="wbsearchentities", search=words, language="en", type="item", limit=str(CANDIDATES)).get("search") or []
    ids = [h["id"] for h in hits if isinstance(h, dict) and re.fullmatch(r"Q\d{1,12}", str(h.get("id")))
           and same_brand(words, h.get("label")) and not any(w in str(h.get("description") or "").lower() for w in NOT_A_BRAND)]
    if not ids:
        return None
    entities = _api(action="wbgetentities", ids="|".join(ids), props="claims|labels", languages="en").get("entities") or {}
    for item in ids:
        entity = entities.get(item)
        if not isinstance(entity, dict):
            continue
        file = _logo_file((entity.get("claims") or {}).get("P154"))
        if file and same_brand(words, _label(entity)):
            return _download(file)
    return None


def _download(file: str) -> tuple[bytes, str] | None:
    url = f"{HOSTS.files}/{urllib.parse.quote(file, safe='')}?{urllib.parse.urlencode({'width': WIDTH})}"
    try:
        data, ctype = _open(url, MAX_LOGO, "image/png,image/*", file=True)
    except FileNotFoundError:
        return None
    if ctype not in TYPES or not data or len(data) > MAX_LOGO:   # (that brand's file, not the service: no logo)
        return None
    return data, ctype
