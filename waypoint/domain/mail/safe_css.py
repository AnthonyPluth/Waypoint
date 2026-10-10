from __future__ import annotations

import re
from collections.abc import Callable
from html import escape

MAX_STYLE = 2_000
MAX_DECLARATIONS = 40
MAX_NAMES = 6

LENGTH = re.compile(r"-?(?:\d{1,4}(?:\.\d{1,3})?|\.\d{1,3})(?:px|em|rem|%|pt|ex|ch)?")
NUMBER = re.compile(r"\d{1,3}(?:\.\d{1,3})?")
HEX = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
FUNCTION = re.compile(r"(?:rgb|rgba|hsl|hsla)\(\s*[\d.]+%?(?:\s*,\s*[\d.]+%?){2,3}\s*\)|(?:rgb|rgba|hsl|hsla)\(\s*[\d.]+%?(?:deg)?(?:\s+[\d.]+%?){2}(?:\s*/\s*[\d.]+%?)?\s*\)")
WORD = re.compile(r"[a-zA-Z]{3,24}")
FONT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}")
SIZES = {"xx-small", "x-small", "small", "medium", "large", "x-large", "xx-large", "smaller", "larger"}
BORDER_STYLES = {"none", "solid", "dashed", "dotted", "double", "groove", "ridge", "inset", "outset", "hidden"}
SIDES = ("top", "right", "bottom", "left")
Check = Callable[[str], str | None]


def length(value: str) -> str | None:
    return value if LENGTH.fullmatch(value) else None


def color(value: str) -> str | None:
    return value if HEX.fullmatch(value) or FUNCTION.fullmatch(value) or WORD.fullmatch(value) else None


def one_of(*allowed: str) -> Check:
    names = frozenset(allowed)
    return lambda value: value.lower() if value.lower() in names else None


def each(check: Check, least: int = 1, most: int = 4, extra: tuple[str, ...] = ()) -> Check:
    def run(value: str) -> str | None:
        tokens = value.split()
        if not least <= len(tokens) <= most:
            return None
        kept: list[str] = []
        for token in tokens:
            got = token.lower() if token.lower() in extra else check(token)
            if got is None:
                return None
            kept.append(got)
        return " ".join(kept)
    return run


def sized(value: str) -> str | None:
    return length(value) or (value.lower() if value.lower() in ("auto", "none") else None)


def font_size(value: str) -> str | None:
    return length(value) or (value.lower() if value.lower() in SIZES else None)


def font_family(value: str) -> str | None:
    names = [n.strip().strip("'\"").strip() for n in value.split(",")]
    if not 1 <= len(names) <= MAX_NAMES or not all(FONT_NAME.fullmatch(n) for n in names):
        return None
    return ", ".join(f"'{n}'" if " " in n else n for n in names)


def line_height(value: str) -> str | None:
    return length(value) or (value if NUMBER.fullmatch(value) else None) or ("normal" if value.lower() == "normal" else None)


def weight(value: str) -> str | None:
    return value.lower() if value.lower() in ("normal", "bold", "bolder", "lighter") or re.fullmatch(r"[1-9]00", value) else None


def border(value: str) -> str | None:
    tokens = value.split()
    if not 1 <= len(tokens) <= 3:
        return None
    kept: list[str] = []
    for token in tokens:
        got = token.lower() if token.lower() in BORDER_STYLES else length(token) or color(token)
        if got is None:
            return None
        kept.append(got)
    return " ".join(kept)


def opacity(value: str) -> str | None:
    return value if re.fullmatch(r"(?:0(?:\.\d{1,3})?|1(?:\.0{1,3})?)", value) else None


def background(value: str) -> str | None:
    return "none" if value.lower() == "none" else color(value)


PROPERTIES: dict[str, Check] = {
    "color": color, "background-color": color, "background": background,
    "font-family": font_family, "font-size": font_size, "font-weight": weight,
    "font-style": one_of("normal", "italic", "oblique"),
    "text-align": one_of("left", "right", "center", "justify", "start", "end"),
    "text-decoration": each(one_of("none", "underline", "line-through", "overline"), 1, 3),
    "text-transform": one_of("none", "uppercase", "lowercase", "capitalize"),
    "text-indent": length, "line-height": line_height, "letter-spacing": lambda v: length(v) or ("normal" if v.lower() == "normal" else None),
    "white-space": one_of("normal", "nowrap", "pre", "pre-wrap", "pre-line"),
    "vertical-align": one_of("baseline", "top", "middle", "bottom", "text-top", "text-bottom", "sub", "super"),
    "display": one_of("none", "block", "inline", "inline-block", "table", "table-row", "table-cell"),
    "width": sized, "min-width": sized, "max-width": sized, "height": sized, "min-height": sized,
    "border": border, "border-collapse": one_of("collapse", "separate"), "border-spacing": each(length, 1, 2),
    "border-radius": each(length, 1, 4), "border-color": each(color, 1, 4), "border-style": each(one_of(*BORDER_STYLES), 1, 4),
    "border-width": each(length, 1, 4), "opacity": opacity,
    "list-style-type": one_of("none", "disc", "circle", "square", "decimal", "lower-alpha", "upper-alpha", "lower-roman", "upper-roman"),
    "margin": each(length, 1, 4, ("auto",)), "padding": each(length, 1, 4),
}
for _side in SIDES:
    PROPERTIES[f"margin-{_side}"] = each(length, 1, 1, ("auto",))
    PROPERTIES[f"padding-{_side}"] = each(length, 1, 1)
    PROPERTIES[f"border-{_side}"] = border
    PROPERTIES[f"border-{_side}-width"] = length
    PROPERTIES[f"border-{_side}-color"] = color
    PROPERTIES[f"border-{_side}-style"] = one_of(*BORDER_STYLES)


def declarations(style: str | None) -> list[tuple[str, str]]:
    if not style or len(style) > MAX_STYLE:
        return []
    kept: list[tuple[str, str]] = []
    for part in style.split(";")[:MAX_DECLARATIONS]:
        name, colon, raw = part.partition(":")
        name = name.strip().lower()
        value = re.sub(r"\s*!\s*important\s*$", "", raw.strip(), flags=re.I)
        check = PROPERTIES.get(name)
        if not colon or check is None or not value or re.search(r"[\\<>@{}]|/\*|\*/|url|expression|image|var\(|attr\(|calc|env\(|\bimport\b", value, re.I):
            continue
        cleaned = check(value)
        if cleaned:
            kept.append((name, cleaned))
    return kept


def attribute(pairs: list[tuple[str, str]]) -> str:
    shown = "; ".join(f"{name}: {value}" for name, value in dict(pairs).items())
    return f' style="{escape(shown, quote=True)}"' if shown else ""
