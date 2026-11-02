from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.reference_links import NO_SCORE_SORT_VALUE, OPEN_SUGGESTION_KEY, decide, link_concept, link_references, open_suggestion_fields, reference_link_relation_id  # noqa: E402

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
        if index_name == "semanticRelationsByNewsroomFeedWithOpenSuggestionFields":
            return [row for row in self.tables["SemanticRelation"].values() if row.get("newsroomFeedKey") == key_value]
        field = {"semanticRelationsBySubjectState": "subjectStateKey", "semanticRelationsByObjectState": "objectStateKey"}[index_name]
        return [row for row in self.tables["SemanticRelation"].values() if row[field] == key_value]

    def open_suggestion_index(self):
        """What the sparse suggestion index holds, most likely first: rows with a key, by their sort value, highest first."""
        rows = [row for row in self.tables["SemanticRelation"].values() if row.get("openSuggestionKey") is not None]
        return sorted(rows, key=lambda row: row["openSuggestionScore"], reverse=True)

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


class SuggestionIndexTests(unittest.TestCase):
    def test_a_suggestion_is_in_the_index_at_its_close_match_and_an_unscored_one_is_last(self):
        client = FakeClient()
        link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.7, now=NOW)
        link_references(client, "reference-a", "reference-c", "related_to", "suggested", actor="auto:vector", score=None, now=NOW)
        link_concept(client, "reference-b", NODE, "suggested", actor="auto:vector", score=0.9, now=NOW)
        order = client.open_suggestion_index()
        self.assertEqual([row["openSuggestionScore"] for row in order], [0.9, 0.7, NO_SCORE_SORT_VALUE])
        self.assertEqual({row["openSuggestionKey"] for row in order}, {OPEN_SUGGESTION_KEY})
        self.assertEqual(order[-1]["objectLineageId"], "reference-c")

    def test_a_score_that_is_not_a_number_sorts_last(self):
        for score in (None, float("nan"), float("inf"), True, "0.8"):
            self.assertEqual(open_suggestion_fields("suggested", score)["openSuggestionScore"], NO_SCORE_SORT_VALUE, repr(score))
        self.assertEqual(open_suggestion_fields("suggested", 0)["openSuggestionScore"], 0.0)
        self.assertEqual(open_suggestion_fields("suggested", -0.25)["openSuggestionScore"], -0.25)

    def test_a_row_that_is_not_a_suggestion_has_no_key(self):
        for state in ("current", "rejected"):
            self.assertEqual(open_suggestion_fields(state, 0.9), {"openSuggestionKey": None, "openSuggestionScore": None})

    def test_a_new_link_a_person_makes_carries_no_index_fields(self):
        client = FakeClient()
        row = client.tables["SemanticRelation"][link_references(client, "reference-a", "reference-b", "related_to", "human", actor="sub-1", now=NOW)["relationId"]]
        self.assertNotIn("openSuggestionKey", row)

    def test_deciding_takes_a_suggestion_out_of_the_index_at_once(self):
        for decision in ("accepted", "rejected"):
            with self.subTest(decision):
                client = FakeClient()
                result = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.8, now=NOW)
                self.assertEqual(len(client.open_suggestion_index()), 1)
                decide(client, result["relationId"], decision, None, None, "sub-1", now=LATER)
                self.assertEqual(client.open_suggestion_index(), [])

    def test_a_link_a_person_writes_over_a_suggestion_takes_it_out(self):
        client = FakeClient()
        link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.8, now=NOW)
        link_references(client, "reference-b", "reference-a", "related_to", "human", actor="sub-1", now=LATER)
        self.assertEqual(client.open_suggestion_index(), [])

    def test_a_later_suggestion_never_overwrites_a_decision_or_returns_it_to_the_index(self):
        client = FakeClient()
        result = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.8, now=NOW)
        decide(client, result["relationId"], "rejected", "off-topic", None, "sub-1", now=LATER)
        again = link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.99, now="2026-11-03T12:00:00Z")
        self.assertEqual(again["outcome"], "kept")
        self.assertEqual(client.open_suggestion_index(), [])
        row = client.tables["SemanticRelation"][result["relationId"]]
        self.assertEqual((row["relationState"], row["score"]), ("rejected", 0.8))

    def test_suggesting_again_moves_an_open_suggestion_to_its_new_place(self):
        client = FakeClient()
        link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.5, now=NOW)
        link_references(client, "reference-a", "reference-c", "related_to", "suggested", actor="auto:vector", score=0.6, now=NOW)
        link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", score=0.95, now=LATER)
        self.assertEqual([row["objectLineageId"] for row in client.open_suggestion_index()], ["reference-b", "reference-c"])


class SharedRowVectorTests(unittest.TestCase):
    """The TypeScript resolvers (scripts/test-reference-links.ts) read the same file and must produce the same rows."""

    def test_the_python_writer_produces_every_row_in_the_shared_vectors(self):
        vectors = json.loads((REPO_ROOT / "scripts" / "fixtures" / "reference-link-row-vectors.json").read_text())
        for case in vectors["cases"]:
            with self.subTest(case["name"]):
                client = FakeClient()
                for step in case["steps"]:
                    if step["op"] == "link":
                        link_references(client, step["a"], step["b"], step["predicate"], "human", actor=step["actor"], note=step.get("note"), now=step["now"])
                    elif step["op"] == "concept":
                        link_concept(client, step["reference"], vectors["node"], "human", actor=step["actor"], now=step["now"])
                    elif step["op"] == "suggest":
                        link_references(client, step["a"], step["b"], "related_to", "suggested", actor="auto:vector", score=step["score"], classifier_id="vector:text-embedding-3-small", now=step["now"])
                    else:
                        predicate, *ends = step["relation"]
                        ends = sorted(ends) if predicate == "related_to" else ends
                        decide(client, reference_link_relation_id(predicate, *ends), step["decision"], step["reasonCode"], step["note"], step["actor"], now=step["now"])
                rows = {key: {**row, "metadata": json.loads(row["metadata"])} for key, row in client.tables["SemanticRelation"].items()}
                self.assertEqual(rows, case["expectedRows"])


if __name__ == "__main__":
    unittest.main()
