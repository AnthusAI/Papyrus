"""The person-only publish rule (publish_by_person.py; features_backend/publish-person-only.feature has it end to end).

Synthetic rows on the in-memory fake backend; no model, no network."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from papyrus_content.localization_publish_test import english, translation
from papyrus_content.localize.backfill import NOT_PUBLISHED, Job, publish_clean
from papyrus_content.publish_by_person import IMPORTED, PERSON_PUBLISH_REQUIRED, POD_LOADED, TRANSLATION, require_person_act, story_kind
from papyrus_content.publishing import PublishError, publish_item
from papyrus_content.story_schedule import Caller, ScheduleError
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.schedule_support import LINEAGE, Clock, FakeScheduler, item, new_story, service_for


@pytest.fixture
def client() -> FakeAuthoringClient:
    return FakeAuthoringClient()


def test_a_translation_is_refused_without_a_person_and_says_how_to_proceed(client) -> None:
    english(client)
    row = translation(client)
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="AI (translation on publish)")
    assert refused.value.code == PERSON_PUBLISH_REQUIRED and refused.value.details == {"storyKind": TRANSLATION}
    assert "publish it by hand" in refused.value.message and row["id"] in refused.value.message
    assert row["status"] == "draft" and "published-" + row["lineageId"] not in client.tables.get("PublishedItem", {})


def test_a_site_approval_does_not_stand_in_for_a_person(client) -> None:
    english(client)
    row = translation(client)
    with pytest.raises(PublishError) as refused:
        publish_item(client, row["id"], actor="scheduled by sam", approved_by="sam-sub")   # a schedule passes the approval, never the person
    assert refused.value.code == PERSON_PUBLISH_REQUIRED


def test_a_person_publishes_a_translation_by_hand(client) -> None:
    english(client)
    row = translation(client)
    assert publish_item(client, row["id"], actor="An Editor", by_person="An Editor").changed


def test_publish_clean_leaves_a_ready_draft(client) -> None:
    english(client)
    row = translation(client)
    job = Job(story="story-one", language="es-419")
    decision = mock.Mock(done=False, version=row)
    with mock.patch("papyrus_content.localize.backfill.publishable", return_value=decision), mock.patch("papyrus_content.localize.backfill.desired_state") as state:
        state.MODEL, state.request_id.return_value = "LocalizationRequest", "r"
        client.tables.setdefault("LocalizationRequest", {})["r"] = {"id": "r"}
        publish_clean(client, job, {}, actor="papyrus-cli", project=lambda *_: {"ok": True})
    assert job.status == NOT_PUBLISHED and PERSON_PUBLISH_REQUIRED in job.detail
    assert "published-" + row["lineageId"] not in client.tables.get("PublishedItem", {})


def test_a_pod_loaded_story_is_a_kind_of_its_own_and_a_page_is_not() -> None:
    client = FakeAuthoringClient()
    pod = {"id": "a-v1", "lineageId": "a", "type": "article", "metadata": json.dumps({"pod": {"id": "https://example.org/id/1"}})}
    assert story_kind(client, pod) == POD_LOADED
    require_person_act(client, {**pod, "type": "page"}, by_person=None)   # a Page has no checklist to skip
    require_person_act(client, pod, by_person="a-person")
    with pytest.raises(PublishError) as refused:
        require_person_act(client, pod, by_person=None)
    assert refused.value.details == {"storyKind": POD_LOADED}


def test_an_imported_story_is_one_whose_every_step_but_publishing_is_not_applicable() -> None:
    client = FakeAuthoringClient()
    story = {"id": "a-v1", "lineageId": "a", "type": "article"}
    steps = [{"stepKey": "draft", "state": "not_applicable", "reason": "imported from a.md"}, {"stepKey": "publish", "state": "open", "reason": None}]
    with mock.patch("papyrus_content.story_checklist.read_steps", return_value=steps):
        assert story_kind(client, story) == IMPORTED
    ticked = [{**steps[0], "state": "done", "reason": None}, steps[1]]   # a person did a step: it is no longer an unreviewed import
    with mock.patch("papyrus_content.story_checklist.read_steps", return_value=ticked):
        assert story_kind(client, story) is None
    with mock.patch("papyrus_content.story_checklist.read_steps", return_value=[]):
        assert story_kind(client, story) is None


def test_a_schedule_of_a_translation_or_a_pod_story_is_refused_when_it_is_made() -> None:
    client, scheduler, clock = FakeAuthoringClient(), FakeScheduler(), Clock("2026-11-10T15:00:00Z")
    new_story(client)
    row = item(client, LINEAGE)
    row["metadata"] = json.dumps({"pod": {"id": "https://example.org/id/1"}})
    service = service_for(client, scheduler, clock)
    with pytest.raises(ScheduleError) as refused:
        service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, Caller(actor="sam", person="sam-sub", groups=("editor",)))
    assert refused.value.code == PERSON_PUBLISH_REQUIRED and not scheduler.schedules
