"""The actions on a booking's card: open it in the provider's app, directions, call. Each is a link built here, from a
booking's own fields, so the web app only draws them. (Wallet needs none: `shoebox://` opens Wallet itself.)"""
from __future__ import annotations

import re
from typing import TypedDict
from urllib.parse import quote, urlsplit

# Provider name (lower case, as `key` makes it) -> (the provider's own host, a path and query with {code} and {name}).
# An entry goes in only when the URL is confirmed from the provider's public site; a provider without one has no
# prefilled link and falls back to the booking's own manage link, when it has one. Each entry needs a test in
# tests/test_links.py that builds the URL for a sample booking (tools/fleet_checks.py checks).
MANAGE: dict[str, tuple[str, str]] = {}

DIGITS = re.compile(r"\d")


class Links(TypedDict):
    app: str | None          # the provider's manage-trip page: its app opens it if installed, the website if not
    directions: str | None   # Apple Maps, to the hotel or the rental desk
    call: str | None         # tel: the provider's number


def key(provider: str | None) -> str:
    return " ".join((provider or "").casefold().split())


def manage_link(provider: str | None, confirmation: str | None, last_name: str | None) -> str | None:
    """The provider's manage-trip URL for this booking: https, on the provider's own host, with the code and name
    URL-encoded; None for a provider with no entry or a booking without what the template needs."""
    entry = MANAGE.get(key(provider))
    if not entry:
        return None
    host, path = entry
    if ("{code}" in path and not confirmation) or ("{name}" in path and not last_name):
        return None
    return f"https://{host}{path.format(code=quote(confirmation or '', safe=''), name=quote(last_name or '', safe=''))}"


def https_only(url: str | None) -> str | None:
    """A link a person or an email supplied, kept only if it's https with a host (never javascript: or the like)."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    return url.strip() if parts.scheme == "https" and parts.hostname else None


def directions_link(place: str | None) -> str | None:
    place = " ".join((place or "").split())
    return f"https://maps.apple.com/?q={quote(place, safe='')}" if place else None


def call_link(phone: str | None) -> str | None:
    """tel: with the digits (and a leading +) of a number as printed; None if it has fewer than 3."""
    phone = (phone or "").strip()
    digits = "".join(DIGITS.findall(phone))
    if len(digits) < 3:
        return None
    return "tel:" + ("+" if phone.startswith("+") else "") + digits


def segment_links(kind: str, provider: str | None, confirmation: str | None, last_name: str | None, manage_url: str | None,
                  details: dict[str, str], origin: str | None) -> Links:
    stay = kind in ("hotel", "car")
    return {"app": manage_link(provider, confirmation, last_name) or https_only(manage_url),
            "directions": directions_link(details.get("address") or origin) if stay else None,
            "call": call_link(details.get("phone"))}
