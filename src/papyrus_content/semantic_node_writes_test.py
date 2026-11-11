from __future__ import annotations

import re
from pathlib import Path

from papyrus_content.analysis_graph import build_generated_graph_supersession_changes, build_graph_export_import_records
from papyrus_content.knowledge_snapshot.publish_run import new_node_row
from papyrus_content.ontology_enrichment import build_concept_authority_changes
from papyrus_content.semantic_node_writes import (
    DERIVED_FIELDS,
    IDENTITY_FIELDS,
    acceptance_patch,
    create_only_record,
    derived_fields_patch,
    is_identity_field,
)

NOW = "2026-11-03T00:00:00Z"
PACKAGE = Path(__file__).resolve().parent

ALLOWED_NODE_WRITERS = {
    "semantic_node_writes.py",
    "knowledge_snapshot/entity_review.py",
    "knowledge_snapshot/entity_retype.py",
    "knowledge_snapshot/entity_merge.py",
    "knowledge_snapshot/entity_add.py",
    "rehydration_commands.py",
    "newsroom_commands.py",
    "site_sweep.py",
    "relevance_decisions.py",
    "graphql_authoring.py",
    "analysis_profiles.py",
}


def an_edited_node(status="accepted"):
    row = new_node_row("concept", "Voice Cloning", status, import_run_id="run", corpus_id="c", now=NOW, reason="seed")
    row["displayName"] = "Voice cloning (edited)"
    row["description"] = "Written by a person."
    row["aliases"] = ["vc", "Voice Cloning"]
    return row


def graph_payload(*labels):
    return {
        "snapshot": {"snapshot_id": "s1", "extractor_id": "x"},
        "nodes": [{"node_id": f"n{index}", "node_type": "concept", "label": label} for index, label in enumerate(labels)],
        "edges": [],
    }


def build(payload, existing=()):
    return build_graph_export_import_records(
        payload, corpus_id="c", classifier_id=None, imported_at=NOW, reference_by_external_item_id={}, existing_nodes=list(existing)
    )


def node_records(plan):
    return [record for record in plan["records"] if record["modelName"] == "SemanticNode"]


def test_identity_is_everything_that_is_not_derived():
    assert not (IDENTITY_FIELDS & DERIVED_FIELDS)
    assert all(is_identity_field(name) for name in IDENTITY_FIELDS | {"changeReason", "versionState"})


def test_a_derived_patch_names_only_derived_fields_and_nothing_when_they_match():
    node = an_edited_node()
    wanted = {"authorityScore": 0.5, "relationCount": 3, "displayName": "Machine name", "status": "rejected"}
    patch = derived_fields_patch(node, wanted, now=NOW)
    assert patch == {"id": node["id"], "authorityScore": 0.5, "relationCount": 3, "updatedAt": NOW}
    assert derived_fields_patch({**node, "authorityScore": 0.5, "relationCount": 3}, wanted, now=NOW) is None


def test_the_acceptance_exception_applies_only_from_generated():
    assert acceptance_patch(an_edited_node("generated"), reason="r", now=NOW)["expected"]["status"] == "accepted"
    assert acceptance_patch(an_edited_node("rejected"), reason="r", now=NOW) is None
    assert acceptance_patch(an_edited_node("accepted"), reason="r", now=NOW) is None


def test_the_authority_changes_are_partial_updates_of_the_derived_numbers():
    node = an_edited_node()
    state = {"models": {"SemanticNode": [node]}}
    ranked = [{"id": node["id"], "score": 0.25, "authorityRank": 1, "acceptedReferenceMentions": 2, "distinctSourceKinds": 1, "relationCount": 4}]
    changes = build_concept_authority_changes(state, ranked, now=NOW)
    assert len(changes) == 1 and changes[0]["action"] == "update"
    assert set(changes[0]["expected"]) <= DERIVED_FIELDS | {"id"}


def test_an_import_reuses_an_existing_node_by_name_or_alias_and_creates_no_node():
    existing = an_edited_node()
    plan = build(graph_payload("voice cloning", "VC"), [existing])
    assert node_records(plan) == [] and plan["semanticNodeCount"] == 2


def test_an_import_creates_an_unknown_concept_once_and_two_imports_make_one_node():
    first = node_records(build(graph_payload("Brand New Idea", "brand  new idea")))
    second = node_records(build(graph_payload("Brand New Idea")))
    assert len(first) == 1 and first[0]["createOnly"] is True
    assert first[0]["expected"]["id"] == second[0]["expected"]["id"]


def test_a_rejected_concept_is_not_revived_or_linked():
    rejected = an_edited_node("rejected")
    plan = build(graph_payload("Voice cloning (edited)"), [rejected])
    assert node_records(plan) == [] and plan["semanticNodeCount"] == 0 and plan["skippedRejectedNodes"] == 1


class NoNodeClient:
    def list_knowledge_import_runs_by_corpus_kind_and_imported_at(self, key):
        return [{"id": "knowledge-import-c-graph-x-old"}]

    def list_semantic_nodes_by_import_run_and_node_key(self, run_id):
        raise AssertionError("an import never reads nodes to supersede them")

    def list_semantic_relations_by_import_run_and_imported_at(self, run_id):
        return []


def test_earlier_imports_do_not_supersede_nodes():
    assert build_generated_graph_supersession_changes(NoNodeClient(), corpus_id="c", extractor_id="x", import_run_id="new", now=NOW) == []


def test_only_the_allowed_modules_write_a_node_that_is_not_create_only():
    pattern = re.compile(r'"modelName":\s*"SemanticNode"[^\n]*|\brecord\(\s*"SemanticNode"[^\n]*')
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).as_posix()
        if path.name.endswith("_test.py") or relative in ALLOWED_NODE_WRITERS:
            continue
        for match in pattern.finditer(path.read_text()):
            if "createOnly" not in match.group(0):
                offenders.append(f"{relative}: {match.group(0).strip()}")
    assert offenders == []
