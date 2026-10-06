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
WIDTH = 256
TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
IMAGE_HOSTS = frozenset({"commons.wikimedia.org", "upload.wikimedia.org"})
USER_AGENT = "Waypoint (https://github.com/AnthonyPluth/Waypoint; self-hosted travel app)"
CANDIDATES = 10
SERVICE_ERRORS = frozenset({"ratelimited", "maxlag", "readonly", "internal_api_error_DBConnectionError"})
NOT_A_BRAND = ("building", "skyscraper", "airport", "hotel in ", "hotel located", "resort in ", "stadium", "station")


@dataclass(frozen=True)
class Hosts:
    wikidata: str = "https://www.wikidata.org/w/api.php"
    files: str = "https://commons.wikimedia.org/wiki/Special:FilePath"
    allow_http: bool = False


HOSTS = Hosts()


class Unavailable(Exception):
    pass


class _Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        host = urllib.parse.urlsplit(newurl).hostname
        if host not in IMAGE_HOSTS and host != urllib.parse.urlsplit(req.full_url).hostname:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url: str, limit: int, accept: str, file: bool = False) -> tuple[bytes, str]:
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
    if "error" in found:
        if str((found["error"] or {}).get("code") if isinstance(found["error"], dict) else "") in SERVICE_ERRORS:
            raise Unavailable("Wikidata is busy or read-only")
        return {}
    return found


_DROP = re.compile(r"\b(the|hotel|hotels|resort|resorts|and|company|group|inc|llc|ltd|restaurants)\b")
_BY = re.compile(r"\bby [a-z0-9 ]+$")


def norm(name: str | None) -> str:
    text = unicodedata.normalize("NFKD", (name or "").lower().replace("&", " and ")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = _BY.sub("", text)
    return " ".join(_DROP.sub(" ", text).split())


def same_brand(name: str, label: str | None) -> bool:
    a, b = norm(name), norm(label)
    return len(a) >= 2 and a == b


def _logo_file(claims: Any) -> str | None:
    best: tuple[int, str] | None = None
    for claim in claims if isinstance(claims, list) else []:
        value = (((claim or {}).get("mainsnak") or {}).get("datavalue") or {}).get("value")
        rank = (claim or {}).get("rank")
        if isinstance(value, str) and value and rank != "deprecated":
            score = 1 if rank == "preferred" else 0
            if best is None or score >= best[0]:
                best = (score, value)
    return best[1] if best else None


def _label(entity: dict[str, Any]) -> str:
    label = (entity.get("labels") or {}).get("en") or {}
    return str(label.get("value") or "")


def find_logo(name: str) -> tuple[bytes, str] | None:
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
    if ctype not in TYPES or not data or len(data) > MAX_LOGO:
        return None
    return data, ctype
