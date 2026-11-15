"""Path segments in each language's own words (features_backend/language-path-segments.feature): the synthetic site of language_serving_steps.py with a
``languages.segments`` table. Nothing reaches AWS and no model runs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from behave import given, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from features_backend.steps.language_serving_steps import ORIGIN, _canonical, _hreflang, _site  # noqa: E402
from papyrus_content.url_paths import encoded_path  # noqa: E402


def parse_segments(text: str) -> dict[str, dict[str, str]]:
    """``"es-419": articles is "articulos", concepts is "conceptos"; "zh-Hans": ...`` as ``{tag: {segment: translated}}``."""
    found = {}
    for part in text.split(";"):
        tag, _, rest = part.strip().partition(":")
        found[tag.strip().strip('"')] = {english.strip(): translated.strip().strip('"')
                                         for english, translated in (entry.split(" is ", 1) for entry in rest.split(", ") if entry.strip())}
    return found


@given("the language segments are {text}")
def step_segments(context, text):
    site = _site(context)
    site.languages["segments"] = parse_segments(text)
    if site.context is not None:   # the table changed after the site was built: the next projection reads it
        site.build()


@then('the page "{key}" exists and "{other}" does not')
def step_exists(context, key, other):
    site = _site(context)
    assert site.exists(key) and not site.exists(other), site.keys()


@then('the Spanish Concepts listing is "{spanish}" and the Chinese one "{chinese}"')
def step_concepts(context, spanish, chinese):
    site = _site(context)
    assert site.exists(spanish) and site.exists(chinese), site.keys()
    assert not site.exists("es/concepts/index.html") and not site.exists("zh/concepts/index.html")


def _absolute(path: str, encoded: bool) -> str:
    return ORIGIN + (encoded_path(path) if encoded else path)


@then('the English page names "{spanish}" and the percent-encoded "{chinese}" in hreflang')
def step_english_hreflang(context, spanish, chinese):
    found = dict(_hreflang(_site(context).text("articles/the-sound/index.html")))
    assert found["es"].startswith(_absolute(spanish, False)[: len(ORIGIN) + len("/es/articulos/")]) and found["es"] == _absolute(spanish, False), found
    assert found["zh-Hans"] == _absolute(chinese, True) and found["zh-Hans"].isascii(), found


@then('the Chinese page is canonical to the percent-encoded "{path}" and lists no raw Chinese character in any address')
def step_chinese_canonical(context, path):
    html = _site(context).text("zh" + path[len("/zh"):].rstrip("/") + "/index.html")
    assert _canonical(html) == _absolute(path, True), _canonical(html)
    addresses = re.findall(r'(?:href|content)="(https?://[^"]+|/[^"]*)"', html)
    assert addresses and all(address.isascii() for address in addresses), [address for address in addresses if not address.isascii()]


@then('the Spanish sitemap lists "{page}" and the Spanish listing "{listing}"')
def step_sitemap(context, page, listing):
    sitemap = _site(context).text("es/sitemap-0.xml")
    assert f"<loc>{ORIGIN}{page}</loc>" in sitemap and f"<loc>{ORIGIN}{listing}</loc>" in sitemap, sitemap
    assert "/es/articles/" not in sitemap


@then('the Spanish home links "{page}" and no "{old}"')
def step_home(context, page, old):
    html = _site(context).text("es/index.html")
    assert f'href="{page}"' in html and old not in html, html


@then('the Articles listing is offered in each language at "{english}", "{spanish}" and the percent-encoded "{chinese}"')
def step_articles_alternates(context, english, spanish, chinese):
    _offered(context, "articles", [english, spanish, encoded_path(chinese)])


@then('the Concepts listing is offered in each language at "{english}", "{spanish}" and the percent-encoded "{chinese}"')
def step_concepts_offered(context, english, spanish, chinese):
    _offered(context, "wiki", [english, spanish, encoded_path(chinese)])


def _offered(context, base: str, expected: list[str]) -> None:
    site = _site(context)
    view = site.context.projector._language_view(site.context.source.site_index())
    assert [alternate.url for alternate in view.listing_alternates(base)] == expected, view.listing_alternates(base)
    for url in expected:   # the switcher maps both ways: from any of the three pages the other two are offered
        assert view.links[url] == dict(zip(("en", "es-419", "zh-Hans"), expected)), view.links.get(url)


@then('the redirect store sends "{old}" to "{new}" and "{old_story}" to "{new_story}"')
def step_redirects(context, old, new, old_story, new_story):
    mapping = _site(context).redirects.mapping
    assert mapping.get(old) == new and mapping.get(old_story) == new_story, mapping


@then('it sends "{old}" to "{new}"')
def step_sends(context, old, new):
    assert _site(context).redirects.mapping.get(old) == new, _site(context).redirects.mapping


@then('it sends the percent-encoded "{old}" to the percent-encoded "{new}"')
def step_sends_encoded(context, old, new):
    mapping = _site(context).redirects.mapping
    assert mapping.get(encoded_path(old)) == encoded_path(new), mapping


@then('it sends "{old}" to the percent-encoded "{new}"')
def step_sends_to_encoded(context, old, new):
    assert _site(context).redirects.mapping.get(old) == encoded_path(new), _site(context).redirects.mapping


@then("no English address is redirected and every redirect source and target is ASCII")
def step_ascii(context):
    mapping = _site(context).redirects.mapping
    assert all(source.isascii() and target.isascii() for source, target in mapping.items()), mapping
    assert not any(source.startswith(("/articles/", "/wiki/")) for source in mapping), mapping
