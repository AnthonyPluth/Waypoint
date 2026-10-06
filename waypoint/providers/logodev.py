"""Brand logos from Logo.dev: the one module that talks to it.

A request carries the brand's name (an airline, a hotel, a rental company, a cruise line, as a booking names it) or, once
Brand Search has found it, its website, and the household's Logo.dev key: nothing else, never a traveller, a confirmation
code, a date or which trip it was on (AGENTS.md, "Email stays on the server"). The keys are saved encrypted in Settings
(the publishable pk_ key fetches a logo; the optional secret sk_ key adds Brand Search, to pick the right brand for a name)
and are never logged or put in an error message (monitoring.scrub hides them too). Without the publishable key nothing is asked.

What comes back is kept only if it is a small PNG, JPEG, WebP or GIF (never SVG, which can carry scripts); a redirect is
followed only to img.logo.dev. Which brands to ask about, and keeping what comes back, is waypoint/domain/logos.py.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import IO, Any

from .. import tls

TIMEOUT = 8
MAX_LOGO = 256 * 1024
TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
SIZE = 96   # pixels: shown at 24–40, so sharp on a dense screen
_SITE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")


@dataclass(frozen=True)
class Hosts:
    """The service's addresses. Tests point them at a fake one (and allow its plain http)."""
    images: str = "https://img.logo.dev"
    search: str = "https://api.logo.dev/search"
    allow_http: bool = False


HOSTS = Hosts()


class LogoError(Exception):
    """Something went wrong asking Logo.dev; the message is fixed text, safe to show and log."""


class Refused(LogoError):
    """Logo.dev doesn't accept the key (wrong, not the right kind, or its plan doesn't include this)."""


class Unavailable(LogoError):
    """Logo.dev couldn't be reached, or answered with something that isn't what was asked for."""


def site(domain: Any) -> str | None:
    """A website as Logo.dev names it ("https://www.Example.com/x" -> "example.com"), or None when it isn't one."""
    text = domain.strip().lower() if isinstance(domain, str) else ""
    if not text:
        return None
    try:
        host = urllib.parse.urlsplit(text if "//" in text else "https://" + text).hostname or ""
    except ValueError:
        return None
    host = host.removeprefix("www.")
    return host if len(host) <= 253 and _SITE.match(host) else None


class _SameHost(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only to the host the request went to."""
    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: urllib.request.Request, fp: IO[bytes], code: int, msg: str, headers: Any,
                         newurl: str) -> urllib.request.Request | None:
        return None


def _open(req: urllib.request.Request, limit: int, redirects: urllib.request.HTTPRedirectHandler) -> tuple[bytes, str]:
    try:
        with tls.urlopen(req, timeout=TIMEOUT, allow_http=HOSTS.allow_http, handlers=(redirects,)) as resp:
            return resp.read(limit + 1), (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.HTTPError as e:
        e.close()
        if e.code in (401, 402, 403):
            raise Refused("Logo.dev refused the key (check it is the right kind, and that your plan includes this)") from None
        if e.code == 404:
            raise FileNotFoundError from None
        raise Unavailable(f"Logo.dev answered HTTP {e.code}") from None
    except (urllib.error.URLError, OSError, ValueError):   # (not what it says: the address holds the key)
        raise Unavailable("Logo.dev couldn't be reached") from None


def fetch(token: str, name: str | None = None, domain: str | None = None) -> tuple[bytes, str] | None:
    """The logo of a brand by its website, else by its name, as (image, content type); None when Logo.dev knows no such
    brand. Raises Refused or Unavailable when it couldn't be asked, so a failure is never taken for "no such brand"."""
    if domain is not None:
        path = site(domain)
    else:
        words = " ".join((name or "").split())
        path = "name/" + urllib.parse.quote(words, safe="") if words else None
    if not path:
        return None
    query = urllib.parse.urlencode({"token": token, "size": SIZE, "format": "png", "fallback": 404})
    req = urllib.request.Request(f"{HOSTS.images}/{path}?{query}", headers={"User-Agent": "Waypoint", "Accept": "image/png,image/*"})
    try:
        data, ctype = _open(req, MAX_LOGO, _SameHost())
    except FileNotFoundError:
        return None
    if ctype not in TYPES or not data or len(data) > MAX_LOGO:
        raise Unavailable("Logo.dev answered with something that isn't an image")
    return data, ctype


def search(secret: str, name: str) -> list[dict[str, str]]:
    """Brand Search for a name: [{name, domain}], best first. Raises Refused or Unavailable."""
    req = urllib.request.Request(f"{HOSTS.search}?{urllib.parse.urlencode({'q': name})}", headers={
        "Authorization": f"Bearer {secret}", "Accept": "application/json", "User-Agent": "Waypoint"})
    try:
        data, _ = _open(req, 512 * 1024, _NoRedirects())
        found = json.loads(data)
    except FileNotFoundError:
        return []
    except ValueError:
        raise Unavailable("Logo.dev answered with something that isn't a list of brands") from None
    items = found if isinstance(found, list) else (found.get("results") or found.get("data") or []) if isinstance(found, dict) else []
    out: list[dict[str, str]] = []
    for item in items[:10]:
        domain = site(item.get("domain")) if isinstance(item, dict) else None
        if domain:
            out.append({"name": str(item.get("name") or "")[:100], "domain": domain})
    return out
