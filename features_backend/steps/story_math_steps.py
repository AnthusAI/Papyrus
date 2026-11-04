from __future__ import annotations

import sys
from pathlib import Path

from behave import then, when

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.email_render.render import _body as email_body  # noqa: E402
from papyrus_content.email_render.theme import EmailTheme  # noqa: E402
from papyrus_content.markus_renderer import derive_body  # noqa: E402


@when("I derive the body of an article containing")
def derive_article(context) -> None:
    context.derivation = derive_body("", context.text + "\n")


@then("the derivation has no warnings")
def no_warnings(context) -> None:
    assert context.derivation.warnings == (), context.derivation.warnings


@then('the derivation warns with code "{code}" on line {line:d}')
def warns(context, code: str, line: int) -> None:
    found = [(warning.code, warning.line) for warning in context.derivation.warnings]
    assert (code, line) in found, found


@then('the stored body keeps the TeX source "{tex}"')
def keeps_source(context, tex: str) -> None:
    values = [block.get("value", "") for block in context.derivation.body_ir["document"]["children"] if block["type"] == "code"]
    assert any(tex in value for value in values), values


@when("I render an email whose body is")
def render_email(context) -> None:
    theme = EmailTheme(accent="#b3261e", text="#222222", background="#f1ece4")
    context.email_html, context.email_text = email_body(context.text + "\n", theme, "https://example.org")


@then('the email html says "{text}"')
def email_html_says(context, text: str) -> None:
    assert text in context.email_html, context.email_html[:3000]


@then('the email html does not say "{text}"')
def email_html_does_not_say(context, text: str) -> None:
    assert text not in context.email_html, context.email_html[:3000]


@then('the email text says "{text}"')
def email_text_says(context, text: str) -> None:
    assert text in context.email_text, context.email_text
