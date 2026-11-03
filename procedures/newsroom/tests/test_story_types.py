"""The Story types a site offers: one definition per language, the same cases as scripts/test-story-types.ts."""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.content_item_lifecycle import SYSTEM_ITEM_TYPES, UNTYPED_ITEM_TYPE, build_new_content_item_version  # noqa: E402
from papyrus_content.projection.standard.config import standard_settings_from_mapping  # noqa: E402
from papyrus_content.story_types import default_story_type, require_story_type, site_story_types, story_types_from_mapping, type_for_new_story  # noqa: E402

CASES = json.loads((REPO_ROOT / "scripts" / "fixtures" / "story-types-cases.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_the_shared_cases(case):
    if case["expect"].get("error"):
        with pytest.raises(ValueError):
            story_types_from_mapping(case["projection"])
        return
    found = story_types_from_mapping(case["projection"])
    assert found.default == case["expect"]["default"]
    assert list(found.offered) == case["expect"]["types"]


def test_the_system_set_is_the_same_list_in_typescript():
    source = (REPO_ROOT / "lib" / "content-item-lifecycle.ts").read_text(encoding="utf-8")
    declared = re.search(r"export const SYSTEM_ITEM_TYPES: readonly string\[\] = \[([^\]]*)\]", source)
    assert declared is not None
    assert tuple(re.findall(r'"([^"]+)"', declared.group(1))) == SYSTEM_ITEM_TYPES


def test_a_system_type_is_refused_as_a_story_type():
    assert require_story_type("guide") == "guide"
    for name in (*SYSTEM_ITEM_TYPES, "Guide", "", None):
        with pytest.raises(ValueError):
            require_story_type(name)


def test_the_site_reads_its_types_from_the_projection_json_it_ships(tmp_path):
    (tmp_path / "projection.json").write_text(json.dumps({"storyTypes": {"default": "post", "types": ["post", "guide"]}}), encoding="utf-8")
    environment = {"PAPYRUS_SITE_STATIC_DIR": str(tmp_path)}
    assert site_story_types(environment).offered == ("post", "guide")
    assert default_story_type(environment) == "post"


def test_with_no_projection_json_there_is_no_default_and_a_new_story_has_no_type():
    assert default_story_type({}) is None
    assert type_for_new_story({}) == "untyped"
    assert site_story_types({"PAPYRUS_SITE_STATIC_DIR": "/no/such/directory"}).offered == ()


def test_the_untyped_value_is_the_same_string_in_typescript_and_cannot_be_chosen_as_a_type():
    source = (REPO_ROOT / "lib" / "content-item-lifecycle.ts").read_text(encoding="utf-8")
    assert re.search(r'export const UNTYPED_ITEM_TYPE = "untyped"', source) and UNTYPED_ITEM_TYPE == "untyped"
    with pytest.raises(ValueError, match="no type yet"):
        require_story_type("untyped")


def test_an_untyped_story_cannot_be_published():
    from papyrus_content.publishing import PublishError, publish_item
    from procedures.newsroom.tests.fake_client import FakeAuthoringClient

    client = FakeAuthoringClient()
    client.upsert("Item", {"id": "item-a", "lineageId": "item-a", "type": "untyped", "typeStatus": "untyped#draft", "slug": "a", "status": "draft", "bodyMarkus": "Body.\n", "metadata": "{}", "contentHash": "h"})
    with pytest.raises(PublishError) as raised:
        publish_item(client, "item-a", actor="editor")
    assert raised.value.code == "type-required"


def test_a_new_content_item_gets_the_sites_default_type_unless_one_is_given(tmp_path, monkeypatch):
    (tmp_path / "projection.json").write_text(json.dumps({"storyTypes": {"default": "guide"}}), encoding="utf-8")
    monkeypatch.setenv("PAPYRUS_SITE_STATIC_DIR", str(tmp_path))
    arguments = dict(lineage_id="content-item-x", title="T", summary=None, section_key=None, stage="idea", actor_label="AI", now="2026-11-02T00:00:00Z")
    assert build_new_content_item_version(**arguments)["type"] == "guide"
    assert build_new_content_item_version(**arguments)["typeStatus"] == "guide#draft"
    assert build_new_content_item_version(**arguments, item_type="post")["type"] == "post"


def test_a_bad_story_types_declaration_fails_the_projection_settings():
    base = {"site": {"name": "Site"}}
    standard_settings_from_mapping({**base, "storyTypes": {"default": "post", "types": ["post"]}})
    with pytest.raises(ValueError, match="storyTypes.default"):
        standard_settings_from_mapping({**base, "storyTypes": {"default": "page"}})


def test_publishing_a_changed_type_moves_the_page_and_leaves_a_redirect(tmp_path):
    from papyrus_content.projection.engine import ProjectionContext, project
    from papyrus_content.projection.projector import MarkusSiteProjector
    from papyrus_content.projection.source import PublishedContentSource
    from papyrus_content.publishing import ItemFields, publish_item, save_item
    from procedures.newsroom.tests.fake_client import FakeAuthoringClient
    from procedures.newsroom.tests.incremental_site import FakeRedirectStore
    from procedures.newsroom.tests.projection_fixtures import ACTOR, NOW, RecordingWriter

    static = tmp_path / "static"
    static.mkdir()
    (static / "projection.json").write_text(json.dumps({
        "site": {"name": "Example", "productionUrl": "https://example.org"},
        "urls": {"style": "directory", "types": {"article": {"base": "articles"}, "post": {"base": "posts"}}},
        "listings": {"types": ["article", "post"]},
    }), encoding="utf-8")
    client, redirects, writer = FakeAuthoringClient(), FakeRedirectStore(), RecordingWriter(tmp_path / "site")
    context = ProjectionContext(
        source=PublishedContentSource(client), projector=MarkusSiteProjector.from_static_directory(static), writer=writer, redirect_store=redirects,
    )
    context.source.extra_types = context.projector.projectable_types
    fields = dict(slug="moving", section=None, front_matter_yaml="title: Moving\ndate: '2026-03-01'\n", body_markus="Body.\n", aliases=[], id="item-moving")
    save_item(client, ItemFields(type="article", **fields), actor=ACTOR, now=NOW)
    publish_item(client, "item-moving", actor=ACTOR, now=NOW)
    first = project(context, "item-moving")
    assert first.item_paths[0] == "articles/moving/index.html"
    # the new version is another type; the live row keeps the old one until it is published
    save_item(client, ItemFields(type="post", **fields), actor=ACTOR, now=NOW, allow_published_slug_change=True)
    publish_item(client, "item-moving", actor=ACTOR, now=NOW)
    second = project(context, "item-moving")
    assert second.item_paths[0] == "posts/moving/index.html"
    assert redirects.get("/articles/moving/") == "/posts/moving/", redirects.mapping
    assert not (tmp_path / "site" / "articles" / "moving" / "index.html").exists()
