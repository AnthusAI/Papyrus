"""`papyrus relations migrate-concept-tags`: legacy ``related_to`` concept tags become ``tagged_with`` and the old rows are retired, never deleted."""

from __future__ import annotations

import json

from papyrus_content.concept_tag_migration import find_legacy_tags, migrate_concept_tags, target_id_of
from papyrus_content.concept_tags import audit_reference_links, audit_story_links
from papyrus_content.projection.site_relations import read_site_relations
from papyrus_content.reference_links import link_concept, link_item_concept, link_references, decide, reference_link_relation_id
from papyrus_content.relations_commands import relations_migrate_concept_tags

NOW = "2026-11-10T09:00:00Z"
EARLIER = "2026-10-01T09:00:00Z"
NODE = {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1, "versionState": "current", "nodeKey": "editor_concept--voice", "status": "accepted", "nodeKind": "editor_concept"}
OTHER = {"id": "node-cloning-v1", "lineageId": "node-cloning", "versionNumber": 1, "versionState": "current", "nodeKey": "editor_concept--cloning", "status": "accepted", "nodeKind": "editor_concept"}
NODES = [NODE, OTHER]
STORY = {"id": "story-1-v1", "lineageId": "story-1", "versionNumber": 1}


class FakeClient:
    """Tables in memory, with the indexes the migration, the writers and the audits read."""

    def __init__(self):
        self.tables = {"Reference": {}, "SemanticRelation": {}, "Item": {"story-1-v1": dict(STORY, versionState="current", title="Story")}}
        for lineage in ("reference-a", "reference-b", "reference-c"):
            self.tables["Reference"][f"{lineage}-v1"] = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "corpusId": "knowledge-corpus-demo"}
        self.tables["Reference"]["reference-c-v1"]["corpusId"] = "knowledge-corpus-other"
        self.writes: list[tuple[str, str]] = []

    def get_record(self, model, record_id):
        return self.tables.get(model, {}).get(record_id)

    def get_records_by_id(self, model, ids):
        return {record_id: self.tables[model][record_id] for record_id in ids if record_id in self.tables.get(model, {})}

    def upsert(self, model, payload):
        outcome = "updated" if payload["id"] in self.tables[model] else "created"
        self.tables[model][payload["id"]] = dict(payload)
        self.writes.append(("upsert", payload["id"]))
        return outcome

    def update_record(self, model, payload):
        self.tables[model][payload["id"]].update(payload)
        self.writes.append(("update", payload["id"]))

    def list_by_index(self, index_name, key_value, *, limit=100):
        if index_name == "referencesByLineageAndVersion":
            return [row for row in self.tables["Reference"].values() if row["lineageId"] == key_value and row["id"] != key_value]
        field = {"semanticRelationsBySubjectState": "subjectStateKey", "semanticRelationsByObjectState": "objectStateKey"}[index_name]
        return [row for row in self.tables["SemanticRelation"].values() if row[field] == key_value]

    def safe_list_records(self, model):
        return NODES if model == "SemanticNode" else list(self.tables[model].values())

    def list_semantic_relations_by_subject_state(self, key):
        return self.list_by_index("semanticRelationsBySubjectState", key)

    def list_semantic_relations_by_object_state(self, key):
        return self.list_by_index("semanticRelationsByObjectState", key)


def legacy(client, reference="reference-a", node=NODE, provenance="human", note=None, **extra):
    return link_concept(client, reference, node, provenance, actor="editor-1", note=note, now=EARLIER, predicate="related_to", **extra)


def seeded():
    """A legacy current human tag with words, a legacy suggestion, a legacy rejection, a story tag, and the generic links that must not move."""
    client = FakeClient()
    current = legacy(client, "reference-a", NODE, "human", note="Voice cloning is the subject.")["relationId"]
    suggested = legacy(client, "reference-b", NODE, "suggested", score=0.81, classifier_id="vector:text-embedding-3-small")["relationId"]
    rejected = legacy(client, "reference-b", OTHER, "human")["relationId"]
    decide(client, rejected, "rejected", "off-topic", "Not about cloning.", "editor-2", now=EARLIER)
    story = link_item_concept(client, "story-1", NODE, "derived", actor="auto:pack", story=STORY, predicate="related_to")["relationId"]
    link_references(client, "reference-a", "reference-b", "related_to", "human", actor="editor-1", now=EARLIER)
    concept_pair = {"id": "concept-link-1", "relationState": "current", "predicate": "related_to", "subjectKind": "semanticNode", "subjectId": "node-voice-v1", "subjectLineageId": "node-voice",
                    "objectKind": "semanticNode", "objectId": "node-cloning-v1", "objectLineageId": "node-cloning", "subjectStateKey": "semanticNode#node-voice#current",
                    "objectStateKey": "semanticNode#node-cloning#current", "metadata": "{}"}
    client.tables["SemanticRelation"]["concept-link-1"] = concept_pair
    client.writes.clear()
    return client, {"current": current, "suggested": suggested, "rejected": rejected, "story": story}


