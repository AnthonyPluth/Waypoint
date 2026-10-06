"""An email's HTML rebuilt for the preview (waypoint/domain/mail/safe_html.py): only an allowlist survives, and nothing the sender
wrote is passed through. Invented content."""
import unittest
from unittest import mock

from tests.test_mail_extract import eml, message
from waypoint.domain.mail import extract, safe_html


def clean(html: str, limit: int = 10_000) -> str:
    return safe_html.clean(html, limit)[0]


class Allowed(unittest.TestCase):
    def test_text_headings_lists_and_tables_stay(self):
        html = "<h1>Trip</h1><p>Hello <b>Jane</b></p><ul><li>One</li></ul><table><tr><td colspan='2'>Seat 12A</td></tr></table>"
        self.assertEqual(clean(html), "<h1>Trip</h1><p>Hello <b>Jane</b></p><ul><li>One</li></ul><table><tr><td colspan=\"2\">Seat 12A</td></tr></table>")

    def test_text_is_escaped_and_so_is_text_that_looks_like_markup(self):
        self.assertEqual(clean("<p>a &lt;script&gt;alert(1)&lt;/script&gt; &amp; b</p>"), "<p>a &lt;script&gt;alert(1)&lt;/script&gt; &amp; b</p>")

    def test_unclosed_and_stray_tags_are_closed_or_ignored(self):
        self.assertEqual(clean("</b><p>one<b>two"), "<p>one<b>two</b></p>")

    def test_a_cell_span_is_a_small_number_or_nothing(self):
        self.assertEqual(clean("<td colspan='x' rowspan='99999'>a</td>"), "<td>a</td>")


class Dropped(unittest.TestCase):
    def test_scripts_styles_forms_and_frames_go_with_what_is_inside(self):
        for tag in ("script", "style", "iframe", "button", "object", "svg", "noscript", "template", "title", "head"):
            with self.subTest(tag=tag):
                self.assertEqual(clean(f"<p>a</p><{tag}>EVIL <b>x</b></{tag}><p>b</p>"), "<p>a</p><p>b</p>")

    def test_a_dropped_tag_inside_a_dropped_tag_does_not_end_it_early(self):
        self.assertEqual(clean("<select><select>x</select>EVIL</select>ok"), "ok")

    def test_no_attribute_but_a_links_address_survives(self):
        out = clean('<p style="x" onclick="evil()" class="c" id="i" onmouseover="e()">hi</p><div background="x" style="background:url(http://t.example/p)">d</div>')
        self.assertEqual(out, "<p>hi</p><div>d</div>")

    def test_an_image_becomes_its_alt_text_and_loads_nothing(self):
        out = clean('<p><img src="https://t.example/p.gif" alt="Example Air logo"><img src="x"> hi</p><img src="https://t.example/pixel.gif" width=1>')
        self.assertEqual(out, "<p>Example Air logo  hi</p>")
        self.assertNotIn("t.example", out)
        self.assertNotIn("<img", out)

    def test_a_link_keeps_https_and_mailto_only(self):
        for href, kept in (("https://example.com/a?b=1&c=2", True), ("mailto:help@example.com", True), ("HTTPS://EXAMPLE.COM", True),
                           ("http://example.com", False), ("javascript:alert(1)", False), ("  JaVa\tScRiPt:alert(1)", False),
                           ("data:text/html,<script>1</script>", False), ("//example.com", False), ("/relative", False), ("https:", False), ("", False)):
            with self.subTest(href=href):
                out = clean(f'<a href="{href}">go</a>')
                if kept:
                    self.assertIn('target="_blank" rel="noopener noreferrer"', out)
                    self.assertRegex(out, r'^<a href="[^"]+" target="_blank" rel="noopener noreferrer">go</a>$')
                else:
                    self.assertEqual(out, "<a>go</a>")

    def test_a_quote_in_a_link_cannot_break_out_of_its_attribute(self):
        out = clean('<a href=\'https://example.com/" onmouseover="evil()\'>x</a>')
        self.assertNotIn('" onmouseover', out)
        self.assertIn("&quot;", out)


