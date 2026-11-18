"""The schedule trigger (features_backend/schedule-trigger.feature). A fake site, a fake EventBridge Scheduler group and a fake FIFO wake queue; no network.

The fakes follow the rules the code relies on and nothing more: the scheduler fills in the scheduled time and puts the entry's message on the target queue with
the entry's message group; the queue has content-based deduplication (the scheduler sets no deduplication id), drops a repeated body inside its window and gives
one message at a time; the site's API answers a second start with the same wake key as a duplicate."""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_procedure_runner as tpr  # noqa: E402
from papyrus_content import agent_wakes, automations as au, model_attachments, procedure_runner as pr, wake_keys  # noqa: E402
from papyrus_content.agent_definitions import cli as agents_cli, definition as agent_definition, release, schedules  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore, PersonStart, PolicyGate  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from schedule_fakes import ACCOUNT, ADMIN, ENDPOINT, KEY_PARAMETER, MONITOR, PROCEDURES, REGION, Backend, FakeScheduler, FakeSqs, Reader, Site, WakeQueue  # noqa: E402


def patch(context, target, name, value):
    patcher = mock.patch.object(target, name, value)
    patcher.start()
    context.add_cleanup(patcher.stop)


@given('the site "{site}" with its wake queue, its schedule group and the runner')
def background(context, site):
    names = schedules.names_for(site)
    context.site_id, context.names = site, names
    context.api, context.backend = Site(site), Backend()
    context.scheduler, context.sqs, context.queue = FakeScheduler(names.group), FakeSqs(names.queue), WakeQueue()
    context.reader, context.executed, context.error, context.preview = Reader(site), [], None, None
    context.work = Path(tempfile.mkdtemp(prefix="schedule-trigger-"))
    context.core_dir, context.site_dir = context.work / "core", context.work / "site"
    context.core_dir.mkdir()
    context.site_dir.mkdir()
    context.add_cleanup(shutil.rmtree, context.work, True)
    context.agents, context.gate, context.writes_before, context.result = {}, PersonStart(), 0, {}

    def execute(workdir, source_path, inputs, **_):
        context.executed.append(inputs)
        return {"success": True, "output": {"title": "x"}, "seconds": 1}

    patch(context, model_attachments, "download_attachment_buffer", lambda client, entry, **_: entry["body"])
    patch(context, pr, "execute_in_child", execute)


@given('the agent "{agent}" runs the procedure "{procedure}"')
def agent_runs(context, agent, procedure):
    context.agents[agent] = {"procedure": procedure, "enabled": False, "link": None, "definition": None}


@given('"{agent}" is switched on and linked to the router publication of the site')
def switched_on_linked(context, agent):
    context.agents[agent].update(enabled=True, link={"monitorId": MONITOR, "publicationId": context.site_id})


@given('"{agent}" is not switched on')
def not_switched_on(context, agent):
    context.agents[agent]["enabled"] = False


@given('"{agent}" is switched on but names no router publication')
def switched_on_unlinked(context, agent):
    context.agents[agent].update(enabled=True, link=None)


@given('"{agent}" is linked to the router publication "{publication}"')
def linked_elsewhere(context, agent, publication):
    context.agents[agent]["link"] = {"monitorId": MONITOR, "publicationId": publication}


@when('"{agent}" is switched off')
def switch_off(context, agent):
    context.agents[agent]["enabled"] = False


@when('"{agent}" is switched on')
def switch_on(context, agent):
    context.agents[agent]["enabled"] = True


def definition_text(agent, procedure, wakes):
    data = copy.deepcopy(yaml.safe_load((agent_definition.CORE_DIRECTORY / "rate.yaml").read_text(encoding="utf-8")))
    data.update(id=agent, procedure=procedure, wakes=wakes)
    return yaml.safe_dump(data, sort_keys=False)


def write_definition(context, agent, wakes):
    (context.site_dir / f"{agent}.yaml").write_text(definition_text(agent, context.agents[agent]["procedure"], wakes), encoding="utf-8")


