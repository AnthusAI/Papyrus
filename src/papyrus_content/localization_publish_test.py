"""Publishing a translation: the rules that are not a page (features_backend/translation-publishing.feature has the pages end to end).

Synthetic rows on the in-memory fake backend; no model, no network."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import pytest

from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from papyrus_content import review_requests
from papyrus_content.item_language import localization_original
from papyrus_content.localization_publish import ORIGINAL_UNPUBLISHED, TRANSLATION_HELD, hold_request_id, require_publishable
from papyrus_content.localize import record
from papyrus_content.projection.model import ItemSummary
from papyrus_content.projection.source import served
from papyrus_content.publishing import PublishError, publish_item

ORIGINAL = "story-one"
LINEAGE = "story-one--es-419"
RUN_KEY = "a" * 32
BODY = "Una frase.\n"


def english(client: FakeAuthoringClient, *, published: bool = True) -> None:
    row = {"id": "story-one-v1", "lineageId": ORIGINAL, "versionNumber": 1, "type": "article", "slug": "story-one", "section": "articles", "title": "One",
           "status": "published" if published else "draft", "language": "en", "languageGroupId": ORIGINAL, "bodyMarkus": "One.\n", "contentHash": "h1"}
    client.tables.setdefault("Item", {})[row["id"]] = row
    if published:
        client.tables.setdefault("PublishedItem", {})["published-" + ORIGINAL] = {"id": "published-" + ORIGINAL, "itemLineageId": ORIGINAL, "status": "published"}


def translation(client: FakeAuthoringClient, *, outcome: str = "saved") -> dict:
    row = {"id": LINEAGE + "-v1", "lineageId": LINEAGE, "versionNumber": 1, "type": "article", "slug": "una", "section": "articles", "title": "Una",
           "status": "draft", "language": "es-419", "languageGroupId": ORIGINAL, "sourceLineageId": ORIGINAL, "sourceVersionNumber": 1, "bodyMarkus": BODY,
           "contentHash": "h2", "metadata": json.dumps({"localization": {"runKey": RUN_KEY, "outcome": outcome, "reason": "a number was lost"}})}
    client.tables.setdefault("Item", {})[row["id"]] = row
    return row


def held(client: FakeAuthoringClient) -> dict:
    row = translation(client, outcome="held")
    request = SimpleNamespace(run_key=RUN_KEY, language="es-419", localization_lineage=LINEAGE)
    review_requests.raise_review(client, subject={"type": "story", "id": LINEAGE}, mode="flag", reason="held", raised_by=record.RAISED_BY,
                                 request_id=hold_request_id(request.run_key))
    return row


@pytest.fixture
def client() -> FakeAuthoringClient:
    return FakeAuthoringClient()


def test_a_translation_is_recognised_by_its_derived_lineage() -> None:
    assert localization_original({"lineageId": LINEAGE, "languageGroupId": ORIGINAL, "language": "es-419"}, None) == ORIGINAL
    assert localization_original({"itemLineageId": LINEAGE, "languageGroupId": "tenant-1#" + ORIGINAL, "language": "es-419"}, "tenant-1") == ORIGINAL
    assert localization_original({"lineageId": ORIGINAL, "languageGroupId": ORIGINAL, "language": "es-419"}, None) is None   # a Story of its own, whatever language it is written in
    assert localization_original({"lineageId": "story-1", "languageGroupId": "story-1-v1", "language": "en"}, None) is None   # a group that is not the derived one is no translation


def test_a_clean_translation_publishes_without_a_checklist_while_its_original_is_published(client) -> None:
    english(client)
    row = translation(client)
    result = publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
    assert result.changed and client.tables["PublishedItem"]["published-" + LINEAGE]["language"] == "es-419"
    assert not [step for step in client.tables["Item"].values() if step.get("type") == "sub-task"]


def test_a_translation_is_refused_while_its_original_is_not_published(client) -> None:
    english(client, published=False)
    row = translation(client)
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
    assert refused.value.code == ORIGINAL_UNPUBLISHED and ORIGINAL in refused.value.message
    assert "published-" + LINEAGE not in client.tables.get("PublishedItem", {})


@pytest.mark.parametrize("decision, may_publish", [("approve", True), ("acknowledge", True), ("reject", False)])
def test_a_held_translation_publishes_only_after_a_person_approves_or_acknowledges_its_review_request(client, decision, may_publish) -> None:
    english(client)
    row = held(client)
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
    assert refused.value.code == TRANSLATION_HELD and hold_request_id(RUN_KEY) in refused.value.message
    review_requests.answer_review(client, hold_request_id(RUN_KEY), decision=decision, by="An Editor")
    if may_publish:
        assert publish_item(client, row["id"], actor="An Editor", by_person="An Editor").changed
    else:
        with pytest.raises(PublishError) as still:
            publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
        assert still.value.code == TRANSLATION_HELD and "rejected" in still.value.message


def test_a_held_translation_whose_review_request_is_missing_is_refused(client) -> None:
    english(client)
    row = translation(client, outcome="held")
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
    assert refused.value.code == TRANSLATION_HELD and "missing" in refused.value.message


def test_the_rating_requirement_is_the_originals_and_never_blocks_a_translation(client) -> None:
    english(client)
    row = translation(client)
    with mock.patch("papyrus_content.story_rating.read_required", lambda _client: True):
        assert publish_item(client, row["id"], actor="An Editor", by_person="An Editor").changed   # no rating of its own, and none is asked for
    assert not row.get("starRating")


def test_the_english_checklist_still_gates_a_story_of_its_own(client) -> None:
    english(client)
    row = {**client.tables["Item"]["story-one-v1"], "id": "other-v1", "lineageId": "other", "languageGroupId": "other", "status": "draft", "slug": "other"}
    client.tables["Item"]["other-v1"] = row
    with mock.patch("papyrus_content.story_checklist.require_checklist_closed", side_effect=__import__("papyrus_content.story_checklist", fromlist=["x"]).ChecklistError("open")) as gate:
        with pytest.raises(PublishError) as refused:
            publish_item(client, "other-v1", actor="An Editor", by_person="An Editor")
    assert refused.value.code == "checklist-open" and gate.called


def test_require_publishable_names_the_original(client) -> None:
    english(client, published=False)
    with pytest.raises(PublishError, match=ORIGINAL):
        require_publishable(client, translation(client), ORIGINAL)


def summary(lineage: str, group: str, language: str) -> ItemSummary:
    return ItemSummary(item_id=lineage + "-v1", type="article", section="a", slug=lineage, output_path=f"a/{lineage}.md", version_number=1, title=lineage, page_title=None,
                       front_matter={}, aliases=(), published_at=None, lineage_id=lineage, language=language, language_group_id=group)


def test_the_site_serves_a_translation_only_beside_its_original() -> None:
    one, other, native = summary("one", "one", "en"), summary("one--es-419", "one", "es-419"), summary("nativa", "nativa", "es-419")
    assert [item.lineage_id for item in served([one, other, native])] == ["one", "one--es-419", "nativa"]
    assert [item.lineage_id for item in served([other, native])] == ["nativa"]   # the original is gone: the translation leaves, a Story of its own stays


def test_a_localization_takes_its_own_address_from_its_title_and_keeps_it(client) -> None:
    english(client)
    primary = client.tables["Item"]["story-one-v1"]
    request = SimpleNamespace(slug_policy="translated", language="es-419", localization_lineage=LINEAGE)
    assert record._first_slug(client, request, primary, "Bajan los choques") == "bajan-los-choques"
    other = {"id": "x-v1", "lineageId": "x--es-419", "slug": "bajan-los-choques", "language": "es-419", "section": "articles"}
    client.tables["Item"]["x-v1"] = other
    assert record._first_slug(client, request, primary, "Bajan los choques") == "bajan-los-choques-2"
    assert record._first_slug(client, SimpleNamespace(**{**vars(request), "slug_policy": "characters", "language": "zh-Hans"}), primary, "能泄露你住在哪里的声音，吗？") == "能泄露你住在哪里的声音-吗"
    assert record._first_slug(client, SimpleNamespace(**{**vars(request), "slug_policy": "primary"}), primary, "Cualquiera") == "story-one"


def _tagged_original(client: FakeAuthoringClient) -> None:
    """The original is tagged with one accepted concept, and the site's primary language is English."""
    client.tables.setdefault("EditorialCheckSettings", {})["settings"] = {"id": "settings", "settings": json.dumps({"languages": {"primary": "en", "enabled": ["en", "es-419"]}})}
    client.tables.setdefault("SemanticNode", {})["pi-v1"] = {"id": "pi-v1", "lineageId": "pi", "versionNumber": 1, "versionState": "current", "nodeKey": "topic--prompt-injection",
                                                             "nodeKind": "topic", "displayName": "prompt injection", "status": "accepted", "language": "en"}
    client.tables.setdefault("SemanticRelation", {})["rel-1"] = {"id": "rel-1", "subjectStateKey": "item#story-one#current", "objectKind": "semanticNode", "objectId": "pi-v1",
                                                                 "relationState": "current", "predicate": "tagged_with"}


