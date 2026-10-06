from __future__ import annotations

import re
from collections import Counter
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

KEEP = {"p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s", "small", "sub", "sup", "blockquote", "pre", "code",
        "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "caption", "a", "center", "font"}
VOID = {"br", "hr"}
DROP = {"script", "style", "head", "title", "template", "noscript", "iframe", "object", "embed", "svg", "math", "select",
        "textarea", "button", "audio", "video", "canvas", "applet", "frameset"}
SCHEMES = {"https", "mailto"}
MAX_DEPTH = 40
SPAN = re.compile(r"[1-9]\d?")


def safe_href(value: str | None) -> str | None:
    href = re.sub(r"[\x00-\x20\x7f-\x9f]", "", value or "")
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.scheme.lower() not in SCHEMES or (parts.scheme.lower() == "https" and not parts.netloc):
        return None
    return href


class _Clean(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[tuple[str, bool]] = []
        self.counts: Counter[str] = Counter()
        self.skip: list[str] = []
        self.limit = limit
        self.size = 0
        self.cut = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "body" and self.skip and self.skip[0] == "head":
            self.skip.clear()
        if self.skip:
            if tag in DROP and tag not in VOID:
                self.skip.append(tag)
            return
        if tag in DROP:
            self.skip.append(tag)
        elif tag == "img":
            alt = next((v for k, v in attrs if k == "alt" and v), None)
            if alt:
                self.handle_data(alt.strip() + " ")
        elif tag in KEEP and not self.cut:
            if tag in VOID:
                self.out.append(f"<{tag}>")
            else:
                shown = len(self.open) < MAX_DEPTH
                if shown:
                    self.out.append(f"<{tag}{self._attributes(tag, dict(attrs))}>")
                self.open.append((tag, shown))
                self.counts[tag] += 1

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if tag in DROP and not self.skip:
            return
        self.handle_starttag(tag, attrs)
        if tag in KEEP and tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag in self.skip:
                while self.skip and self.skip.pop() != tag:
                    pass
            return
        if self.counts[tag]:
            while self.open:
                last, shown = self.open.pop()
                self.counts[last] -= 1
                if shown:
                    self.out.append(f"</{last}>")
                if last == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self.skip or self.cut:
            return
        room = self.limit - self.size
        if len(data) > room:
            data, self.cut = data[:max(room, 0)], True
        self.size += len(data)
        self.out.append(escape(data, quote=False))

    @staticmethod
    def _attributes(tag: str, attrs: dict[str, str | None]) -> str:
        if tag == "a":
            href = safe_href(attrs.get("href"))
            return f' href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer"' if href else ""
        if tag in ("td", "th"):
            return "".join(f' {name}="{value}"' for name in ("colspan", "rowspan") if (value := (attrs.get(name) or "").strip()) and SPAN.fullmatch(value))
        return ""


def clean_counted(html: str, limit: int) -> tuple[str, bool, int]:
    parser = _Clean(limit)
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, RecursionError, AssertionError):
        pass
    while parser.open:
        last, shown = parser.open.pop()
        if shown:
            parser.out.append(f"</{last}>")
    return "".join(parser.out), parser.cut, parser.size


def clean(html: str, limit: int) -> tuple[str, bool]:
    markup, cut, _size = clean_counted(html, limit)
    return markup, cut