@given('the definition of "{agent}" says to run at "{cron}" in "{zone}"')
@when('the definition of "{agent}" is changed to run at "{cron}" in "{zone}"')
def definition_schedule(context, agent, cron, zone):
    write_definition(context, agent, {"schedule": {"cron": cron, "timeZone": zone}})


@when('the definition of "{agent}" no longer names a schedule')
def definition_without_schedule(context, agent):
    write_definition(context, agent, {"changes": [{"kind": "Item", "change": "step_changed"}]})


@when('the definition of "{agent}" is removed from Git')
def definition_removed(context, agent):
    (context.site_dir / f"{agent}.yaml").unlink()


@given('an entry "{name}" that no definition names is in the schedule group')
@given('a one-shot entry "{name}" of another helper is in the schedule group')
def stray_entry(context, name):
    context.scheduler.entries[name] = {"Name": name, "GroupName": context.names.group, "ScheduleExpression": "at(2026-12-01T00:00:00)"}


@given("the site's schedule group is not deployed yet")
def group_not_deployed(context):
    context.scheduler.deployed = False


def person_changes(context):
    """What a person did to each agent's record since the last deploy: switched it on or off and named its router publication."""
    for agent, state in context.agents.items():
        row = context.api.rows.get(agent)
        if row is None or au.read_record(row).get("definitionRetiredAt"):
            continue
        record = au.read_record(row)
        config = dict(state["link"] or {})
        context.api.rows[agent] = au.stored_payload(au.build_record({"id": agent, "enabled": state["enabled"], "trigger": {"kind": "schedule", "config": config}},
                                                                    existing=record, actor="person"))


def deploy(context, *, apply=True):
    context.error, context.writes_before = None, context.scheduler.writes
    try:
        release.apply_release(context.api, release.load(context.site_dir, context.core_dir), PROCEDURES, apply=True, now="2026-11-17T04:00:00Z")
        person_changes(context)
        context.result = schedules.reconcile_site(context.sqs, context.scheduler, context.api.list_tenant_rows("Automation", ""), context.site_id,
                                                  reader=context.reader, endpoint=ENDPOINT, apply=apply)
    except (release.ReleaseError, schedules.ScheduleError) as error:
        context.error = error


@given("the site deploys")
@when("the site deploys")
@when("the site deploys again")
def site_deploys(context):
    deploy(context)


@when("a person previews the schedules")
def preview(context):
    deploy(context, apply=False)


@when('a definition says to run at "{cron}" in "{zone}"')
def check_definition(context, cron, zone):
    (context.site_dir / "rate-daily.yaml").write_text(definition_text("rate-daily", "rate_items", {"schedule": {"cron": cron, "timeZone": zone}}), encoding="utf-8")
    context.problems = agent_definition.load_sets(context.site_dir, context.core_dir).problems


@when('the cron expression "{cron}" is translated for the scheduler')
def translate(context, cron):
    context.translated = schedules.scheduler_expression(cron)


def entry_of(context, agent):
    return context.scheduler.entries[schedules.entry_name(agent)]


@then("the schedule group holds exactly {count:d} entry")
@then("the schedule group holds exactly {count:d} entries")
def holds_entries(context, count):
    assert context.error is None, context.error
    assert len(context.scheduler.entries) == count, sorted(context.scheduler.entries)


@then('the entry for "{agent}" says "{expression}" in the time zone "{zone}"')
def entry_says(context, agent, expression, zone):
    entry = entry_of(context, agent)
    assert (entry["ScheduleExpression"], entry["ScheduleExpressionTimezone"]) == (expression, zone), entry


@then("the entry has no flexible window")
def no_window(context):
    (entry,) = context.scheduler.entries.values()
    assert entry["FlexibleTimeWindow"] == {"Mode": "OFF"} and entry["State"] == "ENABLED", entry


