"""A story based on a Reference: the link, the story's own text, the seeded image, the copy guard and the backfill (PPY-d9090f)."""

from __future__ import annotations

import json

import pytest

from papyrus_content import cli as cli_module
from papyrus_content import items_commands
from papyrus_content.story_from_reference import (
    COPIED_RUN_WORDS,
    StoryCopiedFromReference,
    create_story_from_references,
    plan_reference_links,
    reference_lineages_of_targets,
    shared_span,
    story_from_story_draft,
    url_key,
)
from papyrus_content.story_reporting import stories_based_on_reference, link_reference_to_story, story_references
from procedures.newsroom.tests.fake_client import FakeAuthoringClient

NOW = "2026-10-29T12:00:00Z"
ARTICLE_URL = "https://blog.example.com/clef-decision-models"
SOURCE_TEXT = (
    "Clef is a family of decision models that route every request to the cheapest model able to answer it. "
    "The team trained them on a year of production traffic and reports that the router matches the largest model on most prompts."
)


def reference(lineage="reference-clef", url=ARTICLE_URL, title="Clef decision models") -> dict:
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "title": title, "sourceUri": url, "curationStatus": "accepted"}


def backend(*, with_preview=True, with_text=True) -> FakeAuthoringClient:
    client = FakeAuthoringClient()
    row = reference()
    client.tables["Reference"] = {row["id"]: row}
    attachments = {}
    if with_preview:
        attachments["a-preview"] = {"id": "a-preview", "referenceId": row["id"], "referenceLineageId": "reference-clef", "role": "preview", "sortKey": "002-preview",
                                    "sourceUri": "https://blog.example.com/og/clef.png", "filename": "Example Blog", "metadata": json.dumps({"siteName": "Example Blog"})}
    if with_text:
        attachments["a-text"] = {"id": "a-text", "referenceId": row["id"], "referenceLineageId": "reference-clef", "role": "extracted_text", "sortKey": "010-text", "storagePath": "corpus/clef.txt"}
    client.tables["ReferenceAttachment"] = attachments
    return client


def reader(path: str) -> str:
    assert path == "corpus/clef.txt"
    return SOURCE_TEXT


OWN_TEXT = "A new family of routers decides, for each request, which model should answer it. We read the report and asked what it means for small teams.\n"


def make(client, **overrides):
    options = dict(references=[reference()], section="articles", slug="clef", title="Clef", actor="papyrus-cli", body_markus=OWN_TEXT, source_text_reader=reader, now=NOW)
    options.update(overrides)
    return create_story_from_references(client, **options)


def test_a_story_is_linked_to_its_reference_by_lineage_ids_and_keeps_our_own_body():
    client = backend()
    result = make(client)
    assert result["created"] and result["linked"] == ["reference-clef"] and result["copyCheck"] == "passed"
    item = client.get_record("Item", result["itemId"])
    assert OWN_TEXT.strip() in item["bodyMarkus"] and "decision models that route" not in item["bodyMarkus"]
    [link] = story_references(client, result["lineageId"])
    assert (link["referenceLineageId"], link["role"]) == ("reference-clef", "based_on")
    [relation] = client.tables["SemanticRelation"].values()
    assert (relation["predicate"], relation["subjectLineageId"], relation["objectLineageId"]) == ("uses_evidence", result["lineageId"], "reference-clef")
    assert stories_based_on_reference(client, "reference-clef") == [{"relationId": relation["id"], "storyLineageId": result["lineageId"], "role": "based_on"}]


def test_without_a_body_the_story_starts_from_a_brief_that_carries_none_of_the_source_text():
    client = backend()
    result = make(client, body_markus=None)
    body = client.get_record("Item", result["itemId"])["bodyMarkus"]
    assert body.startswith("Brief for the copywriter") and ARTICLE_URL in body and "cheapest model" not in body


def test_the_link_survives_a_new_version_of_the_story_and_of_the_reference():
    from papyrus_content.story_reporting import save_story_version

    client = backend()
    result = make(client)
    save_story_version(client, result["lineageId"], front_matter_yaml='title: "Clef"', body_markus="Rewritten.\n", actor="copywriter", change_reason="draft", now=NOW)
    client.tables["Reference"]["reference-clef-v2"] = {**reference(), "id": "reference-clef-v2", "versionNumber": 2}
    client.tables["Reference"]["reference-clef-v1"]["versionState"] = "superseded"
    assert [row["referenceLineageId"] for row in story_references(client, result["lineageId"])] == ["reference-clef"]


