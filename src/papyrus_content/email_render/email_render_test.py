from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from papyrus_content.email_render import (
    EmailFooter,
    EmailTheme,
    PostalAddressMissing,
    render_issue,
    render_transactional,
    theme_from_config,
)

SITE = "https://example.com"
THEME = EmailTheme(accent="#b3261e", text="#222222", background="#f1ece4", site_name="Example Times")
DOC = """# Big title

Para with [rel](/a/b), [abs](https://example.com/x), <b>raw</b> and [bad](javascript:alert(1)).

## Section

### Sub

- one
- two

1. first
2. second

> quoted

![Alt text](/img/a.png)

| a | b |
|---|---|
| 1 | 2 |
"""


def footer(address: str | None = "1 Example Way\nExample City") -> EmailFooter:
    return EmailFooter(
        site_name="Example & Co",
        site_url=f"{SITE}/",
        reason="You get this because you subscribed.",
        manage_url=f"{SITE}/manage?t=abc",
        unsubscribe_url=f"{SITE}/unsubscribe?t=abc",
        postal_address=address,
    )


def issue(**kw):
    args = dict(subject="Hello", markus=DOC, theme=THEME, footer=footer(), preheader="Pre text", site_url=SITE)
    args.update(kw)
    return render_issue(**args)


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def tags(html: str):
    p = _Tags()
    p.feed(html)
    return p.tags


def test_structure_and_safety():
    html = issue().html
    assert "<script" not in html.lower()
    assert "stylesheet" not in html
    assert 'name="color-scheme"' in html and 'name="supported-color-schemes"' in html
    assert 'name="viewport"' in html
    assert "Pre text" in html and "display:none" in html
    assert html.count("<style") == 1
    assert "<b>raw</b>" not in html and "&lt;b&gt;raw&lt;/b&gt;" in html


def test_inline_styles_and_absolute_links():
    parsed = tags(issue().html)
    for name in ("p", "h1", "h2", "h3", "a", "li", "blockquote", "td", "th"):
        found = [a for t, a in parsed if t == name]
        assert found, name
        assert all("style" in a for a in found), name
    hrefs = [a["href"] for t, a in parsed if t == "a"]
    assert hrefs and all(re.match(r"https?://", h) for h in hrefs)
    assert "https://example.com/a/b" in hrefs
    assert not any("javascript" in h for h in hrefs)
    img = next(a for t, a in parsed if t == "img" and "a.png" in a.get("src", ""))
    assert img["src"] == "https://example.com/img/a.png"
    assert "max-width:100%" in img["style"] and "height:auto" in img["style"] and "display:block" in img["style"]


def test_footer_links_and_text_part():
    mail = issue()
    assert "Manage your subscription" in mail.html and "Unsubscribe" in mail.html
    assert f"{SITE}/manage?t=abc" in mail.html and f"{SITE}/unsubscribe?t=abc" in mail.html
    assert "1 Example Way<br />Example City" in mail.html
    assert "Example &amp; Co" in mail.html
    assert f"{SITE}/unsubscribe?t=abc" in mail.text
    assert "BIG TITLE" in mail.text and "rel (https://example.com/a/b)" in mail.text
    assert "- one" in mail.text and "1. first" in mail.text and "> quoted" in mail.text
    assert max(len(line) for line in mail.text.splitlines() if "http" not in line) <= 76


@pytest.mark.parametrize("address", [None, "", "  \n "])
def test_postal_address_required(address):
    with pytest.raises(PostalAddressMissing):
        issue(footer=footer(address))


def test_escaping():
    mail = issue(subject="A <b> & C", preheader="x <i> & y")
    assert "<title>A &lt;b&gt; &amp; C</title>" in mail.html
    assert "x &lt;i&gt; &amp; y" in mail.html
    assert "<i>" not in mail.html
    assert mail.subject == "A <b> & C"


def test_subject_is_single_line():
    assert issue(subject="a\r\nBcc: x").subject == "a Bcc: x"


