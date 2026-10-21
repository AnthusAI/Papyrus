"""The relevance cyclotron's own corpus and the shadow-run sample, through the sweep (no network, no model)."""
import json
from pathlib import Path
from unittest import mock

import pytest

from features_backend.steps.cyclotron_relevance_sweep_steps import DOCTRINE, LocalBucket, Model, SweepClient, configure
from papyrus_content.relevance_sample import draw_sample, load_manifest, write_manifest
from papyrus_content.relevance_sweep import run_decide_relevance

RESEARCH = "knowledge-corpus-research"
CANONICAL = "knowledge-corpus-example"
NOW = "2026-10-21T10:00:00Z"


def pending(lineage, corpus_id, *, day, reason="reference-import", actor="importer", title=None):
    return {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current",
            "corpusId": corpus_id, "title": title or f"A security paper {lineage}", "sourceUri": f"https://example.org/{lineage}",
            "curationStatus": "pending", "curationStatusKey": f"{corpus_id}#pending", "changeReason": reason,
            "curationStatusUpdatedBy": actor, "importedAt": f"2026-05-{day:02d}T00:00:00Z", "contentHash": lineage}


def context_for(tmp_path, *, relevance_corpus="research"):
    context = type("Context", (), {})()
    context.tmp = str(tmp_path)
    configure(context, tmp_path / "worker")
    context.steering["corpora"].append({"key": "research", "name": "research", "path": None, "s3Prefix": None,
                                        "role": "source", "localClassifiers": [], "canonicalProjection": None})
    if relevance_corpus:
        context.steering["relevanceCyclotron"]["corpusKey"] = relevance_corpus
    return context


def sweep(context, client, tmp_path, model, **options):
    bodies = client.bodies

    def store_body(recording_client, attachment, body):
        recording_client.upsert("ModelAttachment", attachment)
        bodies[attachment["id"]] = body

    with mock.patch("papyrus_content.records.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.assignments.upload_attachment_body", side_effect=store_body), \
            mock.patch("papyrus_content.relevance_sweep.download_attachment_buffer",
                       side_effect=lambda recording_client, attachment: bodies.get(attachment["id"])):
        return run_decide_relevance(client, context.steering, DOCTRINE, worker="worker-a", model=model,
                                    snapshots=LocalBucket(tmp_path / "bucket"), now=lambda: NOW,
                                    extract_url=lambda url: {}, grobid_alive=None, **options)


def written(client):
    return {name: dict(rows) for name, rows in client.tables.items() if rows}


def decided(client):
    return sorted(row["subjectLineageId"] if "subjectLineageId" in row else row["subjectId"]
                  for row in client.tables.get("SemanticRelation", {}).values() if row.get("predicate") == "relevance_decision_is")


def research_rows():
    return [pending(f"res-{index}", RESEARCH, day=1 + index * 4, reason="reference-import" if index % 2 else "other-import",
                    actor="importer" if index % 2 else "scout") for index in range(6)]


def test_the_sweep_decides_the_relevance_corpus_not_the_canonical_one(tmp_path):
    context = context_for(tmp_path)
    client = SweepClient({"Reference": [*research_rows(), pending("canon-1", CANONICAL, day=2)]})
    model = Model()
    dry = sweep(context, client, tmp_path, model, apply=False)
    assert sorted(dry.pending) == sorted(f"res-{index}" for index in range(6))
    assert model.calls == 0 and "SemanticRelation" not in client.tables
    applied = sweep(context, client, tmp_path, model, apply=True)
    assert applied.decided == 6 and model.calls == 6
    assert all("canon-1" not in str(row) for row in client.tables["SemanticRelation"].values())


def test_without_a_relevance_corpus_the_canonical_corpus_is_decided(tmp_path):
    context = context_for(tmp_path, relevance_corpus=None)
    client = SweepClient({"Reference": [*research_rows(), pending("canon-1", CANONICAL, day=2)]})
    assert sweep(context, client, tmp_path, Model(), apply=False).pending == ["canon-1"]


def test_a_dry_run_sample_lists_the_draw_and_changes_nothing(tmp_path):
    context = context_for(tmp_path)
    client = SweepClient({"Reference": research_rows()})
    model = Model()
    before = written(client)
    result = sweep(context, client, tmp_path, model, apply=False, sample_size=4, sample_seed="seed-1")
    assert len(result.pending) == 4 and result.sample["size"] == 4 and result.sample["seed"] == "seed-1"
    assert result.sample["toDecide"] == result.pending
    assert model.calls == 0 and written(client) == before
    again = sweep(context, client, tmp_path, model, apply=False, sample_size=4, sample_seed="seed-1")
    assert again.pending == result.pending


def test_a_sample_is_not_the_oldest_references(tmp_path):
    context = context_for(tmp_path)
    client = SweepClient({"Reference": research_rows()})
    oldest = ["res-0", "res-1", "res-2"]
    result = sweep(context, client, tmp_path, Model(), apply=False, sample_size=3, sample_seed="seed-1")
    assert result.pending != oldest and max(result.pending) > "res-2"


def test_batches_walk_through_the_manifest_and_never_decide_twice(tmp_path):
    context = context_for(tmp_path)
    client = SweepClient({"Reference": research_rows()})
    model = Model()
    manifest = draw_sample([row for row in research_rows()], size=5, seed="seed-1", corpus_id=RESEARCH)
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    batches = []
    for _ in range(4):
        result = sweep(context, client, tmp_path, model, apply=True, max_count=2,
                       sample_manifest=load_manifest(path, RESEARCH))
        batches.append((result.decided, result.sample["alreadyDecided"]))
    assert [count for count, _ in batches] == [2, 2, 1, 0]
    assert batches[1][1] == 2 and batches[3][1] == 5
    assert model.calls == 5
    assert len(decided(client)) == 5


def test_references_an_editor_decided_after_the_draw_are_left_out(tmp_path):
    context = context_for(tmp_path)
    rows = research_rows()
    client = SweepClient({"Reference": rows})
    manifest = draw_sample(rows, size=4, seed="seed-1", corpus_id=RESEARCH)
    edited = manifest["lineageIds"][0]
    row = client.tables["Reference"][f"{edited}-v1"]
    row.update({"curationStatus": "accepted", "curationStatusKey": f"{RESEARCH}#accepted"})
    result = sweep(context, client, tmp_path, Model(), apply=False, sample_manifest=manifest)
    assert edited not in result.pending and result.sample["leftPending"] == 1 and len(result.pending) == 3


def test_decisions_record_the_sample_they_came_from(tmp_path):
    context = context_for(tmp_path)
    client = SweepClient({"Reference": research_rows()})
    result = sweep(context, client, tmp_path, Model(), apply=True, max_count=1, sample_size=3, sample_seed="seed-9")
    relation = next(row for row in client.tables["SemanticRelation"].values() if row.get("predicate") == "relevance_decision_is")
    provenance = json.loads(relation["metadata"])["provenance"]["sample"]
    assert provenance == {key: result.sample[key] for key in ("policy", "seed", "poolFingerprint", "selectionFingerprint")}


def test_a_sample_needs_a_seed_and_exactly_one_source(tmp_path):
    context = context_for(tmp_path)
    client = SweepClient({"Reference": research_rows()})
    with pytest.raises(ValueError, match="seed"):
        sweep(context, client, tmp_path, Model(), apply=False, sample_size=3)
    manifest = draw_sample(research_rows(), size=3, seed="s", corpus_id=RESEARCH)
    with pytest.raises(ValueError, match="not both"):
        sweep(context, client, tmp_path, Model(), apply=False, sample_size=3, sample_seed="s", sample_manifest=manifest)
