from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.email_render import EmailFooter, render_issue, render_transactional, theme_from_config  # noqa: E402

SITE = "https://example.com/"
LIME = "#C6F432"
INK = "#1A1615"
WORDMARK = "https://example.com/assets/wordmark-2x.png"
BASE = {"accent": INK, "text": INK, "background": "#F5F1EA", "surface": "#FFFFFF", "muted": "#5E5752"}
BODY = "# Liquid AI releases a model\n\nRead [the announcement](/open-weights/liquid/).\n"
BEFORE_BRANDING = {
    "confirm_html": "321635f79cc2dc49942cc2d41e84c93b81b896692d7fb8ec9e1d3c19ffe2ca39",
    "confirm_text": "87c5efe1080e98055a90ad14449dde8cc6fc669a3a8fa4c1d581edabba0cabe2",
}
FOOTER = EmailFooter(
    site_name="Example Times", site_url=SITE, reason="You get this because you subscribed.",
    manage_url=f"{SITE}newsletter/preferences/", unsubscribe_url=f"{SITE}newsletter/preferences/",
    postal_address="1 Example Way\nExample City, EX 00000",
)


def theme(context, **extra):
    context.theme_config = {**BASE, **extra}
    context.theme = theme_from_config(context.theme_config, "Example Times")


def wordmark_fields(alt: str, width: int, height: int) -> dict:
    return {"wordmarkImageUrl": WORDMARK, "wordmarkAlt": alt, "wordmarkWidth": width, "wordmarkHeight": height}


def issue(context, list_name: str):
    context.mail = render_issue(
        subject="Liquid AI releases a model", markus=BODY, theme=context.theme, footer=FOOTER, site_url=SITE, list_name=list_name
    )


def confirmation(context, theme_value=None):
    return render_transactional(
        subject="Confirm", markus="Please confirm.", theme=theme_value or context.theme, site_name="Example Times",
        site_url=SITE.rstrip("/"), preheader="p", action_url="https://example.com/c?t=1", action_label="Confirm subscription",
    )


def band(html: str, name: str) -> str:
    start = html.index(f'class="{name}')
    return html[start : html.index("</td></tr>", start)]


@given('a branded theme with a lime header band and a wordmark image {width:d} by {height:d} with alt text "{alt}"')
def header_with_wordmark(context, width: int, height: int, alt: str) -> None:
    theme(context, headerBand=LIME, headerText=INK, **wordmark_fields(alt, width, height))


@given("a branded theme with a lime header band and no wordmark image")
def header_without_wordmark(context) -> None:
    theme(context, headerBand=LIME, headerText=INK)


@given('a branded theme with a lime footer band and a wordmark image {width:d} by {height:d} with alt text "{alt}"')
def footer_with_wordmark(context, width: int, height: int, alt: str) -> None:
    theme(context, footerBand=LIME, footerText=INK, **wordmark_fields(alt, width, height))


@given("a branded theme with lime buttons, ink button text and an ink button border")
def branded_buttons(context) -> None:
    theme(context, buttonFill=LIME, buttonText=INK, buttonBorder=INK)


@given("a branded theme with a lime header band and a lime footer band")
def both_bands(context) -> None:
    theme(context, headerBand=LIME, headerText=INK, footerBand=LIME, footerText=INK)


@given("a theme with only an accent, text and background")
def plain_theme(context) -> None:
    context.theme_config = {"accent": "#b3261e", "text": "#222222", "background": "#f1ece4"}  # as in the recorded hashes
    context.theme = theme_from_config(context.theme_config, "Example Times")


@when('an alert email is rendered for the list "{name}"')
def render_alert(context, name: str) -> None:
    issue(context, name)


@when('a roundup email is rendered for the list "{name}"')
def render_roundup(context, name: str) -> None:
    issue(context, name)


@when("the confirmation email is rendered")
def render_confirmation(context) -> None:
    context.mail = confirmation(context)


@when("the confirmation email and an alert email are rendered")
def render_both(context) -> None:
    context.confirmation = confirmation(context)
    issue(context, "Alerts")