def test_transactional():
    mail = render_transactional(
        subject="Confirm", markus="Please confirm.", theme=THEME, site_name="Example Times",
        site_url=SITE, preheader="Confirm now", action_url=f"{SITE}/confirm?t=1", action_label="Confirm subscription",
    )
    assert "Confirm subscription" in mail.html and f"{SITE}/confirm?t=1" in mail.html
    assert "bgcolor=\"#b3261e\"" in mail.html
    assert "someone entered this address on Example Times" in mail.html
    assert f"{SITE}/confirm?t=1" in mail.text
    assert "Unsubscribe" not in mail.html
    plain = render_transactional(subject="x", markus="Hi", theme=THEME, site_name="S", site_url=SITE)
    assert "<a href=\"https://example.com\" style" in plain.html


def test_theme_from_config_and_validation():
    t = theme_from_config({"accent": "#111", "text": "#222", "background": "#333", "logoUrl": "https://example.com/l.png"}, "S")
    assert t.surface == "#ffffff" and t.logo_url == "https://example.com/l.png" and t.site_name == "S"
    assert 'src="https://example.com/l.png"' in issue(theme=t).html
    with pytest.raises(ValueError):
        theme_from_config({"accent": "#111"}, "S")
    with pytest.raises(ValueError):
        EmailTheme(accent='red;"><script>', text="#000", background="#fff")


def test_long_document_stays_under_gmail_clip():
    section = DOC.split("\n", 1)[1]
    big = "# Roundup\n\n" + "\n\n".join(
        f"## Story {i}\n\n" + section.replace("# Big title", "") for i in range(25)
    )
    mail = issue(markus=big)
    assert len(mail.html.encode()) < 100 * 1024


def test_text_linked_heading_keeps_url_and_case():
    url = "https://shipped.example.com/open-weights/Liquid-AI-Releases-A-Very-Long-Slug-That-Exceeds-The-Wrap-Width-Of-The-Text-Part"
    mail = render_issue(
        subject="S", markus=f"## [Liquid AI releases new model]({url})\n\nBody.", theme=THEME, footer=footer(), site_url=SITE
    )
    lines = mail.text.splitlines()
    assert "LIQUID AI RELEASES NEW MODEL" in lines
    assert f"<{url}>" in lines
    assert "(" + url.upper() not in mail.text


# --- Branding: bands, wordmark, branded buttons, dark mode ---------------------------------------------------------

BRAND_CONFIG = {
    "accent": "#1A1615", "text": "#1A1615", "background": "#F5F1EA", "surface": "#FFFFFF", "muted": "#5E5752",
    "fontFamily": "Archivo, Arial, Helvetica, sans-serif",
    "headerBand": "#C6F432", "headerText": "#1A1615",
    "buttonFill": "#C6F432", "buttonText": "#1A1615", "buttonBorder": "#1A1615",
    "footerBand": "#C6F432", "footerText": "#1A1615",
    "wordmarkImageUrl": "https://example.com/assets/wordmark-2x.png", "wordmarkAlt": "Example Times",
    "wordmarkWidth": 168, "wordmarkHeight": 40,
    "labelFont": "'JetBrains Mono', 'Courier New', monospace",
}
BRAND = theme_from_config(BRAND_CONFIG, "Example Times")


def test_default_theme_renders_exactly_as_before():
    """Hashes taken from develop before the branding fields existed."""
    import hashlib

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    mail = issue(theme=THEME, subject="Hello")
    assert digest(mail.html) == "dcfc692808c0062398e3b9a10f5a250664a18abf14bc7a2076bb47c9a890b9a9"
    assert digest(mail.text) == "ffd2392f22187b49406efba783635c701b33dee6cb5a65cdc0eb488508f9bcf3"
    conf = render_transactional(
        subject="Confirm", markus="Please confirm.", theme=THEME, site_name="Example Times", site_url=SITE,
        preheader="p", action_url=f"{SITE}/c?t=1", action_label="Confirm subscription",
    )
    assert digest(conf.html) == "321635f79cc2dc49942cc2d41e84c93b81b896692d7fb8ec9e1d3c19ffe2ca39"
    assert digest(conf.text) == "87c5efe1080e98055a90ad14449dde8cc6fc669a3a8fa4c1d581edabba0cabe2"
    assert "em-hband" not in mail.html and "em-fband" not in mail.html and "em-btn" not in conf.html


