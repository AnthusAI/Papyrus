from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest import mock

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.graphql_authoring import INDEX_DEFINITIONS  # noqa: E402
from papyrus_content.relevance_decisions import current_relevance_decision  # noqa: E402
from papyrus_content.relevance_sweep import CyclotronClaimed, run_decide_relevance, sweep_assignment_id  # noqa: E402
from papyrus_content.steering import load_steering_config  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

CORPUS_ID = "knowledge-corpus-example"
DOCTRINE = [{"kind": "mission", "body": ["Publish practical AI security analysis."]},
            {"kind": "policy", "body": ["Prefer primary evidence over vendor marketing."]}]
INDEX_MODELS = {
    "referencesByCurationStatusKey": "Reference",
    "semanticRelationsBySubjectState": "SemanticRelation",
    "semanticRelationsByObjectState": "SemanticRelation",
    "assignmentsByQueueStatusAndPriority": "Assignment",
    "modelAttachmentsByOwnerRoleAndSortKey": "ModelAttachment",
}


class SweepClient(FakeAuthoringClient):
    """The fake authoring client with the indexes and attachment bodies the sweep uses."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bodies: dict[str, bytes] = {}

    def list_by_index(self, index_name, key_value, **_kwargs):
        partition_key = INDEX_DEFINITIONS[index_name]["partitionKey"]
        return [dict(row) for row in self._table(INDEX_MODELS[index_name]).values() if row.get(partition_key) == key_value]

    def create_record(self, model_name, payload):
        self.upsert(model_name, payload)


class Model:
    model_identity = "scripted-relevance"

    def __init__(self):
        self.calls = 0

    async def classify_many(self, configs, target, training, **kwargs):
        from decision_flywheel.batched_classification import BatchedAnswers
        from decision_flywheel.models import DecisionResult

        self.calls += 1
        p = 0.8 if "security" in target.values["text"] else 0.3
        return BatchedAnswers({cid: {"decision": DecisionResult("include" if p > .5 else "exclude",
                                                                {"include": p, "exclude": 1 - p})}
                               for cid in configs}, "scripted", {"input_tokens": 1000, "output_tokens": 0}, 1)


class LocalBucket:
    """A private bucket stand-in on the local disk."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, uri):
        return self.root / uri.removeprefix("s3://")

    def download(self, uri, path):
        source = self._path(uri)
        if not source.exists():
            return False
        shutil.copy(source, path)
        return True

    def upload(self, path, uri):
        target = self._path(uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, target)


def reference(lineage, title, status):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current",
            "corpusId": CORPUS_ID, "title": title, "sourceUri": f"https://example.org/{lineage}",
            "curationStatus": status, "curationStatusKey": f"{CORPUS_ID}#{status}",
            "curationStatusReason": "Found by source discovery." if status == "pending" else None,
            "importedAt": f"2026-10-0{1 + len(lineage) % 8}T00:00:00Z"}


def configure(context, worker_dir: Path):
    raw = {
        "schemaVersion": 1,
        "publication": {"name": "Example"},
        "canonicalTopicSet": {"corpusKey": "example", "classifierId": "example"},
        "corpora": [{"key": "example", "name": "example", "path": "corpora/example", "role": "canonical"}],
        "relevanceCyclotron": {"optimizer": None,
                               "store": {"localPath": str(worker_dir / "cyclotron"),
                                         "s3Prefix": "s3://example-private-media/cyclotrons/papyrus-relevance/"}},
    }
    path = Path(context.tmp) / "steering.yml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    context.steering = load_steering_config(str(path))


def run(context, *, apply=True, fresh_worker=False):
    if fresh_worker:
        configure(context, Path(tempfile.mkdtemp()))
    context.error = None
    def store_body(client, attachment, body):
        client.upsert("ModelAttachment", attachment)
        client.bodies[attachment["id"]] = body

    with mock.patch("papyrus_content.relevance_sweep.knowledge_corpus_id", return_value=CORPUS_ID), \
            mock.patch("papyrus_content.records.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.assignments.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer",
                       side_effect=lambda client, attachment: client.bodies.get(attachment["id"])):
        try:
            context.result = run_decide_relevance(context.client, context.steering, DOCTRINE, apply=apply,
                                                  worker="worker-a", model=context.model, snapshots=context.bucket)
        except CyclotronClaimed as error:
            context.error = error


@given("a publication with a relevance cyclotron")
def step_publication(context):
    context.tmp = tempfile.mkdtemp()
    context.model = Model()
    context.bucket = LocalBucket(Path(context.tmp) / "bucket")
    configure(context, Path(context.tmp) / "worker-1")


@given("two pending references and one accepted reference")
def step_references(context):
    context.pending = [reference("reference-a", "A security advisory for model servers", "pending"),
                       reference("reference-bb", "A vendor launch announcement", "pending")]
    context.accepted = reference("reference-ccc", "An accepted security paper", "accepted")
    context.client = SweepClient({"Reference": [*context.pending, context.accepted]})


