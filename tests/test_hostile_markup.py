from __future__ import annotations

import json
import re
import time
import unittest
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from tests import hostile_markup
from waypoint.domain.mail import safe_html

TAGS = safe_html.KEEP | {"img"}
ATTRIBUTES = {"href", "target", "rel", "title", "style", "align", "valign", "colspan", "rowspan", "width", "height", "border",
              "cellpadding", "cellspacing", "alt", "data-i"}
PROPERTIES = (set(safe_html.KEYWORDS) | safe_html.COLORS | safe_html.LENGTH_PROPERTIES | safe_html.BORDERS
              | {"font-family", "background-color"})
FORBIDDEN_IN_STYLE = ("url(", "expression", "@", "\\", "/*", "var(", "--", "javascript", "binding", "behavior")


class Inspect(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag not in TAGS:
            self.problems.append(f"tag {tag}")
        found = dict(attrs)
        for name, value in attrs:
            if name not in ATTRIBUTES:
                self.problems.append(f"attribute {name}")
            if name == "style":
                self.inspect_style(value or "")
        if tag == "a" and "href" in found:
            scheme = urlsplit(found["href"] or "").scheme.lower()
            if scheme not in safe_html.SCHEMES:
                self.problems.append(f"link scheme {scheme}")
            if found.get("target") != "_blank" or found.get("rel") != "noopener noreferrer":
                self.problems.append("link opens the app or keeps the opener")
        if tag == "img" and not re.fullmatch(r"\d{1,3}", found.get("data-i") or ""):
            self.problems.append("image without a kept picture")

    def inspect_style(self, value: str) -> None:
        lowered = value.lower()
        for text in FORBIDDEN_IN_STYLE:
            if text in lowered:
                self.problems.append(f"style has {text}")
        for declaration in filter(None, value.split(";")):
            if declaration.partition(":")[0].strip() not in PROPERTIES:
                self.problems.append(f"style property {declaration.partition(':')[0]}")

    def handle_startendtag(self, tag: str, attrs: Any) -> None:
        self.handle_starttag(tag, attrs)


def problems(markup: str) -> list[str]:
    parser = Inspect()
    parser.feed(markup)
    parser.close()
    return parser.problems


def keeps_the_first_picture(src: str) -> int | None:
    return 0 if src.startswith("x") else None


class HostileMarkup(unittest.TestCase):
    def test_the_corpus_covers_each_kind_of_payload_the_issue_names(self):
        names = " ".join(p["name"] for p in hostile_markup.build()).lower()
        for kind in ("script", "handler", "javascript", "data link", "style block", "import", "expression", "svg", "onerror",
                     "nested forms", "deeply nested", "huge", "noscript", "math"):
            with self.subTest(kind=kind):
                self.assertIn(kind, names)

    def test_every_payload_comes_out_inert_and_without_its_canary(self):
        for found in hostile_markup.build():
            for label, resolve in (("without pictures", None), ("with pictures", keeps_the_first_picture)):
                with self.subTest(payload=found["name"], pictures=label):
                    started = time.monotonic()
                    out = safe_html.clean_counted(found["html"], 200_000, resolve)[0]
                    self.assertLess(time.monotonic() - started, 3)
                    self.assertEqual(problems(out), [])
                    self.assertNotIn(found["canary"], out)

    def test_no_payload_leaves_a_script_a_handler_or_an_address_that_loads(self):
        for found in hostile_markup.build():
            with self.subTest(payload=found["name"]):
                out = safe_html.clean(found["html"], 200_000)[0]
                self.assertNotRegex(out, r"(?i)<(script|style|iframe|object|embed|svg|math|form|input|button|link|meta|base)\b")
                self.assertNotIn("javascript:", out.lower())
                self.assertNotIn("data:", out.lower())
                self.assertNotRegex(out, r"http://")

    def test_nesting_and_size_stay_bounded(self):
        for found in hostile_markup.build():
            with self.subTest(payload=found["name"]):
                out = safe_html.clean(found["html"], 200_000)[0]
                self.assertLessEqual(len(out), safe_html.MARKUP_LIMIT + 1000)
                depth = deepest = 0
                for match in re.finditer(r"<(/?)([a-z0-9]+)", out):
                    if match.group(2) in safe_html.VOID or match.group(2) == "img":
                        continue
                    depth += -1 if match.group(1) else 1
                    deepest = max(deepest, depth)
                self.assertLessEqual(deepest, safe_html.MAX_DEPTH)

    def test_the_inspection_itself_catches_what_a_naive_cleaner_would_leave(self):
        for markup, expected in (("<script>x</script>", "tag script"), ("<p onclick='x'>a</p>", "attribute onclick"),
                                 ('<a href="javascript:x" target="_blank" rel="noopener noreferrer">a</a>', "link scheme javascript"),
                                 ('<a href="https://example.com">a</a>', "link opens the app or keeps the opener"),
                                 ('<p style="background:url(https://evil.example/x)">a</p>', "style has url("),
                                 ('<p style="position:fixed">a</p>', "style property position"),
                                 ('<img src="https://evil.example/x.gif">', "attribute src")):
            with self.subTest(markup=markup):
                self.assertIn(expected, problems(markup))

    def test_the_frontend_corpus_is_current(self):
        stored = json.loads(hostile_markup.CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(stored, hostile_markup.corpus(), "regenerate it with: poetry run python -m tests.hostile_markup")


if __name__ == "__main__":
    unittest.main()