@then('the entry\'s only target is the wake queue of "{site}"')
def only_target(context, site):
    (entry,) = context.scheduler.entries.values()
    target = entry["Target"]
    assert target["Arn"] == f"arn:aws:sqs:{REGION}:{ACCOUNT}:{agent_wakes.queue_name(site)}", target
    assert target["RoleArn"] == f"arn:aws:iam::{ACCOUNT}:role/{schedules.names_for(site).role}", target
    assert set(target) == {"Arn", "RoleArn", "Input", "SqsParameters"}, "one target, and no retry or dead-letter settings invented here"


@then('the entry\'s message group is the group the wake queue gives wakes of "{agent}" about its schedule')
def message_group(context, agent):
    expected = agent_wakes.group_id({"agent": agent, "subject": "schedule"})
    assert entry_of(context, agent)["Target"]["SqsParameters"] == {"MessageGroupId": expected}


@then('the entry for "{agent}" says the local time and the zone, and no offset from UTC')
def local_time(context, agent):
    entry = entry_of(context, agent)
    assert entry["ScheduleExpression"] == "cron(0 6 * * ? *)" and entry["ScheduleExpressionTimezone"] == "America/New_York", entry
    assert "UTC" not in entry["ScheduleExpression"] and "+" not in entry["ScheduleExpression"]


@then('the entry would fire at 6 in the morning in New York, which is "{before}" the day before the clock change and "{after}" the day after')
def fires_at_six(context, before, after):
    """The scheduler's own job, shown with the same zone database: 6 in the morning in New York is 11:00 UTC in winter and 10:00 UTC after the clock change."""
    zone = ZoneInfo("America/New_York")
    for day, expected in ((datetime(2026, 3, 7, 6, tzinfo=zone), before), (datetime(2026, 3, 9, 6, tzinfo=zone), after)):
        assert day.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ") == expected


def fire(context, agent_time):
    (entry,) = [entry for name, entry in context.scheduler.entries.items() if name.startswith(schedules.ENTRY_PREFIX)]
    body = entry["Target"]["Input"].replace(schedules.SCHEDULED_TIME, agent_time)
    context.queue.send(body, entry["Target"]["SqsParameters"]["MessageGroupId"])


@when('the scheduler fires the entry for the time "{when}"')
@when('the scheduler fires the entry for the time "{when}" again')
def scheduler_fires(context, when):
    fire(context, when)


@then("the wake queue holds {count:d} scheduled message")
@then("the wake queue holds {count:d} scheduled messages")
def queue_holds(context, count):
    assert len(context.queue.messages) == count, [message.body for message in context.queue.messages]


@then('the message\'s wake key is "{key}"')
def wake_key_is(context, key):
    wake = json.loads(context.queue.messages[0].body)["wake"]
    assert wake["key"] == key and wake_keys.checked(key) == key, wake


@then("the message says in words why it started")
def says_why(context):
    wake = json.loads(context.queue.messages[0].body)["wake"]
    assert wake["why"].startswith("Scheduled run of rate-daily (0 6 * * * America/New_York)"), wake
    assert wake["agent"] == "rate-daily" and wake["subject"] == "schedule", wake


def run_one(context, message):
    event = {"Records": [{"eventSource": "aws:sqs", "messageId": "m", "body": message.body}]}
    request = {**agent_wakes.request_from_event(event), "appsyncEndpoint": ENDPOINT}
    context.result = pr.run_procedure_request(request, client=context.backend, policy=context.gate, execute=pr.execute_in_child, seconds_available=900, environment={})
    context.queue.delete(message)


@when("the runner runs the next scheduled message")
def runner_runs_next(context):
    run_one(context, context.queue.receive())


@when("the runner runs every scheduled message")
def runner_runs_all(context):
    while context.queue.messages:
        run_one(context, context.queue.receive())


@then("the site has {count:d} scheduled run record, made from the wake key")
@then("the site has {count:d} scheduled run records")
def run_records(context, count):
    assert len(context.backend.records) == count, context.backend.records
    for record in context.backend.records.values():
        assert record["id"] == "run-for-" + record["wakeKey"], record