def test_publishing_a_translation_notes_that_its_languages_pages_need_the_originals_concepts(client) -> None:
    english(client)
    _tagged_original(client)
    row = translation(client)
    publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
    wanted = [label for label in client.tables.get("EntityLabel", {}).values() if label.get("syncState") == "wanted"]
    assert [(label["entityId"], label["language"]) for label in wanted] == [("pi", "es-419")]
    assert not [label for label in client.tables["EntityLabel"].values() if label["role"] == "preferred"]   # nothing is named by a publish


def test_tagging_the_original_notes_the_concept_for_each_language_it_is_published_in(client) -> None:
    from papyrus_content.entity_labels.wanted import record_wanted_for_tagging

    english(client)
    _tagged_original(client)
    row = translation(client)
    publish_item(client, row["id"], actor="An Editor", by_person="An Editor")
    for label in [label for label in client.tables["EntityLabel"].values()]:
        client.tables["EntityLabel"].pop(label["id"])
    node = client.tables["SemanticNode"]["pi-v1"]
    assert record_wanted_for_tagging(client, ORIGINAL, [node], now="2026-11-16T00:00:00Z") == 1
    assert record_wanted_for_tagging(client, ORIGINAL, [node], now="2026-11-16T00:00:00Z") == 0   # already recorded


