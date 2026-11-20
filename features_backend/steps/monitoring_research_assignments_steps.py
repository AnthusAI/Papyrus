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

    def watching(client, options, **kwargs):
        row = current.backend.rows[options["assignment"]]
        seen.append((options["assignment"], row["status"], row.get("assigneeKey"), row.get("claimExpiresAt")))
        return inner(client, options, **kwargs)

    current.seen = seen
    current.result = worker.run(current.backend, watching, out_of_time=current.limit or (lambda: False), time_left=getattr(current, "time_left", None))


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


@then("while its research ran, assignment 1 was claimed by the research worker with a lease that ends 16 minutes later")
def step_lease(context):
    assert state(context).seen == [("assignment-1", "claimed", worker.WORKER_LABEL, "2026-11-03T12:16:00.000Z")], state(context).seen


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


@then("the pass reports that it stopped by time with {count:d} left open")
def step_report(context, count):
    result = state(context).result
    assert result["stoppedBy"] == "time" and result["leftOpen"] == count


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


@given("a backend {tenancy} that answers like a small real one")
def step_tenancy(context, tenancy):
    state(context).tenant_id = None if tenancy == "with no tenant" else tenancy.split('"')[1]


@when("one assignment is run on the real client with its transport replaced, taking in a cited source, linking it to the Story and curating it")
def step_record(context):
    from _pytest.monkeypatch import MonkeyPatch

    patches = MonkeyPatch()
    patches.setenv("PAPYRUS_GRAPHQL_AUTH", "iam")
    try:
        state(context).asked = worker.recorded_fields_of_a_full_run(patches, getattr(state(context), "tenant_id", None))
    finally:
        patches.undo()


@then("every field it asked for is granted to the research worker's role on any publication API")
def step_granted(context):
    asked, granted = state(context).asked, worker.worker_grants()
    assert asked <= granted, sorted(asked - granted)


@then("the grant has no publish field and no updateItem or deleteItem: it may only create Items, such as a checklist step")
def step_no_story_writes(context):
    granted = worker.worker_grants()
    forbidden = {name for kind, name in granted if kind == "Mutation" and (name.startswith(("publish", "unpublish")) or name in ("updateItem", "deleteItem"))}
    assert not forbidden, sorted(forbidden)


@then("the router role has gained no policy")
def step_no_policy(context):
    resources = worker.tr._template()["Resources"]
    attached = [name for name, resource in resources.items() if resource["Type"] == "AWS::IAM::ManagedPolicy" and ("Ref", "RouterRole") in (resource["Properties"].get("Roles") or [])]
    assert len(attached) <= 20, len(attached)


@given("only {seconds:d} of the worker's 900 seconds are left")
def step_time_left(context, seconds):
    state(context).time_left = lambda: seconds


@then("no research ran and assignment 1 is still open")
def step_still_open(context):
    assert state(context).research.asked == [] and state(context).backend.rows["assignment-1"]["status"] == "open"


@given("a fact check whose time runs short after its first judge answer")
def step_short_judge(context):
    state(context).short = [False]


@when("the claims are checked")
def step_check(context):
    from papyrus_content.fact_check import check_claims
    from papyrus_content.multi_search_research import stop_judging_when_short_of_time

    current = state(context)

    def judge(claim, cited, info):
        current.short[0] = True
        return {"verdict": "supported", "quotes": [], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}

    claims = [{"claim": "Alpha beta gamma.", "sources": ["1"]}, {"claim": "Delta epsilon.", "sources": ["1"]}]
    current.report = check_claims(claims, {"1": "Alpha beta gamma. Delta epsilon."}, judge=stop_judging_when_short_of_time(judge, lambda: current.short[0]), urls={"1": "https://a.example/x"})


@then("the claims not yet judged are unchecked with the reason that the run ran short of time")
def step_unchecked(context):
    rows = [claim for claim in state(context).report["claims"] if claim["verdict"] == "unchecked"]
    assert rows and all("ran short of time" in claim["reasons"][0] for claim in rows)


@then("the packet is still made")
def step_packet(context):
    assert state(context).report["counts"]["total"] == 2


@given("assignment 1 already produces a research packet message")
def step_produces(context):
    current = state(context)
    current.backend.relations["assignment#assignment-1#current"] = [worker.produces_relation(1)]


@given("assignment 1 has a research.multi.completed event from a terminal run")
def step_event(context):
    state(context).backend.history["assignment-1"] = [{"eventType": "research.multi.completed"}]


