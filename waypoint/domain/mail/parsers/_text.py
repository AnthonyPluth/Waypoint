"""Shared by the parsers: an HTML email as lines of text. Not a parser itself (the fleet check skips `_` modules)."""
from __future__ import annotations

import re
from html.parser import HTMLParser

BLOCKS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "section", "hr"}
CELLS = {"td", "th"}   # (a table row's cells stay on one line)
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
    """The message's visible text, one non-empty line each, whitespace collapsed: the HTML part's if there is one, else the
    plain part's."""
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
