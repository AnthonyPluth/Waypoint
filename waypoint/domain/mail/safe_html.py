from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from . import safe_css

KEEP = {"p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s", "small", "sub", "sup", "blockquote", "pre", "code",
        "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "caption", "a", "center", "font"}
LAYOUT = {"body", "section", "article", "header", "footer", "main", "nav", "aside", "figure", "figcaption", "abbr", "cite", "mark",
          "del", "ins", "strike", "big", "tt", "address", "colgroup", "col"}
VOID = {"br", "hr", "col", "embed"}
DROP = {"script", "style", "head", "title", "template", "noscript", "iframe", "object", "embed", "svg", "math", "select",
        "textarea", "button", "audio", "video", "canvas", "applet", "frameset"}
SCHEMES = {"https", "mailto"}
MAX_DEPTH = 40
SPAN = re.compile(r"[1-9]\d?")
SIZE = re.compile(r"\d{1,4}(?:px|%)?")
COUNT = re.compile(r"\d{1,3}")
FONT_SIZES = {"1": "x-small", "2": "small", "3": "medium", "4": "large", "5": "x-large", "6": "xx-large", "7": "xx-large"}
TINY = 2
MAX_LINK = 2_000

Resolve = Callable[[str], int | None]


def safe_href(value: str | None) -> str | None:
    href = re.sub(r"[\x00-\x20\x7f-\x9f]", "", value or "")
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.scheme.lower() not in SCHEMES or (parts.scheme.lower() == "https" and not parts.netloc):
        return None
    return href


def _pixels(value: str | None) -> int | None:
    found = re.fullmatch(r"\s*(\d{1,4})(?:px)?\s*", value or "")
    return int(found.group(1)) if found else None


class _Clean(HTMLParser):
    def __init__(self, limit: int, resolve: Resolve | None = None, markup_limit: int | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[tuple[str, bool]] = []
        self.counts: Counter[str] = Counter()
        self.skip: list[str] = []
        self.limit = limit
        self.size = 0
        self.cut = False
        self.resolve = resolve
        self.rich = resolve is not None
        self.keep = KEEP | LAYOUT if self.rich else KEEP
        self.markup_limit = markup_limit
        self.markup = 0

    def _emit(self, piece: str) -> None:
        self.out.append(piece)
        self.markup += len(piece)
        if self.markup_limit is not None and self.markup > self.markup_limit:
            self.cut = True

    def _alt(self, attrs: Any) -> None:
        alt = next((v for k, v in attrs if k == "alt" and v), None)
        if alt:
            self.handle_data(alt.strip() + " ")

    def _image(self, attrs: Any) -> None:
        values = dict(attrs)
        width, height = _pixels(values.get("width")), _pixels(values.get("height"))
        source = (values.get("src") or "").strip()
        index = None
        if self.resolve is not None and source and not (width is not None and width <= TINY) and not (height is not None and height <= TINY):
            index = self.resolve(source)
        if index is None or self.cut:
            self._alt(attrs)
            return
        shown = "".join(f' {name}="{value}"' for name, value in (("width", self._size(values.get("width"))), ("height", self._size(values.get("height")))) if value)
        alt = " ".join((values.get("alt") or "").split())[:300]
        style = safe_css.attribute(safe_css.declarations(values.get("style")))
        self._emit(f'<img data-image="{index}" alt="{escape(alt, quote=True)}"{shown}{style}>')

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "body" and self.skip and self.skip[0] == "head":
            self.skip.clear()
        if self.skip:
            if tag in DROP and tag not in VOID:
                self.skip.append(tag)
            return
        if tag in DROP:
            if tag not in VOID:
                self.skip.append(tag)
        elif tag == "img":
            self._image(attrs)
        elif tag in self.keep and not self.cut:
            if tag in VOID:
                self._emit(f"<{tag}>")
            else:
                shown = len(self.open) < MAX_DEPTH
                if shown:
                    self._emit(f"<{self._name(tag)}{self._attributes(tag, dict(attrs))}>")
                self.open.append((tag, shown))
                self.counts[tag] += 1

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        if tag in DROP and not self.skip:
            return
        self.handle_starttag(tag, attrs)
        if tag in self.keep and tag not in VOID:
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
                    self._emit(f"</{self._name(last)}>")
                if last == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self.skip or self.cut:
            return
        room = self.limit - self.size
        if len(data) > room:
            data, self.cut = data[:max(room, 0)], True
        self.size += len(data)
        self._emit(escape(data, quote=False))

    @staticmethod
    def _name(tag: str) -> str:
        return "div" if tag in ("body", "section", "article", "header", "footer", "main", "nav", "aside", "figure", "address") else tag

    @staticmethod
    def _size(value: str | None) -> str | None:
        found = (value or "").strip().lower()
        return found if SIZE.fullmatch(found) else None

    def _attributes(self, tag: str, attrs: dict[str, str | None]) -> str:
        if tag == "a":
            href = safe_href(attrs.get("href"))
            if not href:
                return ""
            where = f' title="{escape(href[:MAX_LINK], quote=True)}"' if self.rich else ""
            styled = safe_css.attribute(safe_css.declarations(attrs.get("style"))) if self.rich else ""
            return f' href="{escape(href, quote=True)}"{where}{styled} target="_blank" rel="noopener noreferrer"'
        if self.rich:
            return self._styled(tag, attrs)
        if tag in ("td", "th"):
            return "".join(f' {name}="{value}"' for name in ("colspan", "rowspan") if (value := (attrs.get(name) or "").strip()) and SPAN.fullmatch(value))
        return ""

    def _styled(self, tag: str, attrs: dict[str, str | None]) -> str:
        shown = ""
        pairs: list[tuple[str, str]] = []
        if tag in ("td", "th"):
            shown += "".join(f' {name}="{span}"' for name in ("colspan", "rowspan") if (span := (attrs.get(name) or "").strip()) and SPAN.fullmatch(span))
        if tag in ("table", "td", "th", "col", "colgroup"):
            shown += "".join(f' {name}="{dim}"' for name in ("width", "height") if (dim := self._size(attrs.get(name))))
        if tag == "table":
            shown += "".join(f' {name}="{num}"' for name in ("border", "cellpadding", "cellspacing") if (num := (attrs.get(name) or "").strip()) and COUNT.fullmatch(num))
        if tag in ("table", "td", "th", "tr", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "col", "colgroup", "caption", "tbody", "thead", "tfoot", "center", "body"):
            align = (attrs.get("align") or "").strip().lower()
            if align in ("left", "right", "center", "justify"):
                shown += f' align="{align}"'
            valign = (attrs.get("valign") or "").strip().lower()
            if valign in ("top", "middle", "bottom", "baseline"):
                shown += f' valign="{valign}"'
        if (direction := (attrs.get("dir") or "").strip().lower()) in ("ltr", "rtl"):
            shown += f' dir="{direction}"'
        if tag in ("table", "td", "th", "tr", "body", "div", "p", "tbody", "thead", "tfoot") and (bg := safe_css.color((attrs.get("bgcolor") or "").strip())):
            pairs.append(("background-color", bg))
        if tag == "font":
            if tint := safe_css.color((attrs.get("color") or "").strip()):
                pairs.append(("color", tint))
            if (face := safe_css.font_family((attrs.get("face") or "").strip())) is not None:
                pairs.append(("font-family", face))
            if size := FONT_SIZES.get((attrs.get("size") or "").strip()):
                pairs.append(("font-size", size))
        pairs += safe_css.declarations(attrs.get("style"))
        return shown + safe_css.attribute(pairs)


def _run(parser: _Clean, html: str) -> tuple[str, bool, int]:
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, RecursionError, AssertionError):
        pass
    while parser.open:
        last, shown = parser.open.pop()
        if shown:
            parser.out.append(f"</{parser._name(last)}>")
    return "".join(parser.out), parser.cut, parser.size


def clean_counted(html: str, limit: int) -> tuple[str, bool, int]:
    return _run(_Clean(limit), html)


def clean_rich(html: str, limit: int, resolve: Resolve, markup_limit: int | None = None) -> tuple[str, bool, int]:
    return _run(_Clean(limit, resolve, markup_limit), html)


def clean(html: str, limit: int) -> tuple[str, bool]:
    markup, cut, _size = clean_counted(html, limit)
    return markup, cut
