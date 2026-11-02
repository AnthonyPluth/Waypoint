from __future__ import annotations

import re
from collections.abc import Iterable
from html.parser import HTMLParser
from urllib.parse import urlsplit

LIMIT = 2000
TEXT_LIMIT = 80
OPENS = re.compile(r"^(?:manage|view|see|modify|change|review|access|open|retrieve|find|check|go to)\b", re.IGNORECASE)
BOOKING = re.compile(r"\b(?:booking|reservation|trip|itinerary|stay|parking pass|rental|voyage|cruise|sailing|ticket)s?\b", re.IGNORECASE)
NOT_THIS = re.compile(r"unsubscribe|preferences|privacy|terms|receipt|invoice|survey|feedback|refer|download|statement|points|rewards|account", re.IGNORECASE)


class _Anchors(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "a":
            self._href, self._text = a.get("href", "").strip(), []
        elif tag == "img" and self._href is not None:
            self._text.append(a.get("alt", ""))

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.found.append((" ".join(" ".join(self._text).split())[:TEXT_LIMIT], self._href))
            self._href = None


def _usable(href: str) -> bool:
    parts = urlsplit(href)
    return parts.scheme == "https" and bool(parts.hostname) and len(href) <= LIMIT


def manage_link(htmls: Iterable[str]) -> str | None:
    for html in htmls:
        scanner = _Anchors()
        try:
            scanner.feed(html)
            scanner.close()
        except (ValueError, RecursionError, AssertionError):
            continue
        for text, href in scanner.found:
            if OPENS.match(text) and BOOKING.search(text) and not NOT_THIS.search(f"{text} {href}") and _usable(href):
                return href
    return None
