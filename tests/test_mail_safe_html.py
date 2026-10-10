import email.message
import unittest
from unittest import mock

from tests.privacy import no_leaks
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
                    self.assertRegex(out, r'^<a href="[^"]+" target="_blank" rel="noopener noreferrer" title="[^"]+">go</a>$')
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
        self.assertTrue(clean("<div>" * 45 + "deep" + "</div>" * 45 + "<p>after</p>").endswith("</div><p>after</p>"))
        clean("<<>><a href=><td colspan=\"<b>\">&#xZZ; <!-- <p> -->")


class FromAMessage(unittest.TestCase):
    def test_a_message_is_read_in_memory_alone(self):
        html = '<html><body><p>CANARY-BODY-PREVIEW-8M3Q</p></body></html>'
        with no_leaks(self, "CANARY-BODY-PREVIEW-8M3Q"):
            self.assertEqual(extract.safe_markup(message(eml(html))), ("<p>CANARY-BODY-PREVIEW-8M3Q</p>", False))

    def test_a_messages_html_part_is_cleaned_and_a_text_only_message_has_none(self):
        html = '<html><head><style>p{}</style></head><body><p onclick="x()">Gate <b>B12</b></p><script>evil()</script></body></html>'
        self.assertEqual(extract.safe_markup(message(eml(html))), ("<p>Gate <b>B12</b></p>", False))
        self.assertIsNone(extract.safe_markup(message(eml("Just text", ctype="text/plain"))))
        two = (b"From: a@example.example\nSubject: s\nMIME-Version: 1.0\nContent-Type: multipart/mixed; boundary=B\n\n"
               b"--B\nContent-Type: text/html; charset=utf-8\n\n<p>one</p><script>never closed\n"
               b"--B\nContent-Type: text/html; charset=utf-8\n\n<p>two</p>\n--B--\n")
        self.assertEqual(extract.safe_markup(message(two)), ("<p>one</p><hr><p>two</p>", False))
        self.assertEqual(extract.safe_markup(message(two), 3), ("<p>one</p>", True))
        self.assertEqual(extract.safe_markup(message(eml("<p>one</p>")), 3), ("<p>one</p>", False))
        amps = two.replace(b"<p>one</p>", b"<p>a&amp;b&lt;c</p>")
        self.assertEqual(extract.safe_markup(message(amps), 7), ("<p>a&amp;b&lt;c</p><hr><p>tw</p>", True))
        self.assertIsNone(extract.safe_markup({"raw": None}))


PNG = b"\x89PNG\r\n\x1a\n" + b"CANARY-IMAGE-BYTES-6T1K" + bytes(32)
GIF = b"GIF89a" + bytes(16)
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def with_images(html: str, *related: tuple[str, bytes, str]) -> dict:
    msg = email.message.EmailMessage()
    msg["From"], msg["Subject"], msg["Date"] = "Example Air <a@example-air.example>", "Hello", "Mon, 12 Oct 2026 09:30:00 -0400"
    msg.set_content("Plain CANARY-TEXT-BODY-2V7N")
    msg.add_alternative(html, subtype="html")
    for cid, data, subtype in related:
        msg.get_payload()[1].add_related(data, "image", subtype, cid=f"<{cid}>")
    return message(msg.as_bytes())


