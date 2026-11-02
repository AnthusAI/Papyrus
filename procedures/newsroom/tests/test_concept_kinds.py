"""Which nodes are concepts (src/papyrus_knowledge_query/concept_kinds.py) and the cleanup of suggestions to the ones that are not (src/papyrus_content/junk_suggestions.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from papyrus_content.junk_suggestions import find_junk_suggestions, retire_junk_suggestions  # noqa: E402
from papyrus_content.knowledge_wiki.kinds import INTERNAL_KINDS, OPT_IN_KINDS  # noqa: E402
from papyrus_knowledge_query.concept_kinds import NON_CONCEPT_KINDS, is_concept, kind_token  # noqa: E402


def test_the_bookkeeping_and_author_kinds_are_the_ones_the_public_wiki_already_leaves_out_plus_bulk_extractions():
    wiki = {kind_token(kind) for kind in (*INTERNAL_KINDS, *OPT_IN_KINDS)}
    assert wiki <= NON_CONCEPT_KINDS and NON_CONCEPT_KINDS - wiki == {"entity", "identifier"}


def test_real_vocabulary_kinds_are_concepts_and_authors_and_bookkeeping_are_not():
    for kind in ("task", "topic", "product", "model", "model-family", "model_family", "technique", "concept", "licence"):
        assert is_concept(kind, f"{kind}--x"), kind
    for kind, key in (("personAuthor", "author.name.x"), ("coverageQuestion", "coverage.ai"), ("commentConcept", "comment.general"), ("qualityRating", "quality.rating.4_star"),
                      ("relevanceDecision", "relevance.include"), ("editorialForm", "editorial.form.reporting"), ("entity", "ner-entities:x"), ("identifier", "arxiv:2104.08691")):
        assert not is_concept(kind, key), kind
    assert not is_concept(None, "coverage-ai") and is_concept(None, "topic--x")   # no kind: the key's prefix decides


def test_an_allowlist_names_the_only_kinds():
    assert is_concept("task", "task--x", ["task", "topic"]) and not is_concept("model", "model--x", ["task", "topic"])


class Client:
    def __init__(self, rows, nodes):
        self.rows, self.nodes, self.updates = rows, nodes, []

    def list_by_index(self, index, key):
        return self.rows

    def get_record(self, model, record_id):
        return self.rows_by_id.get(record_id) if model == "SemanticRelation" else self.nodes.get(record_id)

    @property
    def rows_by_id(self):
        return {row["id"]: row for row in self.rows}

    def update_record(self, model, record):
        self.updates.append(record)


def suggestion(number, node, **changes):
    return {"id": f"rel-{number}", "relationState": "suggested", "objectKind": "semanticNode", "objectLineageId": node, "subjectKind": "reference", "subjectLineageId": "ref",
            "predicate": "related_to", "score": 0.357, "classifierId": "vector:text-embedding-3-small", "metadata": json.dumps({"suggestedBy": "vector:text-embedding-3-small", "provenance": "suggested"}), **changes}


def world():
    nodes = {"n-author": {"nodeKind": "personAuthor", "nodeKey": "author.name.x"}, "n-cover": {"nodeKind": "coverageQuestion", "nodeKey": "coverage.ai"}, "n-task": {"nodeKind": "task", "nodeKey": "task--translation"}}
    rows = [suggestion(1, "n-author"), suggestion(2, "n-cover"), suggestion(3, "n-task"), suggestion(4, "n-author", relationState="current"), suggestion(5, "n-author", objectKind="reference")]
    return Client(rows, nodes)


def test_a_dry_run_lists_the_open_vector_suggestions_to_junk_nodes_and_writes_nothing():
    client = world()
    result = retire_junk_suggestions(client)
    assert result["executed"] is False and result["suggestions"] == 2 and result["byKind"] == {"personAuthor": 1, "coverageQuestion": 1}
    assert [row["relationId"] for row in find_junk_suggestions(client)] == ["rel-1", "rel-2"] and client.updates == []


def test_execute_marks_them_rejected_by_the_cleanup_and_deletes_nothing():
    client = world()
    retire_junk_suggestions(client, execute=True, now="2026-11-02T12:00:00Z")
    assert [(u["id"], u["relationState"]) for u in client.updates] == [("rel-1", "rejected"), ("rel-2", "rejected")]
    metadata = json.loads(client.updates[0]["metadata"])
    assert metadata["decidedBy"] == "auto:cleanup" and metadata["reasonCode"] == "not_a_concept" and metadata["decision"] == "rejected"
