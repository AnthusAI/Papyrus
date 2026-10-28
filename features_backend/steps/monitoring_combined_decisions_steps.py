from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content.monitoring_cloud import DynamoStore, run_collection  # noqa: E402
from papyrus_content.monitoring_router import RouterStore  # noqa: E402

ROUTE = ("MONITOR#hn", "ROUTE#101#000001")


def route_of(context):
    return context.table_.items[ROUTE]


def run(context, now=2000):
    context.result = tr.go(context.table_, context.store, context.cyclotron, now=now, deliver=context.delivery)


@given("a router for three publications with a combined Cyclotron endpoint")
def step_router(context):
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    context.table_.put_item(tr.router_config())
    context.store, context.cyclotron, context.delivery = RouterStore(context.table_), tr.FakeCyclotron(), tr.Delivery()
    context.cyclotron.combined_enabled = True


@given("the monitor has collected a story that every publication could use")
def step_collected(context):
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.ONE_FEED, now=1000)


@given("Cyclotron is busy with another run when the router first asks")
def step_busy(context):
    context.cyclotron.combined_post_override = (409, {"code": "run_busy"})


@given("Cyclotron does not have the combined endpoint yet")
def step_old(context):
    context.cyclotron.combined_enabled = False
    context.table_.put_item(tr.router_config())


@given("Cyclotron reports that a publication binding changed")
def step_changed(context):
    context.cyclotron.combined_post_override = (409, {"detail": "publication binding changed"})


@given("Cyclotron says one publication's criteria are pending inside the combined answer")
def step_pending(context):
    context.cyclotron.combined_entry_override["threat-intelligence"] = {"status": 409, "detail": "publication criteria are pending"}


@given("Cyclotron refuses the story's source for one publication inside the combined answer")
def step_refused(context):
    context.cyclotron.combined_entry_override["p-apyr-us"] = {"status": 409, "code": "source_refused"}


@when("the router sweeps the collected story")
def step_run(context):
    run(context)


@when("Cyclotron is free and the router sweeps again")
@when("the binding is current and the router sweeps again")
def step_run_again(context):
    context.first_ids = [c[2]["requestId"] for c in context.cyclotron.combined_calls if c[0] == "POST"]
    context.cyclotron.combined_post_override = None
    run(context, now=3000)


@then("Cyclotron receives exactly one decision request for the story")
def step_one(context):
    assert len([c for c in context.cyclotron.combined_calls if c[0] == "POST"]) == 1


@then("that request names the binding of all three publications")
def step_names(context):
    body = [c for c in context.cyclotron.combined_calls if c[0] == "POST"][0][2]
    assert set(body["payload"]["bindings"]) == set(tr.PUBS)


@then("no publication is decided with a request of its own")
def step_none_single(context):
    assert context.cyclotron.calls == []


@then("each publication's decision receipt has the same shape as a single-publication receipt")
def step_shape(context):
    for pub, job in route_of(context)["jobs"].items():
        assert set(job["checked"]) >= {"decisionId", "output", "label", "fingerprint", "version", "source"}, pub


@then("the publications that said include are delivered the Reference")
def step_delivered(context):
    assert sorted(c[0] for c in context.delivery.calls) == sorted(tr.PUBS)


@then("the router stops and defers the story")
def step_deferred(context):
    assert context.result["status"] == "stopped" and context.result["stoppedBy"] == "run_busy"


@then("the story is decided by a request with the same identity as the first attempt")
def step_same_id(context):
    posts = [c[2]["requestId"] for c in context.cyclotron.combined_calls if c[0] == "POST"]
    assert len(posts) == 2 and posts[0] == posts[1] == context.first_ids[0]
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed"


@then("the router asks the combined endpoint once and remembers the answer for the run")
def step_asked_once(context):
    assert len(context.cyclotron.combined_calls) == 1


@then("each publication is decided with its own request")
def step_each(context):
    assert sorted(c[1].split("/")[3] for c in context.cyclotron.posts()) == sorted(tr.PUBS)


