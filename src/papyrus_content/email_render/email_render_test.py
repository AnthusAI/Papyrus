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
