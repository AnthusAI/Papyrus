"""The reviewer of a published version (src/papyrus_content/published_reviewer.py, features_backend/stories/published-reviewer.feature). The backend is a fake."""

from __future__ import annotations

import json

from papyrus_content import story_checklist as checklist
from papyrus_content.projection.directory_source import DirectoryContentSource
from papyrus_content.projection.source import summary_from_row
from papyrus_content.published_reviewer import (
    REVIEWED_BY_KEY,
    front_matter_with_recorded_reviewer,
    public_reviewer_name,
    reviewed_by_from_stamp,
)
from papyrus_content.publishing import publish_item, published_item_id_for
from papyrus_content.story_reporting import create_story, save_story_version
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

REVIEW_TIME = "2026-11-22T10:00:00Z"


def a_story(client) -> dict:
    return create_story(client, title="A Story", section_key=None, actor="AI", item_type="article")


def record_review(client, lineage: str, actor: dict, instruction: dict | None = None) -> None:
    checklist.set_step(client, lineage, checklist.SITE_REVIEW_KEY, "done", actor=actor, note="Read it through as a reader", now=REVIEW_TIME, instruction=instruction)


def published_metadata(client, lineage: str) -> dict:
    return json.loads(client.get_record("PublishedItem", published_item_id_for(lineage))["metadata"])


def test_a_persons_review_of_the_published_version_is_on_the_published_record_and_the_entry():
    client = FakeAuthoringClient()
    story = a_story(client)
    record_review(client, story["lineageId"], {"kind": "person", "label": "Ana Reviewer", "sub": "sub-ana"})
    publish_item(client, story["id"], actor="editor", approved_by="sub-ana")
    assert published_metadata(client, story["lineageId"])[REVIEWED_BY_KEY] == {"name": "Ana Reviewer", "at": REVIEW_TIME}
    row = client.get_record("PublishedItem", published_item_id_for(story["lineageId"]))
    assert summary_from_row(row).front_matter[REVIEWED_BY_KEY] == {"name": "Ana Reviewer", "at": REVIEW_TIME}


def test_a_delegated_review_names_the_person_and_never_the_agent():
    client = FakeAuthoringClient()
    story = a_story(client)
    record_review(client, story["lineageId"], {"kind": "agent", "label": "Claude"}, instruction={"person": "Ana Reviewer", "quote": "I read it, mark it reviewed"})
    publish_item(client, story["id"], actor="editor", approved_by="sub-ana")
    assert published_metadata(client, story["lineageId"])[REVIEWED_BY_KEY] == {"name": "Ana Reviewer", "at": REVIEW_TIME}


def test_an_unreviewed_story_carries_no_reviewer():
    client = FakeAuthoringClient()
    story = a_story(client)
    publish_item(client, story["id"], actor="editor", approved_by="sub-ana")
    assert REVIEWED_BY_KEY not in published_metadata(client, story["lineageId"])
    row = client.get_record("PublishedItem", published_item_id_for(story["lineageId"]))
    assert REVIEWED_BY_KEY not in summary_from_row(row).front_matter


def test_a_review_of_an_earlier_version_carries_no_reviewer():
    client = FakeAuthoringClient()
    story = a_story(client)
    record_review(client, story["lineageId"], {"kind": "person", "label": "Ana Reviewer", "sub": "sub-ana"})
    second = save_story_version(client, story["lineageId"], front_matter_yaml="title: A Story\n", body_markus="A rewritten paragraph.\n", actor="AI", change_reason="edit")
    publish_item(client, second["id"], actor="editor", approved_by="sub-ana")
    assert REVIEWED_BY_KEY not in published_metadata(client, story["lineageId"])


def test_a_review_recorded_after_the_version_went_live_is_carried_by_publishing_it_again_as_the_same_version():
    client = FakeAuthoringClient()
    story = a_story(client)
    first = publish_item(client, story["id"], actor="editor", approved_by="sub-ana")
    record_review(client, story["lineageId"], {"kind": "person", "label": "Ana Reviewer", "sub": "sub-ana"})
    again = publish_item(client, story["id"], actor="editor", approved_by="sub-ana")
    assert again.changed and again.version_number == first.version_number
    assert published_metadata(client, story["lineageId"])[REVIEWED_BY_KEY]["name"] == "Ana Reviewer"
    assert not publish_item(client, story["id"], actor="editor", approved_by="sub-ana").changed   # nothing new: a no-op as before


def test_only_a_persons_public_name_is_published():
    assert public_reviewer_name("Ana Reviewer") == "Ana Reviewer"
    assert public_reviewer_name("  Lucía  ") == "Lucía"
    for withheld in ("ana@example.com", "3f2b8c1e-9d4a-4b7e-8f6a-1c2d3e4f5a6b", "ss1_abcdefghijk", "papyrus-cli", "editor", "Editor", "", None):
        assert public_reviewer_name(withheld) is None, withheld


def test_a_stamp_whose_person_has_no_public_name_carries_nothing():
    assert reviewed_by_from_stamp(None) is None
    assert reviewed_by_from_stamp({"by": "ana@example.com", "at": REVIEW_TIME}) is None
    assert reviewed_by_from_stamp({"by": "Ana Reviewer", "at": REVIEW_TIME}) == {"name": "Ana Reviewer", "at": REVIEW_TIME}


def test_an_authored_reviewer_in_a_cms_storys_front_matter_never_reaches_the_entry():
    authored = {"title": "A Story", REVIEWED_BY_KEY: {"name": "Somebody Else"}}
    assert front_matter_with_recorded_reviewer(authored, {}) == {"title": "A Story"}
    assert front_matter_with_recorded_reviewer(authored, {REVIEWED_BY_KEY: {"name": "Ana Reviewer", "at": REVIEW_TIME}}) == {
        "title": "A Story", REVIEWED_BY_KEY: {"name": "Ana Reviewer", "at": REVIEW_TIME}}


def test_a_file_based_sites_own_reviewer_is_carried_as_written(tmp_path):
    (tmp_path / "articles").mkdir()
    (tmp_path / "articles" / "reviewed.md").write_text(
        "---\ntitle: Reviewed\nreviewedBy:\n  name: Ana Reviewer\n  at: '2026-11-22T10:00:00Z'\n---\nBody.\n", encoding="utf-8")
    (tmp_path / "articles" / "unreviewed.md").write_text("---\ntitle: Unreviewed\n---\nBody.\n", encoding="utf-8")
    items = {item.summary.slug: item.summary for item in DirectoryContentSource(tmp_path).all_published_items()}
    assert items["reviewed"].front_matter[REVIEWED_BY_KEY] == {"name": "Ana Reviewer", "at": REVIEW_TIME}
    assert REVIEWED_BY_KEY not in items["unreviewed"].front_matter
