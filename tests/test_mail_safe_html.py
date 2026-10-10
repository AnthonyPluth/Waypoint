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
        self.assertTrue(clean("<div>" * 45 + "deep" + "</div>" * 45 + "<p>after</p>").endswith("</div><p>after</p>"))
        clean("<<>><a href=><td colspan=\"<b>\">&#xZZ; <!-- <p> -->")


def rich(html: str, images: dict[str, int] | None = None, limit: int = 10_000, markup_limit: int | None = None) -> str:
    wanted = images or {}
    return safe_html.clean_rich(html, limit, lambda source: wanted.get(source), markup_limit)[0]


LOGO = "https://img.example-air.example/logo.png"


class LayoutKept(unittest.TestCase):
    def test_layout_tables_widths_colours_and_fonts_survive(self):
        html = ('<body bgcolor="#eef2f7" style="margin:0"><table width="600" align="center" cellpadding="0" cellspacing="0" border="0" '
                'style="background-color:#ffffff; border:1px solid #d5dbe5; max-width:600px"><tr><td colspan="2" align="center" valign="top" '
                'width="50%" bgcolor="#f3f6fb" style="padding:24px 12px; font-family:Georgia, \'Times New Roman\', serif; font-size:15px; '
                'color:#1f2937; text-align:center; line-height:1.5">Hello <font color="#0b3d91" size="4" face="Arial">Jane</font></td></tr></table></body>')
        out = rich(html)
        for part in ('<div style="background-color: #eef2f7; margin: 0">', '<table width="600" border="0" cellpadding="0" cellspacing="0" align="center"',
                     "background-color: #ffffff", "border: 1px solid #d5dbe5", "max-width: 600px", 'colspan="2"', 'align="center" valign="top"',
                     'width="50%"', "background-color: #f3f6fb", "padding: 24px 12px", "font-family: Georgia, &#x27;Times New Roman&#x27;, serif",
                     "font-size: 15px", "color: #1f2937", "text-align: center", "line-height: 1.5",
                     '<font style="color: #0b3d91; font-family: Arial; font-size: large">Jane</font>'):
            self.assertIn(part, out)
        self.assertEqual(out.count("<div"), out.count("</div>"))

    def test_the_allowed_inline_styles_each_survive_and_values_are_kept_as_written(self):
        for style in ("color: red", "color: rgb(10, 20, 30)", "color: rgba(10,20,30,0.5)", "background-color: hsl(10, 20%, 30%)",
                      "background: #fff", "font-weight: bold", "font-weight: 600", "font-style: italic", "text-decoration: underline",
                      "text-transform: uppercase", "letter-spacing: 0.5px", "white-space: nowrap", "vertical-align: middle",
                      "margin: 0 auto", "padding-left: 4px", "border-top: 2px dashed #ccc", "border-radius: 4px", "border-collapse: collapse",
                      "width: 100%", "height: 40px", "min-width: 200px", "display: none", "display: inline-block", "opacity: 0.5",
                      "list-style-type: disc", "text-indent: 1em"):
            with self.subTest(style=style):
                self.assertEqual(rich(f'<p style="{style}">x</p>'), f'<p style="{style}">x</p>')

    def test_links_open_in_a_new_tab_without_a_referrer_and_say_where_they_go(self):
        out = rich('<a href="https://example-air.example/manage?id=1&amp;x=2" style="color:#0b3d91;font-weight:bold">Manage</a>')
        self.assertEqual(out, '<a href="https://example-air.example/manage?id=1&amp;x=2" title="https://example-air.example/manage?id=1&amp;x=2" '
                              'style="color: #0b3d91; font-weight: bold" target="_blank" rel="noopener noreferrer">Manage</a>')
        self.assertEqual(rich('<a href="mailto:help@example-air.example">Write</a>').count('rel="noopener noreferrer"'), 1)

    def test_an_image_that_was_kept_is_named_by_number_and_never_by_address(self):
        out = rich(f'<img src="{LOGO}" alt="Example Air" width="600" height="80" style="display:block; width:100%; position:fixed">', {LOGO: 3})
        self.assertEqual(out, '<img data-image="3" alt="Example Air" width="600" height="80" style="display: block; width: 100%">')
        self.assertNotIn("example-air.example", out)
        self.assertNotIn(" src", out)

    def test_an_image_that_was_not_kept_is_its_alt_text(self):
        self.assertEqual(rich(f'<p><img src="{LOGO}" alt="Example Air logo"> hi</p>'), "<p>Example Air logo  hi</p>")
        self.assertEqual(rich('<p><img src="cid:gone" alt="Seat map">x</p>', {"cid:other": 1}), "<p>Seat map x</p>")

    def test_a_tracking_pixel_is_never_asked_for(self):
        asked: list[str] = []

        def ask(source: str) -> int:
            asked.append(source)
            return 0

        out = safe_html.clean_rich(f'<img src="{LOGO}?pixel=1" width="1" height="1"><img src="{LOGO}?p=2" width=2><img src="{LOGO}?p=3" height="0px">'
                                   f'<img src="{LOGO}?real=1" width="200">', 1000, ask)[0]
        self.assertEqual(asked, [f"{LOGO}?real=1"])
        self.assertEqual(out.count("<img"), 1)

    def test_a_page_with_a_head_and_a_body_shows_the_body_alone(self):
        self.assertEqual(rich("<html><head><title>T</title><style>p{color:red}</style></head><body><p>Gate B12</p></body></html>"), "<div><p>Gate B12</p></div>")

    def test_the_text_is_cut_at_the_limit_and_the_markup_at_its_own(self):
        out, cut, size = safe_html.clean_rich("<p>" + "x" * 100 + "</p><p>more</p>", 20, lambda s: None)
        self.assertEqual((out, cut, size), ("<p>" + "x" * 20 + "</p>", True, 20))
        out = rich("<p>one</p>" * 100, markup_limit=100)
        self.assertLess(len(out), 200)
        self.assertEqual(out.count("<p>"), out.count("</p>"))
        self.assertEqual(safe_html.clean_rich("<p>one</p>" * 100, 10_000, lambda s: None, 100)[1], True)