@then("the story is delivered exactly as it would have been")
def step_same_delivery(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed"
    assert sorted({c[0] for c in context.delivery.calls}) == sorted(tr.PUBS)


@then("the router stops with the reason binding changed")
def step_binding(context):
    assert context.result["status"] == "stopped" and context.result["stoppedBy"] == "binding_changed"


@then("the story is still waiting for the router")
def step_waiting(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "collected"


@then("the story is decided and delivered")
def step_decided(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed" and context.delivery.calls


@then("that publication is waiting for a classifier")
def step_parked(context):
    assert context.result["waitingForClassifier"] == ["threat-intelligence"]


@then("the other two publications are decided and delivered")
def step_other_two(context):
    assert sorted(c[0] for c in context.delivery.calls) == ["anth-us", "p-apyr-us"]


@then("the story is refused")
def step_story_refused(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "refused"


@then("the answers of the other publications are kept on the story's receipt")
def step_kept(context):
    assert {p for p, j in route_of(context)["jobs"].items() if j.get("checked")} == {"anth-us", "threat-intelligence"}


def stale_job(context, **marker):
    """Leave the story holding a real combined job, then rewrite it as posted under another run."""
    cy = context.cyclotron
    tr.leave_job_pending(context.table_, context.store, cy)
    job = route_of(context)["combinedJob"]
    job.update(marker)
    context.old_job = job["jobId"]
    cy.pending_polls, cy.combined_calls = 0, []


@given("the story holds a combined job that was posted under an earlier Cyclotron run")
def step_stale(context):
    stale_job(context, runId="run-0", bindingRevision="0")


@given("the story holds a combined job under the current run that the lab answers with not found once")
def step_gone_once(context):
    stale_job(context, runId="run-1", bindingRevision="1")
    context.cyclotron.combined_poll_queue = [(404, {"detail": "Not Found"})]


@given("the lab answers not found for every job of the first two stories")
def step_gone_always(context):
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1100)   # two more stories behind the first
    context.cyclotron.combined_poll_queue = [(404, {"detail": "Not Found"}), (404, {"detail": "Not Found"})]


@given("the story holds a combined job that was posted under an old-format request id")
def step_old_format(context):
    stale_job(context)
    route_of(context)["combinedJob"]["requestId"] = "old-format-request-id-0"


@given("the story holds a pending combined job stored under an old-format request id")
def step_old_format_pending(context):
    step_old_format(context)
    context.cyclotron.pending_polls = 10_000


@given("the story holds a combined job that the lab reports as failed")
def step_failed_job(context):
    stale_job(context, runId="run-1", bindingRevision="1")
    context.cyclotron.combined_poll_queue = [(200, {"status": "failed"})]


@given("the story holds a combined job that the lab reports as reconciled")
def step_reconciled_job(context):
    stale_job(context, runId="run-1", bindingRevision="1")
    context.cyclotron.combined_poll_queue = [(409, {"code": "reconciliation_required"})]


@given("the story holds a combined job and the lab reports every job as reconciled")
def step_every_reconciled(context):
    stale_job(context, runId="run-1", bindingRevision="1")
    context.cyclotron.combined_poll_override = (409, {"code": "reconciliation_required"})


@given("the story holds a combined job and the lab answers polling with a conflict the router does not recognise")
def step_poll_other_conflict(context):
    stale_job(context, runId="run-1", bindingRevision="1")
    context.cyclotron.combined_poll_override = (409, {"code": "something_else"})


@when("the router sweeps the collected story again")
def step_sweep_again(context):
    run(context, now=2200)


@then("the earlier run's job is polled")
def step_polled(context):
    assert any(c[0] == "GET" and c[1].endswith(context.old_job) for c in context.cyclotron.combined_calls)


@then("the story is not posted again")
def step_not_posted(context):
    assert not [c for c in context.cyclotron.combined_calls if c[0] == "POST"]


@then("the story is posted again once")
def step_reposted(context):
    assert len([c for c in context.cyclotron.combined_calls if c[0] == "POST"]) == 1


@then("the first story is an error")
def step_first_error(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "error"


@then("the run is complete rather than stopped")
def step_complete(context):
    assert context.result["status"] == "complete" and not context.result.get("stoppedBy")


@given("Cyclotron answers the combined request with a conflict the router does not recognise")
def step_unknown_conflict(context):
    context.cyclotron.combined_post_override = (409, {"detail": "something unexpected"})


@then("the run does not stop")
def step_not_stopped(context):
    assert context.result["stoppedBy"] is None


@then("the story is not given up on and waits to be asked again later")
def step_backed_off(context):
    route = route_of(context)
    assert "final" not in route and tr.routing_of(context.table_)["DISC#101#000001"] == "collected"
    assert route["refusals"] == 1 and route["nextAttemptAt"] > 2000
    context.wait_until = int(route["nextAttemptAt"])


@when("the router sweeps again before the wait is over")
def step_early(context):
    context.posts_before = len([c for c in context.cyclotron.combined_calls if c[0] == "POST"])
    run(context, now=context.wait_until - 1)


@then("Cyclotron is not asked about the story again")
def step_not_asked(context):
    assert len([c for c in context.cyclotron.combined_calls if c[0] == "POST"]) == context.posts_before


@when("Cyclotron stops refusing and the router sweeps after the wait")
def step_after_wait(context):
    context.cyclotron.combined_post_override = None
    run(context, now=context.wait_until)


@given("the lab refuses the first story with a conflict the router does not recognise")
def step_first_refused(context):
    run_collection(DynamoStore(context.table_), "hn", fetch=lambda url: tr.FEED, now=1100, force=True)   # two more stories behind the first
    context.cyclotron.combined_post_queue = [(409, {"detail": "something unexpected"})]


@then("the other story is decided and delivered")
def step_other_story(context):
    states = tr.routing_of(context.table_)
    assert states["DISC#101#000001"] == "collected" and "routed" in states.values() and context.delivery.calls, (states, context.delivery.calls)


@then("the run receipt says what Cyclotron answered")
def step_receipt(context):
    assert any("http 409" in e["message"] and "something unexpected" in e["message"] for e in context.result["errors"])


def posted_ids(context):
    return [c[2]["requestId"] for c in context.cyclotron.combined_calls if c[0] == "POST"]


def build(context, publications):
    config = tr.validate_router_config(context.table_.items[("MONITOR#hn", "CONFIG#router")])
    disc = context.table_.items[("MONITOR#hn", "DISC#101#000001")]
    return tr.mr.build_combined_request(config, publications(config), disc)["body"]["requestId"]


@when("the router builds the decision request for the story")
def step_build(context):
    context.built_id = build(context, lambda config: config["publications"])


@then("building it again gives the same request identity")
def step_build_again(context):
    assert build(context, lambda config: config["publications"]) == context.built_id


@then("a request with a different set of publication bindings has a different request identity")
def step_build_other(context):
    assert build(context, lambda config: config["publications"][:2]) != context.built_id


@given("the router has a pending job for the story under the current publication set")
def step_pending_job(context):
    context.cyclotron.combined_poll_override = (202, {"status": "running"})
    run(context)
    context.old_job = route_of(context)["combinedJob"]["jobId"]
    context.first_ids = posted_ids(context)
    context.cyclotron.combined_calls.clear()
    context.cyclotron.combined_post_override = context.cyclotron.combined_poll_override = None


@when("the publication set changes and the router sweeps again")
def step_change_set(context):
    key = ("MONITOR#hn", "CONFIG#router")
    config = context.table_.items[key]
    context.table_.put_item({**config, "publications": config["publications"][:2]})
    run(context, now=3000)


@then("the stored job is polled and collected")
def step_polled_collected(context):
    assert any(c[0] == "GET" and c[1].endswith(context.old_job) for c in context.cyclotron.combined_calls)


@then("the story is decided and delivered without a conflict")
def step_no_conflict(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed"


@given("Cyclotron answers the first request with a request conflict")
def step_first_conflict(context):
    context.cyclotron.combined_post_queue = [(409, {"code": "request_conflict", "detail": "command identity has different content"})]


@then("the router posts the story a second time under a different request identity")
def step_second_post(context):
    ids = posted_ids(context)
    assert len(ids) == 2 and ids[0] != ids[1]


@given("Cyclotron answers every request with a request conflict")
def step_every_conflict(context):
    context.cyclotron.combined_post_override = (409, {"code": "request_conflict"})


@then("the router posts the story exactly twice")
def step_twice(context):
    assert len(posted_ids(context)) == 2


@then("every stored job of the story is marked as posted to the decisions route")
def step_via(context):
    assert {j["via"] for j in route_of(context)["jobs"].values()} == {"decisions"}


@then("no job of the story was polled on a per-publication route")
def step_no_commands(context):
    assert not [c for c in context.cyclotron.calls if c[0] == "GET"], context.cyclotron.calls


@given("a story whose combined job was stored without a recorded route")
def step_legacy(context):
    tr.leave_job_pending(context.table_, context.store, context.cyclotron)
    job = route_of(context)["combinedJob"]
    job.pop("via", None)
    context.old_job = job["jobId"]
    context.cyclotron.pending_polls, context.cyclotron.combined_calls = 0, []
