"""Shared fixtures for the auto-reject specs: a confident scripted model, a proof file and a sweep runner."""
import json
from unittest import mock

from features_backend.steps.cyclotron_relevance_sweep_steps import (CORPUS_ID, DOCTRINE, LocalBucket, Model, configure,
                                                                     reference)
from papyrus_content.reference_vote import HUMAN, latest_vote, vote_fields
from papyrus_content.relevance_sweep import run_decide_relevance

VENDOR_TITLE = "A vendor launch announcement"
SECURITY_TITLE = "A security advisory for model servers"
BORDERLINE_TITLE = "A borderline roundup"
SWEEP_TIME = "2026-10-18T10:00:00Z"


class ConfidentModel(Model):
    """Vendor items are excluded with 0.99, borderline ones with 0.90, security ones included with 0.8."""

    async def classify_many(self, configs, target, training, **kwargs):
        from decision_flywheel.batched_classification import BatchedAnswers
        from decision_flywheel.models import DecisionResult

        self.calls += 1
        text = target.values["text"]
        exclude = 0.99 if "vendor" in text else 0.90 if "borderline" in text else 0.2
        label = "exclude" if exclude > 0.5 else "include"
        return BatchedAnswers({cid: {"decision": DecisionResult(label, {"include": 1 - exclude, "exclude": exclude})}
                               for cid in configs}, "scripted", {"input_tokens": 1000, "output_tokens": 0}, 1)


def make_reference(lineage, title):
    return reference(lineage, title, "pending")


def write_approved_proof(path):
    proof = {"proofId": "ti-cv-1", "ranAt": "2026-10-10T00:00:00Z", "heldOut": {"size": 0},
             "points": [{"labels": 0, "agreement": 0.78}, {"labels": 18, "agreement": 0.96}]}
    path.write_text(json.dumps(proof), encoding="utf-8")
    return str(path)


def auto_reject_context(tmp_path, *, auto_reject, proof, extra=None):
    context = type("Context", (), {})()
    context.tmp = str(tmp_path)
    configure(context, tmp_path / "worker")
    block = context.steering["relevanceCyclotron"]
    if auto_reject is not None:
        block["autoReject"] = auto_reject
    if proof:
        block["approvedProofPath"] = write_approved_proof(tmp_path / "approved-proof.json")
    block.update(extra or {})
    return context


def sweep_with(context, model, client, tmp_path, *, apply=True, now=SWEEP_TIME):
    stored_bodies = client.bodies

    def store_body(recording_client, attachment, body):
        recording_client.upsert("ModelAttachment", attachment)
        stored_bodies[attachment["id"]] = body

    with mock.patch("papyrus_content.relevance_sweep.knowledge_corpus_id", return_value=CORPUS_ID), \
            mock.patch("papyrus_content.records.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.assignments.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer",
                       side_effect=lambda recording_client, attachment: stored_bodies.get(attachment["id"])):
        return run_decide_relevance(client, context.steering, DOCTRINE, apply=apply, worker="worker-a", model=model,
                                    snapshots=LocalBucket(tmp_path / "bucket"), now=lambda: now)


def reopen_as_a_person(client, item, *, at="2026-10-09T12:00:00Z"):
    """A person reopens the Reference: the vote is recorded on the Reference itself."""
    row = client.tables["Reference"][item["id"]]
    row.update({"curationStatus": "pending", "curationStatusKey": f"{CORPUS_ID}#pending", "curationStatusUpdatedAt": at,
                "curationStatusUpdatedBy": "editor-7", **vote_fields(HUMAN)})


def votes_of(client, lineage_id):
    """The Reference's recorded votes: at most one, because it keeps only its latest."""
    rows = [row for row in client.tables["Reference"].values() if row.get("lineageId") == lineage_id]
    return [vote for vote in (latest_vote(row) for row in rows) if vote]


def labels_of_store(context):
    from decision_flywheel import Cyclotron
    from papyrus_content.relevance_cyclotron import build_relevance_cyclotron

    plan = build_relevance_cyclotron(context.steering, DOCTRINE)
    with Cyclotron.open(plan.local_path, plan.definition, Model(), review_program=plan.review_program) as cyclotron:
        return {row["item"].id: row["label"] for row in cyclotron.labels()}
