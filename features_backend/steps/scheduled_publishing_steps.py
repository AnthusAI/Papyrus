"""Scheduled publishing (features_backend/scheduled-publishing*.feature): the real content-actions handler over the shared in-memory client and a recording Scheduler."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shlex
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import story_commands, story_retire, story_schedule_commands  # noqa: E402
from papyrus_content import story_schedule  # noqa: E402
from papyrus_content.story_reporting import save_story_version  # noqa: E402
from papyrus_content.story_schedule import BLOCKED_MESSAGE, Caller  # noqa: E402
from papyrus_content.story_signals_mcp import call_story_signal_tool  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402
from procedures.newsroom.tests.incremental_site import Site, add_item  # noqa: E402
from procedures.newsroom.tests.schedule_support import LINEAGE, Clock, FakeScheduler, SiteClient, new_story, service_for  # noqa: E402

HANDLER_PATH = REPO_ROOT / "amplify/functions/content-actions/handler.py"
MONTHS = {"January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6, "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12}
SAM = Caller(actor="sam", person="sam-sub", groups=("editor",))
LEE = Caller(actor="lee", person="lee-sub", groups=("reader",))


def load_handler():
    specification = importlib.util.spec_from_file_location("content_actions_handler_for_schedule_steps", HANDLER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class World:
    """One scenario's site: the client, the Scheduler's timers, the clock and the Lambda handler wired to them."""

    def __init__(self) -> None:
        self.zone: str | None = "America/New_York"
        self.client = FakeAuthoringClient()
        self.scheduler = FakeScheduler()
        self.clock = Clock("2026-11-10T15:00:00Z")
        self.versions, self.first_published, self.title = 1, None, "Robots in the warehouse"
        self.built = False
        self.caller = SAM
        self.handler = load_handler()
        self.response: dict | None = None
        self.published_log: list[str] = []

    def story(self) -> None:
        if not self.built:
            new_story(self.client, first_published=self.first_published, versions=self.versions)
            self.built = True

    @property
    def service(self):
        return service_for(self.client, self.scheduler, self.clock, self.zone)

    def row(self, number: int) -> dict:
        self.story()
        return next(row for row in self.client.tables["Item"].values() if row.get("lineageId") == LINEAGE and row["versionNumber"] == number)

    def rows(self) -> list[dict]:
        return sorted((row for row in self.client.tables["Item"].values() if row.get("lineageId") == LINEAGE), key=lambda row: row["versionNumber"])

    def event(self, field: str, payload: dict, caller: Caller | None = None) -> dict:
        who = caller or self.caller
        return {"fieldName": field, "arguments": {"input": json.dumps(payload)},
                "identity": {"username": who.actor, "sub": who.person, "issuer": "https://cognito", "groups": list(who.groups or ())}}

    def call(self, event: dict) -> dict:
        """Run the handler with the world's client, service and clock: everything outside the data (the page build) is stood in for."""
        handler = self.handler
        go_live = self.clock.iso()
        with mock.patch.object(handler, "create_authoring_client", return_value=(self.client, {})), mock.patch.object(handler, "schedule_service", side_effect=lambda client: self.service), \
                mock.patch.object(handler, "render_preflight"), mock.patch.object(handler, "projection_configured", return_value=False), \
                mock.patch.object(handler, "project_item_action", return_value={"projected": True}), mock.patch("papyrus_content.publishing.utc_now_iso", return_value=go_live):
            return handler.handler(event, None)

    def schedule(self, payload: dict, caller: Caller | None = None) -> dict:
        self.response = self.call(self.event("scheduleItem", {"operation": "schedule", "arguments": payload}, caller))
        return self.response

    def fire(self, item_id: str, at: str) -> dict:
        return self.call({"projectionTask": {"task": "publish-scheduled", "itemId": item_id, "scheduledPublishAt": at}})

    def utc(self, day: int, month: str, year: int, hour: int, minute: int) -> str:
        return f"{year:04d}-{MONTHS[month]:02d}-{day:02d}T{hour:02d}:{minute:02d}:00Z"


def world(context) -> World:
    if not hasattr(context, "world"):
        context.world = World()
    return context.world


def local_text(day: int, month: str, year: int, hour: int, minute: int) -> str:
    return f"{year:04d}-{MONTHS[month]:02d}-{day:02d} {hour:02d}:{minute:02d}"


