from pathlib import Path
import sys

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"))
import test_monitoring_router as tr  # noqa: E402
from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content.monitoring_router import RouterStore  # noqa: E402

DECISION_CONTRACT = "cyclotron-decision/v1"


@given("a router for one publication with a combined Cyclotron endpoint")
def step_one_publication(context):
    config = tr.router_config()
    config["publications"] = config["publications"][:1]
    context.table_ = tr.FakeTable()
    context.table_.put_item(tr.COLLECTOR_CONFIG)
    context.table_.put_item(config)
    context.store, context.cyclotron, context.delivery = RouterStore(context.table_), tr.FakeCyclotron(), tr.Delivery()
    context.cyclotron.combined_enabled = True


@given("Cyclotron answers the combined job in the publication contract")
def step_legacy_answer(context):
    original = context.cyclotron.combined

    def legacy(method, path, data):
        status, body = original(method, path, data)
        if method == "GET" and status == 200:
            entries = body.pop("decisions")
            body = {**body, "contractVersion": mr.LEGACY_CONTRACT_VERSION, "publications": {
                pub: {("publicationId" if key == "bindingId" else key): value for key, value in entry.items()}
                | {"contractVersion": mr.LEGACY_CONTRACT_VERSION} for pub, entry in entries.items()}}
        return status, body
    context.cyclotron.combined = legacy


@when("the router decides the collected story")
def step_run(context):
    context.result = tr.go(context.table_, context.store, context.cyclotron, now=2000, deliver=context.delivery)


@then("the router posted one combined decision in the decision contract")
def step_combined(context):
    posts = [c for c in context.cyclotron.combined_calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/machine/decisions"
    assert posts[0][2]["contractVersion"] == DECISION_CONTRACT
    assert sorted(posts[0][2]["payload"]["bindings"]) == sorted(tr.PUBS)
    assert context.cyclotron.calls == []


@then("the router posted the story to the publication's binding route in the decision contract")
def step_single(context):
    posts = context.cyclotron.posts()
    assert [c[1] for c in posts] == ["/machine/bindings/anth-us/operations"]
    assert posts[0][2]["contractVersion"] == DECISION_CONTRACT
    assert [c[1] for c in context.cyclotron.calls if c[0] == "GET"][0].startswith("/machine/bindings/anth-us/commands/")


@then("the story is routed and delivered to every publication that includes it")
def step_delivered(context):
    assert tr.routing_of(context.table_)["DISC#101#000001"] == "routed"
    configured = [p["publicationId"] for p in context.table_.items[("MONITOR#hn", "CONFIG#router")]["publications"]]
    assert sorted({c[0] for c in context.delivery.calls}) == sorted(configured)


@then("the router posted the story only once")
def step_once(context):
    assert len([c for c in context.cyclotron.combined_calls if c[0] == "POST"]) == 1


@then("the feedback names the calling site and a reviewer in the decision contract")
def step_feedback(context):
    sent = [c for c in context.cyclotron.posts() if c[2]["operation"] == "feedback"]
    assert len(sent) == 1 and sent[0][1] == "/machine/bindings/anth-us/operations"
    body = sent[0][2]
    assert body["contractVersion"] == DECISION_CONTRACT and "editor" not in body["payload"]
    assert body["payload"]["caller"] == "anth-us.example"
    assert body["payload"]["reviewer"].startswith("editor:") and "@" not in body["payload"]["reviewer"]