class Styled(unittest.TestCase):
    def test_colors_fonts_sizes_spacing_alignment_and_widths_survive(self):
        out = clean('<table width="600" align="center" bgcolor="#ffffff" cellpadding="0" cellspacing="0" border="0">'
                    '<tr><td width="50%" valign="top" style="color:#112233;font-size:14px;line-height:1.4;font-weight:bold;text-align:center;'
                    'padding:4px 8px;font-family:Arial, sans-serif;background-color:rgb(1, 2, 3);border:1px solid #cccccc">x</td></tr></table>')
        for kept in ('width="600"', 'align="center"', 'cellpadding="0"', 'cellspacing="0"', 'border="0"', 'width="50%"', 'valign="top"',
                     "background-color:#ffffff", "color:#112233", "font-size:14px", "line-height:1.4", "font-weight:bold", "text-align:center",
                     "padding:4px 8px", "font-family:Arial, sans-serif", "background-color:rgb(1, 2, 3)", "border:1px solid #cccccc"):
            self.assertIn(kept, out)

    def test_a_font_tag_and_the_body_keep_their_colors(self):
        self.assertEqual(clean('<font color="#cc0000" face="Verdana, Arial" size="3">hot</font>'),
                         '<font style="color:#cc0000;font-family:Verdana, Arial">hot</font>')
        self.assertEqual(clean('<body bgcolor="#eeeeee"><p>a</p></body>'), '<div style="background-color:#eeeeee"><p>a</p></div>')
        self.assertEqual(clean("<body><p>a</p></body>"), "<p>a</p>")

    def test_hostile_css_is_dropped_declaration_by_declaration(self):
        hostile = ("background:url(http://t.example/p);color:expression(alert(1));position:fixed;top:0;left:0;width:100%;height:100%;z-index:9999;"
                   "background-image:url(https://t.example/x.png);behavior:url(x.htc);-moz-binding:url(x);filter:blur(9px);opacity:0;"
                   "content:'x';margin:-9999px;padding:0\\0;width:calc(100% - 4px);font-size:12px/* c */;"
                   "color:\\72 ed;background-color:var(--x);@import 'x';display:flex;transform:scale(99);color:red")
        out = clean(f'<div style="{hostile}">x</div>')
        for banned in ("url", "expression", "position", "fixed", "z-index", "behavior", "binding", "filter", "opacity", "content", "calc",
                       "var(", "@import", "flex", "transform", "-9999", "\\", "/*", "t.example"):
            self.assertNotIn(banned, out)
        self.assertIn("width:100%", out)
        self.assertIn("color:red", out)

    def test_nothing_in_a_style_can_leave_its_attribute(self):
        out = clean('<p style="font-family:&quot; onmouseover=&quot;evil()">x</p>')
        self.assertNotIn("onmouseover", out)
        out = clean("<p style=\"font-family:'Helvetica Neue', Arial\" onclick=\"evil()\">x</p>")
        self.assertEqual(out, "<p style=\"font-family:&#x27;Helvetica Neue&#x27;, Arial\">x</p>")
        self.assertEqual(clean('<p style="color:red;;;:;color">x</p>'), '<p style="color:red">x</p>')

    def test_style_blocks_forms_and_inputs_are_gone_but_their_words_stay_readable(self):
        html = ('<style>@import url(http://t.example/x.css);body{background:url(http://t.example/p)}</style><link rel="stylesheet" href="https://t.example/x.css">'
                '<form action="https://t.example/steal" method="post"><label>Name</label><input name="x" value="v"><button>Go</button></form>'
                '<base href="https://t.example/"><meta http-equiv="refresh" content="0;url=https://t.example/">')
        out = clean(html)
        self.assertEqual(out, "Name")
        self.assertNotIn("t.example", out)

    def test_every_event_handler_and_scripting_link_goes(self):
        out = clean('<a href="javascript:alert(1)" onclick="e()" onmouseover="e()">a</a><a href="data:text/html,<script>1</script>">b</a>'
                    '<table onload="e()" background="https://t.example/p.png"><tr onclick="e()"><td onmouseover="e()" style="color:red">c</td></tr></table>')
        self.assertEqual(out, '<a>a</a><a>b</a><table><tr><td style="color:red">c</td></tr></table>')

    def test_a_link_shows_where_it_goes_and_opens_elsewhere_safely(self):
        out = clean('<a href="https://example.com/a?b=1&c=2" style="color:#0000ee">go</a>')
        self.assertEqual(out, '<a href="https://example.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer" '
                              'title="https://example.com/a?b=1&amp;c=2" style="color:#0000ee">go</a>')

    def test_a_very_large_message_is_cut_by_its_markup_size_too(self):
        out, cut, _size = safe_html.clean_counted("<p style='color:red'>a</p>" * 200, 10_000, None, 300)
        self.assertTrue(cut)
        self.assertLessEqual(len(out), 300 + len("</p>") * 2)
        self.assertTrue(out.endswith("</p>"))


class Pictures(unittest.TestCase):
    def test_a_picture_the_resolver_knows_becomes_a_numbered_placeholder_and_never_a_source(self):
        asked = []

        def resolve(source: str) -> int | None:
            asked.append(source)
            return {"cid:logo": 0, "https://images.example/b.png": 1}.get(source)

        out, _cut, _size = safe_html.clean_counted(
            '<img src="cid:logo" alt="Example &quot;Air&quot;" width="64px" height="64" style="border-radius:4px;position:fixed" onerror="evil()">'
            '<img src="https://images.example/b.png" width="9999999" height="x"><img src="https://t.example/p.gif" alt="gone"><img src="data:image/png;base64,AAAA">'
            '<img alt="no source">', 1000, resolve)
        self.assertEqual(out, '<img data-i="0" alt="Example &quot;Air&quot;" width="64" height="64" style="border-radius:4px"><img data-i="1" alt="">gone no source ')
        self.assertEqual(asked, ["cid:logo", "https://images.example/b.png", "https://t.example/p.gif", "data:image/png;base64,AAAA"])
        for banned in ("src=", "http", "onerror", "position"):
            self.assertNotIn(banned, out)

    def test_without_a_resolver_nothing_loads_and_the_alt_text_stays(self):
        self.assertEqual(clean('<img src="https://images.example/b.png" alt="Logo"><img src="cid:x">'), "Logo ")


