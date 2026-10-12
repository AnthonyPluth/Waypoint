from __future__ import annotations

import json
from typing import Any
from pathlib import Path

from waypoint.domain.mail import safe_html

CORPUS = Path(__file__).resolve().parent.parent / "frontend" / "src" / "test" / "hostile-corpus.json"
EVIL = "https://evil.example"
BIG = 20_000


def payload(name: str, html: str, canary: str) -> dict[str, Any]:
    return {"name": name, "html": html, "canary": canary}


def scripts() -> list[dict[str, Any]]:
    return [
        payload("script tag", "<p>a</p><script>window.CANARY_script=1</script><p>b</p>", "CANARY_script"),
        payload("script with a remote source", f'<script src="{EVIL}/CANARY_script_src.js"></script>', "CANARY_script_src"),
        payload("upper-case and split script", "<SCRIPT>window.CANARY_script_case=1</SCRIPT><scr<script>ipt>window.CANARY_script_split=1</script>", "<script"),
        payload("script in a table", "<table><tr><td><script>window.CANARY_script_table=1</script></td></tr></table>", "CANARY_script_table"),
        payload("noscript", "<noscript><script>window.CANARY_noscript=1</script></noscript>", "CANARY_noscript"),
        payload("template", "<template><script>window.CANARY_template=1</script><img src=x onerror=window.CANARY_template_img=1></template>", "CANARY_template"),
        payload("conditional comment", "<!--[if IE]><script>window.CANARY_comment=1</script><![endif]--><p>x</p>", "CANARY_comment"),
        payload("cdata and processing instruction", "<![CDATA[<script>window.CANARY_cdata=1</script>]]><?php window.CANARY_pi=1 ?>", "CANARY_"),
        payload("comment that ends badly", "<!-- --!><img src=x onerror=window.CANARY_badcomment=1>-->", "CANARY_badcomment"),
        payload("null byte in a tag", "<scr\x00ipt>window.CANARY_null=1</scr\x00ipt><img src=x onerror\x00=window.CANARY_null_img=1>", "<scr"),
        payload("base, meta and link", f'<base href="{EVIL}/CANARY_base/"><meta http-equiv="refresh" content="0;url=javascript:window.CANARY_meta=1"><link rel="stylesheet" href="{EVIL}/CANARY_link.css">', "CANARY_"),
        payload("frames and embeds", f'<iframe src="javascript:window.CANARY_iframe=1"></iframe><iframe srcdoc="<script>window.CANARY_srcdoc=1</script>"></iframe><object data="{EVIL}/CANARY_object"></object><embed src="{EVIL}/CANARY_embed">', "CANARY_"),
        payload("custom element and unknown attributes", '<x-evil onclick="window.CANARY_custom=1" is="x-evil" slot="a" popover>hello</x-evil><div contenteditable draggable="true" tabindex="0" autofocus onfocus="window.CANARY_focus=1">d</div>', "CANARY_"),
    ]


def handlers() -> list[dict[str, Any]]:
    return [
        payload("click handler", '<p onclick="window.CANARY_click=1">tap</p>', "CANARY_click"),
        payload("hover and focus handlers", '<a href="https://example.com" onmouseover="window.CANARY_hover=1" onfocus="window.CANARY_focus_a=1">x</a>', "CANARY_"),
        payload("body onload", '<body onload="window.CANARY_onload=1"><p>x</p></body>', "CANARY_onload"),
        payload("details toggle", '<details open ontoggle="window.CANARY_toggle=1"><summary>s</summary></details>', "CANARY_toggle"),
        payload("img onerror", '<img src="x" onerror="window.CANARY_img_error=1">', "CANARY_img_error"),
        payload("img onerror without quotes", "<img src=x onerror=window.CANARY_img_bare=1>", "CANARY_img_bare"),
        payload("img onload with a slash", '<img/src=x/onerror=window.CANARY_img_slash=1>', "CANARY_img_slash"),
        payload("table and cell handlers", '<table onmouseover="window.CANARY_table=1"><tr onclick="window.CANARY_tr=1"><td onfocus="window.CANARY_td=1">x</td></tr></table>', "CANARY_"),
        payload("style attribute handler", '<p style="color:red" onanimationstart="window.CANARY_anim=1">x</p>', "CANARY_anim"),
    ]


