"""The Story types a site defines (features_backend/story-types.feature)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.content_item_lifecycle import is_story_item_type  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.story_types import site_story_types  # noqa: E402
from standard_frontend_content_support import cms_site, item, settings  # noqa: E402
from test_content_actions_handler import ContentActionsHandlerTest, save_payload  # noqa: E402


def held(context) -> SimpleNamespace:
    if not hasattr(context, "st"):
        context.st = SimpleNamespace(projection=None, error=None, handler=None, ids={}, result=None, site=None, items=[], urls={})
    return context.st


def use_site_directory(context, projection: dict | None) -> None:
    """Point PAPYRUS_SITE_STATIC_DIR at a directory holding this projection.json (none when `projection` is None)."""
    directory = tempfile.mkdtemp(prefix="story-types-")
    context.add_cleanup(shutil.rmtree, directory, True)
    if projection is not None:
        (Path(directory) / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
    patch = mock.patch.dict(os.environ, {"PAPYRUS_SITE_STATIC_DIR": directory})
    patch.start()
    context.add_cleanup(patch.stop)


@given('the site\'s default Story type is "{item_type}"')
def _default_type(context, item_type):
    use_site_directory(context, {"storyTypes": {"default": item_type}})


@given('a site whose projection.json declares the Story types "{first}" and "{second}" with the default "{default}"')
def _declares(context, first, second, default):
    use_site_directory(context, {"storyTypes": {"default": default, "types": [first, second]}})


@given('a site whose type settings are article "{articles}" and post "{posts}" and which declares no Story types')
def _routed_only(context, articles, posts):
    use_site_directory(context, {"urls": {"types": {"article": {"base": articles}, "post": {"base": posts}}}})


@given("a site with no projection.json")
def _none(context):
    use_site_directory(context, None)


@given('a site whose projection.json declares the default Story type "{item_type}"')
def _bad(context, item_type):
    held(context).projection = {"site": {"name": "Site"}, "storyTypes": {"default": item_type}}


@then('the site offers "{offered}" and its default type is "{default}"')
def _offers(context, offered, default):
    found = site_story_types()
    assert ", ".join(found.offered) == offered and found.default == default, found


@then("the declaration is refused because that type is not a Story")
def _refused(context):
    try:
        standard_settings_from_mapping(held(context).projection)
    except ValueError as error:
        assert "not a Story" in str(error), error
    else:
        raise AssertionError("the declaration was accepted")


def quoted_list(text: str) -> list[str]:
    return [part.strip().strip('"') for part in text.replace(" and ", ", ").split(",") if part.strip()]


@then("{types} are Story types")
def _are_stories(context, types):
    assert all(is_story_item_type(name) for name in quoted_list(types)), types


@then("{types} are not")
def _are_not(context, types):
    assert not any(is_story_item_type(name) for name in quoted_list(types)), types


@given('Items of the types "{first}", "{second}" and "{third}"')
def _items_of_types(context, first, second, third):
    held(context).types = [first, second, third]


@then("the Stories among them are the guide and the article")
def _stories_among(context):
    assert [name for name in held(context).types if is_story_item_type(name)] == ["guide", "article"]


# --- a new version changes the type ---------------------------------------------------------------------------------

def handler(context) -> ContentActionsHandlerTest:
    state = held(context)
    if state.handler is None:
        state.handler = ContentActionsHandlerTest("test_derive_ok_reports_size_and_optional_ir")
        state.handler.setUp()
        context.add_cleanup(state.handler.doCleanups)
    return state.handler


@given("a published article")
def _published_article(context):
    state = held(context)
    test = handler(context)
    state.first = test.call("saveItemDraft", save_payload())["item"]
    test.call("publishItem", {"id": state.first["id"]})


@when("the editor saves a new version of it as a post")
def _new_version_post(context):
    state = held(context)
    state.result = handler(context).call(
        "saveItemDraft", save_payload(id=state.first["id"], type="post", newVersion=True, expectedContentHash=state.first["contentHash"], bodyMarkus="Changed\n"),
    )


@then("the new version is a post and the published article keeps its type")
def _version_type(context):
    state = held(context)
    tables = handler(context).client.tables
    assert tables["Item"][state.result["item"]["id"]]["type"] == "post"
    assert tables["PublishedItem"]["published-" + state.first["id"]]["type"] == "article"


@then('publishing the new version reports that the type changed from "{previous}"')
def _publish_reports(context, previous):
    state = held(context)
    published = handler(context).call("publishItem", {"id": state.result["item"]["id"]})
    assert published["typeChangedFrom"] == previous, published


@when("the editor saves it in place as a post")
def _in_place(context):
    state = held(context)
    state.result = handler(context).call("saveItemDraft", save_payload(id=state.first["id"], type="post", expectedContentHash=state.first["contentHash"]))


@then("the save is refused and says to save a new version")
def _refused_in_place(context):
    result = held(context).result
    assert not result["ok"] and result["errors"][0]["code"] == "type-locked" and "new version" in result["errors"][0]["message"], result


# --- a type with no address -----------------------------------------------------------------------------------------

@given('a site that gives the type "article" the base "articles" and names no other type')
def _only_articles(context):
    held(context).urls = {"style": "directory", "types": {"article": {"base": "articles"}}}


@given('a site that gives the types "article" and "guide" the bases "articles" and "guides"')
def _articles_and_guides(context):
    held(context).urls = {"style": "directory", "types": {"article": {"base": "articles"}, "guide": {"base": "guides"}}}


@given('a published Story of the type "{item_type}"')
def _story_of_type(context, item_type):
    held(context).items = [item("an-article", section=None, type="article", date="2026-03-01"), item("a-guide", section=None, type=item_type, date="2026-03-02")]


@when("the site pages are built")
def _projected(context):
    state = held(context)
    site = cms_site(settings(urls=state.urls, listings={"types": ["article"]}), state.items)
    context.add_cleanup(site.cleanup)
    state.site = site


@then("no page is built for the guide")
def _no_guide(context):
    keys = set(held(context).site.tree)
    assert not [key for key in keys if "a-guide" in key], sorted(keys)


@then('the article has its page under "/{base}/"')
@then('the guide has its page under "/{base}/"')
def _page_under(context, base):
    keys = set(held(context).site.tree)
    assert any(key.startswith(f"{base}/") and key.endswith("index.html") and key != f"{base}/index.html" for key in keys), sorted(keys)


@given('a site that gives the types "article" and "post" the bases "articles" and "posts"')
def _articles_and_posts(context):
    held(context).urls = {"style": "directory", "types": {"article": {"base": "articles"}, "post": {"base": "posts"}}}


@given('an article that is live under "/articles/moving/"')
def _live_article(context):
    pass


@when("a version of it as a post is published")
def _post_published(context):
    pass


@then('the page is under "/posts/moving/", the old page is gone and "/articles/moving/" redirects to it')
def _moved(context):
    # The projection of the move is exercised end to end, with a redirect store, by the test of the same name.
    from test_story_types import test_publishing_a_changed_type_moves_the_page_and_leaves_a_redirect

    directory = Path(tempfile.mkdtemp(prefix="story-types-move-"))
    context.add_cleanup(shutil.rmtree, directory, True)
    test_publishing_a_changed_type_moves_the_page_and_leaves_a_redirect(directory)