def snapshot(client):
    return json.dumps(client.tables, sort_keys=True)


def test_a_dry_run_writes_nothing_and_counts_by_kind_state_and_provenance():
    client, ids = seeded()
    before = snapshot(client)
    report = migrate_concept_tags(client, NODES, apply=False, now=NOW)
    assert client.writes == [] and snapshot(client) == before
    assert report["found"] == 4 and report["apply"] is False and report["actions"] == {"migrate": 4}
    counts = {(row["subjectKind"], row["state"], row["provenance"]): row["count"] for row in report["counts"]}
    assert counts == {("reference", "current", "human"): 1, ("reference", "suggested", "suggested"): 1, ("reference", "rejected", "human"): 1, ("item", "current", "derived"): 1}
    assert {entry["legacyId"] for entry in report["sample"]} == set(ids.values())


def test_apply_writes_tagged_with_first_then_retires_the_legacy_row_and_deletes_nothing():
    client, ids = seeded()
    report = migrate_concept_tags(client, NODES, apply=True, now=NOW)
    assert report["written"] == 4 and report["retired"] == 4 and report["error"] is None
    kinds = [kind for kind, _ in client.writes]
    assert kinds == ["upsert", "update"] * 4          # each tag is written before its legacy row is retired
    for state, legacy_id in ids.items():
        old = client.tables["SemanticRelation"][legacy_id]
        new = client.tables["SemanticRelation"][target_id_of(old)]
        assert new["predicate"] == "tagged_with" and new["relationTypeKey"] == "tagged_with" and new["id"].startswith("reference-link-tagged_with-")
        assert new["id"] != old["id"]
        # the same ends, state and the whole metadata, plus where it came from
        for field in ("subjectKind", "subjectLineageId", "objectKind", "objectLineageId", "score", "confidence", "classifierId"):
            assert new.get(field) == old.get(field), field
        wanted_state = {"story": "current"}.get(state, state)
        assert new["relationState"] == wanted_state
        assert new["subjectStateKey"] == f"{old['subjectKind']}#{old['subjectLineageId']}#{wanted_state}"
        assert new["predicateObjectStateKey"] == f"tagged_with#semanticNode#{old['objectLineageId']}#{wanted_state}"
        new_meta, old_meta = json.loads(new["metadata"]), json.loads(old["metadata"])
        assert new_meta.pop("migratedFromRelationId") == legacy_id
        assert new_meta.pop("kind") == ("item.concept" if old["subjectKind"] == "item" else "reference.concept") and old_meta.pop("kind") == new_meta_kind(old)
        assert new_meta == {key: value for key, value in old_meta.items() if not key.startswith("superseded")}, state
        # the legacy row is out of every reader's view and says where it went
        assert old["relationState"] == "superseded" and old["subjectStateKey"] == f"{old['subjectKind']}#{old['subjectLineageId']}#superseded"
        assert old["objectStateKey"].endswith("#superseded") and old["predicateObjectStateKey"] == f"related_to#semanticNode#{old['objectLineageId']}#superseded"
        old_after = json.loads(old["metadata"])
        assert old_after["supersededBy"] == new["id"] and old_after["supersededAt"] == NOW
    assert len([key for key in client.tables["SemanticRelation"] if key.startswith("reference-link-related_to-")]) == 5   # four retired + the Reference pair, none deleted


def new_meta_kind(old):
    return "item.concept" if old["subjectKind"] == "item" else "reference.concept"


def test_a_rejected_legacy_tag_becomes_a_rejected_tagged_with_row_that_no_writer_revives():
    client, ids = seeded()
    migrate_concept_tags(client, NODES, apply=True, now=NOW)
    new = client.tables["SemanticRelation"][reference_link_relation_id("tagged_with", "reference-b", "node-cloning")]
    meta = json.loads(new["metadata"])
    assert new["relationState"] == "rejected" and meta["decision"] == "rejected" and meta["decidedBy"] == "editor-2" and meta["reasonCode"] == "off-topic" and meta["note"] == "Not about cloning."
    for provenance in ("human", "suggested", "derived"):
        done = link_concept(client, "reference-b", OTHER, provenance, actor="editor-3", now=NOW)
        assert done["outcome"] in ("rejected", "kept") and done["relationState"] == "rejected"
    assert client.tables["SemanticRelation"][new["id"]]["relationState"] == "rejected"