def test_publishing_a_concepts_page_notes_that_its_name_is_needed_in_every_served_language(client) -> None:
    _tagged_original(client)
    client.tables["EditorialCheckSettings"]["settings"]["settings"] = json.dumps({"languages": {"primary": "en", "enabled": ["en", "es-419", "zh-Hans"]}})
    page = {"id": "wiki-pi-v1", "lineageId": "wiki-pi", "versionNumber": 1, "type": "wiki_page", "slug": "prompt-injection", "section": "wiki", "title": "Prompt injection",
            "status": "draft", "language": "en", "languageGroupId": "wiki-pi", "bodyMarkus": "A page.\n", "contentHash": "h9",
            "metadata": json.dumps({"frontMatterYaml": "entityKey: topic--prompt-injection\n"})}
    client.tables.setdefault("Item", {})["wiki-pi-v1"] = page
    with pytest.raises(PublishError):   # the page has no review stamp, so it does not publish; the need is noted only once publishing goes ahead
        publish_item(client, "wiki-pi-v1", actor="An Editor", by_person="An Editor")
    assert not [label for label in client.tables.get("EntityLabel", {}).values() if label.get("syncState") == "wanted"]
    from papyrus_content.entity_labels.wanted import record_wanted_for_page

    assert record_wanted_for_page(client, "topic--prompt-injection", now="2026-11-16T00:00:00Z") == 2
    assert record_wanted_for_page(client, "topic--prompt-injection", now="2026-11-16T00:00:00Z") == 0
    assert record_wanted_for_page(client, "no-such-concept", now="2026-11-16T00:00:00Z") == 0
    assert sorted(label["language"] for label in client.tables["EntityLabel"].values() if label["syncState"] == "wanted") == ["es-419", "zh-Hans"]