@when("the decide-relevance sweep runs with apply")
@given("the decide-relevance sweep has run with apply")
def step_run(context):
    run(context)


@when("the decide-relevance sweep runs with apply on a fresh worker")
def step_run_fresh(context):
    run(context, fresh_worker=True)


@when("the decide-relevance sweep runs without apply")
def step_dry_run(context):
    run(context, apply=False)


def decisions(context, lineage):
    return [relation for relation in context.client.list_records("SemanticRelation")
            if relation.get("predicate") == "relevance_decision_is" and relation.get("subjectLineageId") == lineage]


@then("each pending reference has a current relevance decision")
@then("each pending reference still has one current relevance decision")
def step_each_decided(context):
    for item in context.pending:
        assert current_relevance_decision(decisions(context, item["lineageId"]), item["lineageId"]) is not None
        assert len([d for d in decisions(context, item["lineageId"]) if d["relationState"] == "current"]) == 1


@then("the accepted reference has no relevance decision")
def step_accepted_none(context):
    assert decisions(context, context.accepted["lineageId"]) == []


def status(context):
    payload = context.client.get_record("KnowledgeRawPayload", "knowledge-raw-payload-cyclotron-status-papyrus-relevance")
    assert payload is not None
    attachment = next(row for row in context.client.list_records("ModelAttachment") if row.get("ownerId") == payload["id"])
    return json.loads(context.client.bodies[attachment["id"]])


@then("the cyclotron status snapshot is recorded with {count:d} decisions awaiting review")
def step_status(context, count):
    snapshot = status(context)
    assert snapshot["schema"] == "cyclotron-status/v1"
    assert snapshot["pending"]["decisionsAwaitingReview"] == count, snapshot["pending"]


@then("no reference changed its curation status")
def step_no_status_change(context):
    for item in [*context.pending, context.accepted]:
        assert context.client.get_record("Reference", item["id"])["curationStatus"] == item["curationStatus"]


@then("the cyclotron store snapshot is in the private bucket")
def step_snapshot(context):
    assert (context.bucket.root / "example-private-media/cyclotrons/papyrus-relevance/state.tar.gz").exists()
    assignment = context.client.get_record("Assignment", sweep_assignment_id("papyrus-relevance"))
    assert assignment["status"] == "open" and not assignment.get("assigneeKey")  # the claim was released


@then("the decision model was called once per pending reference in total")
def step_calls(context):
    assert context.model.calls == len(context.pending), context.model.calls


def curate(context, item, *, status, action, reason, note, shareable):
    row = context.client.tables["Reference"][item["id"]]
    row.update({"curationStatus": status, "curationStatusKey": f"{CORPUS_ID}#{status}",
                "curationStatusReason": note, "curationStatusUpdatedAt": "2026-10-09T12:00:00Z"})
    message_id = f"message-reference-curation-{item['lineageId']}-{action}"
    metadata = {"action": action, "reasonCode": reason, **({"shareable": shareable} if shareable is not None else {})}
    context.client.upsert("Message", {"id": message_id, "messageKind": "reference_curation", "authorLabel": "editor-7",
                                      "createdAt": "2026-10-09T12:00:00Z", "metadata": json.dumps(metadata)})
    context.client.upsert("SemanticRelation", {
        "id": f"relation-{message_id}", "relationState": "current", "predicate": "comment", "subjectKind": "message",
        "subjectId": message_id, "objectKind": "reference", "objectLineageId": item["lineageId"],
        "objectStateKey": f"reference#{item['lineageId']}#current", "subjectStateKey": f"message#{message_id}#current"})


@given('an editor rejected the first pending reference as "{reason}" saying "{note}" and allowed quoting')
def step_editor_rejects_shareable(context, reason, note):
    curate(context, context.pending[0], status="rejected", action="reject", reason=reason, note=note, shareable=True)


@given('an editor accepted the second pending reference saying "{note}"')
def step_editor_accepts(context, note):
    curate(context, context.pending[1], status="accepted", action="accept", reason=None, note=note, shareable=False)


@given('an editor rejected the first pending reference as "{reason}" saying "{note}"')
def step_editor_rejects(context, reason, note):
    item = context.pending[0]
    row = context.client.tables["Reference"][item["id"]]
    row.update({"curationStatus": "rejected", "curationStatusKey": f"{CORPUS_ID}#rejected",
                "curationStatusReason": note, "curationStatusUpdatedAt": "2026-10-09T12:00:00Z"})
    message_id = f"message-reference-curation-{item['lineageId']}-reject"
    context.client.upsert("Message", {"id": message_id, "messageKind": "reference_curation", "authorLabel": "editor-7",
                                      "createdAt": "2026-10-09T12:00:00Z",
                                      "metadata": json.dumps({"action": "reject", "reasonCode": reason})})
    context.client.upsert("SemanticRelation", {
        "id": f"relation-{message_id}", "relationState": "current", "predicate": "comment", "subjectKind": "message",
        "subjectId": message_id, "objectKind": "reference", "objectLineageId": item["lineageId"],
        "objectStateKey": f"reference#{item['lineageId']}#current", "subjectStateKey": f"message#{message_id}#current"})


