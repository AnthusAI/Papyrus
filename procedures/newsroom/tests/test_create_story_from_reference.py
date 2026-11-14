"""The editor's one-tap Create Story from a Reference (PPY-3c11bd; features_backend/create-story-from-reference.feature). The backend is a fake."""

from __future__ import annotations

import json

import pytest

from papyrus_content.ideas.monitor_stories import has_based_on_story
from papyrus_content.story_from_reference import create_story_from_reference, story_rows
from papyrus_content.story_reporting import stories_based_on_reference, story_references
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from papyrus_content.content_item_lifecycle import without_sub_tasks

NOW = "2026-11-02T12:00:00Z"
URL = "https://blog.example.com/clef-decision-models"
SOURCE_TEXT = (
    "Clef is a family of decision models that route every request to the cheapest model able to answer it. "
    "The team trained them on a year of production traffic and reports that the router matches the largest model on most prompts."
)
SUMMARY = "A new family of routers picks the cheapest model for each request and, the authors say, matches the largest model on most prompts."


def backend(*, status="pending", preview=True, text=True, sections=()) -> FakeAuthoringClient:
    client = FakeAuthoringClient()
    row = {"id": "reference-clef-v1", "lineageId": "reference-clef", "versionNumber": 1, "versionState": "current", "title": "Clef decision models", "sourceUri": URL, "curationStatus": status}
    client.tables["Reference"] = {row["id"]: row}
    attachments = {}
    if preview:
        attachments["a-preview"] = {"id": "a-preview", "referenceId": row["id"], "referenceLineageId": "reference-clef", "role": "preview", "sortKey": "002-preview",
                                    "sourceUri": "https://blog.example.com/og/clef.png", "filename": "Example Blog", "metadata": json.dumps({"siteName": "Example Blog"})}
    if text:
        attachments["a-text"] = {"id": "a-text", "referenceId": row["id"], "referenceLineageId": "reference-clef", "role": "extracted_text", "sortKey": "010-text", "storagePath": "corpus/clef.txt"}
    client.tables["ReferenceAttachment"] = attachments
    if sections:
        client.tables["NewsroomSection"] = {name: {"id": name, "title": name.title(), "enabled": True} for name in sections}
    return client


def create(client, **options):
    options = {"actor": "editor@example.test", "summary_of": lambda lineage: SUMMARY, "source_text_reader": lambda path: SOURCE_TEXT, "now": NOW, **options}
    return create_story_from_reference(client, "reference-clef-v1", **options)


def item_of(client, result):
    return client.get_record("Item", result["itemId"])


def test_one_call_makes_a_linked_article_at_copywriting_started_from_the_summary():
    client = backend()
    result = create(client)
    assert result["created"] and (result["itemType"], result["stage"], result["title"]) == ("untyped", "copywriting", "Clef decision models")
    item = item_of(client, result)
    assert (item["type"], item["stage"], item["title"]) == ("untyped", "copywriting", "Clef decision models")
    body = item["bodyMarkus"]
    assert body.startswith('::image{src="https://blog.example.com/og/clef.png"') and 'credit="Image: Example Blog"' in body
    assert SUMMARY in body and body.rstrip().endswith(f"Source: [Clef decision models]({URL}), Example Blog.")
    [link] = story_references(client, result["lineageId"])
    assert (link["referenceLineageId"], link["role"]) == ("reference-clef", "based_on")
    assert [row["storyLineageId"] for row in stories_based_on_reference(client, "reference-clef")] == [result["lineageId"]]


def test_the_front_matter_records_where_the_draft_and_the_image_came_from():
    client = backend()
    result = create(client)
    front = json.loads(json.dumps(__import__("yaml").safe_load(json.loads(item_of(client, result)["metadata"])["frontMatterYaml"])))
    assert front["seededFrom"] == {"kind": "reference", "referenceLineageId": "reference-clef", "summary": "included", "by": "editor@example.test"}
    assert front["seededImage"] == {"url": "https://blog.example.com/og/clef.png", "from": "reference-preview", "hosted": False, "credit": "Image: Example Blog", "page": URL}
    assert result["imageCredit"] == "Image: Example Blog" and result["image"] == "seeded"


def test_without_a_summary_the_body_is_the_source_line_only_and_nothing_is_invented():
    client = backend()
    result = create(client, summary_of=lambda lineage: "")
    body = item_of(client, result)["bodyMarkus"]
    assert body.split("\n\n", 1)[1].strip() == f"Source: [Clef decision models]({URL}), Example Blog."
    assert result["summary"] == "none"


def test_without_a_preview_there_is_no_image_and_a_site_name_falls_back_to_the_host():
    client = backend(preview=False)
    result = create(client)
    body = item_of(client, result)["bodyMarkus"]
    assert "::image" not in body and result["image"] == "none" and body.rstrip().endswith(f"({URL}), blog.example.com.")


def test_a_post_is_the_other_story_type_and_an_unknown_type_is_refused():
    client = backend()
    assert item_of(client, create(client, item_type="post"))["type"] == "post"
    with pytest.raises(ValueError):
        create(backend(), item_type="wiki_page")


def test_the_curation_status_is_never_changed_by_creating_a_story():
    for status in ("pending", "rejected", "accepted"):
        client = backend(status=status)
        create(client)
        assert client.get_record("Reference", "reference-clef-v1")["curationStatus"] == status


def test_tapping_again_offers_the_existing_story_and_makes_no_duplicate():
    client = backend()
    first = create(client)
    again = create(client)
    assert again["created"] is False and [row["itemId"] for row in again["existing"]] == [first["itemId"]]
    assert len(without_sub_tasks(client.tables["Item"].values())) == 1 and len(client.tables["SemanticRelation"]) == 1


def test_creating_another_on_purpose_makes_a_second_story_with_its_own_address():
    client = backend()
    first = create(client)
    second = create(client, again=True)
    assert second["created"] and second["itemId"] != first["itemId"] and len(story_rows(client, "reference-clef")) == 2


def test_a_summary_that_repeats_the_captured_text_is_left_out_and_the_story_still_starts():
    client = backend()
    result = create(client, summary_of=lambda lineage: SOURCE_TEXT)
    body = item_of(client, result)["bodyMarkus"]
    assert result["summary"] == "withheld" and "decision models that route" not in body and "Source:" in body


def test_a_site_with_one_section_uses_it_and_a_site_with_several_leaves_it_to_the_editor():
    assert create(backend(sections=("analysis",)))["section"] == "analysis"
    assert create(backend(sections=("analysis", "tools")))["section"] is None


def test_the_idea_pipeline_no_longer_offers_the_reference_as_a_single_item_idea():
    client = backend(status="accepted")
    create(client)
    assert has_based_on_story(client.list_semantic_relations_by_object_state("reference#reference-clef#current"))


def test_an_unknown_reference_is_refused():
    with pytest.raises(ValueError):
        create_story_from_reference(backend(), "nope", actor="editor@example.test")
