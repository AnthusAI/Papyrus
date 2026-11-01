from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.reference_links import decide, link_concept, link_references  # noqa: E402

NOW = "2026-11-01T12:00:00Z"
LATER = "2026-11-02T12:00:00Z"


class FakeClient:
    def __init__(self):
        self.tables = {"Reference": {}, "SemanticRelation": {}}
        for lineage in ("reference-a", "reference-b", "reference-c"):
            self.tables["Reference"][f"{lineage}-v1"] = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current"}

    def get_record(self, model, record_id):
        return self.tables.get(model, {}).get(record_id)

    def upsert(self, model, payload):
        outcome = "updated" if payload["id"] in self.tables[model] else "created"
        self.tables[model][payload["id"]] = dict(payload)
        return outcome

    def update_record(self, model, payload):
        self.tables[model][payload["id"]].update(payload)

    def list_by_index(self, index_name, key_value, *, limit=100):
        if index_name == "referencesByLineageAndVersion":
            return [row for row in self.tables["Reference"].values() if row["lineageId"] == key_value and row["id"] != key_value]
        field = {"semanticRelationsBySubjectState": "subjectStateKey", "semanticRelationsByObjectState": "objectStateKey"}[index_name]
        return [row for row in self.tables["SemanticRelation"].values() if row[field] == key_value]

    def current_edges(self, kind, lineage):
        key = f"{kind}#{lineage}#current"
        return self.list_by_index("semanticRelationsBySubjectState", key) + self.list_by_index("semanticRelationsByObjectState", key)


NODE = {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1}


class ReferenceLinkTests(unittest.TestCase):
    def test_a_second_write_updates_and_never_duplicates(self):
        client = FakeClient()
        first = link_references(client, "reference-a", "reference-b", "related_to", "human", actor="sub-1", now=NOW)
        second = link_references(client, "reference-b", "reference-a", "related_to", "human", actor="sub-2", now=LATER)
        self.assertEqual((first["outcome"], second["outcome"]), ("created", "updated"))
        self.assertEqual(len(client.tables["SemanticRelation"]), 1)
        row = client.tables["SemanticRelation"][first["relationId"]]
        self.assertEqual((row["subjectLineageId"], row["objectLineageId"]), ("reference-a", "reference-b"))
        self.assertEqual(json.loads(row["metadata"])["addedBy"], "sub-1")

    def test_a_directional_predicate_keeps_its_direction(self):
        client = FakeClient()
        result = link_references(client, "reference-b", "reference-a", "cites", "derived", actor="rule", classifier_id="rule:citation-resolution", now=NOW)
        row = client.tables["SemanticRelation"][result["relationId"]]
        self.assertEqual((row["subjectLineageId"], row["relationState"]), ("reference-b", "current"))

    def test_a_suggestion_is_not_returned_by_any_current_query(self):
        client = FakeClient()
        result = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.83, classifier_id="vector:text-embedding-3-small", now=NOW)
        row = client.tables["SemanticRelation"][result["relationId"]]
        self.assertEqual(row["subjectStateKey"], "reference#reference-a#suggested")
        self.assertEqual(client.current_edges("reference", "reference-a"), [])
        self.assertEqual(client.current_edges("reference", "reference-b"), [])
        self.assertEqual(row["classifierId"], "vector:text-embedding-3-small")
        self.assertEqual(json.loads(row["metadata"])["suggestedBy"], "vector:text-embedding-3-small")

    def test_deciding_records_who_and_why_and_moves_the_state_keys(self):
        client = FakeClient()
        result = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", now=NOW)
        decide(client, result["relationId"], "accepted", "same-topic", "good match", "sub-9", now=LATER)
        row = client.tables["SemanticRelation"][result["relationId"]]
        metadata = json.loads(row["metadata"])
        self.assertEqual(row["relationState"], "current")
        self.assertEqual(len(client.current_edges("reference", "reference-a")), 1)
        self.assertEqual((metadata["decidedBy"], metadata["decision"], metadata["reasonCode"], metadata["note"]), ("sub-9", "accepted", "same-topic", "good match"))
        self.assertEqual(metadata["provenance"], "suggested")
        decide(client, result["relationId"], "rejected", "off-topic", None, "sub-9", now=LATER)
        self.assertEqual(client.current_edges("reference", "reference-a"), [])
        self.assertEqual(row["predicateObjectStateKey"], "related_to#reference#reference-b#rejected")

    def test_a_later_suggestion_does_not_override_a_decision(self):
        client = FakeClient()
        result = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", now=NOW)
        decide(client, result["relationId"], "rejected", "off-topic", None, "sub-9", now=NOW)
        again = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", now=LATER)
        self.assertEqual(again["outcome"], "kept")
        self.assertEqual(client.tables["SemanticRelation"][result["relationId"]]["relationState"], "rejected")

    def test_a_concept_tag_is_related_to_from_the_reference_to_the_node(self):
        client = FakeClient()
        result = link_concept(client, "reference-a", NODE, "human", actor="sub-1", now=NOW)
        row = client.tables["SemanticRelation"][result["relationId"]]
        self.assertEqual((row["predicate"], row["subjectKind"], row["objectKind"]), ("related_to", "reference", "semanticNode"))
        self.assertEqual(row["objectStateKey"], "semanticNode#node-voice#current")
        self.assertEqual(json.loads(row["metadata"])["kind"], "reference.concept")
        self.assertEqual(link_concept(client, "reference-a", NODE, "human", actor="sub-1", now=LATER)["outcome"], "updated")
        self.assertEqual(len(client.tables["SemanticRelation"]), 1)

    def test_unknown_inputs_are_refused(self):
        client = FakeClient()
        with self.assertRaises(ValueError):
            link_references(client, "reference-a", "reference-missing", "related_to", "human", actor="x")
        with self.assertRaises(ValueError):
            link_references(client, "reference-a", "reference-b", "mentions", "human", actor="x")
        with self.assertRaises(ValueError):
            link_references(client, "reference-a", "reference-a", "related_to", "human", actor="x")


if __name__ == "__main__":
    unittest.main()
