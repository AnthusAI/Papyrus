"""The router's hourly suggest-backlog task (features_backend/monitoring-suggest-backlog.feature). The index, the backends and the clock are fakes."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from functools import partial
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_router as tr  # noqa: E402
import test_monitoring_stories as tms  # noqa: E402
import test_monitoring_vectors as tv  # noqa: E402
from ideas_fixtures import NOW  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content import monitoring_vectors as vectors  # noqa: E402

INDEXED = {**tms.SINGLE_ITEM_ONLY, "vectorIndexArn": tv.ARN, "storageBucketName": tv.BUCKET}
PUBLICATION = tms.PUBLICATION


def state(context):
    return context.backlog


def fresh(context, settings, publications=(PUBLICATION,)):
    from _pytest.monkeypatch import MonkeyPatch

    patches = MonkeyPatch()
    patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    patches.setattr(vectors, "s3vectors_client_missing_reason", lambda region_name=None: None)
    context.add_cleanup(patches.undo)
    table, store = tms.router(publications, settings)
    context.backlog = SimpleNamespace(table=table, store=store, patches=patches, rows=[], pass_=tv.Pass(), left=[600], per_suggestion=0, result=None, lines=[], started=[],
                                      earlier=[], publication=PUBLICATION)


@given("a router with five publications, two of which have a vector index and suggestions on")
def step_five(context):
    names = ("a-site", "no-index", "no-suggestions", "disabled", "b-site")
    fresh(context, {"a-site": INDEXED, "no-index": tms.SINGLE_ITEM_ONLY, "no-suggestions": {**INDEXED, "suggestions": {"enabled": False}},
                    "disabled": {**INDEXED, "enabled": False}, "b-site": INDEXED}, names)


@given("a suggest-backlog publication with an index and a storage bucket")
def step_indexed(context):
    fresh(context, {PUBLICATION: INDEXED})


@given("a suggest-backlog publication with no index")
def step_unindexed(context):
    fresh(context, {PUBLICATION: tms.SINGLE_ITEM_ONLY})


@given("{count:d} accepted References, one of which has no summary vector yet")
def step_three(context, count):
    state(context).rows = [tv.accepted(number, f"2026-10-30T{9 + number}:00:00Z") for number in range(1, count + 1)]
    state(context).pass_ = tv.Pass(no_vector={"ref-2"})


@given("{count:d} accepted References")
def step_n_references(context, count):
    state(context).rows = [tv.accepted(number, f"2026-10-{number:02d}T10:00:00Z") for number in range(1, count + 1)]


@given("each suggestion takes {seconds:d} of the run's 600 seconds")
def step_slow(context, seconds):
    state(context).per_suggestion = seconds

    class Slow(tv.Pass):
        def suggester(self, client, provider, reference_id, **options):
            state(context).left[0] -= seconds
            return super().suggester(client, provider, reference_id, **options)

    state(context).pass_ = Slow()


@given("the suggest-backlog run of that publication is in progress")
def step_in_progress(context):
    assert state(context).store.acquire_router_lock("hn", "other", now=NOW.timestamp(), sk=f"LOCK#suggest-backlog#{PUBLICATION}")


def run(context, *, publication_id=PUBLICATION, fan_out=None, pass_=None):
    current = state(context)
    pass_ = pass_ or current.pass_
    current.patches.setattr(mr, "run_suggest_backlog", partial(vectors.run_suggest_backlog, suggester=pass_.suggester, provider_for=lambda arn: ("provider", arn),
                                                              calibration_loader=lambda client: None, workers=1))
    out = io.StringIO()
    with redirect_stdout(out):
        current.result = mr.run_router(current.store, "hn", now=NOW.timestamp(), task="suggest-backlog", appsync=lambda endpoint: tv.AcceptedClient(current.rows),
                                       deliver=tr.Delivery(), time_left=lambda: current.left[0], publication_id=publication_id, fan_out=fan_out)
    current.lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith('{"suggestBacklog"')]


@when("the router runs the suggest-backlog task without naming a publication")
def step_fan_out(context):
    run(context, publication_id=None, fan_out=state(context).started.append)


@when("the router runs the suggest-backlog task for that publication")
def step_run(context):
    state(context).left[0] = 600
    run(context)


@when("an hour later the router runs the suggest-backlog task for that publication")
def step_run_later(context):
    current = state(context)
    current.earlier = list(current.pass_.order)
    current.left[0] = 600
    current.pass_ = tv.Pass()
    run(context)


@when("the router runs the suggest-backlog task for a publication the monitor does not list")
def step_unknown(context):
    run(context, publication_id="nowhere")


@then("it started one run for each of those two publications")
def step_started(context):
    assert state(context).started == ["a-site", "b-site"] and state(context).result["status"] == "fanned-out", state(context).started


@then("the fan-out took no lock and wrote no receipt")
def step_no_lock(context):
    assert not [key for key in state(context).table.items if key[1].startswith(("LOCK#", "ROUTERUN#"))]


@then("suggestions were made for the 3 References, the newest first")
def step_order(context):
    assert state(context).pass_.order == ["suggest:ref-3", "suggest:ref-2", "suggest:ref-1"], state(context).pass_.order


@then("the index was not synced and nothing was embedded")
def step_no_sync(context):
    assert state(context).pass_.sync_calls == [], state(context).pass_.sync_calls


@then("the log line says {written:d} suggestions written, {left:d} suggestion left and {waiting:d} awaiting the index")
def step_line(context, written, left, waiting):
    (line,) = state(context).lines
    assert (line["suggestionsWritten"], line["suggestionsRemaining"], line["awaitingIndex"]) == (written, left, waiting), line


@then("the log line says the cost was 0 and gives the seconds of each step")
def step_line_cost(context):
    (line,) = state(context).lines
    assert line["costUsd"] == 0 and {"planSeconds", "suggestSeconds"} <= set(line["timings"]) and "suggestionsPerSecond" in line, line


@then("the router's table holds the saved place and the Reference that is owed to the index")
def step_table(context):
    table = state(context).table
    place = json.loads(table.get_item({"pk": "MONITOR#hn", "sk": vectors.watermark_sort_key(PUBLICATION)})["Item"]["watermark"])
    assert place["accepted"]["high"].endswith("#ref-3") and place["accepted"]["low"].endswith("#ref-1"), place
    owed = [json.loads(item["entries"]) for key, item in table.items.items() if key[1].startswith(vectors.owed_prefix(PUBLICATION))]
    assert len(owed) == 1 and owed[0]["lineage-2"]["r"] is None, owed


@then("the run was stopped by time with {count:d} suggestion left")
def step_stopped(context, count):
    (line,) = state(context).lines
    assert line["status"] == "stopped" and line["stoppedBy"] == "time" and line["suggestionsRemaining"] == count, line


@then("the log line says no suggestions are left")
def step_none_left(context):
    assert state(context).lines[-1]["suggestionsRemaining"] == 0, state(context).lines


@then("every Reference was suggested for once")
def step_once(context):
    current = state(context)
    both = current.earlier + current.pass_.order
    assert sorted(both) == sorted(f"suggest:ref-{number}" for number in range(1, 6)), both


@then("the suggest-backlog run reports that it is locked")
def step_locked(context):
    assert state(context).result["status"] == "locked" and state(context).pass_.order == [] and state(context).lines == []


@then("the routing pass lock is free")
def step_routing_free(context):
    assert state(context).store.acquire_router_lock("hn", "route", now=NOW.timestamp())


@then("the monitor-stories lock of that publication is free")
def step_stories_free(context):
    assert state(context).store.acquire_router_lock("hn", "stories", now=NOW.timestamp(), sk=f"LOCK#monitor-stories#{PUBLICATION}")


@then("the suggest-backlog run is refused as an unknown publication and does nothing")
def step_refused(context):
    result = state(context).result
    assert result["status"] == "error" and "nowhere" in result["reason"] and state(context).pass_.order == []


@then("nothing was suggested and the log line says the publication was skipped")
def step_skipped(context):
    current = state(context)
    assert current.pass_.order == [] and current.lines[0]["status"] == "skipped", current.lines


@given("the monitoring stack template")
def step_template(context):
    context.resources = tr._template()["Resources"]


NAMES = ("SuggestBacklogSchedule", "DistinctiveSuggestBacklogSchedule")


@then("the stack has an hourly suggest-backlog schedule for the hn monitor and one for the web-distinctive monitor")
def step_schedules(context):
    inputs = {name: json.loads(context.resources[name]["Properties"]["Target"]["Input"]) for name in NAMES}
    assert inputs == {"SuggestBacklogSchedule": {"task": "suggest-backlog", "monitorId": "hn"}, "DistinctiveSuggestBacklogSchedule": {"task": "suggest-backlog", "monitorId": "web-distinctive"}}
    assert all(context.resources[name]["Properties"]["ScheduleExpression"].endswith("* * * ? *)") for name in NAMES)


@then("neither suggest-backlog schedule retries a failed run")
def step_no_retry(context):
    for name in NAMES:
        assert context.resources[name]["Properties"]["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0


@then("the schedules do not start in the ten minutes after the daily monitor-stories run")
def step_offset(context):
    minutes = {int(context.resources[name]["Properties"]["ScheduleExpression"].split("(")[1].split()[0]) for name in NAMES}
    assert not any(30 <= minute <= 40 for minute in minutes), minutes   # the daily runs start at 07:30 and may take the Lambda's ten minutes


@then("the router role needs no new permission for the task")
def step_iam(context):
    policies = context.resources["RouterRole"]["Properties"]["Policies"]
    actions = {action for policy in policies for statement in policy["PolicyDocument"]["Statement"] for action in
               ([statement["Action"]] if isinstance(statement["Action"], str) else statement["Action"])}
    assert {"dynamodb:Query", "dynamodb:PutItem", "dynamodb:GetItem"} <= actions   # the owed rows and the saved place are rows of the monitoring table the role already reads and writes
    assert context.resources["RouterScheduleRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]["Resource"] == ("GetAtt", "RouterFunction.Arn")