BRANDED_BEFORE_FOOTER_CHANGE = {  # a branded theme with neither footerWordmarkWidth nor archive_url, taken from develop at 11cc76e2
    "html": "1be71076a6d37c500eae46cbbf0466b80aa1457af75f3aae94d1713ac7e5035c", "text": "180fef046f30f3fc01cf601b1737d0aaf12fbc80da6ee45bee4bf6625d095ab5", "conf_html": "512bbc064bf3b86c62f9eed28f7c4f4fa50bd84c08e14a56d5dc0933df70804b", "conf_text": "011b2cd2a008cfaa4bcd55f312d8cbfa8200f71b68fd275f50e9af01ab3fe2e9",
}


def test_branded_theme_without_the_new_footer_fields_renders_exactly_as_before():
    import hashlib

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    mail = issue(theme=BRAND, list_name="The Shipped roundup")
    conf = render_transactional(
        subject="Confirm", markus="Please confirm.", theme=BRAND, site_name="Example Times", site_url=SITE,
        preheader="p", action_url=f"{SITE}/c?t=1", action_label="Confirm subscription",
    )
    assert digest(mail.html) == BRANDED_BEFORE_FOOTER_CHANGE["html"]
    assert digest(mail.text) == BRANDED_BEFORE_FOOTER_CHANGE["text"]
    assert digest(conf.html) == BRANDED_BEFORE_FOOTER_CHANGE["conf_html"]
    assert digest(conf.text) == BRANDED_BEFORE_FOOTER_CHANGE["conf_text"]


def test_theme_from_config_reads_the_branding_fields():
    t = BRAND
    assert (t.header_band, t.header_text, t.footer_band, t.footer_text) == ("#C6F432", "#1A1615", "#C6F432", "#1A1615")
    assert (t.button_fill, t.button_text, t.button_border) == ("#C6F432", "#1A1615", "#1A1615")
    assert (t.wordmark_image_url, t.wordmark_alt, t.wordmark_width, t.wordmark_height) == (
        "https://example.com/assets/wordmark-2x.png", "Example Times", 168, 40,
    )
    assert t.label_font.startswith("'JetBrains Mono'")
    plain = theme_from_config({"accent": "#111", "text": "#222", "background": "#333"}, "S")
    assert plain.header_band is None and plain.wordmark_image_url is None and not plain.is_branded


@pytest.mark.parametrize(
    "change",
    [
        {"headerBand": "red;"}, {"footerBand": "#fff\"><script>"}, {"buttonFill": "url(x)"}, {"buttonBorder": "a{b}"},
        {"labelFont": "x; y"}, {"wordmarkImageUrl": "http://example.com/w.png"}, {"wordmarkImageUrl": "//example.com/w.png"},
        {"wordmarkImageUrl": "https://example.com/w.png\"onerror=x"}, {"wordmarkWidth": None}, {"wordmarkHeight": 0},
        {"wordmarkWidth": "168"}, {"wordmarkAlt": "bad\nalt"},
    ],
)
def test_branding_values_are_validated(change):
    with pytest.raises(ValueError):
        theme_from_config({**BRAND_CONFIG, **change}, "S")


def test_issue_has_header_band_wordmark_and_label():
    html = issue(theme=BRAND, list_name="The Shipped roundup").html
    assert re.search(r'<td class="em-hband em-pad" bgcolor="#C6F432"', html)
    img = next(a for t, a in tags(html) if t == "img" and "wordmark" in a.get("src", ""))
    assert img["src"] == "https://example.com/assets/wordmark-2x.png"
    assert img["alt"] == "Example Times" and img["width"] == "168" and img["height"] == "40"
    assert "display:block" in img["style"]
    assert "The Shipped roundup" in html and "text-transform:uppercase" in html
    assert "'JetBrains Mono', 'Courier New', monospace" in html


