from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

KEEP = {"p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s", "small", "sub", "sup", "blockquote", "pre", "code",
        "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd", "table", "thead", "tbody", "tfoot", "tr", "td", "th",
        "caption", "a", "center", "font", "section", "article", "header", "footer", "main", "aside", "figure", "figcaption",
        "address", "colgroup"}
VOID = {"br", "hr"}
DROP = {"script", "style", "head", "title", "template", "noscript", "iframe", "object", "embed", "svg", "math", "select",
        "textarea", "button", "audio", "video", "canvas", "applet", "frameset"}
SCHEMES = {"https", "mailto"}
MAX_DEPTH = 40
MARKUP_LIMIT = 900_000
TITLE_LIMIT = 300
SPAN = re.compile(r"[1-9]\d?")
SIZE = re.compile(r"\d{1,4}%?")
COUNT = re.compile(r"\d{1,3}")
COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}|(?:rgb|hsl)a?\([\d\s.,%/-]{1,40}\)")
LENGTH = re.compile(r"\d{1,4}(?:\.\d{1,3})?(?:px|em|rem|pt|ex|ch|%)?")
LENGTHS = re.compile(rf"(?:{LENGTH.pattern}|auto)(?:\s+(?:{LENGTH.pattern}|auto)){{0,3}}")
FAMILY_NAME = r"(?:'[\w \-]{1,40}'|\"[\w \-]{1,40}\"|[\w\- ]{1,40})"
FAMILY = re.compile(rf"{FAMILY_NAME}(?:\s*,\s*{FAMILY_NAME}){{0,9}}")
FONT_FACE = re.compile(r"[\w\- ,]{1,80}")
BORDER_STYLES = {"none", "solid", "dashed", "dotted", "double", "hidden", "groove", "ridge", "inset", "outset"}
KEYWORDS = {
    "text-align": {"left", "right", "center", "justify", "start", "end"},
    "vertical-align": {"top", "middle", "bottom", "baseline", "text-top", "text-bottom", "sub", "super"},
    "font-weight": {"normal", "bold", "bolder", "lighter", *(str(n) for n in range(100, 1000, 100))},
    "font-style": {"normal", "italic", "oblique"},
    "text-decoration": {"none", "underline", "line-through", "overline"},
    "text-transform": {"none", "uppercase", "lowercase", "capitalize"},
    "white-space": {"normal", "nowrap", "pre", "pre-wrap", "pre-line"},
    "border-collapse": {"collapse", "separate"},
    "display": {"none", "block", "inline", "inline-block", "table", "table-row", "table-cell"},
    "word-break": {"normal", "break-all", "break-word", "keep-all"},
    "list-style-type": {"disc", "circle", "square", "decimal", "none", "lower-alpha", "upper-alpha", "lower-roman",
                        "upper-roman"},
    "border-style": BORDER_STYLES,
    "font-size": {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large", "smaller", "larger"},
    "width": {"auto"}, "height": {"auto"}, "max-width": {"none"}, "line-height": {"normal"},
}
SIDES = ("top", "right", "bottom", "left")
COLORS = {"color", "background-color", "border-color", *(f"border-{side}-color" for side in SIDES)}
LENGTH_PROPERTIES = {
    "width", "height", "max-width", "min-width", "min-height", "max-height", "font-size", "line-height", "letter-spacing",
    "text-indent", "border-width", "border-radius", "border-spacing", "padding", "margin",
    *(f"{box}-{side}" for box in ("padding", "margin") for side in SIDES),
    *(f"border-{side}-width" for side in SIDES),
}
BORDERS = {"border", *(f"border-{side}" for side in SIDES)}
ALIGN = {"left", "right", "center", "justify"}
VALIGN = {"top", "middle", "bottom", "baseline"}
Resolve = Callable[[str], int | None]


def safe_declaration(name: str, value: str) -> str | None:
    name = name.strip().lower()
    value = re.sub(r"\s*!\s*important$", "", value.strip(), flags=re.I).strip()
    lowered = value.lower()
    if not value or len(value) > 200:
        return None
    if name in COLORS or name == "background":
        return f"{'background-color' if name == 'background' else name}:{value}" if COLOR.fullmatch(value) else None
    if name in KEYWORDS and lowered in KEYWORDS[name]:
        return f"{name}:{lowered}"
    if name in LENGTH_PROPERTIES and LENGTHS.fullmatch(lowered):
        return f"{name}:{lowered}"
    if name == "font-family" and FAMILY.fullmatch(value):
        return f"{name}:{value}"
    if name in BORDERS:
        parts = value.split()
        if 1 <= len(parts) <= 3 and all(LENGTH.fullmatch(p) or p.lower() in BORDER_STYLES or COLOR.fullmatch(p) for p in parts):
            return f"{name}:{value}"
    return None


def safe_style(value: str | None) -> str:
    kept = []
    for declaration in (value or "")[:4000].split(";"):
        name, colon, text = declaration.partition(":")
        found = safe_declaration(name, text) if colon else None
        if found:
            kept.append(found)
    return ";".join(kept)


def safe_href(value: str | None) -> str | None:
    href = re.sub(r"[\x00-\x20\x7f-\x9f]", "", value or "")
    try:
        parts = urlsplit(href)
    except ValueError:
        return None
    if parts.scheme.lower() not in SCHEMES or (parts.scheme.lower() == "https" and not parts.netloc):
        return None
    return href


def _quoted(name: str, value: str) -> str:
    return f' {name}="{escape(value, quote=True)}"'


class _Clean(HTMLParser):
    def __init__(self, limit: int, resolve: Resolve | None = None, markup_limit: int = MARKUP_LIMIT) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[tuple[str, bool]] = []
        self.counts: Counter[str] = Counter()
        self.skip: list[str] = []
        self.limit = limit
        self.resolve = resolve
        self.markup_limit = markup_limit
        self.written = 0
        self.size = 0
        self.cut = False
        self.body_shown = False

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
            self._image(dict(attrs))
        elif tag == "body":
            if not self.body_shown and not self.cut and (found := self._attributes("div", dict(attrs))):
                self.body_shown = True
                self._put(f"<div{found}>")
                self.open.append(("div", True))
                self.counts["div"] += 1
        elif tag in KEEP and not self.cut:
            if tag in VOID:
                self._put(f"<{tag}>")
            else:
                shown = len(self.open) < MAX_DEPTH
                if shown:
                    self._put(f"<{tag}{self._attributes(tag, dict(attrs))}>")
                self.open.append((tag, shown))
                self.counts[tag] += 1

    def _put(self, markup: str) -> None:
        if self.cut:
            return
        self.written += len(markup)
        if self.written > self.markup_limit:
            self.cut = True
            return
        self.out.append(markup)

    def _image(self, attrs: dict[str, str | None]) -> None:
        source = (attrs.get("src") or "").strip()
        found = self.resolve(source) if self.resolve and source and not self.cut else None
        alt = (attrs.get("alt") or "").strip()
        if found is None:
            if alt:
                self.handle_data(alt + " ")
            return
        shown = "".join(_quoted(name, value) for name in ("width", "height")
                        if (value := (attrs.get(name) or "").strip().removesuffix("px")) and SIZE.fullmatch(value))
        style = safe_style(attrs.get("style"))
        self._put(f'<img data-i="{found}"{_quoted("alt", alt)}{shown}{_quoted("style", style) if style else ""}>')

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
        if tag == "body":
            if not self.body_shown:
                return
            self.body_shown = False
            tag = "div"
        if self.counts[tag]:
            while self.open:
                last, shown = self.open.pop()
                self.counts[last] -= 1
                if shown:
                    self.written += len(last) + 3
                    self.out.append(f"</{last}>")
                if last == tag:
                    break

    def handle_data(self, data: str) -> None:
        if self.skip or self.cut:
            return
        room = self.limit - self.size
        over = len(data) > room
        data = data[:max(room, 0)] if over else data
        self.size += len(data)
        self._put(escape(data, quote=False))
        self.cut = self.cut or over

    @staticmethod
    def _attributes(tag: str, attrs: dict[str, str | None]) -> str:
        def word(name: str, allowed: set[str]) -> str:
            value = (attrs.get(name) or "").strip().lower()
            return _quoted(name, value) if value in allowed else ""

        def matching(name: str, pattern: re.Pattern[str]) -> str:
            value = (attrs.get(name) or "").strip().removesuffix("px")
            return _quoted(name, value) if pattern.fullmatch(value) else ""

        def colour(name: str, into: str) -> str:
            value = (attrs.get(name) or "").strip()
            return f";{into}:{value}" if COLOR.fullmatch(value) else ""

        style = safe_style(attrs.get("style"))
        if tag == "a":
            href = safe_href(attrs.get("href"))
            if not href:
                return _quoted("style", style) if style else ""
            return (f'{_quoted("href", href)} target="_blank" rel="noopener noreferrer"{_quoted("title", href[:TITLE_LIMIT])}'
                    f'{_quoted("style", style) if style else ""}')
        out = ""
        if tag == "font":
            style = ";".join(filter(None, [style, colour("color", "color").lstrip(";")]))
            face = (attrs.get("face") or "").strip()
            if FONT_FACE.fullmatch(face):
                style = ";".join(filter(None, [style, f"font-family:{face}"]))
        if tag in ("table", "td", "th", "tr", "tbody", "thead", "tfoot", "div", "p", "center", "caption", "h1", "h2", "h3", "h4", "h5", "h6"):
            out += word("align", ALIGN)
        if tag in ("td", "th", "tr", "tbody", "thead", "tfoot"):
            out += word("valign", VALIGN)
        if tag in ("td", "th"):
            out += "".join(f' {name}="{value}"' for name in ("colspan", "rowspan") if (value := (attrs.get(name) or "").strip()) and SPAN.fullmatch(value))
        if tag in ("table", "td", "th", "col", "colgroup"):
            out += matching("width", SIZE)
        if tag in ("table", "td", "th", "tr"):
            out += matching("height", SIZE)
        if tag == "table":
            out += matching("border", COUNT) + matching("cellpadding", COUNT) + matching("cellspacing", COUNT)
        if tag in ("table", "td", "th", "tr", "tbody", "thead", "tfoot", "div"):
            style = ";".join(filter(None, [colour("bgcolor", "background-color").lstrip(";"), style]))
        return out + (_quoted("style", style) if style else "")


def clean_counted(html: str, limit: int, resolve: Resolve | None = None, markup_limit: int = MARKUP_LIMIT) -> tuple[str, bool, int]:
    parser = _Clean(limit, resolve, markup_limit)
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
