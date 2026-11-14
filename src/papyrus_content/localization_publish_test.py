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
    assert localization_original({"lineageId": LINEAGE, "languageGroupId": ORIGINAL, "language": "es-419"}) == ORIGINAL
    assert localization_original({"itemLineageId": LINEAGE, "languageGroupId": "tenant-1#" + ORIGINAL, "language": "es-419"}, "tenant-1") == ORIGINAL
    assert localization_original({"lineageId": ORIGINAL, "languageGroupId": ORIGINAL, "language": "es-419"}) is None   # a Story of its own, whatever language it is written in
    assert localization_original({"lineageId": "story-1", "languageGroupId": "story-1-v1", "language": "en"}) is None   # a group that is not the derived one is no translation


def test_a_clean_translation_publishes_without_a_checklist_while_its_original_is_published(client) -> None:
    english(client)
    row = translation(client)
    result = publish_item(client, row["id"], actor="An Editor")
    assert result.changed and client.tables["PublishedItem"]["published-" + LINEAGE]["language"] == "es-419"
    assert not [step for step in client.tables["Item"].values() if step.get("type") == "sub-task"]


def test_a_translation_is_refused_while_its_original_is_not_published(client) -> None:
    english(client, published=False)
    row = translation(client)
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="An Editor")
    assert refused.value.code == ORIGINAL_UNPUBLISHED and ORIGINAL in refused.value.message
    assert "published-" + LINEAGE not in client.tables.get("PublishedItem", {})


@pytest.mark.parametrize("decision, may_publish", [("approve", True), ("acknowledge", True), ("reject", False)])
def test_a_held_translation_publishes_only_after_a_person_approves_or_acknowledges_its_review_request(client, decision, may_publish) -> None:
    english(client)
    row = held(client)
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="An Editor")
    assert refused.value.code == TRANSLATION_HELD and hold_request_id(RUN_KEY) in refused.value.message
    review_requests.answer_review(client, hold_request_id(RUN_KEY), decision=decision, by="An Editor")
    if may_publish:
        assert publish_item(client, row["id"], actor="An Editor").changed
    else:
        with pytest.raises(PublishError) as still:
            publish_item(client, row["id"], actor="An Editor")
        assert still.value.code == TRANSLATION_HELD and "rejected" in still.value.message


def test_a_held_translation_whose_review_request_is_missing_is_refused(client) -> None:
    english(client)
    row = translation(client, outcome="held")
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="An Editor")
    assert refused.value.code == TRANSLATION_HELD and "missing" in refused.value.message


def test_the_rating_requirement_is_the_originals_and_never_blocks_a_translation(client) -> None:
    english(client)
    row = translation(client)
    with mock.patch("papyrus_content.story_rating.read_required", lambda _client: True):
        assert publish_item(client, row["id"], actor="An Editor").changed   # no rating of its own, and none is asked for
    assert not row.get("starRating")


def test_the_english_checklist_still_gates_a_story_of_its_own(client) -> None:
    english(client)
    row = {**client.tables["Item"]["story-one-v1"], "id": "other-v1", "lineageId": "other", "languageGroupId": "other", "status": "draft", "slug": "other"}
    client.tables["Item"]["other-v1"] = row
    with mock.patch("papyrus_content.story_checklist.require_checklist_closed", side_effect=__import__("papyrus_content.story_checklist", fromlist=["x"]).ChecklistError("open")) as gate:
        with pytest.raises(PublishError) as refused:
            publish_item(client, "other-v1", actor="An Editor")
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