def links() -> list[dict[str, Any]]:
    return [
        payload("javascript link", '<a href="javascript:window.CANARY_js=1">x</a>', "CANARY_js"),
        payload("javascript link with odd case and whitespace", '<a href="  JaVa\tScRiPt:window.CANARY_js_case=1">x</a>', "CANARY_js_case"),
        payload("javascript link with entities", '<a href="&#106;avascript:window.CANARY_js_entity=1">x</a><a href="java&#x0A;script:window.CANARY_js_newline=1">y</a>', "CANARY_js_"),
        payload("javascript link with a control character", '<a href="\x01javascript:window.CANARY_js_ctl=1">x</a>', "CANARY_js_ctl"),
        payload("vbscript link", '<a href="vbscript:msgbox(CANARY_vb)">x</a>', "CANARY_vb"),
        payload("data link", '<a href="data:text/html,<script>window.CANARY_data=1</script>">x</a>', "CANARY_data"),
        payload("data link in base64", '<a href="data:text/html;base64,PHNjcmlwdD53aW5kb3cuQ0FOQVJZX2I2ND0xPC9zY3JpcHQ+">x</a>', "PHNjcmlwdD53aW5kb3cu"),
        payload("plain http link", '<a href="http://evil.example/CANARY_http">x</a>', "CANARY_http"),
        payload("protocol-relative and relative links", '<a href="//evil.example/CANARY_rel">x</a><a href="/CANARY_path">y</a>', "CANARY_"),
        payload("link that tries to keep the opener", f'<a href="{EVIL}" target="_self" rel="opener">x</a><a href="{EVIL}" target="_top">y</a>', "CANARY_none"),
        payload("quote that tries to leave the attribute", '<a href=\'https://example.com/" onmouseover="window.CANARY_quote=1\'>x</a>', "\" onmouseover=\""),
        payload("form action", f'<form action="{EVIL}/CANARY_form" method="post"><input name="a" value="CANARY_value"><button formaction="javascript:window.CANARY_formaction=1">go</button></form>', "CANARY_"),
        payload("nested forms", f'<form action="{EVIL}/CANARY_outer"><form action="{EVIL}/CANARY_inner"><input type="image" src="{EVIL}/CANARY_input.gif"><select><option>CANARY_option</option></select><textarea>CANARY_textarea</textarea></form></form>', "CANARY_"),
    ]


def styles() -> list[dict[str, Any]]:
    return [
        payload("style block with an import", f"<style>@import url({EVIL}/CANARY_import.css);body{{background:url({EVIL}/CANARY_bg)}}</style><p>x</p>", "CANARY_"),
        payload("style block inside a table", f"<table><style>td{{background:url({EVIL}/CANARY_table_bg)}}</style><tr><td>x</td></tr></table>", "CANARY_table_bg"),
        payload("background url", f'<p style="background:url({EVIL}/CANARY_style_bg)">x</p><p style="background-image:url(\'{EVIL}/CANARY_style_img\')">y</p>', "CANARY_style_"),
        payload("css expression", '<p style="width:expression(window.CANARY_expr=1)">x</p><p style="color:expression(window.CANARY_expr2=1)">y</p>', "CANARY_expr"),
        payload("behavior and binding", f'<p style="behavior:url({EVIL}/CANARY_behavior.htc);-moz-binding:url({EVIL}/CANARY_binding.xml)">x</p>', "CANARY_"),
        payload("css escape of url", f'<p style="background:\\75 rl({EVIL}/CANARY_escape)">x</p><p style="background:u\\72l({EVIL}/CANARY_escape2)">y</p>', "CANARY_escape"),
        payload("import in a style attribute", f'<p style="@import url({EVIL}/CANARY_attr_import.css)">x</p>', "CANARY_attr_import"),
        payload("css comment and a second declaration", f'<p style="color:red;/*;background:url({EVIL}/CANARY_comment_bg)*/">x</p>', "CANARY_comment_bg"),
        payload("font family that closes its quote", f"<p style=\"font-family:'a';background:url({EVIL}/CANARY_font)\">x</p>", "CANARY_font"),
        payload("custom properties and variables", f'<p style="--x:url({EVIL}/CANARY_var);background:var(--x)">x</p>', "CANARY_var"),
        payload("a box that covers the app", '<div style="position:fixed;top:0;left:0;width:100%;height:100%;z-index:9999;background:#fff">CANARY_overlay</div>', "position"),
        payload("opacity, filters and transforms", '<p style="opacity:0;filter:blur(9px);transform:scale(9);pointer-events:none;cursor:url(x.cur)">x</p>', "transform"),
        payload("body background", f'<body background="{EVIL}/CANARY_body_bg" bgcolor="red" style="background:url({EVIL}/CANARY_body_style)"><p>x</p></body>', "CANARY_body_"),
        payload("font tag", '<font face="a;background:url(https://evil.example/CANARY_face)" color="red;background:url(https://evil.example/CANARY_color)">x</font>', "CANARY_"),
        payload("presentation attributes with markup in them", '<table width="600\" onmouseover=\"window.CANARY_w=1" cellpadding="<b>" border="1;background:url(https://evil.example/CANARY_border)"><tr><td align="center\" onclick=\"window.CANARY_align=1">x</td></tr></table>', "CANARY_"),
        payload("huge style value", f'<p style="color:red;font-family:{"A" * BIG}">x</p>', "AAAAAAAAAAAAAAAAAAAA"),
    ]


