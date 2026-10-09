from __future__ import annotations

import re
from datetime import time
from html.parser import HTMLParser

BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section", "hr"}
CELLS = {"td", "th"}
SKIPPED = {"script", "style", "head", "title"}


class _Lines(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED:
            self._skip += 1
        elif tag in BLOCKS:
            self.out.append("\n")
        elif tag in CELLS:
            self.out.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag in BLOCKS:
            self.out.append("\n")
        elif tag in CELLS:
            self.out.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.out.append(data)


def lines(html: str, text: str) -> list[str]:
    if html.strip():
        scanner = _Lines()
        try:
            scanner.feed(html)
            scanner.close()
        except (ValueError, RecursionError, AssertionError):
            return []
        raw = "".join(scanner.out)
    else:
        raw = text
    return [line for line in (re.sub(r"[ \t\r\f\v\xa0]+", " ", ln).strip() for ln in raw.split("\n")) if line]


def clock(hour: int, minute: int, meridiem: str) -> time | None:
    if not (1 <= hour <= 12 and minute < 60):
        return None
    return time(hour % 12 + (12 if meridiem.upper() == "P" else 0), minute)