# --- Given -------------------------------------------------------------------------------------------------------------------------------------------


@given("the publication's time zone is {zone}")
def _zone(context, zone) -> None:
    world(context).zone = zone


@given("the publication has no time zone set")
def _no_zone(context) -> None:
    world(context).zone = None


@given("Sam may publish on this site")
def _sam(context) -> None:
    world(context).caller = SAM


@given("Lee may edit but not publish")
def _lee(context) -> None:
    world(context).lee = LEE


@given("it is {day:d} {month} {year:d} at {hour:d}:{minute:d} UTC")
def _now(context, day, month, year, hour, minute) -> None:
    w = world(context)
    w.clock.set(w.utc(day, month, year, hour, minute))


@given('the Story "{title}" has {count:d} versions')
def _versions(context, title, count) -> None:
    w = world(context)
    w.title, w.versions = title, count
    w.story()


@given('the Story "{title}" was first published on {day:d} {month} {year:d} and has {count:d} versions')
def _first(context, title, day, month, year, count) -> None:
    w = world(context)
    w.title, w.versions, w.first_published = title, count, w.utc(day, month, year, 15, 2)
    w.story()


@given("Sam scheduled version {number:d} for {day:d} {month} {year:d} at {hour:d}:{minute:d} New York time")
def _scheduled(context, number, day, month, year, hour, minute) -> None:
    w = world(context)
    answer = w.schedule({"itemId": w.row(number)["id"], "at": local_text(day, month, year, hour, minute)})
    assert answer.get("ok") is True, answer


@given("the timer delivered its event at {day:d} {month} {year:d} at {hour:d}:{minute:d} UTC")
def _delivered(context, day, month, year, hour, minute) -> None:
    w = world(context)
    w.clock.set(w.utc(day, month, year, hour, minute))
    event = _scheduled_event(w)
    w.response = w.fire(event["itemId"], event["scheduledPublishAt"])


@given("the copywriting agent saved version {number:d} on {day:d} {month} {year:d}")
@when("the copywriting agent saved version {number:d} on {day:d} {month} {year:d}")
def _agent_saved(context, number, day, month, year) -> None:
    w = world(context)
    w.story()
    saved = save_story_version(w.client, LINEAGE, front_matter_yaml="title: Robots in the warehouse\n", body_markus=f"The agent saved version {number}.\n", actor="copywriting-agent",
                               change_reason="rewrite", now=w.utc(day, month, year, 12, 0))
    assert saved["versionNumber"] == number, saved


@given("Sam published version {number:d}")
def _published_now(context, number) -> None:
    w = world(context)
    answer = w.call(w.event("publishItem", {"id": w.row(number)["id"]}))
    assert answer["ok"] is True and answer["changed"] is True, answer


@given("a scheduled version whose schedule fires twice at the same moment")
def _fires_twice(context) -> None:
    w = world(context)
    answer = w.schedule({"itemId": w.row(3)["id"], "at": "2026-11-13 09:00"})
    assert answer["ok"] is True, answer
    w.clock.set("2026-11-13T14:00:01Z")


@given("Sam moved a schedule from 09:00 to 11:00 on {day:d} {month} {year:d}")
def _moved(context, day, month, year) -> None:
    w = world(context)
    for hour in (9, 11):
        answer = w.schedule({"itemId": w.row(3)["id"], "at": local_text(day, month, year, hour, 0)})
        assert answer["ok"] is True, answer


@given('a published Story "{old}" with a scheduled newer version, and another published Story "{new}"')
def _retire_world(context, old, new) -> None:
    w = world(context)
    work = tempfile.mkdtemp(prefix="retire-schedule-")
    context.tmp_dirs.append(work)
    site = Site("feed", Path(work))
    for item_id, slug in (("item-old", "old-warehouse-piece"), ("item-new", "warehouse-automation")):
        add_item(site, item_id, slug)
        site.project_item(item_id)
    save_story_version(site.client, "item-old", front_matter_yaml="title: Old\n", body_markus="A newer version.\n", actor="Alex", change_reason="edit", now="2026-11-09T12:00:00Z")
    w.client = site.client
    w.retire_site = site
    answer = w.service.schedule({"storyLineageId": "item-old", "at": "2026-11-13 09:00"}, SAM)
    assert answer["ok"] is True, answer
    w.built = True


# --- When --------------------------------------------------------------------------------------------------------------------------------------------