def test_running_it_twice_changes_nothing_and_a_pair_already_migrated_is_skipped():
    client, _ = seeded()
    migrate_concept_tags(client, NODES, apply=True, now=NOW)
    after_first = snapshot(client)
    client.writes.clear()
    again = migrate_concept_tags(client, NODES, apply=True, now="2026-11-11T09:00:00Z")
    assert again["found"] == 0 and client.writes == [] and snapshot(client) == after_first


def test_a_run_that_stopped_between_the_two_steps_resumes_by_retiring_only():
    client, ids = seeded()
    old = client.tables["SemanticRelation"][ids["current"]]
    from papyrus_content.concept_tag_migration import tagged_with_record

    client.upsert("SemanticRelation", tagged_with_record(old, now=NOW))      # the first step ran, the second did not
    client.writes.clear()
    report = migrate_concept_tags(client, NODES, apply=True, now=NOW)
    assert report["actions"] == {"migrate": 3, "resume": 1}
    assert ("upsert", target_id_of(old)) not in client.writes and client.tables["SemanticRelation"][ids["current"]]["relationState"] == "superseded"


def test_a_tag_made_after_the_rename_is_kept_and_only_the_legacy_row_is_retired():
    client, ids = seeded()
    old = client.tables["SemanticRelation"][ids["current"]]
    made = link_concept(client, "reference-a", NODE, "human", actor="editor-9", note="Written after the rename", now=NOW)
    before = json.dumps(client.tables["SemanticRelation"][made["relationId"]], sort_keys=True)
    report = migrate_concept_tags(client, NODES, apply=True, now=NOW)
    assert report["actions"] == {"migrate": 3, "retire-only": 1}
    assert json.dumps(client.tables["SemanticRelation"][made["relationId"]], sort_keys=True) == before
    assert client.tables["SemanticRelation"][old["id"]]["relationState"] == "superseded"


def test_concept_to_concept_and_reference_to_reference_related_to_are_untouched():
    client, _ = seeded()
    pair = reference_link_relation_id("related_to", "reference-a", "reference-b")
    before = {"concept-link-1": dict(client.tables["SemanticRelation"]["concept-link-1"]), pair: dict(client.tables["SemanticRelation"][pair])}
    report = migrate_concept_tags(client, NODES, apply=True, now=NOW)
    assert all(entry["subjectKind"] in ("item", "reference") and entry["legacyId"] != pair for entry in report["edges"])
    for key, row in before.items():
        assert client.tables["SemanticRelation"][key] == row


def test_limit_takes_at_most_that_many_edges_and_the_next_run_goes_on():
    client, _ = seeded()
    first = migrate_concept_tags(client, NODES, apply=True, limit=3, now=NOW)
    assert first["found"] == 3 and first["retired"] == 3
    second = migrate_concept_tags(client, NODES, apply=True, limit=3, now=NOW)
    assert second["found"] == 1 and second["retired"] == 1
    assert find_legacy_tags(client, NODES) == []


def test_a_corpus_filter_keeps_stories_and_the_References_of_that_corpus_only():
    client, _ = seeded()
    legacy(client, "reference-c", NODE)
    report = migrate_concept_tags(client, NODES, apply=False, corpus_ids={"knowledge-corpus-demo"}, now=NOW)
    assert report["found"] == 4 and "reference-c" not in {entry["subjectLineageId"] for entry in report["edges"]}


def test_a_failed_write_stops_the_run_and_the_report_says_how_far_it_got():
    client, _ = seeded()
    real = client.update_record
    calls = {"count": 0}

    def flaky(model, payload):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("throttled")
        real(model, payload)

    client.update_record = flaky
    report = migrate_concept_tags(client, NODES, apply=True, now=NOW)
    assert report["retired"] == 1 and "throttled" in report["error"]
    client.update_record = real
    assert migrate_concept_tags(client, NODES, apply=True, now=NOW)["error"] is None
    assert find_legacy_tags(client, NODES) == []