def open_store(context):
    from decision_flywheel import Cyclotron
    from papyrus_content.relevance_cyclotron import build_relevance_cyclotron
    plan = build_relevance_cyclotron(context.steering, DOCTRINE)
    return Cyclotron.open(plan.local_path, plan.definition, context.model, review_program=plan.review_program)


@then('the cyclotron has a label "{label}" for the first pending reference with the explanation "{note}"')
def step_label(context, label, note):
    with open_store(context) as cyclotron:
        labels = {row["item"].id: row for row in cyclotron.labels()}
    row = labels[context.pending[0]["lineageId"]]
    assert (row["label"], row["explanation"], row["reason_code"], row["reviewer"]) == (label, note, "out_of_scope", "editor-7")


@then("the cyclotron has no label for the first pending reference")
def step_no_label(context):
    with open_store(context) as cyclotron:
        assert context.pending[0]["lineageId"] not in {row["item"].id for row in cyclotron.labels()}


@given("another worker holds the relevance cyclotron claim")
def step_claimed(context):
    context.client.upsert("Assignment", {"id": sweep_assignment_id("papyrus-relevance"), "assignmentTypeKey": "cyclotron.relevance",
                                         "queueKey": f"cyclotron.relevance#{CORPUS_ID}", "status": "claimed",
                                         "assigneeKey": "worker-b", "claimExpiresAt": "2999-01-01T00:00:00Z"})


@then("the sweep stops because the cyclotron is claimed")
def step_stopped(context):
    assert context.error is not None and "worker-b" in str(context.error)


@then("the decision model was not called")
def step_no_calls(context):
    assert context.model.calls == 0


@then("the plan lists {count:d} pending references to decide")
def step_plan(context, count):
    assert context.result.pending == [item["lineageId"] for item in sorted(
        context.pending, key=lambda r: r["importedAt"])][:count] and len(context.result.pending) == count


def request_review_rate(context, payload, at):
    from papyrus_content.relevance_decisions import review_rate_request_id
    record_id = review_rate_request_id("papyrus-relevance")
    context.client.upsert("KnowledgeRawPayload", {"id": record_id, "ownerType": "cyclotron", "ownerId": "papyrus-relevance",
                                                   "payloadKind": "cyclotron-review-rate-request", "createdAt": at})
    attachment_id = f"model-attachment-request-{at}"
    context.client.upsert("ModelAttachment", {"id": attachment_id, "ownerKind": "knowledgeRawPayload", "ownerId": record_id,
                                              "role": "raw_payload", "status": "active", "createdAt": at, "updatedAt": at,
                                              "storagePath": f"newsroom/payloads/{attachment_id}.json"})
    context.client.bodies[attachment_id] = json.dumps(payload).encode()


@given("an editor asked for a {percent:d}% review rate for {days:d} days")
def step_request_rate(context, percent, days):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    request_review_rate(context, {"rate": percent / 100, "expiresAt": (now + timedelta(days=days)).isoformat(),
                                  "setBy": "managing-editor", "requestedAt": now.isoformat()}, now.isoformat())


@given("the editor then asked to clear the manual rate")
def step_request_clear(context):
    from datetime import datetime, timedelta, timezone
    later = datetime.now(timezone.utc) + timedelta(seconds=1)
    request_review_rate(context, {"clear": True, "setBy": "managing-editor", "requestedAt": later.isoformat()},
                        later.isoformat())


@then('the cyclotron status snapshot reports a manual rate of {percent:d}% set by "{who}"')
def step_manual_rate(context, percent, who):
    rate = status(context)["reviewRate"]
    assert rate["state"] == "manual" and rate["rate"] == percent / 100, rate
    assert rate["override"]["setBy"] == who and rate["override"]["expiresAt"]


@then("the cyclotron applied the manual rate once")
def step_applied_once(context):
    from decision_flywheel import Cyclotron  # noqa: F401
    with open_store(context) as cyclotron:
        changes = [event for event in cyclotron.subscribe(limit=1000)["events"] if event["kind"] == "review-rate-changed"]
    assert len(changes) == 1, changes


@then("the cyclotron status snapshot reports no manual rate")
def step_no_manual(context):
    rate = status(context)["reviewRate"]
    assert rate["override"] is None and rate["state"] != "manual", rate