def _scheduled_event(w: World) -> dict:
    return next(iter(w.scheduler.schedules.values()))


@when("{day:d} {month} {year:d} at {hour:d}:{minute:d} UTC arrives")
def _arrives(context, day, month, year, hour, minute) -> None:
    w = world(context)
    w.clock.set(w.utc(day, month, year, hour, minute))
    event = _scheduled_event(w)
    w.response = w.fire(event["itemId"], event["scheduledPublishAt"])


@when("{day:d} {month} {year:d} at {hour:d}:{minute:d} UTC arrives and nothing ran")
def _arrives_nothing_ran(context, day, month, year, hour, minute) -> None:
    w = world(context)
    w.clock.set(w.utc(day, month, year, hour, minute))


@when("both runs try to publish it")
def _both(context) -> None:
    """Run B reads the version while it is still scheduled; run A then claims and publishes it; run B's claim loses."""
    w = world(context)
    event = _scheduled_event(w)
    snapshot = {"claimed_by_rival": None}
    real_get = w.client.get_record
    state = {"rival_running": False}

    def get_record(model_name: str, record_id: str):
        row = real_get(model_name, record_id)
        if model_name == "Item" and record_id == event["itemId"] and not state["rival_running"] and snapshot["claimed_by_rival"] is None:
            state["rival_running"] = True
            snapshot["claimed_by_rival"] = w.fire(event["itemId"], event["scheduledPublishAt"])   # run A, complete, between B's read and B's claim
            state["rival_running"] = False
        return row

    w.client.get_record = get_record   # type: ignore[method-assign]
    context.first_run = None
    second = w.fire(event["itemId"], event["scheduledPublishAt"])
    w.client.get_record = real_get   # type: ignore[method-assign]
    context.first_run, context.second_run = snapshot["claimed_by_rival"], second


@when("a run for 09:00 arrives late")
def _late(context) -> None:
    w = world(context)
    w.clock.set("2026-11-13T14:05:00Z")
    old = w.scheduler.history[0]
    w.response = w.fire(old["itemId"], old["scheduledPublishAt"])


@when("Sam publishes version {number:d} now")
def _publish_now(context, number) -> None:
    w = world(context)
    w.response = w.call(w.event("publishItem", {"id": w.row(number)["id"]}))


@when("Sam takes the Story down")
def _take_down(context) -> None:
    w = world(context)
    served = next(row for row in w.rows() if row.get("status") == "published")
    w.response = w.call(w.event("unpublishItem", {"id": served["id"]}))


@when("an editor retires \"{old}\" into \"{new}\"")
def _retire(context, old, new) -> None:
    w = world(context)
    session = SiteClient(w.client, w.service)
    context.retire_session = session
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(session, {"sub": "ed-sub"})):
        story_retire.stories_retire(["--story", "item-old", "--redirect-to", "item-new", "--no-trigger"])
    context.retire_output = out.getvalue()


@when("Sam schedules version {number:d} for {day:d} {month} {year:d} at {hour:d}:{minute:d} New York time")
def _schedules(context, number, day, month, year, hour, minute) -> None:
    w = world(context)
    answer = w.schedule({"itemId": w.row(number)["id"], "at": local_text(day, month, year, hour, minute)})
    assert answer.get("ok") is True, answer


@when("Sam schedules version {number:d} for the exact time {text}")
def _schedules_exact(context, number, text) -> None:
    w = world(context)
    answer = w.schedule({"itemId": w.row(number)["id"], "at": text})
    assert answer.get("ok") is True, answer


@when("Sam asks to schedule for {day:d} {month} {year:d} at {hour:d}:{minute:d} New York time")
def _asks(context, day, month, year, hour, minute) -> None:
    w = world(context)
    w.story()
    w.schedule({"storyLineageId": LINEAGE, "at": local_text(day, month, year, hour, minute)})


@when("Sam asks to schedule version {number:d} for {day:d} {month} {year:d} at {hour:d}:{minute:d} New York time")
def _asks_version(context, number, day, month, year, hour, minute) -> None:
    w = world(context)
    w.schedule({"itemId": w.row(number)["id"], "at": local_text(day, month, year, hour, minute)})


@when("Lee tries to schedule a version")
def _lee_tries(context) -> None:
    w = world(context)
    w.schedule({"storyLineageId": LINEAGE, "at": "2026-11-13 09:00"}, caller=LEE)