def images() -> list[dict[str, Any]]:
    return [
        payload("remote pixel", f'<p>x</p><img src="{EVIL}/CANARY_pixel.gif" width="1" height="1">', "CANARY_pixel"),
        payload("remote image with srcset", f'<img src="x" srcset="{EVIL}/CANARY_srcset.png 2x" alt="">', "CANARY_srcset"),
        payload("picture and source", f'<picture><source srcset="{EVIL}/CANARY_source.png"><img src="{EVIL}/CANARY_picture.png"></picture>', "CANARY_"),
        payload("image tag with a data address", '<img src="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\' onload=\'window.CANARY_svg_img=1\'></svg>" alt="">', "CANARY_svg_img"),
        payload("image with a script address", '<img src="javascript:window.CANARY_img_js=1" alt=""><image src="x" onerror="window.CANARY_image_tag=1">', "CANARY_"),
        payload("image that names a kept picture and a remote one", f'<img data-i="0" src="{EVIL}/CANARY_both.png" onerror="window.CANARY_both=1" alt="" width="64" style="background:url({EVIL}/CANARY_img_style)">', "CANARY_"),
        payload("image with a marker of its own", '<img data-i="9999999999" alt=""><img data-i="x\" onerror=\"window.CANARY_marker=1" alt="">', "CANARY_marker"),
        payload("image alt that looks like markup", '<img src="x" alt="&lt;img src=x onerror=window.CANARY_alt=1&gt;">', "<img src=x"),
        payload("audio and video", f'<video src="{EVIL}/CANARY_video.mp4" poster="{EVIL}/CANARY_poster.png" onerror="window.CANARY_video=1"></video><audio src="{EVIL}/CANARY_audio.mp3" autoplay></audio>', "CANARY_"),
        payload("svg with a script", '<svg xmlns="http://www.w3.org/2000/svg" onload="window.CANARY_svg=1"><script>window.CANARY_svg_script=1</script><a href="javascript:window.CANARY_svg_a=1"><text>x</text></a></svg>', "CANARY_svg"),
        payload("svg animation and use", f'<svg><animate onbegin="window.CANARY_animate=1" attributeName="x"/><use href="{EVIL}/CANARY_use.svg#a"/><foreignObject><iframe src="{EVIL}/CANARY_fo"></iframe></foreignObject></svg>', "CANARY_"),
        payload("math with a link", '<math><mi xlink:href="javascript:window.CANARY_math=1">x</mi><maction actiontype="statusline#" xlink:href="javascript:window.CANARY_maction=1">y</maction></math>', "CANARY_"),
        payload("canvas, button and input", '<canvas onclick="window.CANARY_canvas=1"></canvas><button onclick="window.CANARY_button=1">b</button><input onfocus="window.CANARY_input=1" autofocus>', "CANARY_"),
    ]