@then("assignment 1 is completed with a completion time and a note that its packet already exists")
def step_already(context):
    backend = state(context).backend
    assert backend.rows["assignment-1"]["status"] == "completed" and "completedAt" in backend.rows["assignment-1"]
    assert "packet already exists" in next(event["note"] for event in backend.events if event["assignmentId"] == "assignment-1")


@then("the research ran only for assignment 2")
def step_only_two(context):
    assert [asked["assignment"] for asked in state(context).research.asked] == ["assignment-2"]


@then("assignment 1 is completed and no research ran")
def step_one_done_none_ran(context):
    assert state(context).backend.rows["assignment-1"]["status"] == "completed" and state(context).research.asked == []


@given("an open research.multi assignment")
def step_terminal_assignment(context):
    import test_multi_search_research as multi

    state(context).multi = multi
    state(context).terminal_client = multi.FakeClient(multi.assignment())


def run_terminal(context, providers):
    from unittest import mock

    from papyrus_content import multi_search_research as module

    multi, client = state(context).multi, state(context).terminal_client
    with mock.patch.object(module, "apply_research_packet", return_value={"messageId": "m1"}), \
         mock.patch.object(module, "intake_research_packet_proposals", return_value={"registeredReferenceCount": 1}), \
         mock.patch.object(module, "build_record_changes", side_effect=lambda c, records: records), \
         mock.patch.object(module, "apply_record_changes"), \
         mock.patch.object(module, "update_newsroom_summary_after_research_packet_creates"):
        state(context).terminal_result = module.research_multi(client, {"assignment": "assignment-1", "actor-label": "Papyrus content CLI"}, llm=multi.FakeLlm(), providers=providers)


@when("the research run is applied from the command line and finishes")
def step_terminal_finishes(context):
    run_terminal(context, state(context).multi.two_providers())


@when("the research run is applied from the command line and no search provider answers")
def step_terminal_fails(context):
    multi = state(context).multi
    run_terminal(context, {name: multi.FakeProvider(name, default=multi.ProviderFailure(name, "auth", 401)) for name in ("gemini", "openai")})


@then("the assignment is completed with a completion time and a research.completed event by the command line's actor")
def step_terminal_completed(context):
    client = state(context).terminal_client
    assert [row["status"] for row in client.updates] == ["completed"] and "completedAt" in client.updates[0]
    assert [(event["eventType"], event["actorLabel"]) for event in client.events] == [("research.completed", "Papyrus content CLI")]


@then("the same status change is not made twice when the worker started the run")
def step_not_twice(context):
    from unittest import mock

    from papyrus_content import multi_search_research as module

    multi = state(context).multi
    client = multi.FakeClient(multi.assignment())
    with mock.patch.object(module, "apply_research_packet", return_value={"messageId": "m1"}), \
         mock.patch.object(module, "intake_research_packet_proposals", return_value={"registeredReferenceCount": 1}), \
         mock.patch.object(module, "build_record_changes", side_effect=lambda c, records: records), \
         mock.patch.object(module, "apply_record_changes"), \
         mock.patch.object(module, "update_newsroom_summary_after_research_packet_creates"):
        module.research_multi(client, {"assignment": "assignment-1", "leave-status": True}, llm=multi.FakeLlm(), providers=multi.two_providers())
    assert client.updates == [] and client.events == []


@then("the assignment is failed with a research.failed event giving the plain reason")
def step_terminal_failed(context):
    client = state(context).terminal_client
    assert [row["status"] for row in client.updates] == ["failed"]
    assert client.events[0]["eventType"] == "research.failed" and "no search provider answered" in client.events[0]["note"]


@then("the research worker will not start it again")
def step_worker_skips_failed(context):
    backend = worker.Backend([{**worker.assignment(1), "status": "failed"}])
    research = worker.Research()
    worker.run(backend, research)
    assert research.asked == []


@given("a research run that fails with a permission denied reason followed by a line telling the reader to sign in again at a terminal")
def step_guidance(context):
    current = state(context)
    current.backend = worker.Backend([worker.assignment(1)])

    def research(client, options, **_):
        return {"action": "failed", "error": "GraphQL request failed: 401 Unauthorized: Permission denied\nYour AWS session may have expired or lack access. Run `aws sso login --profile <profile>` and retry."}

    current.research = research


@then("the failed event note holds the permission denied reason")
def step_note_reason(context):
    note = next(event["note"] for event in state(context).backend.events if event["eventType"] == "research.failed")
    assert note == "GraphQL request failed: 401 Unauthorized: Permission denied", note


@then("the note has no sign-in advice")
def step_note_clean(context):
    note = next(event["note"] for event in state(context).backend.events if event["eventType"] == "research.failed")
    assert "sso login" not in note and "papyrus login" not in note