HOSTILE_STYLES = (
    "width: expression(alert(1))", "background: url(https://t.example/p.gif)", "background-image: url('https://t.example/p.gif')",
    "background: red url(https://t.example/p.gif)", "@import url(https://t.example/x.css)", "position: fixed; top: 0; left: 0; width: 100%; height: 100%",
    "position: absolute", "color: red; position: fixed", "behavior: url(x.htc)", "-moz-binding: url(https://t.example/x.xml#b)",
    "width: calc(100% - 10px)", "color: \\72 ed", "background: u\\72 l(https://t.example/p.gif)", "background: u/**/rl(https://t.example/p.gif)",
    "font-family: x; } body { display: none", "font-family: 'a'; background: url(x)", "content: url(https://t.example/p.gif)",
    "list-style-image: url(https://t.example/p.gif)", "color: var(--x)", "z-index: 99999", "cursor: url(https://t.example/c.cur), auto",
    "filter: url(#x)", "color: red\\9", "color: red <script>alert(1)</script>", "background: image-set(url(x) 1x)",
    "transform: scale(100)", "overflow: visible", "float: left", "left: 0", "display: flex", "color: javascript:alert(1)",
)


class LayoutDropped(unittest.TestCase):
    def test_hostile_styles_are_dropped_and_nothing_of_them_is_left(self):
        for style in HOSTILE_STYLES:
            with self.subTest(style=style):
                out = rich(f'<div style="{style}">x</div><a href="https://example-air.example/" style="{style}">y</a>')
                self.assertNotRegex(out.replace("https://example-air.example/", ""),
                                    r"(?i)expression|url|@import|position|behavior|binding|image|calc|var\(|z-index|cursor|filter|javascript|script|\\|/\*|99999|transform|overflow|float|left:|flex")

    def test_a_style_cannot_close_its_attribute_or_add_one(self):
        out = rich('<p style="color: red&quot; onmouseover=&quot;alert(1)">x</p><p style=\'font-family: &quot;a&quot; onload=&quot;x&quot;\'>y</p>')
        self.assertNotIn("onmouseover", out)
        self.assertNotIn("onload", out)
        self.assertNotIn("alert", out)

    def test_scripts_handlers_style_blocks_forms_and_frames_go(self):
        html = ('<p onclick="evil()" onmouseover="e()" onload="e()">a</p><script>evil()</script><style>body{display:none}</style>'
                '<form action="https://t.example/steal" method="post"><input name=x value=1><select><option>EVIL</option></select><button>Go</button>'
                '<textarea>EVIL</textarea></form><iframe src="https://t.example"></iframe><object data="https://t.example/x"></object>'
                '<embed src="https://t.example/x"><svg onload="evil()"><script>1</script></svg><math><mi>EVIL</mi></math>'
                '<link rel="stylesheet" href="https://t.example/x.css"><base href="https://t.example/"><meta http-equiv="refresh" content="0;url=https://t.example/">'
                '<video src="https://t.example/v.mp4"></video><audio src="https://t.example/a.mp3"></audio><canvas></canvas><template><p>EVIL</p></template>'
                '<noscript><img src="https://t.example/p.gif"></noscript><p>b</p>')
        out = rich(html, {"https://t.example/p.gif": 0})
        self.assertEqual(out, "<p>a</p><p>b</p>")

    def test_no_attribute_that_loads_or_runs_survives_on_any_tag(self):
        html = ('<div class="x" id="y" onclick="e()" background="https://t.example/b.gif" data-x="1" srcset="https://t.example/s.gif 2x" '
                'src="https://t.example/p.gif" href="https://t.example/" action="https://t.example/" formaction="https://t.example/" '
                'poster="https://t.example/p.gif" ping="https://t.example/p" xlink:href="https://t.example/" style="color: red">'
                '<table background="https://t.example/b.gif" bgcolor="url(https://t.example/b.gif)"><tr><td background="https://t.example/b.gif" '
                'bgcolor="javascript:1" width="expression(1)" align="javascript:1">x</td></tr></table></div>')
        out = rich(html)
        self.assertEqual(out, '<div style="color: red"><table><tr><td>x</td></tr></table></div>')

    def test_links_with_a_script_or_data_address_are_no_links(self):
        for href in ("javascript:alert(1)", "  JaVa\tScRiPt:alert(1)", "data:text/html,<script>1</script>", "vbscript:x", "http://example.com",
                     "//example.com", "/relative", "file:///etc/passwd", "ftp://example.com", "blob:https://example.com/1", "https:", ""):
            with self.subTest(href=href):
                out = rich(f'<a href="{href}" style="color:red">go</a>')
                self.assertEqual(out, "<a>go</a>")

    def test_an_image_address_is_never_written_to_the_markup_whatever_it_is(self):
        sources = (LOGO, "http://t.example/p.gif", "javascript:alert(1)", "data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,AAAA", "//t.example/p.gif",
                   "cid:logo", "file:///etc/passwd", "blob:https://t.example/1", "", " ")
        for source in sources:
            with self.subTest(source=source):
                for known in ({}, {source: 5}):
                    out = rich(f'<img src="{source}" alt="x" onerror="evil()" srcset="{LOGO} 2x" lowsrc="{LOGO}" dynsrc="{LOGO}">', known)
                    self.assertNotRegex(out, r"(?i)\bsrc|srcset|lowsrc|dynsrc|onerror|http|javascript|data:|file:|blob:")

    def test_text_that_looks_like_markup_or_styles_stays_text(self):
        out = rich("<p>a &lt;img src=&quot;https://t.example/p.gif&quot; onerror=&quot;e()&quot;&gt; &lt;style&gt;x&lt;/style&gt;</p>")
        self.assertEqual(out, "<p>a &lt;img src=\"https://t.example/p.gif\" onerror=\"e()\"&gt; &lt;style&gt;x&lt;/style&gt;</p>")

    def test_the_original_cleaner_still_drops_every_style_and_image(self):
        out = clean(f'<div style="color:red" bgcolor="red"><img src="{LOGO}" alt="Logo"><a href="https://example-air.example/" style="color:red">x</a></div>')
        self.assertEqual(out, '<div>Logo <a href="https://example-air.example/" target="_blank" rel="noopener noreferrer">x</a></div>')


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


if __name__ == "__main__":
    unittest.main()