class KeptWithPictures(unittest.TestCase):
    def test_an_attached_picture_is_kept_and_a_remote_one_is_fetched_once(self):
        html = ('<p>CANARY-HTML-BODY-8F2D</p><img src="cid:logo1" alt="Logo"><img src="https://images.example/hero.gif?t=CANARY-URL-TOKEN-5M9X" alt="Hero">'
                '<img src="https://images.example/hero.gif?t=CANARY-URL-TOKEN-5M9X"><img src="cid:logo1">')
        fetched = []

        def fetch(url: str):
            fetched.append(url)
            return ("image/gif", GIF)

        content, images = extract.keep(with_images(html, ("logo1", PNG, "png")), fetch)
        self.assertEqual(fetched, ["https://images.example/hero.gif?t=CANARY-URL-TOKEN-5M9X"])
        self.assertEqual(images, [{"type": "image/png", "data": PNG}, {"type": "image/gif", "data": GIF}])
        self.assertEqual((content["images"], content["original"], content["truncated"]), (2, True, False))
        self.assertEqual(content["html"].count('data-i="0"'), 2)
        self.assertEqual(content["html"].count('data-i="1"'), 2)
        for banned in ("images.example", "CANARY-URL-TOKEN", "cid:", "src="):
            self.assertNotIn(banned, content["html"])
        self.assertIn("CANARY-HTML-BODY-8F2D", content["html"])

    def test_without_a_fetcher_only_attached_pictures_are_kept(self):
        content, images = extract.keep(with_images('<img src="cid:logo1"><img src="https://images.example/a.png" alt="A">', ("logo1", PNG, "png")))
        self.assertEqual([i["type"] for i in images], ["image/png"])
        self.assertIn("A ", content["html"])

    def test_a_picture_that_is_missing_refused_or_not_an_image_leaves_the_message_readable(self):
        html = '<p>Read me</p><img src="cid:nope" alt="N"><img src="cid:logo2" alt="S"><img src="https://images.example/x.png" alt="R">'
        content, images = extract.keep(with_images(html, ("logo2", SVG, "svg+xml")), lambda url: None)
        self.assertEqual((images, content["images"]), ([], 0))
        self.assertEqual(content["html"], "<p>Read me</p>N S R \n")

    def test_an_attached_picture_over_the_size_limit_or_past_the_total_is_left_out(self):
        big = PNG + bytes(2_000_000)
        _content, images = extract.keep(with_images('<img src="cid:a"><img src="cid:b">', ("a", big, "png"), ("b", PNG, "png")))
        self.assertEqual([i["data"] for i in images], [PNG])
        with mock.patch.object(extract.mailimages, "MAX_TOTAL_BYTES", len(PNG) + 1):
            _content, images = extract.keep(with_images('<img src="cid:a"><img src="cid:b">', ("a", PNG, "png"), ("b", GIF + PNG, "png")))
        self.assertEqual(len(images), 1)

    def test_a_message_is_only_cut_past_the_hard_cap(self):
        long_text = "word " * 20_000
        content, _images = extract.keep(message(eml(f"<p>{long_text}</p>")))
        self.assertFalse(content["truncated"])
        self.assertGreater(len(content["text"]), 90_000)
        with mock.patch.object(extract, "KEPT_LIMIT", 1000):
            content, _images = extract.keep(message(eml(f"<p>{long_text}</p>")))
        self.assertTrue(content["truncated"])
        self.assertEqual(len(content["text"]), 1000)
        self.assertGreater(extract.KEPT_LIMIT, 100_000)

    def test_a_message_that_cannot_be_read_still_gives_an_empty_original(self):
        content, images = extract.keep({"raw": None})
        self.assertEqual((content["text"], content["html"], content["images"], content["original"], images), ("", None, 0, True, []))

    def test_what_is_kept_is_read_in_memory_alone(self):
        html = '<p>CANARY-HTML-BODY-8F2D</p><img src="cid:logo1"><img src="https://images.example/hero.gif?t=CANARY-URL-TOKEN-5M9X">'
        with no_leaks(self, "CANARY-HTML-BODY-8F2D", "CANARY-IMAGE-BYTES-6T1K", "CANARY-URL-TOKEN-5M9X", "CANARY-TEXT-BODY-2V7N"):
            extract.keep(with_images(html, ("logo1", PNG, "png")), lambda url: ("image/gif", GIF))


if __name__ == "__main__":
    unittest.main()
