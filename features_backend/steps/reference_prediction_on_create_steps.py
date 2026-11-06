"""features_backend/reference-prediction-on-create.feature. Fakes only; procedures/newsroom/tests/test_reference_prediction_queue.py shares them."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import monitoring_router as mr  # noqa: E402
from papyrus_content import reference_prediction_queue as queue  # noqa: E402
from papyrus_content.monitoring_view import TableViewStore  # noqa: E402
from procedures.newsroom.tests import test_reference_prediction_queue as tp  # noqa: E402
from procedures.newsroom.tests.test_monitoring_router import FakeTable, LabAppSync, go, router_config, setup_router  # noqa: E402


def world(context):
    if not hasattr(context, "prediction"):
        patcher = mock.patch("papyrus_content.records.upload_attachment_body", lambda client, expected, body: None)
        patcher.start()
        context.add_cleanup(patcher.stop)
        table = FakeTable()
        store, cyclotron = setup_router(table)
        client = LabAppSync(tp.ENDPOINT_ANTH, tp.CORPUS)
        context.prediction = type("World", (), {"table": table, "router_store": store, "cyclotron": cyclotron, "client": client,
                                                "queue_store": TableViewStore(table, "hn"), "result": None, "answer": None, "now": 2000})
    return context.prediction


def ask(context, references=None):
    held = world(context)
    return queue.queue_reference_predictions(held.queue_store, endpoint=tp.ENDPOINT_ANTH, references=references or [tp.request_of()], subject="user-intake")


def drain(context, **kwargs):
    held = world(context)
    held.result = go(held.table, held.router_store, held.cyclotron, now=held.now, task="email-references", appsync=lambda endpoint: held.client, **kwargs)
    held.now += 24 * 3600   # the next run is a day later, past any backoff
    return held.result


def reference(context, identifier="reference-user-intake-aaa-v1"):
    return world(context).client.rows[("Reference", identifier)]


@given("a pending Reference with no prediction")
def step_pending(context):
    world(context).client.rows[("Reference", tp.reference_row()["id"])] = tp.reference_row()


@given("a pending Reference that already has a prediction")
def step_predicted(context):
    world(context).client.rows[("Reference", tp.reference_row()["id"])] = tp.reference_row(
        predictedAcceptProbability=0.7, predictionDecidedAt="2026-11-05T09:00:00.000Z")


@given("a route that created it asks for its prediction")
def step_asked(context):
    ask(context)


@given("its request was decided and the numbers were then removed from the row")
def step_numbers_removed(context):
    ask(context)
    drain(context)
    row = reference(context)
    for key in ("predictedAcceptProbability", "predictionDecidedAt"):
        row.pop(key)
    world(context).table.items.clear()
    world(context).table.put_item(router_config())


@given("the Cyclotron is not ready to decide")
def step_not_ready(context):
    world(context).cyclotron.post_override["anth-us"] = (409, {"detail": "publication criteria are pending"})


@when("a route that created it asks for its prediction twice")
def step_asks_twice(context):
    context.first, context.second = ask(context), ask(context)


@when("the router works through the queued requests")
def step_router_runs(context):
    drain(context)


@when("the router works through a second request for it")
def step_router_second(context):
    ask(context)
    context.posts_before = len(world(context).cyclotron.posts())
    drain(context)


@then("there is exactly one queued request for it and the publication's data was not written")
def step_one_request(context):
    held = world(context)
    assert context.first["queued"] == 1 and context.second["queued"] == 0 and context.second["alreadyQueued"] == 1
    assert len(tp.lane_rows(held.table)) == 1
    assert not [op for op in held.client.ops if op[0] in ("create", "update")]


@then("the Reference has a probability, a time and a sort key, and one current decision relation")
def step_recorded(context):
    held = world(context)
    row = reference(context)
    assert isinstance(row["predictedAcceptProbability"], float) and row["predictionDecidedAt"] and row["predictionSortKey"] != tp.reference_row()["predictionSortKey"]
    (relation,) = held.client.relations()
    assert relation["subjectId"] == row["id"] and json.loads(relation["metadata"])["provenance"]["system"] == "cyclotron-lab"


@then("its vote and status are unchanged and the request has left the lane")
def step_unchanged(context):
    row = reference(context)
    assert row["curationStatus"] == "pending" and row["feedStateKey"] == f"{tp.CORPUS}#unrated"
    assert not tp.lane_rows(world(context).table)


@then("the Cyclotron was asked to decide once and was sent no feedback")
def step_no_feedback(context):
    posts = world(context).cyclotron.posts()
    assert len(posts) == 1 and posts[0][2]["operation"] == "decide"
    assert not [call for call in world(context).cyclotron.calls if call[2] and call[2].get("operation") == "feedback"]


@then("the decision input was the title and address with no summary")
def step_input(context):
    values = world(context).cyclotron.posts()[0][2]["payload"]["item"]["values"]
    assert values["text"] == f"A pasted page\n{tp.URL}" and "summary" not in values


@then("the Cyclotron was not called and the earlier prediction stands")
def step_not_called(context):
    assert world(context).cyclotron.posts() == [] and reference(context)["predictedAcceptProbability"] == 0.7


@then("the Cyclotron was not called again and the row has its probability back")
def step_copied(context):
    assert len(world(context).cyclotron.posts()) == context.posts_before
    assert reference(context)["predictedAcceptProbability"] is not None and reference(context)["predictionDecidedAt"]


@then("the Reference still has no prediction and its request is still queued")
def step_hidden(context):
    assert "predictedAcceptProbability" not in reference(context) and len(tp.lane_rows(world(context).table)) == 1


@then("later, when the Cyclotron answers, the Reference is predicted and the request is gone")
def step_later(context):
    world(context).cyclotron.post_override.clear()
    drain(context)
    assert reference(context)["predictedAcceptProbability"] is not None and not tp.lane_rows(world(context).table)


@given("an import that created a pending Reference")
def step_import_one(context):
    context.created = {"references": [{"id": "reference-user-intake-aaa-v1", "sourceUri": tp.URL, "curationStatus": "pending"}]}


@when("the publication is not served by the cloud router")
def step_not_served(context):
    context.answer = queue.queue_after_intake(context.created, {"items": []}, store=world(context).queue_store,
                                              env={"PAPYRUS_GRAPHQL_ENDPOINT": "https://zzz.appsync-api.us-east-1.amazonaws.com/graphql"})


@then("the answer says plainly that the prediction was not requested, names the command that asks again, and nothing was raised")
def step_reported(context):
    assert context.answer["ok"] is False and context.answer["error"]
    line = queue.request_line("references\tcreate-from-catalog", queue.PredictionRequest(error=context.answer["error"]))
    assert "NOT-REQUESTED" in line and "papyrus references queue-predictions" in line


@given("an import that created thirty pending References")
def step_import_many(context):
    held = world(context)
    context.rows = [tp.reference_row(f"reference-import-{n}-v1", sourceUri=f"https://example.org/p{n}", title=f"Paper {n}") for n in range(30)]
    for row in context.rows:
        held.client.rows[("Reference", row["id"])] = row


@when("the route asks for their predictions")
def step_asks_many(context):
    context.answer = ask(context, [tp.request_of(row) for row in context.rows])


@then("thirty requests are queued with one conditional write each and no decision was made in the request")
def step_queued_many(context):
    held = world(context)
    assert context.answer["queued"] == 30 and len(tp.lane_rows(held.table)) == 30 and held.cyclotron.posts() == []


@then("the router decides them within its own time and stops, without loss, when that time is up")
def step_time(context):
    held = world(context)
    drain(context, time_left=lambda: 1e9 if len(held.cyclotron.posts()) < 10 else 10)
    waiting = len(tp.lane_rows(held.table))
    assert 0 < waiting < 30
    drain(context)
    assert not tp.lane_rows(held.table)
    assert all(reference(context, row["id"]).get("predictedAcceptProbability") is not None for row in context.rows)


@when("the monitor is changed to deliver by rule and the router works through the queued requests")
def step_rule(context):
    held = world(context)
    held.table.put_item(router_config(decisions="direct"))
    held.result = go(held.table, held.router_store, None, now=held.now, task="email-references", appsync=lambda endpoint: held.client)


@then("the Cyclotron was not called and the request is still queued")
def step_waiting(context):
    held = world(context)
    assert held.cyclotron.posts() == [] and len(tp.lane_rows(held.table)) == 1 and held.result["counts"]["predictionsWaiting"] == 1
    assert mr.PREDICTION_LANE == queue.LANE


@given("the partition every site backend queues prediction requests into by default")
def step_default_partition(context):
    from papyrus_content import prediction_lane_drain_test as drain_test
    context.default_partition = drain_test.site_default_partition()


@then("the monitoring stack has a five minute schedule that runs the email-references task for that same partition")
def step_drained(context):
    from papyrus_content import prediction_lane_drain_test as drain_test
    assert drain_test.parameter_default("ReferencePredictionMonitorId") == context.default_partition
    drain_test.test_the_partition_sites_queue_into_by_default_is_drained_by_a_schedule()


@given("a Reference that an import created already accepted and that has no prediction")
def step_accepted(context):
    context.accepted = tp.reference_row("reference-accepted-v1", curationStatus="accepted")


@then("it is one of the References a prediction is requested for")
def step_accepted_requested(context):
    assert [item["referenceId"] for item in queue.references_for_prediction([context.accepted])] == ["reference-accepted-v1"]