def test_a_later_citation_never_weakens_a_based_on_link():
    client = backend()
    result = make(client)
    link_reference_to_story(client, result["lineageId"], "reference-clef-v1", role="cited", actor="copywriter", citation_key="clef")
    [link] = story_references(client, result["lineageId"])
    assert (link["role"], link["citationKey"]) == ("based_on", "clef")


def test_a_post_is_seeded_with_the_preview_image_and_an_article_is_not():
    client = backend()
    post = make(client, item_type="post", slug="clef-post")
    body = client.get_record("Item", post["itemId"])["bodyMarkus"]
    assert post["image"] == "seeded"
    assert body.splitlines()[0] == '::image{src="https://blog.example.com/og/clef.png" alt="Clef decision models" credit="Image: Example Blog"}'
    assert OWN_TEXT.strip() in body
    article = make(client, slug="clef-article")
    assert article["image"] == "not a post" and "::image" not in client.get_record("Item", article["itemId"])["bodyMarkus"]


def test_a_post_whose_reference_has_no_preview_has_no_image():
    client = backend(with_preview=False)
    post = make(client, item_type="post")
    assert post["image"] == "none" and "::image" not in client.get_record("Item", post["itemId"])["bodyMarkus"]


def test_a_body_copied_from_the_reference_text_is_refused_and_nothing_is_written():
    client = backend()
    copied = "Our take. " + " ".join(SOURCE_TEXT.split()[3 : 3 + COPIED_RUN_WORDS]) + " and more.\n"
    with pytest.raises(StoryCopiedFromReference, match="own words"):
        make(client, body_markus=copied)
    assert not client.tables.get("Item") and not client.tables.get("SemanticRelation")


def test_a_short_shared_phrase_is_not_a_copy():
    assert shared_span("the router matches the largest model on most prompts today", SOURCE_TEXT) is None
    assert shared_span("x " + " ".join(SOURCE_TEXT.split()[:COPIED_RUN_WORDS]), SOURCE_TEXT) is not None


def test_an_unreadable_source_text_is_reported_as_unchecked_not_hidden():
    client = backend()
    def broken(path):
        raise OSError("offline")
    assert make(client, source_text_reader=broken)["copyCheck"] == "unchecked"


def test_a_story_that_exists_keeps_its_text_and_still_gets_its_link():
    client = backend()
    first = make(client)
    client.update_record("Item", {"id": first["itemId"], "bodyMarkus": "The editor wrote this.\n"})
    client.tables["SemanticRelation"].clear()
    again = make(client)
    assert again["created"] is False and client.get_record("Item", first["itemId"])["bodyMarkus"] == "The editor wrote this.\n"
    assert len(story_references(client, first["lineageId"])) == 1


def draft(**overrides) -> dict:
    return {"title": "Clef routes requests to the cheapest model", "summary": "A router family", "body": "A router picks the model per request. [1]\n\n## Source\n\n1. Clef " + ARTICLE_URL + "\n\nSection: articles. Drafted by AI.\n",
            "targets": json.dumps([{"type": "entity", "id": "reference:reference-clef"}]), **overrides}


def test_a_story_draft_becomes_a_story_with_the_drafts_own_body_linked_to_its_reference():
    client = backend()
    result = story_from_story_draft(client, draft(), actor="papyrus-cli", source_text_reader=reader, now=NOW)
    item = client.get_record("Item", result["itemId"])
    assert (item["section"], item["status"], item["stage"]) == ("articles", "draft", "copywriting")
    assert item["bodyMarkus"].startswith("A router picks the model per request. [1]")
    assert result["linked"] == ["reference-clef"]
    assert [row["role"] for row in story_references(client, result["lineageId"])] == ["based_on"]


def test_a_story_draft_that_cites_no_reference_is_refused():
    with pytest.raises(ValueError, match="no Reference"):
        story_from_story_draft(backend(), draft(targets="[]"), actor="papyrus-cli")
    assert reference_lineages_of_targets([{"type": "entity", "id": "reference:a"}, {"type": "entity", "id": "concept:b"}]) == ["a"]