def test_header_without_an_image_uses_the_site_name_and_the_subject_label():
    t = theme_from_config({**BRAND_CONFIG, "wordmarkImageUrl": None, "wordmarkWidth": None, "wordmarkHeight": None}, "S")
    mail = issue(theme=t, footer=footer(), subject="Subject line")
    assert 'class="em-hband' in mail.html and "<img" in mail.html  # the body image remains
    assert "wordmark" not in mail.html
    assert "Subject line" in mail.html.split("em-card")[0]  # label in the band, above the card
    assert mail.text.startswith("Example Times\nSUBJECT LINE\n\n")


def test_footer_band_has_links_reason_and_address():
    html = issue(theme=BRAND, list_name="L").html
    band = html[html.index('class="em-fband'):]
    assert 'bgcolor="#C6F432"' in band
    assert 'src="https://example.com/assets/wordmark-2x.png"' in band
    for label, url in (("Unsubscribe", f"{SITE}/unsubscribe?t=abc"), ("Email preferences", f"{SITE}/manage?t=abc")):
        assert f'<a href="{url}" style="color:#1A1615;text-decoration:underline;">{label}</a>' in band
    assert "You get this because you subscribed." in band and "1 Example Way<br />Example City" in band


def test_wordmark_alt_text_leads_the_plain_text():
    mail = issue(theme=BRAND, list_name="The Shipped roundup")
    assert mail.text.startswith("Example Times\nTHE SHIPPED ROUNDUP\n\nBIG TITLE")
    assert "<img" not in mail.text


def test_branded_button_has_fill_text_and_a_border():
    mail = render_transactional(
        subject="Confirm", markus="Please confirm.", theme=BRAND, site_name="Example Times", site_url=SITE,
        action_url=f"{SITE}/c?t=1", action_label="Confirm subscription",
    )
    assert 'bgcolor="#C6F432"' in mail.html and "border:1.5px solid #1A1615" in mail.html
    assert "padding:11px 18px" in mail.html and "font-size:15px" in mail.html and "border-radius" not in mail.html
    assert "Confirm subscription" in mail.html and "Confirm subscription: " in mail.text
    assert 'class="em-hband' in mail.html and 'class="em-fband' in mail.html
    assert "Unsubscribe" not in mail.html
    assert mail.text.startswith("Example Times\n\n")


def test_links_stay_underlined_in_a_branded_theme():
    html = issue(theme=BRAND).html
    body = html[html.index('class="em-card'):html.index('class="em-fband')]
    body_links = [a for t, a in tags(body) if t == "a"]
    assert body_links and all("text-decoration:underline" in a["style"] for a in body_links)
    assert "color:#1A1615;text-decoration:underline;" in html


def test_dark_mode_keeps_the_bands_and_swaps_the_page():
    html = issue(theme=BRAND).html
    dark = html[html.index("@media (prefers-color-scheme: dark)"):html.index("</style>")]
    assert ".em-bg { background-color: #1A1615 !important; }" in dark
    assert ".em-card { background-color: #26211F !important; }" in dark
    assert "color: #F5F1EA !important" in dark
    assert ".em-hband { background-color: #C6F432 !important; }" in dark and "color: #1A1615 !important" in dark
    assert ".em-fband { background-color: #C6F432 !important; }" in dark
    assert "color-scheme: light dark" in html and 'name="color-scheme"' in html
    conf = render_transactional(subject="c", markus="x", theme=BRAND, site_name="S", site_url=SITE, action_url=SITE, action_label="Go")
    assert "a.em-btn { color: #1A1615 !important" in conf.html and ".em-btn-cell { background-color: #C6F432 !important; }" in conf.html