# --- Then --------------------------------------------------------------------------------------------------------------------------------------------


def _lineage_state(w: World) -> list[dict]:
    return [row for row in w.rows() if row.get("scheduleState")]


@then("version {number:d} is published")
def _is_published(context, number) -> None:
    w = world(context)
    row = w.row(number)
    served = w.client.tables["PublishedItem"]["published-" + LINEAGE]
    assert row["status"] == "published" and served["sourceItemId"] == row["id"], (row, served)


@then("no version of the Story goes live")
def _nothing_published(context) -> None:
    w = world(context)
    assert "published-" + LINEAGE not in w.client.tables.get("PublishedItem", {}), w.client.tables["PublishedItem"]
    assert not any(row.get("status") == "published" for row in w.rows())


@then("the Story's published time is the moment it went live")
def _published_time(context) -> None:
    w = world(context)
    assert w.client.tables["PublishedItem"]["published-" + LINEAGE]["publishedAt"] == w.clock.iso()


@then("the version records that it was published as scheduled by Sam")
def _records_scheduler(context) -> None:
    w = world(context)
    served = w.client.tables["PublishedItem"]["published-" + LINEAGE]
    assert served["versionPublishedBy"] == "scheduled by sam", served


@then("the Story no longer shows a schedule")
def _no_schedule(context) -> None:
    w = world(context)
    assert not _lineage_state(w) and w.scheduler.schedules == {}
    assert w.service.listing({})["schedules"] == []


@then("version {number:d} carries the schedule: scheduled for {day:d} {month} {year:d} at {hour:d}:{minute:d} UTC by {who}")
def _carries(context, number, day, month, year, hour, minute, who) -> None:
    w = world(context)
    row = w.row(number)
    assert (row["scheduleState"], row["scheduledPublishAt"], row["scheduledBy"]) == ("scheduled", w.utc(day, month, year, hour, minute), who.lower()), row
    assert row["scheduleName"] and row["scheduledAt"], row


@then("one timer is set to deliver an event for version {number:d} at {hour:d}:{minute:d} UTC on {day:d} {month} {year:d}")
def _one_timer(context, number, hour, minute, day, month, year) -> None:
    w = world(context)
    assert list(w.scheduler.schedules.values()) == [{"itemId": w.row(number)["id"], "scheduledPublishAt": w.utc(day, month, year, hour, minute)}], w.scheduler.schedules


@then("the schedule index lists version {number:d} as scheduled")
def _indexed(context, number) -> None:
    w = world(context)
    listed = [row["id"] for row in w.client.list_schedule("scheduled")]
    assert listed == [w.row(number)["id"]], listed


@then('the schedule says "{message}"')
def _schedule_says(context, message) -> None:
    w = world(context)
    entries = w.service.listing({})["schedules"]
    assert [entry["message"] for entry in entries] == [message] and entries[0]["state"] == "blocked", entries


@then("the site's editors are told")
def _editors_told(context) -> None:
    w = world(context)
    requests = list(w.client.tables.get("ReviewRequest", {}).values())
    assert len(requests) == 1 and requests[0]["mode"] == "flag" and BLOCKED_MESSAGE in requests[0]["ask"], requests


@then("version {number:d} carries no schedule")
def _no_schedule_on(context, number) -> None:
    w = world(context)
    row = w.row(number)
    assert not [name for name in story_schedule.SCHEDULE_FIELDS if row.get(name)], row


@then("version {number:d} is still scheduled for {day:d} {month} {year:d} at {hour:d}:{minute:d} UTC")
def _still_scheduled(context, number, day, month, year, hour, minute) -> None:
    w = world(context)
    row = w.row(number)
    assert (row["scheduleState"], row["scheduledPublishAt"]) == ("scheduled", w.utc(day, month, year, hour, minute)), row


@then("the Story has exactly one schedule, on version {number:d}, for {day:d} {month} {year:d} at {hour:d}:{minute:d} UTC")
def _exactly_one(context, number, day, month, year, hour, minute) -> None:
    w = world(context)
    assert [row["id"] for row in _lineage_state(w)] == [w.row(number)["id"]]
    assert list(w.scheduler.schedules.values()) == [{"itemId": w.row(number)["id"], "scheduledPublishAt": w.utc(day, month, year, hour, minute)}]


