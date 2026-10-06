from __future__ import annotations

import re
from typing import TypedDict
from urllib.parse import quote, urlsplit

MANAGE: dict[str, tuple[str, str]] = {}

DIGITS = re.compile(r"\d")


class Links(TypedDict):
    app: str | None
    directions: str | None
    call: str | None


def key(provider: str | None) -> str:
    return " ".join((provider or "").casefold().split())


def manage_link(provider: str | None, confirmation: str | None, last_name: str | None) -> str | None:
    entry = MANAGE.get(key(provider))
    if not entry:
        return None
    host, path = entry
    if ("{code}" in path and not confirmation) or ("{name}" in path and not last_name):
        return None
    return f"https://{host}{path.format(code=quote(confirmation or '', safe=''), name=quote(last_name or '', safe=''))}"


def https_only(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    return url.strip() if parts.scheme == "https" and parts.hostname else None


def directions_link(place: str | None) -> str | None:
    place = " ".join((place or "").split())
    return f"https://maps.apple.com/?q={quote(place, safe='')}" if place else None


def call_link(phone: str | None) -> str | None:
    phone = (phone or "").strip()
    digits = "".join(DIGITS.findall(phone))
    if len(digits) < 3:
        return None
    return "tel:" + ("+" if phone.startswith("+") else "") + digits


def segment_links(kind: str, provider: str | None, confirmation: str | None, last_name: str | None, manage_url: str | None,
                  details: dict[str, str], origin: str | None) -> Links:
    stay = kind in ("hotel", "car", "cruise")
    return {"app": manage_link(provider, confirmation, last_name) or https_only(manage_url),
            "directions": directions_link(details.get("address") or origin) if stay else None,
            "call": call_link(details.get("phone"))}