def mutations() -> list[dict[str, Any]]:
    return [
        payload("noscript that hides an attribute", '<noscript><p title="</noscript><img src=x onerror=window.CANARY_mxss_noscript=1>"></noscript>', "CANARY_mxss_noscript"),
        payload("svg and style that swap namespaces", '<svg></p><style><a title="</style><img src onerror=window.CANARY_mxss_svg=1>"></style></svg>', "CANARY_mxss_svg"),
        payload("math text and a glyph", '<math><mtext><table><mglyph><style><!--</style><img title="--&gt;&lt;img src=1 onerror=window.CANARY_mxss_math=1&gt;">', "CANARY_mxss_math"),
        payload("form that reopens in math", '<form><math><mtext></form><form><mglyph><style></math><img src onerror=window.CANARY_mxss_form=1>', "CANARY_mxss_form"),
        payload("misnested table and link", '<table><td><a href="https://example.com"></table><a href="javascript:window.CANARY_mxss_table=1">x</a>', "CANARY_mxss_table"),
        payload("textarea and listing", '<textarea><img src=x onerror=window.CANARY_textarea=1></textarea><listing><img src=x onerror=window.CANARY_listing=1></listing>', "CANARY_"),
        {**payload("xmp and plaintext", '<xmp><img src=x onerror=window.CANARY_xmp=1></xmp><plaintext><img src=x onerror=window.CANARY_plaintext=1>', "<img src=x onerror"), "volatile": True},
        payload("title and select that close early", '<title></title><img src=x onerror=window.CANARY_title=1><select><template><option><style></template></select><img src=x onerror=window.CANARY_select=1>', "CANARY_"),
        payload("text that is escaped markup", "<p>a &lt;img src=x onerror=window.CANARY_text=1&gt; b &amp;lt;script&amp;gt;</p>", "<img src=x"),
        payload("entities that decode to a tag", "<p>&#60;script&#62;window.CANARY_entity=1&#60;/script&#62;</p>", "<script"),
        payload("attribute with a double encoded quote", '<table width="1&amp;quot; onmouseover=&amp;quot;window.CANARY_double=1"><tr><td>x</td></tr></table>', "CANARY_double"),
        payload("unclosed tag at the end", '<p>x</p><img src=x onerror=window.CANARY_unclosed=1', "CANARY_unclosed"),
        payload("unclosed attribute at the end", '<p>x</p><a href="https://example.com/CANARY_open', "CANARY_open"),
    ]


def sizes() -> list[dict[str, Any]]:
    return [
        payload("deeply nested divs", "<div>" * 3000 + "deep" + "</div>" * 3000, "CANARY_none"),
        payload("deeply nested tables", "<table><tr><td>" * 300 + "deep" + "</td></tr></table>" * 300, "CANARY_none"),
        payload("deeply nested inline tags", "<b>" * 5000 + "deep", "CANARY_none"),
        payload("stray end tags", "<div>" * 1000 + "</span></b></td>" * 1000 + "deep", "CANARY_none"),
        payload("huge link", f'<a href="https://example.com/{"a" * BIG}">x</a>', "CANARY_none"),
        payload("huge attribute names and values", f'<p {"a" * 5000}="{"b" * 5000}" onclick="window.CANARY_huge=1">x</p>', "CANARY_huge"),
        payload("thousands of attributes", "<p " + " ".join(f'a{i}="x"' for i in range(2000)) + ' onclick="window.CANARY_many=1">x</p>', "CANARY_many"),
        payload("huge text", "<p>" + "word " * 4000 + "</p>", "CANARY_none"),
        payload("thousands of cells", "<table><tr>" + "<td>x</td>" * 1000 + "</tr></table>", "CANARY_none"),
        payload("clobbering names", '<a id="CANARY_id" name="__proto__" class="CANARY_class">x</a><img name="getElementById" id="body"><form name="attributes"></form>', "CANARY_"),
    ]


def build() -> list[dict[str, Any]]:
    found = [*scripts(), *handlers(), *links(), *styles(), *images(), *mutations(), *sizes()]
    names = [p["name"] for p in found]
    assert len(names) == len(set(names))
    return found


def corpus() -> list[dict[str, Any]]:
    found = []
    for p in build():
        volatile = p.pop("volatile", False)
        cleaned = "" if volatile else safe_html.clean(p["html"], 200_000)[0]
        pictured = "" if volatile else safe_html.clean_counted(p["html"], 200_000, lambda src: 0 if src.startswith("x") else None)[0]
        found.append({**p, "cleaned": cleaned, "cleanedWithPictures": pictured})
    return found


def write() -> None:
    CORPUS.write_text(json.dumps(corpus(), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write()