def test_a_story_draft_that_copies_the_source_is_refused():
    copied = draft(body="Clef says: " + SOURCE_TEXT + "\n\nSection: articles.\n")
    with pytest.raises(StoryCopiedFromReference):
        story_from_story_draft(backend(), copied, actor="papyrus-cli", source_text_reader=reader)


def existing_story(client, body, item_id="item-articles-cloudflare-clef-decision-models") -> None:
    client.tables.setdefault("Item", {})[item_id] = {
        "id": item_id, "lineageId": item_id, "versionNumber": 1, "versionState": "current", "type": "article", "slug": "x", "section": "articles",
        "status": "draft", "stage": "copywriting", "title": "x", "aliases": [], "metadata": json.dumps({"frontMatterYaml": 'title: "x"'}), "bodyMarkus": body,
    }


def test_the_addresses_of_one_page_match_after_tracking_and_decoration_are_dropped():
    keys = {url_key(address) for address in [ARTICLE_URL, ARTICLE_URL + "/", "http://www.blog.example.com/clef-decision-models?utm_source=x#top", "HTTPS://Blog.Example.com/clef-decision-models"]}
    assert len(keys) == 1 and url_key("https://blog.example.com/other") not in keys


def test_the_backfill_finds_a_story_that_links_to_a_reference_and_writes_the_link():
    client = backend()
    existing_story(client, f"Cloudflare wrote about [decision models]({ARTICLE_URL}?utm_campaign=a), and so do we.\n")
    existing_story(client, "No links here.\n", item_id="item-articles-unrelated")
    plan = plan_reference_links(client)
    assert [(row["itemId"], row["referenceId"], row["role"], row["exists"]) for row in plan] == [("item-articles-cloudflare-clef-decision-models", "reference-clef-v1", "based_on", False)]


def test_the_backfill_command_dry_runs_then_writes_and_is_idempotent(monkeypatch, capsys):
    client = backend()
    existing_story(client, f"See {ARTICLE_URL} for the original.\n")
    monkeypatch.setattr(items_commands, "create_authoring_client", lambda: (client, {}))
    items_commands.items_link_references(["--site", "anth-us", "--dry-run"])
    assert "would link" in capsys.readouterr().out and not client.tables.get("SemanticRelation")
    items_commands.items_link_references(["--site", "anth-us"])
    out = capsys.readouterr().out
    assert "1 written" in out and len(client.tables["SemanticRelation"]) == 1
    items_commands.items_link_references(["--site", "anth-us"])
    assert "exists" in capsys.readouterr().out and len(client.tables["SemanticRelation"]) == 1


def test_a_story_that_cites_several_references_cites_them_instead_of_being_based_on_each():
    client = backend()
    other = reference("reference-other", "https://other.example.org/post", "Other")
    client.tables["Reference"][other["id"]] = other
    existing_story(client, f"Both [one]({ARTICLE_URL}) and [two](https://other.example.org/post).\n")
    assert {row["role"] for row in plan_reference_links(client)} == {"cited"}


def test_the_command_needs_a_site_and_a_known_role():
    with pytest.raises(ValueError, match="--site"):
        items_commands.items_link_references([])
    with pytest.raises(ValueError, match="--role"):
        items_commands.items_link_references(["--site", "x", "--role", "loves"])


def test_the_papyrus_command_routes_items_link_references(monkeypatch):
    calls = []
    monkeypatch.setattr(items_commands, "items_link_references", lambda flags: calls.append(flags))
    cli_module.dispatch("items", "link-references", ["--site", "x"])
    assert calls == [["--site", "x"]]


def test_stories_create_links_each_reference_as_based_on(monkeypatch, capsys):
    from papyrus_content import story_commands

    client = backend()
    client.tables["NewsroomSection"] = {"articles": {"id": "articles"}}
    monkeypatch.setattr(story_commands, "create_authoring_client", lambda: (client, {}))
    monkeypatch.setattr("papyrus_content.story_triggers.deliver_from_environment", lambda *a, **k: None)
    story_commands.stories_create(["--title", "From a reference", "--section", "articles", "--reference", "reference-clef-v1"])
    [lineage] = {row["lineageId"] for row in client.tables["Item"].values()}
    assert [(row["referenceLineageId"], row["role"]) for row in story_references(client, lineage)] == [("reference-clef", "based_on")]