def test_a_wordmark_alone_replaces_the_brand_line():
    t = theme_from_config({k: v for k, v in BRAND_CONFIG.items() if k not in ("headerBand", "footerBand", "buttonFill", "buttonBorder")}, "S")
    html = issue(theme=t).html
    assert "em-hband" not in html and "em-fband" not in html
    assert 'src="https://example.com/assets/wordmark-2x.png"' in html


SMALL = theme_from_config({**BRAND_CONFIG, "footerWordmarkWidth": 110}, "Example Times")
ARCHIVE = f"{SITE}/roundup/"


def archive_footer(**kw) -> EmailFooter:
    base = footer()
    return EmailFooter(**{**base.__dict__, "site_url": "https://shipped.example.com/", "archive_url": ARCHIVE, **kw})


def band_of(html: str) -> str:
    return html[html.index('class="em-fband'):]


def test_footer_wordmark_is_smaller_with_the_same_image_alt_and_aspect():
    html = issue(theme=SMALL).html
    header = html[html.index('class="em-hband'):html.index('class="em-card')]
    footer_band = band_of(html)
    assert 'width="168" height="40"' in header
    img = next(a for t, a in tags(footer_band) if t == "img")
    assert img["src"] == "https://example.com/assets/wordmark-2x.png" and img["alt"] == "Example Times"
    assert (img["width"], img["height"]) == ("110", "26")


def test_footer_wordmark_width_is_validated():
    for bad in (0, -1, 401, 110.5, "110", True):
        with pytest.raises(ValueError):
            theme_from_config({**BRAND_CONFIG, "footerWordmarkWidth": bad}, "S")
    assert theme_from_config({**BRAND_CONFIG, "footerWordmarkWidth": 400}, "S").footer_wordmark_width == 400


def test_footer_names_the_host_and_links_all_issues_with_every_link_underlined():
    mail = issue(theme=SMALL, footer=archive_footer(), list_name="L")
    band = band_of(mail.html)
    labels = re.findall(r'<a href="([^"]*)" style="color:#1A1615;text-decoration:underline;">([^<]*)</a>', band)
    assert [label for _, label in labels][-4:] == ["shipped.example.com", "All issues", "Unsubscribe", "Email preferences"]
    assert dict((label, url) for url, label in labels)["All issues"] == ARCHIVE
    assert dict((label, url) for url, label in labels)["shipped.example.com"] == "https://shipped.example.com/"
    assert mail.text.count(f"All issues: {ARCHIVE}\n") == 1
    assert "Unsubscribe: " in mail.text and "Manage your subscription: " in mail.text


def test_no_archive_means_no_all_issues_link():
    mail = issue(theme=SMALL, footer=archive_footer(archive_url=None))
    assert "All issues" not in mail.html and "All issues" not in mail.text
    assert "shipped.example.com" in band_of(mail.html)


def test_all_issues_link_in_the_plain_footer_too():
    mail = issue(theme=THEME, footer=archive_footer())
    assert f'<a href="{ARCHIVE}"' in mail.html and "All issues: " in mail.text and "em-fband" not in mail.html


def test_transactional_keeps_only_the_site_link():
    mail = render_transactional(
        subject="Confirm", markus="Please confirm.", theme=SMALL, site_name="Example Times", site_url="https://shipped.example.com/",
    )
    band = band_of(mail.html)
    assert re.findall(r"<a [^>]*>([^<]*)</a>", band) == ["shipped.example.com"]
    assert "Unsubscribe" not in mail.html and "All issues" not in mail.html


def test_all_issues_alone_keeps_the_site_name_and_the_uppercase_labels():
    band = band_of(issue(theme=BRAND, footer=archive_footer()).html)
    assert ">Example &amp; Co</a>" in band and ">All issues</a>" in band
    assert "text-transform:uppercase" in band and "shipped.example.com</a>" not in band


def test_the_smaller_footer_uses_plain_mono_lines():
    band = band_of(issue(theme=SMALL, footer=archive_footer()).html)
    assert "text-transform:uppercase" not in band
    assert "font-size:11px;font-weight:normal" in band