@then("it is published once")
def _once(context) -> None:
    w = world(context)
    assert context.first_run["published"] is True, context.first_run
    served = w.client.tables["PublishedItem"]["published-" + LINEAGE]
    assert served["versionNumber"] == 1 and sum(1 for call in w.client.calls if call[:2] == ("upsert", "PublishedItem")) == 1, [call for call in w.client.calls if call[1] == "PublishedItem"]


@then("the second run stops without changing anything")
def _second_stops(context) -> None:
    assert context.second_run["published"] is False and "claimed" in context.second_run["reason"], context.second_run


@then("the schedule is removed and will not fire")
def _removed(context) -> None:
    w = world(context)
    assert not _lineage_state(w) and w.scheduler.schedules == {}
    for old in w.scheduler.history:   # a timer that fires anyway finds nothing to do
        later = w.fire(old["itemId"], old["scheduledPublishAt"])
        assert later["published"] is False, later


@then('the schedule of "{old}" is removed before the Story is retired')
def _retired_after_unschedule(context, old) -> None:
    w = world(context)
    out = context.retire_output
    assert out.index("unscheduled") < out.index("saved"), out
    assert w.scheduler.schedules == {} and not [row for row in w.client.tables["Item"].values() if row.get("scheduleState")]
    assert [m["arguments"] for m in context.retire_session.mutations] == [{"storyLineageId": "item-old", "clear": True}]


@then("the Story's published time is still {day:d} {month} {year:d}")
def _first_kept(context, day, month, year) -> None:
    w = world(context)
    assert w.client.tables["PublishedItem"]["published-" + LINEAGE]["publishedAt"] == w.utc(day, month, year, 15, 2)
    assert w.row(5)["publishedAt"] == w.utc(day, month, year, 15, 2)


@then("the served version's published time is {day:d} {month} {year:d} at {hour:d}:{minute:d} UTC")
def _served_time(context, day, month, year, hour, minute) -> None:
    w = world(context)
    served = w.client.tables["PublishedItem"]["published-" + LINEAGE]
    assert served["versionPublishedAt"] == w.utc(day, month, year, hour, minute) and w.row(5)["versionPublishedAt"] == served["versionPublishedAt"], served


@then('the schedule list shows "{title}" as overdue with its scheduled time')
def _overdue(context, title) -> None:
    w = world(context)
    entries = w.service.listing({})["schedules"]
    assert [(entry["title"], entry["state"], entry["scheduledPublishAt"]) for entry in entries] == [(title, "overdue", "2026-11-13T14:00:00Z")], entries
    assert entries[0]["label"] == "Fri 13 Nov 2026, 09:00 EST"


@then("the timer is a one-off in UTC that is removed after it runs")
def _timer_one_off(context) -> None:
    from papyrus_content.story_schedule import EventBridgeScheduler

    w = world(context)
    api = _RecordingApi()
    scheduler = EventBridgeScheduler(function_arn="arn:aws:lambda:us-east-1:1:function:f", role_arn="arn:aws:iam::1:role/r", dead_letter_arn="arn:aws:sqs:us-east-1:1:dlq",
                                     name_prefix=w.scheduler.name_prefix, client=api)
    event = _scheduled_event(w)
    scheduler.upsert("papyrus-pub-test-x", event["itemId"], event["scheduledPublishAt"])
    context.timer = api.created[0]
    assert context.timer["ScheduleExpression"] == "at(2026-11-13T14:00:00)" and context.timer["ScheduleExpressionTimezone"] == "UTC"
    assert context.timer["ActionAfterCompletion"] == "DELETE" and context.timer["FlexibleTimeWindow"] == {"Mode": "OFF"}


@then("an event the timer cannot deliver goes to the site's dead letter queue")
def _timer_dlq(context) -> None:
    assert context.timer["Target"]["DeadLetterConfig"] == {"Arn": "arn:aws:sqs:us-east-1:1:dlq"}


class _RecordingApi:
    class exceptions:  # noqa: N801
        ConflictException = type("ConflictException", (Exception,), {})
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_schedule(self, **parameters) -> None:
        self.created.append(parameters)


@then('the scheduling request is refused with "{message}"')
def _refused(context, message) -> None:
    errors = world(context).response["errors"]
    assert world(context).response["ok"] is False and errors[0]["message"] == message, errors


@then("nothing is scheduled")
def _nothing_scheduled(context) -> None:
    w = world(context)
    assert not _lineage_state(w) and w.scheduler.schedules == {}


