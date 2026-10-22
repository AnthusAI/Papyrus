from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.projection.engine import project, project_all  # noqa: E402
from papyrus_content.projection.projector import MarkusSiteProjector  # noqa: E402
from papyrus_content.projection.standard.redirects import first_match  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.publishing import unpublish_item  # noqa: E402
from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW  # noqa: E402
from procedures.newsroom.tests.standard_frontend_support import (  # noqa: E402
    ProjectedSite,
    edit_item,
    fixture_settings,
    static_directory,
    written_keys,
)


def remember(context, site: ProjectedSite) -> None:
    context.site = site
    context.add_cleanup(site.cleanup)


def listed(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


@given("a standard site with only a name and the flat fixture content")
def only_a_name(context) -> None:
    settings = {"site": {"name": "Example", "productionUrl": "https://example.org"}}
    remember(context, ProjectedSite(settings=settings, content=Path(__file__).resolve().parents[1] / "fixtures" / "standard-site" / "flat" / "content"))


@given("a standard site with hand-published routes that carry Markdown twins")
def static_twins_site(context) -> None:
    settings = {
        "site": {"name": "Example", "productionUrl": "https://example.org"},
        "static": {"copy": ["site"]},
        "sitemap": {"extra": ["/docs/usage/", "/docs/missing/"]},
    }
    files = {
        "site/docs/usage/index.html": "<html></html>",
        "site/docs/usage/index.md": "# Using the widget\n\nAdd the script to a page.\n",
    }
    remember(
        context,
        ProjectedSite(settings=settings, extra_files=files, content=Path(__file__).resolve().parents[1] / "fixtures" / "standard-site" / "flat" / "content"),
    )


@given("the standard sectioned fixture site")
def sectioned_site(context) -> None:
    remember(context, ProjectedSite("sectioned"))


@given("the standard flat fixture site")
def flat_site(context) -> None:
    remember(context, ProjectedSite("flat"))


@given('the standard flat fixture site served from "{origin}"')
def flat_site_elsewhere(context, origin: str) -> None:
    remember(context, ProjectedSite("flat", environ={"PAPYRUS_SITE_PUBLIC_URL": origin}))


@given("a static directory whose projection.json has no site object")
def plain_directory(context) -> None:
    work = tempfile.TemporaryDirectory()
    context.add_cleanup(work.cleanup)
    context.projector = MarkusSiteProjector.from_static_directory(static_directory(Path(work.name), {}))


@given("a standard site with only a name and no site URL")
def no_site_url(context) -> None:
    settings = {"site": {"name": "No Origin"}, "publicData": {}}
    remember(context, ProjectedSite(settings=settings, content=Path(__file__).resolve().parents[1] / "fixtures" / "standard-site" / "flat" / "content"))


def public_entries(context) -> dict[str, dict]:
    return {entry["url"]: entry for entry in json.loads(context.site.text("_data/search-index.json"))}


@then('the standard public entry "{url}" has the image "{image}"')
def public_entry_image(context, url: str, image: str) -> None:
    assert public_entries(context)[url].get("image") == image, public_entries(context)[url]


@then('the standard public entry "{url}" has the publication "{name}"')
def public_entry_publication(context, url: str, name: str) -> None:
    assert public_entries(context)[url].get("publication") == name, public_entries(context)[url]


@then("no standard public entry has an image")
def no_public_image(context) -> None:
    assert not [url for url, entry in public_entries(context).items() if "image" in entry]


@then("every standard public entry has the image its page names in its Open Graph tag")
def public_image_matches_open_graph(context) -> None:
    for url, entry in public_entries(context).items():
        assert f'<meta property="og:image" content="{entry["image"]}">' in context.site.text(url.lstrip("/")), url


@then("the standard projector choice is the bare Markus projector")
def bare_projector(context) -> None:
    assert type(context.projector) is MarkusSiteProjector


@then('the standard site has these pages: "{keys}"')
def has_pages(context, keys: str) -> None:
    missing = [key for key in listed(keys) if key not in context.site.tree]
    assert not missing, missing


@then('the standard site lacks these pages: "{keys}"')
def lacks_pages(context, keys: str) -> None:
    present = [key for key in listed(keys) if key in context.site.tree]
    assert not present, present


@then("no standard page lives under a section base")
def no_section_base(context) -> None:
    nested = [key for key in context.site.tree if "/" in key and not key.startswith(("archive/", "tags/", "css/", "_data/", "_plugins/"))]
    assert not nested, nested


@then('the standard page "{key}" says "{text}"')
def page_says(context, key: str, text: str) -> None:
    assert text in context.site.text(key), (key, text)


@then('the standard page "{key}" does not say "{text}"')
def page_does_not_say(context, key: str, text: str) -> None:
    assert key in context.site.tree and text not in context.site.text(key), (key, text)


@when('the body of the standard item "{item_id}" is edited and projected')
def body_edited(context, item_id: str) -> None:
    context.report = edit_item(context.site, item_id, body="A new body.\n")


@when('the title of the standard item "{item_id}" is changed to "{title}" and projected')
def title_changed(context, item_id: str, title: str) -> None:
    context.report = edit_item(context.site, item_id, title=title)


@when('the standard item "{item_id}" is unpublished and projected')
def unpublished(context, item_id: str) -> None:
    unpublish_item(context.site.client, item_id, actor=ACTOR, now=NOW)
    context.report = project(context.site.context, item_id, unpublished=True)


@then('the standard site wrote exactly "{keys}"')
def written_exactly(context, keys: str) -> None:
    assert written_keys(context.site) == set(listed(keys)), written_keys(context.site)


@then('the standard site wrote at least "{keys}"')
def written_include(context, keys: str) -> None:
    missing = set(listed(keys)) - written_keys(context.site)
    assert not missing, (missing, written_keys(context.site))


@then("a fresh standard projection finds the same pages")
def fresh_projection_matches(context) -> None:
    site = context.site
    before = site.digests()
    report = project_all(site.context)
    assert report.ok and site.digests() == before, report.written


def edge_rules(context):
    return standard_settings_from_mapping(fixture_settings("sectioned")).edge_rules()


@then('the standard edge rules send "{source}" to "{target}"')
def edge_sends(context, source: str, target: str) -> None:
    assert first_match(edge_rules(context), source) == (target, 301)


@then('the standard edge rules leave "{path}" alone')
def edge_leaves(context, path: str) -> None:
    assert first_match(edge_rules(context), path) is None


@then('the standard entry date of "{written}" is "{expected}"')
def entry_date(context, written: str, expected: str) -> None:
    from papyrus_content.projection.standard.entries import calendar_date

    assert calendar_date(written) == expected, (written, calendar_date(written), expected)


@then('the standard entry date of "{written}" is blank')
def entry_date_blank(context, written: str) -> None:
    entry_date(context, written, "")
