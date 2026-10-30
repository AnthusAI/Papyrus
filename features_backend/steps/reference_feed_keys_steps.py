"""Steps for features_backend/reference-feed-keys.feature. Everything is in memory: no network, no AWS, no model."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.auto_accept import accept_reference_automatically  # noqa: E402
from papyrus_content.auto_reject import reject_reference_automatically  # noqa: E402
from papyrus_content.monitoring_router import record_original_prediction  # noqa: E402
from papyrus_content.reference_feed_backfill import backfill_feed_keys  # noqa: E402
from papyrus_content.reference_feed_keys import feed_keys  # noqa: E402

CORPUS = "knowledge-corpus-example-site"
FEED_FIELDS = {"id", "feedStateKey", "feedArrivalAt", "predictedAcceptProbability", "predictionDecidedAt", "predictionSortKey"}


class Backend:
    """A publication's Reference table and relations, recording every write."""

    def __init__(self):
        self.rows, self.relations, self.written = {}, {}, []

    def get_record(self, model, record_id):
        assert model == "Reference", model
        row = self.rows.get(record_id)
        return dict(row) if row else None

    def update_record(self, model, payload):
        assert model == "Reference", model
        self.written.append(dict(payload))
        self.rows[payload["id"]].update(payload)

    def upsert(self, model, payload):
        return "created"

    def list_by_index(self, index, key):
        assert index == "referencesByCurationStatusKey", index
        return [dict(row) for row in self.rows.values() if f"{row['corpusId']}#{row['curationStatus']}" == key]

    def list_semantic_relations_by_subject_state(self, key):
        return list(self.relations.get(key.split("#")[1], []))


def world(context):
    if getattr(context, "feeds", None) is None:
        context.feeds = type("State", (), {"backend": Backend(), "ref": None, "publication": {"positiveLabel": "include"},
                                           "named": {}, "counts": None, "lines": []})()
    return context.feeds


def make_reference(number, *, arrived, status="pending", state="current"):
    lineage = f"reference-example-site-r{number}"
    row = {"id": f"{lineage}-v1", "lineageId": lineage, "versionState": state, "corpusId": CORPUS, "curationStatus": status,
           "curationStatusKey": f"{CORPUS}#{status}", "createdAt": arrived, "title": f"Reference {number}"}
    row.update(feed_keys(row))
    return row


def stored(context):
    return world(context).backend.rows[world(context).ref["id"]]


def decide(context, label, percent):
    state = world(context)
    state.backend.written.clear()
    record_original_prediction(state.backend, state.publication, {"label": label, "confidence": percent / 100},
                               state.ref["id"], {"observedAt": "2026-10-28T12:05:00Z"})


@given('a pending Reference that arrived at "{arrived}" and has no prediction')
def step_pending(context, arrived):
    state = world(context)
    state.ref = make_reference(1, arrived=arrived)
    state.backend.rows[state.ref["id"]] = state.ref


@given("an archived Reference")
def step_archived(context):
    state = world(context)
    state.ref = make_reference(1, arrived="2026-10-28T12:00:00Z", status="archived")
    state.backend.rows[state.ref["id"]] = state.ref


@given("a pending Reference that is not the current version")
def step_superseded(context):
    state = world(context)
    state.ref = make_reference(1, arrived="2026-10-28T12:00:00Z", state="superseded")
    state.backend.rows[state.ref["id"]] = state.ref


@given('the Cyclotron decided "{label}" with {percent:d}% confidence')
def step_decided(context, label, percent):
    decide(context, label, percent)


@when('the Cyclotron decides "{label}" with {percent:d}% confidence and the publication\'s positive label is "{positive}"')
def step_decides(context, label, percent, positive):
    world(context).publication = {"positiveLabel": positive}
    decide(context, label, percent)


@then("the Reference records an accept probability of {probability:f}")
@then("the Reference still records an accept probability of {probability:f}")
def step_probability(context, probability):
    assert abs(stored(context)["predictedAcceptProbability"] - probability) < 1e-9, stored(context)