@then("the scheduled procedure ran {count:d} time")
@then("the scheduled procedure ran {count:d} times")
def ran(context, count):
    assert len(context.executed) == count, context.executed


@given('the agent "{agent}" is adopted onto the responsibility "{responsibility}" and the site\'s policy pauses it with the reason "{reason}"')
def paused(context, agent, responsibility, reason):
    row = au.read_record(context.api.rows[agent])
    context.api.rows[agent] = au.stored_payload(au.build_record({"id": agent, "responsibility": responsibility}, existing=row, actor="person"))
    context.api.policy.set_rung("distinctive", ADMIN, responsibility, "observe", reason="the rating policy")
    context.api.policy.pause("distinctive", ADMIN, reason=reason, responsibility=responsibility)
    context.gate = PolicyGate(context.api, policy=context.api.policy, tenant_id="distinctive")


@then('the run record says nothing started, with the reason "{reason}"')
def nothing_started(context, reason):
    (record,) = context.backend.records.values()
    assert record["outcome"] == "nothing" and record["outcomeReason"] == reason and record["runStatus"] == "completed", record
    assert "paused" in record["resultSummary"], record


@then("the scheduled message is deleted from the queue")
def message_deleted(context):
    assert len(context.queue.deleted) == 1 and not context.queue.messages


@then('the schedule group has no entry named "{name}"')
def no_entry(context, name):
    assert name not in context.scheduler.entries


@then('the schedule group holds the one-shot entry "{one_shot}" and the entry for "{agent}"')
def holds_both(context, one_shot, agent):
    assert context.error is None, context.error
    assert sorted(context.scheduler.entries) == sorted([one_shot, schedules.entry_name(agent)]), sorted(context.scheduler.entries)


@then("the scheduler was asked to create, update or delete nothing")
def wrote_nothing(context):
    assert context.scheduler.writes == context.writes_before, (context.scheduler.writes, context.writes_before)


@then('the preview says "{agent}" would be created')
def preview_says(context, agent):
    assert context.error is None, context.error
    assert context.result["created"] == [schedules.entry_name(agent)], context.result


@then('the deploy step stops with a message that says "{agent}" needs a router publication')
def stops_unlinked(context, agent):
    assert isinstance(context.error, schedules.ScheduleError) and f"{agent} is switched on with a schedule but names no router publication" in str(context.error), context.error


@then('the deploy step stops with a message that says "{agent}" belongs to another site')
def stops_other_site(context, agent):
    assert isinstance(context.error, schedules.ScheduleError) and f"{agent} belongs to another site" in str(context.error), context.error


@then("the deploy step says there is no schedule group yet and no agent needs one")
def says_no_group(context):
    assert context.error is None, context.error
    assert context.result["groupDeployed"] is False and context.result["created"] == [], context.result
    out = tpr_stdout(context)
    assert "is not deployed yet, and no agent needs one" in out, out


def tpr_stdout(context):
    import io

    buffer = io.StringIO()
    code = agents_cli.schedules_command(["--site", context.site_id], buffer, client_factory=lambda: context.api,
                                        aws_factory=lambda: (context.sqs, context.scheduler), reader_factory=lambda: context.reader,
                                        site_store_factory=lambda client: context.api.site_store)
    assert code == 0, buffer.getvalue()
    return buffer.getvalue()


@then("the deploy step stops with a message that says the schedule group is not deployed yet")
def stops_no_group(context):
    assert isinstance(context.error, schedules.ScheduleError) and "is not deployed yet" in str(context.error), context.error


@then("the definition is refused with a message that says a day of the month and a day of the week cannot both be named")
def refused_definition(context):
    assert any("a day of the month and a day of the week cannot both be named" in problem.message for problem in context.problems), context.problems


@then('it becomes "{expression}"')
def becomes(context, expression):
    assert context.translated == expression
