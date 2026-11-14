from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.plugins import PLUGIN_PAGE_PREFIXES, PLUGIN_STATIC_ASSETS, plugin_static_files  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import ProjectedSite, fixture_settings  # noqa: E402

PAGES = {"privacy": "alexa/privacy/index.html", "terms": "alexa/terms/index.html"}
CONTACT = "https://contact.example.org/hello"
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def project(context, plugins, settings=None) -> None:
    context.site = ProjectedSite("sectioned", plugins=plugins, settings=settings)
    context.add_cleanup(context.site.cleanup)


def body_text(html: str) -> str:
    main = html.split("<main", 1)[1].split("</main>", 1)[0]
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", main)).strip()


def page(context, name: str) -> str:
    return context.site.text(PAGES[name])


@given("a projected site with the alexa plugin enabled")
def alexa_enabled(context) -> None:
    project(context, ("alexa",))


@given("a projected site with no plugins")
def no_plugins(context) -> None:
    project(context, ())


@given("a projected site with the alexa plugin enabled and a configured contact page")
def alexa_with_contact(context) -> None:
    settings = fixture_settings("sectioned")
    settings["footer"] = {**settings["footer"], "family": {"contactUrl": CONTACT}}
    project(context, ("alexa",), settings)


@then('the site has the pages "{first}" and "{second}"')
def has_pages(context, first: str, second: str) -> None:
    keys = context.site.tree
    assert first in keys and second in keys, sorted(keys)


@then('the site has no page under "{prefix}"')
def has_no_pages(context, prefix: str) -> None:
    assert not [key for key in context.site.tree if key.startswith(prefix)]


def complete_page(html: str) -> None:
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert '<header' in html and '<main' in html and "<footer" in html
    assert 'rel="stylesheet"' in html


@then("the privacy page is a complete page with the site's header, stylesheet and footer")
def privacy_chrome(context) -> None:
    complete_page(page(context, "privacy"))


@then("the terms page is a complete page with the site's header, stylesheet and footer")
def terms_chrome(context) -> None:
    complete_page(page(context, "terms"))


@then('neither page links to an "{fragment}" address')
def no_api_links(context, fragment: str) -> None:
    for name in PAGES:
        hrefs = re.findall(r'href="([^"]*)"', page(context, name))
        assert not [href for href in hrefs if fragment in href], hrefs
    assert 'href="/alexa/terms/"' in page(context, "privacy") and 'href="/alexa/privacy/"' in page(context, "terms")


@then('the privacy page names the publication "{name}"')
def privacy_names(context, name: str) -> None:
    assert name in body_text(page(context, "privacy"))


@then('the terms page names the publication "{name}"')
def terms_names(context, name: str) -> None:
    assert name in body_text(page(context, "terms"))


@then("the privacy page says the skill receives an anonymous Alexa user ID and device information")
def privacy_receives(context) -> None:
    assert "anonymous Alexa user ID and information about the device" in body_text(page(context, "privacy"))


@then("the privacy page says the skill does not receive voice recordings")
def privacy_voice(context) -> None:
    assert "does not receive your voice recording" in body_text(page(context, "privacy"))


@then("the privacy page says account linking is optional and uses Google sign-in")
def privacy_linking(context) -> None:
    text = body_text(page(context, "privacy"))
    assert "Linking is optional" in text and "sign in with Google" in text and "access token" in text


@then("the privacy page says votes are stored like votes made on the website")
def privacy_votes(context) -> None:
    assert "stored the same way as votes made on the website" in body_text(page(context, "privacy"))


@then("the privacy page says how to unlink in the Alexa app")
def privacy_unlink(context) -> None:
    assert "Open the Alexa app" in body_text(page(context, "privacy"))


@then("each page is under 400 words")
def short_pages(context) -> None:
    for name in PAGES:
        count = len(body_text(page(context, name)).split())
        assert count < 400, (name, count)


@then("the privacy page links to the configured contact page")
def privacy_contact_url(context) -> None:
    assert f'href="{CONTACT}"' in page(context, "privacy")


@then("the privacy page points to the footer's Contact link")
def privacy_footer_contact(context) -> None:
    assert "Contact link in the footer" in body_text(page(context, "privacy"))


@then("neither page contains an email address")
def no_emails(context) -> None:
    for name in PAGES:
        assert not EMAIL.search(page(context, name)), name
        assert "mailto:" not in page(context, name)


@then('the alexa plugin protects the page prefix "{prefix}" from orphan deletion')
def protected_prefix(context, prefix: str) -> None:
    assert prefix in PLUGIN_PAGE_PREFIXES["alexa"]


@then("the TypeScript and Python lists of alexa static assets are the same")
def static_lists_match(context) -> None:
    source = (REPO_ROOT / "amplify" / "plugins" / "alexa" / "static-assets.ts").read_text(encoding="utf-8")
    declaration = re.search(r"ALEXA_STATIC_ASSETS: readonly string\[\] = \[(.*?)\];", source, re.S)
    assert declaration is not None
    typescript = sorted(re.findall(r'"([^"]+)"', declaration.group(1)))
    assert typescript == sorted(PLUGIN_STATIC_ASSETS["alexa"]), (typescript, sorted(PLUGIN_STATIC_ASSETS["alexa"]))


@then("the projector knows every plugin in the registry")
def knows_registry(context) -> None:
    source = (REPO_ROOT / "amplify" / "plugins" / "registry.ts").read_text(encoding="utf-8")
    names = re.findall(r'^\s*"?([\w-]+)"?:\s*\w+Plugin,', source, re.M)
    assert "home-page" in names and "alexa" in names, names
    missing = [name for name in names if name not in PLUGIN_STATIC_ASSETS]
    assert not missing, missing
    plugin_static_files(names)


@then("asking the projector for the home-page plugin's files does not fail")
def home_page_known(context) -> None:
    assert plugin_static_files(["home-page"]) == {}
