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
