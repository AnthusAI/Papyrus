"""Scheduled publishing (docs/scheduled-publishing.md): time zones, the schedule on a version, the claim at the scheduled time, and the operation table."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from papyrus_content.publishing import PublishError, publish_item
from papyrus_content.story_schedule import (
    BLOCKED, BLOCKED_MESSAGE, OPERATIONS, OVERDUE, PUBLISHING, SCHEDULED, Caller, EventBridgeScheduler, ScheduleError, ScheduleService, local_view, resolve_instant,
    run_operation, schedule_name, scheduler_from_environment, utc_text,
)
from procedures.newsroom.tests.fake_client import FakeAuthoringClient
from procedures.newsroom.tests.schedule_support import LINEAGE, PREFIX, ZONE, Clock, FakeScheduler, item, new_story, service_for

SAM = Caller(actor="sam", person="sam-sub", groups=("editor",))


def refusal(call: Any) -> ScheduleError:
    with pytest.raises(ScheduleError) as caught:
        call()
    return caught.value


def instant(text: str) -> str:
    return utc_text(resolve_instant(text, ZONE))


# --- time zones ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_local_time_is_read_in_the_publication_zone_and_stored_in_utc() -> None:
    assert instant("2026-11-13 09:00") == "2026-11-13T14:00:00Z"
    assert instant("2026-07-13T09:00") == "2026-07-13T13:00:00Z"   # daylight time


def test_a_time_with_an_offset_is_exact() -> None:
    assert instant("2026-11-13T09:00:00-05:00") == "2026-11-13T14:00:00Z"
    assert instant("2026-11-13T14:00:00Z") == "2026-11-13T14:00:00Z"


def test_a_time_in_the_spring_gap_does_not_exist() -> None:
    error = refusal(lambda: resolve_instant("2026-03-08 02:30", ZONE))
    assert error.code == "nonexistent-time"
    assert error.message == "That time does not exist on 8 March in New York. Pick another time."


def test_a_time_in_the_fall_overlap_asks_which() -> None:
    error = refusal(lambda: resolve_instant("2026-11-01 01:30", ZONE))
    assert error.code == "ambiguous-time"
    assert [choice["label"] for choice in error.details["choices"]] == ["01:30 EDT", "01:30 EST"]
    assert [choice["at"] for choice in error.details["choices"]] == ["2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z"]
    assert "2026-11-01T01:30:00-04:00" in error.message
    assert instant("2026-11-01T01:30:00-04:00") == "2026-11-01T05:30:00Z"   # typing the offset answers it


def test_nonsense_is_refused_in_plain_words() -> None:
    assert refusal(lambda: resolve_instant("next tuesday", ZONE)).code == "bad-time"
    assert refusal(lambda: resolve_instant("2026-11-13 09:00", "Mars/Olympus")).code == "bad-time-zone"


def test_the_stored_instant_is_shown_in_the_publication_zone() -> None:
    assert local_view("2026-11-13T14:00:00Z", ZONE) == {"local": "2026-11-13T09:00:00-05:00", "label": "Fri 13 Nov 2026, 09:00 EST", "zone": ZONE}
    assert local_view("2026-11-13T14:00:00Z", None) == {}


# --- scheduling -----------------------------------------------------------------------------------------------------------------------------------------


def setup(*, versions: int = 1, first_published: str | None = None, zone: str | None = ZONE) -> tuple[FakeAuthoringClient, FakeScheduler, Clock, ScheduleService, str]:
    client, scheduler, clock = FakeAuthoringClient(), FakeScheduler(), Clock("2026-11-10T15:00:00Z")
    newest = new_story(client, versions=versions, first_published=first_published)
    return client, scheduler, clock, service_for(client, scheduler, clock, zone), newest


def test_scheduling_pins_the_newest_version_on_its_row_and_makes_one_timer() -> None:
    client, scheduler, _clock, service, newest = setup()
    result = service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    row = item(client, newest)
    assert (row["scheduleState"], row["scheduledPublishAt"], row["scheduledBy"], row["scheduledAt"]) == (SCHEDULED, "2026-11-13T14:00:00Z", "sam", "2026-11-10T15:00:00Z")
    assert row["scheduleName"] == schedule_name(PREFIX, newest) and scheduler.schedules == {row["scheduleName"]: {"itemId": newest, "scheduledPublishAt": "2026-11-13T14:00:00Z"}}
    assert result["label"] == "Fri 13 Nov 2026, 09:00 EST" and result["notes"] == ["Unrated: it will publish but will not be listed or announced until it is rated."]


def test_a_rated_story_gets_no_unrated_note() -> None:
    client, _scheduler, _clock, service, newest = setup()
    client.update_record("Item", {"id": newest, "starRating": 4})
    assert "notes" not in service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)


def test_scheduling_again_moves_the_one_timer() -> None:
    client, scheduler, _clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 11:00"}, SAM)
    assert item(client, newest)["scheduledPublishAt"] == "2026-11-13T16:00:00Z"
    assert list(scheduler.schedules.values()) == [{"itemId": newest, "scheduledPublishAt": "2026-11-13T16:00:00Z"}]


def test_a_story_has_one_schedule_so_scheduling_a_newer_version_replaces_the_old_one() -> None:
    client, scheduler, _clock, service, first = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    from papyrus_content.story_reporting import save_story_version

    second = save_story_version(client, LINEAGE, front_matter_yaml="title: Robots\n", body_markus="Newer.\n", actor="Alex", change_reason="edit", now="2026-11-11T12:00:00Z")["id"]
    assert "scheduleState" not in item(client, second) or not item(client, second).get("scheduleState")   # a new version never inherits the schedule
    result = service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 09:00"}, SAM)
    assert result["replaced"] == [first] and not item(client, first).get("scheduleState")
    assert list(scheduler.schedules.values()) == [{"itemId": second, "scheduledPublishAt": "2026-11-14T14:00:00Z"}]


def test_only_the_newest_version_can_be_scheduled() -> None:
    _client, _scheduler, _clock, service, _newest = setup(versions=2)
    error = refusal(lambda: service.schedule({"itemId": LINEAGE, "at": "2026-11-13 09:00"}, SAM))
    assert error.code == "not-newest" and "Schedule version 2" in error.message


def test_a_time_that_has_passed_is_refused() -> None:
    _client, scheduler, _clock, service, _newest = setup()
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-09 09:00"}, SAM)).message == "That time has passed."
    assert scheduler.schedules == {}


def test_a_refused_time_writes_nothing() -> None:
    client, scheduler, _clock, service, _newest = setup()
    refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-03-08 02:30"}, SAM))
    assert not [call for call in client.write_calls() if call[0] != "create" and call[1] == "Item" and call[2] != LINEAGE] and scheduler.schedules == {}


def test_only_people_who_may_publish_may_schedule() -> None:
    _client, scheduler, _clock, service, _newest = setup()
    lee = Caller(actor="lee", person="lee-sub", groups=("reader",))
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, lee)).message == "You can't publish on this site, so you can't schedule."
    assert scheduler.schedules == {}


def test_a_site_without_a_publication_zone_says_scheduling_is_off() -> None:
    _client, _scheduler, _clock, service, _newest = setup(zone=None)
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)).code == "scheduling-off"


def test_a_story_without_a_type_or_a_non_story_cannot_be_scheduled() -> None:
    client, _scheduler, _clock, service, newest = setup()
    client.update_record("Item", {"id": newest, "type": "untyped"})
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)).code == "type-required"
    client.update_record("Item", {"id": newest, "type": "wiki_page"})
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)).code == "not-a-story"


def test_a_dry_run_checks_and_writes_nothing() -> None:
    client, scheduler, _clock, service, newest = setup()
    result = service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00", "dryRun": True}, SAM)
    assert result["scheduled"] is False and not item(client, newest).get("scheduleState") and scheduler.schedules == {}


def test_a_site_that_needs_approval_to_publish_asks_before_scheduling() -> None:
    from papyrus_content.publish_gate import REQUIRED, set_publish_approval

    client, scheduler, _clock, service, _newest = setup()
    set_publish_approval(client, REQUIRED, by="admin")
    cli = Caller(actor="agent", person=None, groups=None)
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, cli)).code == "approval-required"
    assert scheduler.schedules == {}
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)   # a signed-in person's schedule is their approval
    assert len(scheduler.schedules) == 1


def test_clearing_removes_the_timer_and_the_fields() -> None:
    client, scheduler, _clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    result = service.schedule({"storyLineageId": LINEAGE, "clear": True}, SAM)
    assert result["itemIds"] == [newest] and scheduler.schedules == {} and not any(item(client, newest).get(name) for name in ("scheduleState", "scheduledPublishAt", "scheduleName"))
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "clear": True}, SAM)).code == "not-scheduled"


def test_exactly_one_of_at_and_clear() -> None:
    _client, _scheduler, _clock, service, _newest = setup()
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE}, SAM)).code == "one-of"
    assert refusal(lambda: service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00", "clear": True}, SAM)).code == "one-of"


# --- the run at the scheduled time ------------------------------------------------------------------------------------------------------------------------


def run_at(client: FakeAuthoringClient, service: ScheduleService, newest: str, at: str, published: list[str]) -> dict[str, Any]:
    def publish(row: dict[str, Any]) -> dict[str, Any]:
        published.append(row["id"])
        publish_item(client, row["id"], actor=f"scheduled by {row['scheduledBy']}", approved_by=row["scheduledBy"], now=service.now().strftime("%Y-%m-%dT%H:%M:%SZ"))
        return {"ok": True}

    return service.run_scheduled_publish(newest, at, publish)


def test_the_scheduled_run_publishes_the_pinned_version_once_and_ends_the_schedule() -> None:
    client, scheduler, clock, service, newest = setup(first_published="2026-11-04T15:02:00Z", versions=2)
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-14 08:00"}, SAM)
    clock.set("2026-11-14T13:00:01Z")
    published: list[str] = []
    result = run_at(client, service, newest, "2026-11-14T13:00:00Z", published)
    assert result["published"] is True and published == [newest]
    row = item(client, newest)
    assert row["status"] == "published" and row["versionPublishedAt"] == "2026-11-14T13:00:01Z" and row["versionPublishedBy"] == "scheduled by sam"
    assert row["publishedAt"] == "2026-11-04T15:02:00Z"   # the first publication stays
    assert not row.get("scheduleState") and scheduler.schedules == {}


def test_a_second_run_of_the_same_schedule_changes_nothing() -> None:
    client, _scheduler, clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    clock.set("2026-11-13T14:00:01Z")
    published: list[str] = []
    assert run_at(client, service, newest, "2026-11-13T14:00:00Z", published)["published"] is True
    writes = len(client.write_calls())
    second = run_at(client, service, newest, "2026-11-13T14:00:00Z", published)
    assert second["published"] is False and published == [newest] and len(client.write_calls()) == writes


def test_two_runs_at_the_same_moment_publish_once() -> None:
    """The second run reads the row while it is still scheduled, then loses the conditional claim."""
    client, _scheduler, clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    clock.set("2026-11-13T14:00:01Z")
    published: list[str] = []
    real_get, rival = client.get_record, {"done": False}

    def racing_get(model_name: str, record_id: str):
        row = real_get(model_name, record_id)
        if model_name == "Item" and record_id == newest and not rival["done"]:
            rival["done"] = True   # the rival run claims the row right after this run read it as scheduled
            assert client.update_record_if("Item", {"id": newest, "scheduleState": PUBLISHING}, {"scheduleState": {"eq": SCHEDULED}})
        return row

    client.get_record = racing_get   # type: ignore[method-assign]
    result = run_at(client, service, newest, "2026-11-13T14:00:00Z", published)
    assert result["published"] is False and published == [] and item(client, newest)["scheduleState"] == PUBLISHING


def test_a_run_for_an_old_time_does_not_publish_after_the_time_was_changed() -> None:
    client, _scheduler, clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 11:00"}, SAM)
    clock.set("2026-11-13T14:05:00Z")
    published: list[str] = []
    result = run_at(client, service, newest, "2026-11-13T14:00:00Z", published)
    assert result["published"] is False and published == []
    row = item(client, newest)
    assert row["scheduleState"] == SCHEDULED and row["scheduledPublishAt"] == "2026-11-13T16:00:00Z"


def test_a_newer_version_saved_after_scheduling_blocks_the_publish_and_tells_the_editors() -> None:
    client, _scheduler, clock, service, scheduled = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    from papyrus_content.story_reporting import save_story_version

    save_story_version(client, LINEAGE, front_matter_yaml="title: Robots\n", body_markus="The agent rewrote it.\n", actor="copywriting-agent", change_reason="rewrite", now="2026-11-12T12:00:00Z")
    clock.set("2026-11-13T14:00:01Z")
    published: list[str] = []
    result = run_at(client, service, scheduled, "2026-11-13T14:00:00Z", published)
    assert result["blocked"] is True and result["reason"] == BLOCKED_MESSAGE and published == []
    assert item(client, scheduled)["scheduleState"] == BLOCKED and item(client, scheduled).get("status") != "published"
    requests = list(client.tables["ReviewRequest"].values())
    assert len(requests) == 1 and requests[0]["id"].startswith("rr-schedule-blocked-") and "Schedule it again." in requests[0]["ask"]
    entry = service.listing({})["schedules"][0]
    assert entry["state"] == BLOCKED and entry["message"] == BLOCKED_MESSAGE


def test_a_publish_that_fails_hands_the_schedule_back_and_shows_it_overdue() -> None:
    client, _scheduler, clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    clock.set("2026-11-13T14:00:01Z")

    def refuse(row: dict[str, Any]) -> None:
        raise PublishError("checklist-open", "A required step is open.")

    with pytest.raises(PublishError):
        service.run_scheduled_publish(newest, "2026-11-13T14:00:00Z", refuse)
    assert item(client, newest)["scheduleState"] == SCHEDULED   # the retry can claim it again
    assert service.listing({})["schedules"][0]["state"] == OVERDUE


def test_clearing_through_a_published_version_removes_older_schedules_only() -> None:
    client, scheduler, _clock, service, first = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    assert service.clear_through(LINEAGE, 1) == [first] and scheduler.schedules == {}
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    assert service.clear_through(LINEAGE, 0) == [] and len(scheduler.schedules) == 1
    assert service.clear_through(LINEAGE) == [first]


# --- listing -------------------------------------------------------------------------------------------------------------------------------------------


def test_the_listing_reads_the_index_by_state_and_range_and_marks_overdue() -> None:
    client, _scheduler, clock, service, newest = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    listing = service.listing({"from": "2026-11-13 00:00", "to": "2026-11-13 23:59"})
    assert [entry["state"] for entry in listing["schedules"]] == [SCHEDULED] and listing["schedules"][0]["label"] == "Fri 13 Nov 2026, 09:00 EST" and listing["timeZone"] == ZONE
    window = ("2026-11-13T05:00:00Z", "2026-11-14T04:59:00Z")
    assert [call for call in client.calls if call[0] == "list_schedule"] == [("list_schedule", state, window) for state in (SCHEDULED, PUBLISHING, BLOCKED)]   # one index query per state, never a table read
    assert not [call for call in client.calls if call[0] == "list" and call[1] == "Item"]
    assert service.listing({"from": "2026-11-14 00:00"})["schedules"] == []
    clock.set("2026-11-13T15:00:00Z")
    assert [entry["state"] for entry in service.listing({})["schedules"]] == [OVERDUE]
    assert service.listing({"states": [SCHEDULED]})["schedules"] == [] and len(service.listing({"states": [OVERDUE]})["schedules"]) == 1
    assert [entry["itemId"] for entry in service.listing({"storyLineageId": LINEAGE})["schedules"]] == [newest]
    assert refusal(lambda: service.listing({"from": "2026-11-14 00:00", "to": "2026-11-13 00:00"})).code == "bad-range"


# --- the operation table -------------------------------------------------------------------------------------------------------------------------------------


def test_the_operation_table_has_one_tool_and_one_command_per_operation() -> None:
    assert {name: (operation.mcp, operation.cli) for name, operation in OPERATIONS.items()} == {"schedule": ("stories_schedule", "schedule"), "schedule_list": ("stories_schedule_list", "schedule-list")}
    from papyrus_content.story_signals_mcp import story_signal_descriptions, story_signal_tools

    tools = story_signal_tools()
    for operation in OPERATIONS.values():
        assert tools[operation.mcp] == ("staff", operation.schema) and story_signal_descriptions()[operation.mcp] == operation.summary


def test_the_table_refuses_unknown_inputs_and_unknown_operations() -> None:
    _client, _scheduler, _clock, service, _newest = setup()
    unknown = run_operation("schedule", {"storyLineageId": LINEAGE, "at": "2026-11-13 09:00", "when": "now"}, service, SAM)
    assert unknown["ok"] is False and unknown["errors"][0]["code"] == "bad-input"
    assert run_operation("explode", {}, service, SAM)["errors"][0]["code"] == "unknown-operation"
    assert run_operation("schedule", {"storyLineageId": LINEAGE, "clear": "yes"}, service, SAM)["errors"][0]["code"] == "bad-input"


def test_a_refusal_is_a_plain_response_carrying_the_choices() -> None:
    _client, _scheduler, _clock, service, _newest = setup()
    response = run_operation("schedule", {"storyLineageId": LINEAGE, "at": "2026-11-01 01:30"}, service, SAM)
    assert response["ok"] is False and response["errors"][0]["code"] == "ambiguous-time" and len(response["errors"][0]["choices"]) == 2


# --- the Scheduler call -----------------------------------------------------------------------------------------------------------------------------------


class FakeSchedulerApi:
    class exceptions:  # noqa: N801
        ConflictException = type("ConflictException", (Exception,), {})
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.deleted: list[str] = []
        self.conflict = False
        self.missing = False

    def create_schedule(self, **parameters: Any) -> None:
        if self.conflict:
            raise self.exceptions.ConflictException()
        self.created.append(parameters)

    def update_schedule(self, **parameters: Any) -> None:
        self.updated.append(parameters)

    def delete_schedule(self, Name: str) -> None:  # noqa: N803
        if self.missing:
            raise self.exceptions.ResourceNotFoundException()
        self.deleted.append(Name)


def test_the_schedule_is_a_one_off_utc_timer_with_a_dead_letter_queue() -> None:
    api = FakeSchedulerApi()
    scheduler = EventBridgeScheduler(function_arn="arn:aws:lambda:us-east-1:1:function:f", role_arn="arn:aws:iam::1:role/r", dead_letter_arn="arn:aws:sqs:us-east-1:1:dlq", name_prefix=PREFIX, client=api)
    name = scheduler.name_for("item-articles-robots-v2")
    scheduler.upsert(name, "item-articles-robots-v2", "2026-11-13T14:00:00Z")
    parameters = api.created[0]
    assert name.startswith(PREFIX) and len(name) <= 64 and parameters["Name"] == name
    assert parameters["ScheduleExpression"] == "at(2026-11-13T14:00:00)" and parameters["ScheduleExpressionTimezone"] == "UTC"
    assert parameters["FlexibleTimeWindow"] == {"Mode": "OFF"} and parameters["ActionAfterCompletion"] == "DELETE"
    assert parameters["Target"]["DeadLetterConfig"] == {"Arn": "arn:aws:sqs:us-east-1:1:dlq"} and parameters["Target"]["RoleArn"] == "arn:aws:iam::1:role/r"
    assert json.loads(parameters["Target"]["Input"]) == {"projectionTask": {"task": "publish-scheduled", "itemId": "item-articles-robots-v2", "scheduledPublishAt": "2026-11-13T14:00:00Z"}}
    api.conflict = True
    scheduler.upsert(name, "item-articles-robots-v2", "2026-11-13T16:00:00Z")
    assert api.updated[0]["ScheduleExpression"] == "at(2026-11-13T16:00:00)"
    scheduler.delete(name)
    api.missing = True
    scheduler.delete(name)   # a schedule the service already deleted after it ran is not an error


def test_names_differ_for_versions_that_share_a_long_prefix() -> None:
    assert schedule_name(PREFIX, "item-articles-robots-v2") != schedule_name(PREFIX, "item-articles-robots-v3")


def test_the_environment_wires_the_scheduler_or_says_what_is_missing() -> None:
    assert scheduler_from_environment({}) is None
    with pytest.raises(ScheduleError) as caught:
        scheduler_from_environment({"PAPYRUS_PUBLICATION_TIME_ZONE": ZONE})
    assert caught.value.code == "scheduling-misconfigured" and "PAPYRUS_SCHEDULER_ROLE_ARN" in caught.value.message
    wired = scheduler_from_environment({"PAPYRUS_PUBLICATION_TIME_ZONE": ZONE, "PAPYRUS_SCHEDULER_ROLE_ARN": "r", "PAPYRUS_SCHEDULER_DEAD_LETTER_ARN": "d", "PAPYRUS_SCHEDULE_NAME_PREFIX": PREFIX},
                                       invoked_function_arn="arn:aws:lambda:us-east-1:1:function:f")
    assert wired is not None and wired.function_arn.endswith(":function:f")


# --- the data API client ---------------------------------------------------------------------------------------------------------------------------------


def api_client(answers: list[Any]):
    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient

    client = PapyrusGraphQLAuthoringClient(endpoint="https://example.appsync-api.us-east-1.amazonaws.com/graphql", tenant_id=None, site_tenant=False)
    client.sent = []   # type: ignore[attr-defined]

    def graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        client.sent.append((query, variables))   # type: ignore[attr-defined]
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client.graphql = graphql   # type: ignore[method-assign]
    return client


def test_the_conditional_update_is_one_conditional_write_and_a_lost_condition_is_an_answer() -> None:
    client = api_client([{"updateItem": {"id": "a"}}, RuntimeError("DynamoDB:ConditionalCheckFailedException: The conditional request failed"), RuntimeError("timed out")])
    condition = {"scheduleState": {"eq": "scheduled"}}
    assert client.update_record_if("Item", {"id": "a", "scheduleState": "publishing"}, condition) is True
    query, variables = client.sent[0]
    assert "$condition: ModelItemConditionInput" in query and "updateItem(input: $input, condition: $condition)" in query and variables["condition"] == condition
    assert client.update_record_if("Item", {"id": "a", "scheduleState": "publishing"}, condition) is False
    with pytest.raises(RuntimeError, match="timed out"):
        client.update_record_if("Item", {"id": "a", "scheduleState": "publishing"}, condition)


def test_the_listing_query_is_a_range_on_the_schedule_index_and_follows_pages() -> None:
    page = lambda ids, token: {"listItemsByScheduleStateAndScheduledPublishAt": {"items": [{"id": i, "tenantId": None} for i in ids], "nextToken": token}}  # noqa: E731
    client = api_client([page(["a"], "t1"), page(["b"], None)])
    assert [row["id"] for row in client.list_schedule("scheduled", "2026-11-13T05:00:00Z", "2026-11-14T04:59:00Z")] == ["a", "b"]
    query, variables = client.sent[0]
    assert "listItemsByScheduleStateAndScheduledPublishAt(scheduleState: $state, scheduledPublishAt: {between: $range}" in query and "scheduleName" in query
    assert variables["range"] == ["2026-11-13T05:00:00Z", "2026-11-14T04:59:00Z"] and client.sent[1][1]["nextToken"] == "t1"
    open_ended = api_client([page([], None)])
    open_ended.list_schedule("blocked", None, None)
    assert "scheduledPublishAt:" not in open_ended.sent[0][0]


def test_a_new_version_does_not_inherit_the_schedule_of_the_one_before() -> None:
    from papyrus_content.story_schedule import SCHEDULE_FIELDS

    client, _scheduler, _clock, service, first = setup()
    service.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, SAM)
    from papyrus_content.story_reporting import save_story_version

    second = save_story_version(client, LINEAGE, front_matter_yaml="title: Robots\n", body_markus="Newer.\n", actor="Alex", change_reason="edit", now="2026-11-11T12:00:00Z")
    assert not [name for name in SCHEDULE_FIELDS if second.get(name)] and item(client, first)["scheduleState"] == SCHEDULED
