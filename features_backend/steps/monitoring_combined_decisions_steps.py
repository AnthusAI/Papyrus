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


@then("the earlier run's job is never polled")
def step_not_polled(context):
    assert not any(c[0] == "GET" and c[1].endswith(context.old_job) for c in context.cyclotron.combined_calls)


@then("the story is decided and delivered under a new request")
def step_new_request(context):
    ids = [c[2]["requestId"] for c in context.cyclotron.combined_calls if c[0] == "POST"]
    assert ids and len(ids) == 1
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed" and context.delivery.calls


@then("the story is posted again once")
def step_reposted(context):
    assert len([c for c in context.cyclotron.combined_calls if c[0] == "POST"]) == 1


@then("the first story is an error")
def step_first_error(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "error"


@then("the run is complete rather than stopped")
def step_complete(context):
    assert context.result["status"] == "complete" and not context.result.get("stoppedBy")
