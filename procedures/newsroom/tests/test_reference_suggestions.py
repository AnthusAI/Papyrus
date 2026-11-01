from __future__ import annotations

import math
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.reference_links import decide, link_references  # noqa: E402
from papyrus_content.reference_suggestions import knee_cut_count, suggest_for  # noqa: E402
from papyrus_knowledge_query.vector_index import reference_summary_vector_key  # noqa: E402
from procedures.newsroom.tests.test_reference_links import FakeClient  # noqa: E402

NOW = "2026-11-01T12:00:00Z"


def _unit(angle: float) -> list[float]:
    return [math.cos(angle), math.sin(angle)]


class FakeVectorProvider:
    def __init__(self):
        self.entries: dict[str, dict] = {}
        self.embedding_requests = 0
        self.queries: list[dict] = []

    def add_reference(self, lineage: str, angle: float, status: str = "accepted") -> None:
        self.entries[reference_summary_vector_key(lineage)] = {
            "vector": _unit(angle),
            "metadata": {"vectorKind": "reference_summary", "lineageId": lineage, "curationStatus": status, "corpusId": "corpus-1"},
        }

    def add_concept(self, lineage: str, angle: float) -> None:
        self.entries[f"concept_card-{lineage}"] = {"vector": _unit(angle), "metadata": {"vectorKind": "concept_card", "lineageId": lineage}}

    def get_vector(self, key):
        entry = self.entries.get(key)
        return entry["vector"] if entry else None

    def query_by_vector(self, vector, top_k, metadata_filter):
        self.queries.append(metadata_filter)
        clauses = metadata_filter.get("$and") or [metadata_filter]
        matches = []
        for key, entry in self.entries.items():
            if all(self._matches(entry["metadata"], clause) for clause in clauses):
                cosine = sum(a * b for a, b in zip(vector, entry["vector"]))
                matches.append({"key": key, "distance": 1.0 - cosine, "metadata": entry["metadata"]})
        return sorted(matches, key=lambda match: match["distance"])[:top_k]

    @staticmethod
    def _matches(metadata, clause):
        (field, condition), = clause.items()
        if "$eq" in condition:
            return metadata.get(field) == condition["$eq"]
        return metadata.get(field) in condition["$in"]


def build():
    client = FakeClient()
    provider = FakeVectorProvider()
    provider.add_reference("reference-a", 0.0)
    provider.add_reference("reference-b", 0.1)
    provider.add_reference("reference-c", 1.2)
    provider.add_concept("node-voice", 0.05)
    return client, provider


class KneeCutTests(unittest.TestCase):
    def test_cuts_at_the_largest_gap_in_the_first_half(self):
        self.assertEqual(knee_cut_count([0.91, 0.88, 0.85, 0.52, 0.50, 0.49]), 3)

    def test_a_late_larger_gap_in_the_second_half_is_ignored(self):
        self.assertEqual(knee_cut_count([0.9, 0.8, 0.79, 0.78, 0.77, 0.1]), 1)

    def test_one_or_no_score_is_kept_whole(self):
        self.assertEqual(knee_cut_count([0.9]), 1)
        self.assertEqual(knee_cut_count([]), 0)


class SuggestForTests(unittest.TestCase):
    def test_suggests_neighbours_without_embedding(self):
        client, provider = build()
        result = suggest_for(client, provider, "reference-a", now=NOW)
        self.assertEqual(provider.embedding_requests, 0)
        self.assertEqual([entry["lineageId"] for entry in result["references"]], ["reference-b"])
        rows = list(client.tables["SemanticRelation"].values())
        self.assertEqual({row["relationState"] for row in rows}, {"suggested"})
        self.assertEqual(len(rows), 2)
        self.assertEqual([entry["lineageId"] for entry in result["concepts"]], ["node-voice"])

    def test_own_lineage_is_excluded(self):
        client, provider = build()
        result = suggest_for(client, provider, "reference-a", now=NOW)
        self.assertNotIn("reference-a", [entry["lineageId"] for entry in result["references"]])

    def test_rejected_never_returns(self):
        client, provider = build()
        link_references(client, "reference-a", "reference-b", "related_to", "suggested", actor="auto:vector", now=NOW)
        row_id = next(iter(client.tables["SemanticRelation"]))
        decide(client, row_id, "rejected", "off-topic", None, "editor", now=NOW)
        result = suggest_for(client, provider, "reference-a", now=NOW)
        self.assertNotIn("reference-b", [entry["lineageId"] for entry in result["references"]])
        self.assertEqual(client.tables["SemanticRelation"][row_id]["relationState"], "rejected")

    def test_existing_current_links_are_excluded(self):
        client, provider = build()
        link_references(client, "reference-b", "reference-a", "related_to", "human", actor="editor", now=NOW)
        result = suggest_for(client, provider, "reference-a", now=NOW)
        self.assertNotIn("reference-b", [entry["lineageId"] for entry in result["references"]])

    def test_dry_run_writes_nothing(self):
        client, provider = build()
        result = suggest_for(client, provider, "reference-a", dry_run=True, now=NOW)
        self.assertEqual(client.tables["SemanticRelation"], {})
        self.assertEqual(result["references"][0]["outcome"], "would_write")

    def test_rerun_is_idempotent(self):
        client, provider = build()
        suggest_for(client, provider, "reference-a", now=NOW)
        suggest_for(client, provider, "reference-a", now=NOW)
        self.assertEqual(len(client.tables["SemanticRelation"]), 2)

    def test_a_supplied_cut_replaces_the_knee(self):
        client, provider = build()
        result = suggest_for(client, provider, "reference-a", cut=lambda similarities: len(similarities), now=NOW)
        self.assertEqual({entry["lineageId"] for entry in result["references"]}, {"reference-b", "reference-c"})

    def test_filters_only_accepted_in_the_corpus(self):
        client, provider = build()
        provider.add_reference("reference-d", 0.02, status="pending")
        result = suggest_for(client, provider, "reference-a", corpus_id="corpus-1", now=NOW)
        self.assertNotIn("reference-d", [entry["lineageId"] for entry in result["references"]])

    def test_missing_summary_vector_is_skipped(self):
        client, provider = build()
        provider.entries.pop(reference_summary_vector_key("reference-a"))
        result = suggest_for(client, provider, "reference-a", now=NOW)
        self.assertIsNotNone(result["skipped"])
        self.assertEqual(client.tables["SemanticRelation"], {})


if __name__ == "__main__":
    unittest.main()