class Unclosed(unittest.TestCase):
    def test_a_form_around_the_body_keeps_its_text_without_its_controls(self):
        self.assertEqual(clean('<form action="https://t.example"><p>Gate B12</p><input name=x><button>Go</button></form>'), "<p>Gate B12</p>")

    def test_a_head_that_was_never_closed_ends_at_the_body(self):
        self.assertEqual(clean("<html><head><meta name=x><body><p>Gate B12</p></body></html>"), "<p>Gate B12</p>")


class Odd(unittest.TestCase):
    def test_self_closed_tags_are_kept_or_dropped_like_the_others(self):
        self.assertEqual(clean("a<br/>b<hr/><script/>c<b/>d<img alt='x'/>"), "a<br>b<hr>c<b></b>dx ")

    def test_an_address_that_will_not_parse_is_no_link(self):
        self.assertEqual(clean('<a href="https://[bad">x</a>'), "<a>x</a>")

    def test_a_stray_end_tag_inside_a_dropped_one_changes_nothing(self):
        self.assertEqual(clean("<select></b>EVIL</select>ok"), "ok")

    def test_a_parser_that_gives_up_shows_what_it_had(self):
        with mock.patch.object(safe_html._Clean, "feed", side_effect=ValueError):
            self.assertEqual(safe_html.clean("<p>x</p>", 10), ("", False))


class Limits(unittest.TestCase):
    def test_text_is_cut_at_the_limit_and_says_so(self):
        out, cut = safe_html.clean("<p>" + "x" * 100 + "</p><p>more</p>", 20)
        self.assertTrue(cut)
        self.assertEqual(out, "<p>" + "x" * 20 + "</p>")

    def test_a_short_message_is_not_cut(self):
        self.assertFalse(safe_html.clean("<p>hi</p>", 20)[1])

    def test_many_unclosed_tags_then_many_stray_end_tags_stay_fast(self):
        import time
        started = time.monotonic()
        out = clean("<div>" * 50_000 + "</span>" * 50_000 + "x")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(out.count("<div>"), out.count("</div>"))

    def test_nesting_is_bounded_and_garbage_does_not_raise(self):
        out = clean("<div>" * 500 + "deep")
        self.assertLessEqual(out.count("<div>"), safe_html.MAX_DEPTH)
        self.assertEqual(out.count("<div>"), out.count("</div>"))
        self.assertEqual(clean("<div>" * 45 + "deep" + "</div>" * 45).count("</div>"), safe_html.MAX_DEPTH)
        self.assertTrue(clean("<div>" * 45 + "deep" + "</div>" * 45 + "<p>after</p>").endswith("</div><p>after</p>"))   # (the cut-off tags' ends don't close the outer ones early)
        clean("<<>><a href=><td colspan=\"<b>\">&#xZZ; <!-- <p> -->")


class FromAMessage(unittest.TestCase):
    def test_a_messages_html_part_is_cleaned_and_a_text_only_message_has_none(self):
        html = '<html><head><style>p{}</style></head><body><p onclick="x()">Gate <b>B12</b></p><script>evil()</script></body></html>'
        self.assertEqual(extract.safe_markup(message(eml(html))), ("<p>Gate <b>B12</b></p>", False))
        self.assertIsNone(extract.safe_markup(message(eml("Just text", ctype="text/plain"))))
        two = (b"From: a@example.example\nSubject: s\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=B\n\n"
               b"--B\nContent-Type: text/html; charset=utf-8\n\n<p>one</p><script>never closed\n"
               b"--B\nContent-Type: text/html; charset=utf-8\n\n<p>two</p>\n--B--\n")
        self.assertEqual(extract.safe_markup(message(two)), ("<p>one</p><hr><p>two</p>", False))   # (an unclosed script in one part doesn't hide the next)
        self.assertEqual(extract.safe_markup(message(two), 3), ("<p>one</p>", True))
        self.assertEqual(extract.safe_markup(message(eml("<p>one</p>")), 3), ("<p>one</p>", False))   # (exactly the budget, nothing left out)
        amps = two.replace(b"<p>one</p>", b"<p>a&amp;b&lt;c</p>")
        self.assertEqual(extract.safe_markup(message(amps), 7), ("<p>a&amp;b&lt;c</p><hr><p>tw</p>", True))   # (the budget counts characters as written, not as escaped)
        self.assertIsNone(extract.safe_markup({"raw": None}))


if __name__ == "__main__":
    unittest.main()
