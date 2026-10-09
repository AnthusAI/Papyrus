from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.model_attachments import expand_private_payload_records  # noqa: E402
from papyrus_content.relation_types import semantic_relation_type_fields_for_predicate  # noqa: E402
from papyrus_content.relevance_decisions import (  # noqa: E402
    current_relevance_decision, relevance_decision_records, relevance_label_for_review, status_snapshot_record,
)
from papyrus_knowledge_query.engine import OPERATIONAL_RELATION_DOMAINS  # noqa: E402

NOW = "2026-10-09T12:00:00+00:00"
REFERENCE = {"id": "reference-example-a-v1", "lineageId": "reference-example-a", "versionNumber": 1,
             "versionState": "current", "curationStatus": "pending"}


def decision(label, confidence, *, selected, reason, decision_id):
    other = "exclude" if label == "include" else "include"
    return {"decisionId": decision_id, "itemId": REFERENCE["lineageId"], "createdAt": NOW,
            "classifiers": {"relevant": {"label": label, "confidence": confidence,
                                         "probabilities": {label: confidence, other: round(1 - confidence, 6)},
                                         "version": 3, "fingerprint": "f"}},
            "review": {"selected": selected, "reason": reason, "propensity": 0.25 if selected else 0.25,
                       "detail": "Random audit sample." if reason == "audit" else "Confident decision not sampled."}}


def apply(records, relations):
    """Apply relation records to an in-memory table by id, as the authoring client would."""
    table = {relation["id"]: dict(relation) for relation in relations}
    for record in records:
        if record["modelName"] == "SemanticRelation":
            table[record["expected"]["id"]] = {**table.get(record["expected"]["id"], {}), **record["expected"]}
    return list(table.values())


@given("a pending reference")
def step_pending(context):
    context.relations = []


@given("a pending reference with a current relevance decision")
def step_with_decision(context):
    context.relations = []
    records = relevance_decision_records(REFERENCE, decision("include", 0.82, selected=True, reason="audit",
                                                             decision_id="decision-1"),
                                         cyclotron_id="papyrus-relevance", positive_label="include", now=NOW)
    context.relations = apply(records, [])
    context.older_id = current_relevance_decision(context.relations, REFERENCE["lineageId"])["id"]


@given('a relevance decision of "{label}" at {percent:d}% sent to review as a random audit')
def step_decision_selected(context, label, percent):
    context.decision = decision(label, percent / 100, selected=True, reason="audit", decision_id="decision-new")


@given('a relevance decision of "{label}" at {percent:d}% not sent to review')
def step_decision_unselected(context, label, percent):
    context.decision = decision(label, percent / 100, selected=False, reason=None, decision_id="decision-new")


@when("the decision is recorded")
def step_record(context):
    context.records = relevance_decision_records(REFERENCE, context.decision, cyclotron_id="papyrus-relevance",
                                                 positive_label="include", now=NOW,
                                                 current_relations=context.relations)
    context.relations = apply(context.records, context.relations)


@then('the reference has one current relevance decision of "{label}"')
def step_one_current(context, label):
    current = current_relevance_decision(context.relations, REFERENCE["lineageId"])
    assert current is not None
    assert json.loads(current["metadata"])["label"] == label
    assert current["objectLineageId"] == f"semantic-node-relevance-{label}"


@then("the decision records its confidence, cyclotron classifier, version and that review is recommended")
def step_fields(context):
    current = current_relevance_decision(context.relations, REFERENCE["lineageId"])
    assert current["confidence"] == 0.82 and current["score"] == 0.82
    assert current["classifierId"] == "papyrus-relevance/relevant"
    assert current["modelVersion"] == "3"
    assert current["reviewRecommended"] is True
    metadata = json.loads(current["metadata"])
    assert metadata["decisionId"] == "decision-new" and metadata["reviewReason"] == "audit"
    assert current["relationTypeKey"] == "relevance_decision_is" and current["relationDomain"] == "workflow"


@then('the decision node "{key}" is recorded')
def step_node(context, key):
    nodes = [record["expected"] for record in context.records if record["modelName"] == "SemanticNode"]
    assert [node["nodeKey"] for node in nodes] == [key]


@then("the older decision is superseded")
def step_superseded(context):
    older = next(relation for relation in context.relations if relation["id"] == context.older_id)
    assert older["relationState"] == "superseded"


@when('the relation type "{key}" is looked up')
def step_lookup(context, key):
    context.fields = semantic_relation_type_fields_for_predicate(key)


@then("it is an operational workflow relation that knowledge queries exclude")
def step_operational(context):
    assert context.fields["relationDomain"] == "workflow"
    assert context.fields["relationDomain"] in OPERATIONAL_RELATION_DOMAINS


@given("a cyclotron status snapshot")
def step_status(context):
    example = REPO_ROOT / "procedures" / "newsroom" / "tests" / "fixtures" / "cyclotron-status.v1.example.json"
    context.status = json.loads(example.read_text(encoding="utf-8"))


@when("the snapshot is recorded")
def step_record_status(context):
    context.status_records = expand_private_payload_records([status_snapshot_record("papyrus-relevance", context.status, now=NOW)])


@then("it is a raw payload for the cyclotron with the snapshot as its private attachment")
def step_status_records(context):
    payload = next(r["expected"] for r in context.status_records if r["modelName"] == "KnowledgeRawPayload")
    assert payload["id"] == "knowledge-raw-payload-cyclotron-status-papyrus-relevance"
    assert payload["payloadKind"] == "cyclotron-status" and "payload" not in payload
    attachment = next(r for r in context.status_records if r["modelName"] == "ModelAttachment")
    assert attachment["expected"]["ownerKind"] == "knowledgeRawPayload"
    assert attachment["expected"]["role"] == "raw_payload"
    assert json.loads(attachment["attachmentBody"]) == context.status


@given('a reference curated as "{status}" with reason "{reason}"')
def step_curated(context, status, reason):
    context.reference = {**REFERENCE, "curationStatus": status}
    context.messages = [{"createdAt": NOW, "metadata": json.dumps({"reasonCode": reason})}] if reason else []


@given('a reference curated as "{status}" with reason ""')
def step_curated_without_reason(context, status):
    step_curated(context, status, "")


@when("its cyclotron label is read")
def step_label(context):
    context.label = relevance_label_for_review(context.reference, context.messages, labels=("include", "exclude"))


@then('the label is "{label}"')
def step_label_is(context, label):
    assert context.label == (None if label == "none" else label), context.label
