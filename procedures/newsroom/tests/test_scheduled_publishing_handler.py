"""The content-actions side of scheduled publishing: the ``scheduleItem`` mutation, the Scheduler's ``publish-scheduled`` event, and the schedule ending on a publish now or a takedown."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_client import FakeAuthoringClient  # noqa: E402
from schedule_support import LINEAGE, ZONE, Clock, FakeScheduler, item, new_story, service_for  # noqa: E402

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify/functions/content-actions/handler.py"
specification = importlib.util.spec_from_file_location("content_actions_handler_for_schedule", HANDLER_PATH)
handler = importlib.util.module_from_spec(specification)
specification.loader.exec_module(handler)


@pytest.fixture
def site():
    client, scheduler, clock = FakeAuthoringClient(), FakeScheduler(), Clock("2026-11-10T15:00:00Z")
    newest = new_story(client, first_published="2026-11-04T15:02:00Z", versions=2)
    service = service_for(client, scheduler, clock)
    with mock.patch.object(handler, "create_authoring_client", return_value=(client, {})), mock.patch.object(handler, "schedule_service", return_value=service), \
            mock.patch.object(handler, "render_preflight"), mock.patch.object(handler, "projection_configured", return_value=False), \
            mock.patch.object(handler, "project_item_action", return_value={"projected": True}):
        yield client, scheduler, clock, newest


def event(field: str, payload: dict, groups=("editor",)) -> dict:
    return {"fieldName": field, "arguments": {"input": json.dumps(payload)}, "identity": {"username": "sam", "sub": "sam-sub", "issuer": "https://cognito", "groups": list(groups)}}


def schedule(payload: dict, groups=("editor",)) -> dict:
    return handler.handler(event("scheduleItem", {"operation": "schedule", "arguments": payload}, groups), None)


def test_the_mutation_schedules_as_the_signed_in_person(site) -> None:
    client, scheduler, _clock, newest = site
    answer = schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"})
    assert answer["ok"] is True and answer["scheduledPublishAt"] == "2026-11-13T14:00:00Z" and item(client, newest)["scheduledBy"] == "sam"
    assert len(scheduler.schedules) == 1


def test_a_person_who_may_not_publish_is_refused_in_plain_words(site) -> None:
    _client, scheduler, *_ = site
    answer = schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, groups=("reader",))
    assert answer == {"ok": False, "errors": [{"code": "not-allowed", "message": "You can't publish on this site, so you can't schedule."}]}
    assert scheduler.schedules == {}


def test_the_listing_is_the_same_table(site) -> None:
    schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"})
    answer = handler.handler(event("scheduleItem", {"operation": "schedule_list", "arguments": {}}), None)
    assert [entry["state"] for entry in answer["schedules"]] == ["scheduled"] and answer["timeZone"] == ZONE


def scheduler_event(newest: str, at: str) -> dict:
    return {"projectionTask": {"task": "publish-scheduled", "itemId": newest, "scheduledPublishAt": at}}


def test_the_scheduler_event_publishes_as_scheduled_by_the_person_and_keeps_the_first_date(site) -> None:
    client, scheduler, clock, newest = site
    schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 08:00"})
    clock.set("2026-11-14T13:00:02Z")
    with mock.patch.object(handler.ScheduleService, "now", return_value=clock.moment), mock.patch("papyrus_content.publishing.utc_now_iso", return_value="2026-11-14T13:00:02Z"):
        answer = handler.handler(scheduler_event(newest, "2026-11-14T13:00:00Z"), None)
    assert answer["published"] is True
    row = item(client, newest)
    assert row["status"] == "published" and row["versionPublishedBy"] == "scheduled by sam" and row["publishedAt"] == "2026-11-04T15:02:00Z"
    assert not row.get("scheduleState") and scheduler.schedules == {}


def test_a_refused_publish_fails_the_run_so_lambda_retries_it(site) -> None:
    client, _scheduler, clock, newest = site
    schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 08:00"})
    clock.set("2026-11-14T13:00:02Z")
    client.update_record("Item", {"id": newest, "type": "untyped"})
    with pytest.raises(handler.ProjectionTaskFailed, match="type-required"):
        handler.handler(scheduler_event(newest, "2026-11-14T13:00:00Z"), None)
    assert item(client, newest)["scheduleState"] == "scheduled"


def test_publishing_now_ends_the_schedule(site) -> None:
    client, scheduler, _clock, newest = site
    schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 08:00"})
    answer = handler.handler(event("publishItem", {"id": newest}), None)
    assert answer["ok"] is True and answer["schedule"] == {"removed": [newest]}
    assert not item(client, newest).get("scheduleState") and scheduler.schedules == {}
    later = handler.handler(scheduler_event(newest, "2026-11-14T13:00:00Z"), None)
    assert later["published"] is False   # the timer that fires anyway finds nothing to do


def test_taking_a_story_down_ends_its_schedule(site) -> None:
    client, scheduler, _clock, newest = site
    handler.handler(event("publishItem", {"id": newest}), None)
    from papyrus_content.story_reporting import save_story_version

    third = save_story_version(client, LINEAGE, front_matter_yaml="title: Robots\n", body_markus="Third.\n", actor="Alex", change_reason="edit", now="2026-11-11T12:00:00Z")["id"]
    schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 08:00"})
    answer = handler.handler(event("unpublishItem", {"id": newest}), None)
    assert answer["schedule"] == {"removed": [third]} and scheduler.schedules == {}


def test_a_publish_reports_a_schedule_it_could_not_remove_and_still_publishes(site) -> None:
    client, _scheduler, _clock, newest = site
    schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 08:00"})
    with mock.patch.object(handler.ScheduleService, "clear_through", side_effect=RuntimeError("scheduler unavailable")):
        answer = handler.handler(event("publishItem", {"id": newest}), None)
    assert answer["ok"] is True and answer["changed"] is True and "scheduler unavailable" in answer["schedule"]["error"]
