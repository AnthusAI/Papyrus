"""The router's research-assignments task (features_backend/monitoring-research-assignments.feature). Fakes for the backend, the clock and the research."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_research_assignments_worker as worker  # noqa: E402


def state(context):
    if not hasattr(context, "research"):
        context.research = SimpleNamespace(backend=None, research=worker.Research(), limit=None, result=None, router=None)
    return context.research


def numbers(text):
    return [int(part) for part in text.replace(" and ", ",").split(",") if part.strip()]


@given("a backend with the open research assignments {text} on a Story")
def step_open(context, text):
    state(context).backend = worker.Backend([worker.assignment(number) for number in numbers(text)])


@given("a backend whose only assignment is {kind}")
def step_only(context, kind):
    rows = {"open and has no Story": worker.assignment(1, story=None), "open and has the researcher profile": worker.assignment(1, profile="researcher"),
            "already completed": worker.assignment(1, status="completed"), "a research.candidate assignment": worker.assignment(1, type_key="research.candidate")}
    state(context).backend = worker.Backend([rows[kind]])


@given('the research for assignment {number:d} reports "{reason}"')
def step_reports(context, number, reason):
    state(context).research.fail.add(f"assignment-{number}")


@given("the research for assignment {number:d} raises an error")
def step_raises(context, number):
    state(context).research.raises.add(f"assignment-{number}")


@given("the time runs short after the first assignment")
def step_short(context):
    calls = iter([False, True])
    state(context).limit = lambda: next(calls, True)


@given("a backend with assignment 1 claimed with a lease that ended a minute ago")
def step_stale(context):
    state(context).backend = worker.Backend([worker.assignment(1, status="claimed", expires=(worker.NOW - timedelta(minutes=1)).isoformat())])


@given("assignment 2 claimed with a lease that ends in five minutes")
def step_live(context):
    state(context).backend.rows["assignment-2"] = worker.assignment(2, status="claimed", expires=(worker.NOW + timedelta(minutes=5)).isoformat())


@when("the research-assignments pass runs")
def step_run(context):
    current = state(context)
    seen = []
    inner = current.research

    def watching(client, options):
        row = current.backend.rows[options["assignment"]]
        seen.append((options["assignment"], row["status"], row.get("assigneeKey"), row.get("claimExpiresAt")))
        return inner(client, options)

    current.seen = seen
    current.result = worker.run(current.backend, watching, out_of_time=current.limit or (lambda: False))


@then("the research ran for assignments {text} in that order")
def step_order(context, text):
    assert [asked["assignment"] for asked in state(context).research.asked] == [f"assignment-{n}" for n in numbers(text)]


@then("both assignments are completed")
def step_both(context):
    assert {row["status"] for row in state(context).backend.rows.values()} == {"completed"}


@then("assignment 1 has a claim event and a finished event")
def step_events(context):
    kinds = [event["eventType"] for event in state(context).backend.events if event["assignmentId"] == "assignment-1"]
    assert kinds == ["claim", "research.completed"], kinds


@then("while its research ran, assignment 1 was claimed by the research worker with a lease that ends 11 minutes later")
def step_lease(context):
    assert state(context).seen == [("assignment-1", "claimed", worker.WORKER_LABEL, "2026-11-03T12:11:00.000Z")], state(context).seen


@then("no research ran and no event was written")
def step_nothing(context):
    assert state(context).research.asked == [] and state(context).backend.events == []


@then("assignments 1 and 2 are failed with their reasons in a failed event")
def step_failed(context):
    backend = state(context).backend
    assert [backend.rows[f"assignment-{n}"]["status"] for n in (1, 2)] == ["failed", "failed"]
    notes = {event["assignmentId"]: event["note"] for event in backend.events if event["eventType"] == "research.failed"}
    assert notes == {"assignment-1": "no search provider answered", "assignment-2": "RuntimeError: search is down"}, notes


@then("assignment {number:d} is completed")
def step_completed(context, number):
    assert state(context).backend.rows[f"assignment-{number}"]["status"] == "completed"


@then("assignment 1 is completed and assignments 2 and 3 are still open")
def step_stopped(context):
    assert [row["status"] for row in state(context).backend.rows.values()] == ["completed", "open", "open"]


@then("the pass reports that it stopped by time with 2 left open")
def step_report(context):
    result = state(context).result
    assert result["stoppedBy"] == "time" and result["leftOpen"] == 2


@then("assignment 1 is failed with the reason that its time ran out")
def step_expired(context):
    backend = state(context).backend
    assert backend.rows["assignment-1"]["status"] == "failed" and "time ran out" in backend.events[0]["note"]


@then("assignment 2 is still claimed")
def step_claimed(context):
    assert state(context).backend.rows["assignment-2"]["status"] == "claimed"


@then("no research ran")
def step_no_research(context):
    assert state(context).research.asked == []


def make_router(context, enabled, off=()):
    from _pytest.monkeypatch import MonkeyPatch

    patches = MonkeyPatch()
    patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    context.add_cleanup(patches.undo)
    settings = {name: {"enabled": True} for name in enabled} | {name: None for name in off}
    state(context).table, state(context).router = worker.router_with(settings)


@given('a router whose publications "{first}" and "{second}" turned research assignments on and "{off}" did not')
def step_router_three(context, first, second, off):
    make_router(context, (first, second), (off,))


@given('a router whose publications "{name}" turned research assignments on')
def step_router_one(context, name):
    make_router(context, (name,))
    state(context).backend = worker.Backend([worker.assignment(1)])


@when("the research-assignments task runs without naming a publication")
def step_fan_out(context):
    current = state(context)
    current.started = []
    current.result = worker.run_task(current.router[1] if isinstance(current.router, tuple) else current.router, {}, fan_out=current.started.append)


@when('the research-assignments task runs for "{name}"')
def step_for_one(context, name):
    current = state(context)
    current.result = worker.run_task(current.router, {name: current.backend}, publication_id=name, research=current.research)


@then('it started one run for "{first}" and "{second}"')
def step_started(context, first, second):
    assert state(context).started == [first, second]


@then("the research fan-out took no lock and wrote no receipt")
def step_no_lock(context):
    assert not [key for key in state(context).table.items if key[1].startswith(("LOCK#", "ROUTERUN#"))]


@then("its open assignment is completed")
def step_its_completed(context):
    assert state(context).backend.rows["assignment-1"]["status"] == "completed"


@then("the routing pass lock is free after the research run")
def step_routing_free(context):
    assert state(context).router.acquire_router_lock("hn", "route", now=worker.ROUTER_NOW.timestamp())


@then('the research-assignments lock of "{name}" is free again')
def step_lock_free(context, name):
    assert state(context).router.acquire_router_lock("hn", "again", now=worker.ROUTER_NOW.timestamp(), sk=f"LOCK#research-assignments#{name}")


@given("the monitoring template")
def step_template(context):
    state(context).template = True


@when("one assignment is run on the real client with its transport replaced")
def step_record(context):
    from _pytest.monkeypatch import MonkeyPatch

    patches = MonkeyPatch()
    patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    try:
        state(context).asked = worker.recorded_fields_of_a_full_run(patches)
    finally:
        patches.undo()


@then("every field it asked for is granted to the research worker's role on any publication API")
def step_granted(context):
    asked, granted = state(context).asked, worker.worker_grants()
    assert asked <= granted, sorted(asked - granted)


@then("the router role has gained no policy")
def step_no_policy(context):
    resources = worker.tr._template()["Resources"]
    attached = [name for name, resource in resources.items() if resource["Type"] == "AWS::IAM::ManagedPolicy" and ("Ref", "RouterRole") in (resource["Properties"].get("Roles") or [])]
    assert len(attached) <= 20, len(attached)