@then("the Reference records when the Cyclotron decided it")
def step_decided_at(context):
    assert stored(context)["predictionDecidedAt"] == "2026-10-28T12:05:00.000Z", stored(context)


@then('its Best bets key is "{prefix}" followed by its id')
def step_key(context, prefix):
    assert stored(context)["predictionSortKey"] == prefix + stored(context)["id"], stored(context)["predictionSortKey"]


@then("it is still in the unrated feed")
@then("it is in the unrated feed of its corpus")
def step_unrated(context):
    assert stored(context)["feedStateKey"] == f"{CORPUS}#unrated", stored(context)


@then("it is in the rated feed of its corpus")
def step_rated(context):
    assert stored(context)["feedStateKey"] == f"{CORPUS}#rated", stored(context)


@then("it is in no feed")
def step_no_feed(context):
    assert feed_keys(world(context).ref)["feedStateKey"] is None


@then("nothing more was written to the Reference")
def step_nothing_more(context):
    assert world(context).backend.written == [], world(context).backend.written


@given("pending References that arrived together with predicted accept probabilities {first}, {second}, {third} and {fourth}")
def step_four(context, first, second, third, fourth):
    state = world(context)
    state.named = {}
    for number, value in enumerate([first, second, third, fourth], start=1):
        row = make_reference(number, arrived="2026-10-28T12:00:00Z")
        if value != "none":
            row["predictedAcceptProbability"] = float(value)
        row.update(feed_keys(row))
        state.named[number] = row


@when("their Best bets keys are read highest first")
def step_best(context):
    state = world(context)
    state.order = [row["predictedAcceptProbability"] if row.get("predictedAcceptProbability") is not None else None
                   for row in sorted(state.named.values(), key=lambda row: row["predictionSortKey"], reverse=True)]


@then("the order is 0.9, then the two without a prediction or at one half, then 0.2")
def step_best_order(context):
    assert world(context).order[0] == 0.9 and world(context).order[-1] == 0.2, world(context).order
    assert sorted(map(str, world(context).order[1:3])) == ["0.5", "None"], world(context).order


@given('pending References that arrived at "{first}", "{second}" and "{third}"')
def step_three(context, first, second, third):
    state = world(context)
    state.named = {number: make_reference(number, arrived=arrived) for number, arrived in enumerate([first, second, third], start=1)}


@when("their Newest keys are read latest first")
def step_newest(context):
    state = world(context)
    state.order = [row["feedArrivalAt"] for row in sorted(state.named.values(), key=lambda row: row["feedArrivalAt"], reverse=True)]


@then('the order is "{first}", "{second}", "{third}"')
def step_newest_order(context, first, second, third):
    assert world(context).order == [first, second, third], world(context).order


@when("the Cyclotron accepts it automatically")
def step_accept(context):
    state = world(context)
    before = stored(context)["predictionSortKey"]
    state.key_before = before
    assert accept_reference_automatically(state.backend, state.ref, reason="because", evidence={}, now="2026-10-29T00:00:00Z")


@when("the Cyclotron rejects it automatically")
def step_reject(context):
    state = world(context)
    assert reject_reference_automatically(state.backend, state.ref, cyclotron_id="example", probability=0.97, proof_id="proof-1",
                                          decision_id="decision-1", now="2026-10-29T00:00:00Z")


@then("its Best bets key is unchanged")
def step_key_unchanged(context):
    assert stored(context)["predictionSortKey"] == world(context).key_before


