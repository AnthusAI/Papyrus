"""Daily monitor stories (features_backend/monitoring-daily-stories.feature). The model, the pages and the backends are fakes."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_monitoring_stories as tms  # noqa: E402
from test_monitor_stories import StoryModel, provenance  # noqa: E402
from ideas_fixtures import reference  # noqa: E402
from test_monitor_stories import MonitorClient, decision  # noqa: E402


def before_scenario_environment():
    os.environ["PAPYRUS_GRAPHQL_AUTH"] = "iam"   # the router Lambda's setting
    # The router files ideas through ItemStore; these scenarios read what was filed from the fake backend, so the sink is its recording double.
    from unittest import mock

    from fake_idea_store import FakeIdeaStore

    from procedures.newsroom.tests.test_idea_items import FakeGate

    mock.patch("papyrus_content.ideas.gate.HumanusGate.for_client", classmethod(lambda cls, client, **options: FakeGate())).start()
    mock.patch("papyrus_content.ideas.items.ItemStore", lambda client, **options: FakeIdeaStore(client, gate=options.get("gate"))).start()


def state(context):
    return context.daily


@given('a router with the publication "{publication}" and no monitorStories setting')
def step_router(context, publication):
    before_scenario_environment()
    table, store = tms.router((publication,))
    context.daily = SimpleNamespace(table=table, store=store, clients={}, publications=[publication], model=StoryModel(), left=lambda: 1e9,
                                    lines={}, slow=None)
    context.daily.clients[publication] = MonitorClient(references=[], incoming={}, relations={}, sections=("Analysis", "Tools"))


def add(client, count, status, monitor, verdicts=None):
    for _ in range(count):
        number = len(client.references) + 1
        row = reference(number, status=status, days_ago=number)
        client.references.append(row)
        provenance(row, monitor)
        verdict = (verdicts or {}).get(number, 0.5)
        client.relations[row["lineageId"]] = [decision(row, verdict)]


@given('the publication\'s monitorStories setting is {setting}')
def step_setting(context, setting):
    held = state(context)
    config = held.table.get_item({"pk": "MONITOR#hn", "sk": "CONFIG#router"})["Item"]
    config["publications"][0]["monitorStories"] = json.loads(setting)
    held.table.put_item(config)


@given('{count:d} accepted References that the "{monitor}" monitor delivered')
@given('{count:d} accepted Reference that the "{monitor}" monitor delivered')
def step_accepted(context, count, monitor):
    add(state(context).clients[state(context).publications[0]], count, "accepted", monitor)


@given('{count:d} pending References that the "{monitor}" monitor delivered')
def step_pending(context, count, monitor):
    add(state(context).clients[state(context).publications[0]], count, "pending", monitor)


@given('{count:d} accepted References that the "{monitor}" monitor delivered, which the Cyclotron judged relevant with {a:d}%, {b:d}%, {c:d}% and {d:d}% confidence')
def step_ranked(context, count, monitor, a, b, c, d):
    add(state(context).clients[state(context).publications[0]], count, "accepted", monitor, {1: a / 100, 2: b / 100, 3: c / 100, 4: d / 100})


@given('an enabled Automation that is triggered by the "{monitor}" monitor')
def step_automation(context, monitor):
    held = state(context)
    publication = held.publications[0]
    held.clients[publication].automations = [
        {"id": f"automation-{monitor}", "enabled": True, "procedureKey": f"{monitor}.story",
         "trigger": json.dumps({"kind": "monitor", "config": {"monitorId": monitor, "publicationId": publication}})}]


def first_reference(context, monitor):
    client = state(context).clients[state(context).publications[0]]
    return next(row for row in client.references if row["discoveredByMonitorId"] == monitor)


@given('the Automation has a procedure run in progress for the first "{monitor}" Reference')
def step_run_in_progress(context, monitor):
    row = first_reference(context, monitor)
    tms.trigger_row(state(context).table, row, "running", runId="run-1")


@given('the Automation has already written a story based on the first "{monitor}" Reference')
def step_story_based_on(context, monitor):
    row = first_reference(context, monitor)
    client = state(context).clients[state(context).publications[0]]
    client.incoming[row["lineageId"]] = [{"predicate": "uses_evidence", "relationState": "current", "subjectKind": "item", "objectKind": "reference",
                                              "objectLineageId": row["lineageId"], "metadata": json.dumps({"role": "based_on"})}]


@given('a second publication "{publication}" with {count:d} accepted References that the "{monitor}" monitor delivered')
def step_second(context, publication, count, monitor):
    held = state(context)
    table, store = tms.router((held.publications[0], publication))
    held.table, held.store = table, store
    held.publications.append(publication)
    client = MonitorClient(references=[], incoming={}, relations={}, sections=("Analysis", "Tools"))
    add(client, count, "accepted", monitor)
    held.clients[publication] = client


@given("the Lambda runs out of time after {count:d} drafts")
def step_time(context, count):
    held = state(context)
    held.left = lambda: 1e9 if len(held.model.requests) < count else 0


@given("every draft takes {seconds:d} seconds of a {total:d} second Lambda")
def step_slow(context, seconds, total):
    held = state(context)
    held.slow = tms.SlowModel(seconds, float(total))
    held.slow.model = held.model
    held.left = lambda: held.slow.left


@given("the backend refuses to file ideas")
def step_refuse(context):
    client = state(context).clients[state(context).publications[0]]
    original = client.graphql

    def graphql(query, variables=None):
        if "fileProposal" in query:
            raise RuntimeError("not authorized")
        return original(query, variables)

    client.graphql = graphql


def run(context, publication_id=None):
    held = state(context)
    held.locks = []
    original = held.store.acquire_router_lock
    held.store.acquire_router_lock = lambda *a, **k: (held.locks.append(k.get("sk", "LOCK#router")), original(*a, **k))[1]
    result, lines = tms.run_task(held.store, held.clients, held.slow or held.model, time_left=held.left, gate=getattr(held, "gate", None),
                                 publication_id=publication_id)
    held.result, held.lines = result, lines


@when('the router runs its daily monitor stories for the publication "{publication}"')
def step_run_one(context, publication):
    run(context, publication)


@then('{count:d} story drafts are filed for "{publication}" and none for "{other}"')
def step_filed_for(context, count, publication, other):
    assert len(filed(context, publication)) == count and not filed(context, other)


@then('the run took the lock of "{publication}", not the router lock, and released it')
def step_lock(context, publication):
    held = state(context)
    assert held.locks == [f"LOCK#monitor-stories#{publication}"], held.locks
    assert not [key for key in held.table.items if str(key[1]).startswith("LOCK#")]


@then('the result is an error that names "{publication}", nothing is drafted and nothing stays locked')
def step_unknown(context, publication):
    held = state(context)
    assert held.result["status"] == "error" and publication in held.result["reason"] and not held.locks
    assert not filed(context) and not [key for key in held.table.items if str(key[1]).startswith("LOCK#")]


@when("the router runs its daily monitor stories")
def step_run(context):
    run(context)


@when("the router runs its daily monitor stories again")
def step_again(context):
    run(context)


@when("the router runs its daily monitor stories again with time to spare")
def step_again_spare(context):
    state(context).left = lambda: 1e9
    run(context)


def filed(context, publication=None):
    held = state(context)
    return held.clients[publication or held.publications[0]].filed


@then("{count:d} story drafts are filed, one per Reference, each citing its source")
@then("{count:d} story draft is filed, one per Reference, each citing its source")
def step_filed(context, count):
    rows = filed(context)
    assert len(rows) == count, len(rows)
    assert len({row["title"] for row in rows}) == count, "a Reference was drafted twice"
    for row in rows:
        assert re.match(r"[\w-]+ monitor: https://", json.loads(row["evidence"])["source"]), row["evidence"]   # names the monitor that found it
        assert row["kind"] == "story_draft" and "[1]" in row["body"], row["body"]


@then("still only {count:d} story drafts are filed")
def step_still(context, count):
    assert len(filed(context)) == count


@then('1 story draft is filed, for the "{monitor}" Reference')
def step_one_for(context, monitor):
    (row,) = filed(context)
    assert json.loads(row["evidence"])["source"].startswith(f"{monitor} monitor:"), row["evidence"]


@then("no story draft is filed and the model is never asked")
def step_none(context):
    assert not filed(context) and not state(context).model.requests


@then("the drafts filed are for References {first:d} and {second:d}")
def step_which(context, first, second):
    numbers = sorted(int(json.loads(row["evidence"])["source"].split("example")[1].split(".")[0]) for row in filed(context))
    assert numbers == [first, second], numbers


@then("the model was asked exactly once")
def step_once(context):
    assert len(state(context).model.requests) == 1, len(state(context).model.requests)


def check(context, publication, expected):
    line = state(context).lines[publication]
    for key, value in expected.items():
        assert line[key] == value, (key, line)


@then('the log line for "{publication}" says drafted {drafted:d}, candidates {candidates:d}, notAccepted {not_accepted:d}, skipped {skipped:d} and stoppedBy none')
def step_line_none(context, publication, drafted, candidates, not_accepted, skipped):
    check(context, publication, {"drafted": drafted, "candidates": candidates, "notAccepted": not_accepted, "skipped": skipped, "stoppedBy": None})


@then('the log line for "{publication}" says drafted {drafted:d}, candidates {candidates:d}, notAccepted {not_accepted:d}, skipped {skipped:d}, stoppedBy none and handledByAutomation {handled:d}')
def step_line_handled(context, publication, drafted, candidates, not_accepted, skipped, handled):
    check(context, publication, {"drafted": drafted, "candidates": candidates, "notAccepted": not_accepted, "skipped": skipped, "stoppedBy": None, "handledByAutomation": handled})


@then('the log line for "{publication}" says drafted {drafted:d}, candidates {candidates:d}, notAccepted {not_accepted:d}, skipped {skipped:d} and stoppedBy "{stopped}"')
def step_line_stopped(context, publication, drafted, candidates, not_accepted, skipped, stopped):
    check(context, publication, {"drafted": drafted, "candidates": candidates, "notAccepted": not_accepted, "skipped": skipped, "stoppedBy": stopped})


@then('the log line for "{publication}" says status "{status}" and drafted {drafted:d}')
def step_line_status(context, publication, status, drafted):
    check(context, publication, {"status": status, "drafted": drafted})


@then('the log line for "{publication}" says drafted {drafted:d} and stoppedBy "{stopped}"')
def step_line_drafted_stopped(context, publication, drafted, stopped):
    check(context, publication, {"drafted": drafted, "stoppedBy": stopped})


@then('the log line for "{publication}" says drafted {drafted:d} and stoppedBy none')
def step_line_drafted_none(context, publication, drafted):
    check(context, publication, {"drafted": drafted, "stoppedBy": None})


@then('the log line for "{publication}" says stoppedBy "{stopped}"')
def step_line_stopped_only(context, publication, stopped):
    check(context, publication, {"stoppedBy": stopped})


def _gate(context, gate):
    state(context).gate = gate


@given('the router\'s editorial check finds an error violation of "{policy}" and a warning')
def step_gate_error(context, policy):
    from procedures.newsroom.tests import test_idea_items as support

    _gate(context, support.FakeGate([support.finding("error", policy=policy), support.finding("warn")]))


@given("the router's editorial check finds only a warning")
def step_gate_warning(context):
    from procedures.newsroom.tests import test_idea_items as support

    _gate(context, support.FakeGate([support.finding("warn")]))


@given("the router has no TypeSafe key")
def step_no_key(context):
    from papyrus_content.monitoring_stories import lambda_judgment_key
    from procedures.newsroom.tests import test_idea_items as support

    assert lambda_judgment_key({}) is None   # no parameter configured: the lane is recorded as not run, never an error
    _gate(context, support.FakeGate(classifier={"status": "unavailable", "reason": "no decision model is configured (set TYPESAFE_API_KEY)"}))


@then('the log line for "{publication}" says {count:d} ideas were refused by the editorial check and drafted {drafted:d}')
def step_refused(context, publication, count, drafted):
    line = state(context).lines[publication]
    assert (line["refusedByEditorialCheck"], line["drafted"]) == (count, drafted), line


@then("the editorial check ran on both and its result was stored with each idea")
def step_check_stored(context):
    held = state(context)
    assert len(held.gate.seen) == 2 and len(held.gate.recorded) == 2, (held.gate.seen, held.gate.recorded)


@then("the stored check says the rules lane ran and the judgment lane did not run, and why")
def step_lanes(context):
    [(_, result)] = state(context).gate.recorded
    assert result["lanes"]["rules"]["status"] == "ran" and result["lanes"]["classifier"]["status"] == "unavailable"
    assert "TYPESAFE_API_KEY" in result["lanes"]["classifier"]["reason"]


@then("no story draft is filed")
def step_none_filed(context):
    assert not filed(context), filed(context)


@when("the router runs its daily monitor stories without naming a publication")
def step_fan_out(context):
    from papyrus_content.monitoring_router import run_router

    held = state(context)
    held.started = []
    held.result = run_router(held.store, "hn", now=tms.NOW.timestamp(), task="monitor-stories", fan_out=held.started.append, story_transport=held.model)


@then('it starts one run for "{first}" and one for "{second}", takes no lock and files no story draft')
def step_fanned(context, first, second):
    held = state(context)
    assert held.result["status"] == "fanned-out" and held.started == [first, second]
    assert not filed(context, first) and not filed(context, second)
    assert not [key for key in held.table.items if str(key[1]).startswith("LOCK#")]