@then("Sam is asked to choose between {first} and {second}")
def _choose(context, first, second) -> None:
    error = world(context).response["errors"][0]
    assert error["code"] == "ambiguous-time" and [choice["label"] for choice in error["choices"]] == [first, second], error


# --- the command line and the tools --------------------------------------------------------------------------------------------------------------------------


@when('an agent types "{command}"')
def _agent_runs(context, command) -> None:
    w = world(context)
    w.story()
    tokens = [LINEAGE if token == "LINEAGE" else token for token in shlex.split(command)]
    assert tokens[:2] == ["papyrus", "stories"], tokens
    verb, flags = tokens[2], tokens[3:]
    session = SiteClient(w.client, w.service)
    context.session, context.error, out = session, None, io.StringIO()
    entry = {"schedule": story_schedule_commands.stories_schedule, "schedule-list": story_schedule_commands.stories_schedule_list, "show": story_commands.stories_show}[verb]
    real_effective = story_schedule.effective_state
    with contextlib.redirect_stdout(out), mock.patch("papyrus_content.story_schedule_commands.create_authoring_client", return_value=(session, {})), \
            mock.patch("papyrus_content.story_commands.create_authoring_client", return_value=(session, {})), \
            mock.patch("papyrus_content.story_schedule.effective_state", side_effect=lambda row, now: real_effective(row, w.clock.moment)):
        try:
            entry(flags)
        except ValueError as error:
            context.error = str(error)
    context.output = [line.split("\t") for line in out.getvalue().splitlines()]


@then('the output says the Story is scheduled for "{label}" by {who}')
def _out_scheduled(context, label, who) -> None:
    line = next(columns for columns in context.output if columns[:3] == ["stories", "schedule", "scheduled"])
    assert line[6].startswith(label) and line[7] == f"by {who.lower()}", line


@then("the output says it would schedule the Story")
def _out_would(context) -> None:
    assert context.output[0][2] == "would schedule" and context.output[0][-1] == "dry run", context.output


@then("the output says the schedule was cleared")
def _out_cleared(context) -> None:
    assert context.output[0][2] == "cleared", context.output


@then('the schedule command fails with "{message}"')
def _command_fails(context, message) -> None:
    assert context.error and message in context.error, context.error


@then('the output has a schedule line: scheduled, version {number:d}, "{utc}", by {who}')
def _show_scheduled(context, number, utc, who) -> None:
    line = next(columns for columns in context.output if columns[:3] == ["stories", "show", "schedule"])
    assert line[3:7] == ["scheduled", f"version {number}", f"publish at {utc} (UTC)", f"by {who.lower()}"], line


@then('the output has a schedule line: blocked, version {number:d}, "{message}"')
def _show_blocked(context, number, message) -> None:
    line = next(columns for columns in context.output if columns[:3] == ["stories", "show", "schedule"])
    assert line[3:5] == ["blocked", f"version {number}"] and line[-1] == message, line


@then('the list has one line: "{title}", version {number:d}, scheduled, "{label}", by {who}')
def _list_line(context, title, number, label, who) -> None:
    lines = [columns for columns in context.output if columns[:2] == ["stories", "schedule-list"] and columns[2] == LINEAGE]
    assert len(lines) == 1 and lines[0][3:6] == [title, f"version {number}", "scheduled"] and lines[0][6].startswith(label) and lines[0][7] == f"by {who.lower()}", lines


@then("the schedule was read from the schedule index, one query for each state")
def _list_from_index(context) -> None:
    w = world(context)
    reads = [call for call in w.client.calls if call[0] == "list_schedule"]
    assert [call[1] for call in reads] == ["scheduled", "publishing", "blocked"], reads
    assert not [call for call in w.client.calls if call[0] == "list" and call[1] == "Item"]


@when('an agent asks the stories_schedule tool to schedule the Story for "{at}"')
def _tool_schedules(context, at) -> None:
    w = world(context)
    w.story()
    session = SiteClient(w.client, w.service)
    context.session = session
    context.tool_answer = call_story_signal_tool("stories_schedule", {"storyLineageId": LINEAGE, "at": at}, session)


@then("the stories_schedule_list tool lists it as scheduled")
def _tool_lists(context) -> None:
    listed = call_story_signal_tool("stories_schedule_list", {"storyLineageId": LINEAGE}, context.session)
    assert [entry["state"] for entry in listed["schedules"]] == ["scheduled"], listed