@given("a corpus with these References and no feed keys")
def step_corpus(context):
    state = world(context)
    state.named = {}
    for number, row in enumerate(context.table, start=1):
        reference = make_reference(number, arrived=f"2026-10-{20 + number}T00:00:00Z", status=row["status"])
        for key in ("feedStateKey", "feedArrivalAt", "predictionSortKey"):
            reference.pop(key)
        state.backend.rows[reference["id"]] = reference
        state.named[row["name"]] = reference["id"]
        decision = row["decision"]
        if decision != "none":
            label, _, rest = decision.partition(" with ")
            confidence = int(rest.split("%")[0]) / 100
            state.backend.relations[reference["lineageId"]] = [{
                "predicate": "relevance_decision_is", "relationState": "current", "objectKind": "semanticNode",
                "objectLineageId": f"semantic-node-relevance-{label}", "subjectLineageId": reference["lineageId"],
                "confidence": confidence, "score": confidence, "createdAt": "2026-10-22T00:00:00Z",
                "metadata": json.dumps({"label": label, "positiveLabel": "include", "decidedAt": "2026-10-22T00:00:00Z"})}]


@given('the "{name}" Reference already records an accept probability of {probability:f}')
def step_already(context, name, probability):
    state = world(context)
    row = state.backend.rows[state.named[name]]
    row.update({"predictedAcceptProbability": probability, "predictionDecidedAt": "2026-10-21T00:00:00.000Z"})


@when("the feed key backfill runs for that corpus")
def step_backfill(context):
    state = world(context)
    state.counts = backfill_feed_keys(state.backend, corpus_id=CORPUS)


@when("the feed key backfill runs for that corpus again")
def step_backfill_again(context):
    state = world(context)
    state.backend.written.clear()
    state.counts = backfill_feed_keys(state.backend, corpus_id=CORPUS)


@when("the feed key backfill runs for that corpus as a dry run")
def step_dry(context):
    state = world(context)
    state.counts = backfill_feed_keys(state.backend, corpus_id=CORPUS, dry_run=True)


@then("the second run wrote nothing")
@then("the dry run wrote nothing to the References")
def step_wrote_nothing(context):
    assert world(context).backend.written == [], world(context).backend.written


@then("each backfill write names only the Reference id and feed key fields")
def step_only_feed_fields(context):
    for payload in world(context).backend.written:
        assert set(payload) <= FEED_FIELDS, sorted(set(payload) - FEED_FIELDS)


def row_named(context, name):
    state = world(context)
    return state.backend.rows[state.named[name]]


@then('the "{name}" Reference is unrated with an accept probability of {probability:f}')
def step_named_unrated(context, name, probability):
    row = row_named(context, name)
    assert row["feedStateKey"] == f"{CORPUS}#unrated" and abs(row["predictedAcceptProbability"] - probability) < 1e-9, row


@then('the "{name}" Reference is rated with an accept probability of {probability:f}')
def step_named_rated(context, name, probability):
    row = row_named(context, name)
    assert row["feedStateKey"] == f"{CORPUS}#rated" and abs(row["predictedAcceptProbability"] - probability) < 1e-9, row


@then('the "{name}" Reference still records an accept probability of {probability:f}')
def step_named_still(context, name, probability):
    assert row_named(context, name)["predictedAcceptProbability"] == probability


@then('the "{name}" Reference is unrated with no accept probability and sorts as one half')
def step_named_unpredicted(context, name):
    row = row_named(context, name)
    assert row["feedStateKey"] == f"{CORPUS}#unrated" and row.get("predictedAcceptProbability") is None, row
    assert row["predictionSortKey"].startswith("0.500000#"), row["predictionSortKey"]


@then('the "{name}" Reference is in no feed')
def step_named_none(context, name):
    assert row_named(context, name).get("feedStateKey") is None


@then("the backfill reports {scanned:d} scanned, {recorded:d} predictions recorded and {unpredicted:d} without a prediction")
def step_report(context, scanned, recorded, unpredicted):
    counts = world(context).counts
    assert (counts["scanned"], counts["predictionsRecorded"], counts["unpredicted"]) == (scanned, recorded, unpredicted), counts


@then("the backfill reports {scanned:d} scanned and {changed:d} changed")
def step_report_changed(context, scanned, changed):
    counts = world(context).counts
    assert (counts["scanned"], counts["changed"]) == (scanned, changed), counts