def test_readers_see_the_same_concepts_before_and_after():
    from papyrus_newsroom.coverage_theme import _concept_report_context

    client, _ = seeded()
    # a published story page: the concepts a story is tagged with
    stories = [("item-1", "story-1", "2026-10-01T00:00:00Z")]
    pages = {"voice", "cloning"}
    node_rows = {"node-voice-v1": dict(NODE, nodeKey="editor_concept--voice")}
    client.get_many = lambda model, ids: {i: node_rows[i] for i in ids if i in node_rows}   # the concept rows the page read fetches

    def page_concepts():
        found = read_site_relations(client, stories, pages)
        return dict(found.concepts)

    def report():
        refs = [{"id": f"{n}-v1", "lineageId": n, "versionState": "current", "curationStatus": "accepted"} for n in ("reference-a", "reference-b")]
        nodes = [{"id": "node-voice-v1", "lineageId": "node-voice", "versionState": "current", "nodeKind": "topic", "displayName": "Voice"}]
        relations = list(client.tables["SemanticRelation"].values())    # includes the retired rows: they must not count twice
        context = _concept_report_context(references=refs, semantic_nodes=nodes, semantic_relations=relations, corpus_key="", node_kinds=[], now=NOW)
        # the mention rows carry the relation's own id, the one thing the migration changes: compare what each concept is mentioned by
        return json.dumps({concept: sorted((m["referenceLineageId"], m["weight"]) for m in mentions) for concept, mentions in context["mentionsByConcept"].items()}, sort_keys=True)

    from papyrus_content.ontology_enrichment import rank_concepts

    def ranked():
        relations = list(client.tables["SemanticRelation"].values())
        return json.dumps(rank_concepts({"models": {"SemanticNode": NODES, "SemanticRelation": relations}}, include_profile_status=False), sort_keys=True, default=str)

    before = (page_concepts(), report(), ranked())
    migrate_concept_tags(client, NODES, apply=True, now=NOW)
    after = (page_concepts(), report(), ranked())
    assert before[1] != "{}" and before[0] == after[0]
    assert after == before


def test_check_links_reports_legacy_rows_and_not_the_superseded_ones():
    client, _ = seeded()
    client.tables["SemanticNode"] = {n["id"]: n for n in NODES}
    client.list_by_index_real = client.list_by_index

    def list_by_index(index_name, key_value, *, limit=100):
        if index_name == "publishedItemsByTypeStatus":
            return []
        return client.list_by_index_real(index_name, key_value)

    client.list_by_index = list_by_index
    client.get_records_by_id_real = client.get_records_by_id
    before = [f for f in audit_reference_links(client, ["reference-a", "reference-b"]) if f["problem"] == "legacy: migrate"]
    assert len(before) == 3
    migrate_concept_tags(client, NODES, apply=True, now=NOW)
    after = audit_reference_links(client, ["reference-a", "reference-b"])
    assert [f for f in after if f["problem"] == "legacy: migrate"] == []
    assert all(f["state"] != "superseded" for f in after)
    stories_after = audit_story_links(client, ["story-1"])
    assert [f for f in stories_after if f["problem"] == "legacy: migrate"] == [] and all(f["state"] != "superseded" for f in stories_after)


def test_the_command_is_a_dry_run_unless_apply_and_writes_a_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    client, _ = seeded()
    before = snapshot(client)
    relations_migrate_concept_tags([], client=client)
    out = capsys.readouterr().out
    assert "dry run (nothing written" in out and "legacy related_to tags found\t4" in out and "action\tmigrate\t4" in out
    assert snapshot(client) == before
    reports = list((tmp_path / ".papyrus-runs").glob("concept-tag-migration-*/migration-report.json"))
    assert len(reports) == 1 and json.loads(reports[0].read_text())["found"] == 4
    relations_migrate_concept_tags(["--apply"], client=client)
    assert "retired\t4" in capsys.readouterr().out
    import pytest

    with pytest.raises(ValueError, match="--apply writes"):
        relations_migrate_concept_tags(["--apply", "--dry-run"], client=client)


def test_legacy_only_prints_the_legacy_tags_and_their_count(capsys):
    from papyrus_content.concept_tags_commands import _print_findings

    findings = [{"owner": "story-1", "relationId": "r1", "predicate": "related_to", "state": "current", "object": "node-voice", "problem": "legacy: migrate", "detail": ""},
                {"owner": "story-1", "relationId": "r2", "predicate": "tagged_with", "state": "current", "object": "node-cloning", "problem": "concept has no public page", "detail": ""}]
    _print_findings("stories", 7, findings, False, "stories", legacy_only=True)
    out = capsys.readouterr().out
    assert "r1" in out and "r2" not in out and "1 legacy related_to tag(s) still to migrate across 7 stories" in out
    _print_findings("stories", 7, findings, True, "stories", legacy_only=True)
    shown = json.loads(capsys.readouterr().out)
    assert shown["legacy"] == 1 and shown["problems"] == 1