@when('a theme is built with {field} set to "{value}"')
def build_theme(context, field: str, value: str) -> None:
    config = {**BASE, **wordmark_fields("Example", 168, 40), field: value}
    try:
        theme_from_config(config, "Example")
        context.refused = False
    except ValueError:
        context.refused = True


@then('the header band is lime and holds an image with alt text "{alt}", width {width:d} and height {height:d}')
def header_image(context, alt: str, width: int, height: int) -> None:
    header = band(context.mail.html, "em-hband")
    assert f'bgcolor="{LIME}"' in header, header
    assert f'alt="{alt}" width="{width}" height="{height}"' in header, header
    assert "display:block" in header


@then('the list name "{name}" is in the header band')
def list_name_in_header(context, name: str) -> None:
    assert name in band(context.mail.html, "em-hband")


@then('the plain-text part starts with "{start}"')
def text_starts(context, start: str) -> None:
    assert context.mail.text.startswith(start), context.mail.text[:80]


@then("the header band shows the site name as text")
def header_text(context) -> None:
    header = band(context.mail.html, "em-hband")
    assert ">Example Times</a>" in header and "<img" not in header


@then("the email has no wordmark image")
def no_wordmark(context) -> None:
    assert "wordmark" not in context.mail.html


@then("the footer band is lime and shows the wordmark, an underlined unsubscribe link and an underlined preferences link")
def footer_band(context) -> None:
    footer = band(context.mail.html, "em-fband")
    assert f'bgcolor="{LIME}"' in footer and WORDMARK in footer
    for label in ("Unsubscribe", "Email preferences"):
        assert re.search(rf'text-decoration:underline;">{label}</a>', footer), label


@then("the footer band shows the reason sentence and the postal address")
def footer_reason(context) -> None:
    footer = band(context.mail.html, "em-fband")
    assert "You get this because you subscribed." in footer and "1 Example Way<br />Example City, EX 00000" in footer


@then('the button is filled lime, has the label "{label}" and a 1.5px ink border')
def button(context, label: str) -> None:
    html = context.mail.html
    assert f'bgcolor="{LIME}"' in html and f"border:1.5px solid {INK}" in html and f">{label}</a>" in html


@then("the button has square corners")
def square(context) -> None:
    assert "border-radius" not in context.mail.html


@then("every link in the body is underlined")
def underlined(context) -> None:
    html = context.mail.html
    body = html[html.index('class="em-card') : html.index("</td></tr>", html.index('class="em-card'))]
    links = re.findall(r'<a [^>]*style="([^"]*)"', body)
    assert links and all("text-decoration:underline" in style for style in links), links


@then("they have no header band, footer band or branded button")
def unbranded(context) -> None:
    for html in (context.confirmation.html, context.mail.html):
        assert "em-hband" not in html and "em-fband" not in html and "em-btn" not in html


@then("their markup matches what the renderer produced before branding existed")
def unchanged(context) -> None:
    assert hashlib.sha256(context.confirmation.html.encode()).hexdigest() == BEFORE_BRANDING["confirm_html"]
    assert hashlib.sha256(context.confirmation.text.encode()).hexdigest() == BEFORE_BRANDING["confirm_text"]
    assert "color: #9ec5ff" in context.mail.html and "#111111" in context.mail.html


@then("the email declares both colour schemes")
def schemes(context) -> None:
    html = context.mail.html
    assert 'name="color-scheme" content="light dark"' in html and "color-scheme: light dark" in html


def dark_block(context) -> str:
    html = context.mail.html
    return html[html.index("@media (prefers-color-scheme: dark)") : html.index("</style>")]


@then("in dark mode the page and the panels turn to dark ink and the text to paper")
def dark_tokens(context) -> None:
    dark = dark_block(context)
    assert ".em-bg { background-color: #1A1615 !important; }" in dark
    assert ".em-card { background-color: #26211F !important; }" in dark
    assert "color: #F5F1EA !important" in dark


@then("in dark mode the bands stay lime with ink text")
def dark_bands(context) -> None:
    dark = dark_block(context)
    assert f".em-hband {{ background-color: {LIME} !important; }}" in dark
    assert f".em-fband {{ background-color: {LIME} !important; }}" in dark
    assert f"{{ color: {INK} !important; }}" in dark


@then("building the theme fails")
def refused(context) -> None:
    assert context.refused is True
