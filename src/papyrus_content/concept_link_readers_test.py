"""An editor's link between two concepts, with the words they wrote, is read by every reader of editors' explanations.

The row is the one the Lambda writes (``scripts/fixtures/concept-link-row-vector.json``, asserted byte for byte by ``scripts/test-concept-management.ts``).
Readers: the section context packs (the concept card lists the link and its words), the internal knowledge query (a ``link_explanation`` vector),
the idea signal inputs (``explanation_of``) and the knowledge snapshot (a confirmed relation between two entities). Readers of Reference links
(the Cyclotron's link-fit export, the suggestion cuts) pass it by.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from papyrus_content.ideas.signal_inputs import edges_of, explanation_of
from papyrus_content.knowledge_snapshot.loaders import links_and_relations
from papyrus_content.learning_classifiers import load_link_examples
from papyrus_content.newsroom_context_pack import concept_links
from papyrus_content.suggestion_calibration import decided_suggestions
from papyrus_knowledge_query.vector_index import _link_explanation_text

VECTOR = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "concept-link-row-vector.json").read_text(encoding="utf-8"))
ROW = {**VECTOR["row"], "metadata": json.dumps(VECTOR["row"]["metadata"])}
WORDS = VECTOR["input"]["note"]
FIRST = VECTOR["row"]["objectLineageId"]    # containment
SECOND = VECTOR["row"]["subjectLineageId"]  # confinement-problem


def node(row_id: str, lineage: str, name: str) -> dict:
    return {"id": row_id, "lineageId": lineage, "versionState": "current", "nodeKey": f"editor_concept--{name.lower().replace(' ', '-')}",
            "nodeKind": "editor_concept", "displayName": name, "status": "accepted"}


NODES = [node("n1", FIRST, "Containment"), node("n2", SECOND, "Confinement problem")]


class Store:
    def __init__(self, rows):
        self.rows = rows

    def safe_list_records(self, model):
        return NODES

    def list_semantic_relations_by_subject_state(self, key):
        return [row for row in self.rows if row["subjectStateKey"] == key]

    def list_semantic_relations_by_object_state(self, key):
        return [row for row in self.rows if row["objectStateKey"] == key]


def situation(rows):
    from papyrus_content.section_concepts import current_concept_nodes, nodes_by_lineage

    store = Store(rows)
    return SimpleNamespace(store=store, concept_nodes=lambda: nodes_by_lineage(current_concept_nodes(store)))


def test_the_section_context_pack_lists_the_link_from_either_concept_with_its_words():
    for lineage, other in ((FIRST, "Confinement problem"), (SECOND, "Containment")):
        links = concept_links(situation([ROW]), lineage)
        assert [(link["name"], link["predicate"], link["person"], link["note"]) for link in links] == [(other, "related_to", True, WORDS)]


def test_the_internal_knowledge_query_indexes_the_words():
    assert _link_explanation_text(ROW) == WORDS


def test_the_idea_signal_inputs_read_the_words_but_not_as_a_link_between_references():
    assert explanation_of(ROW) == WORDS
    assert edges_of([ROW]) == []


def test_the_knowledge_snapshot_reads_a_confirmed_relation_between_the_two_entities():
    links, relations = links_and_relations([ROW])
    assert links == [] and len(relations) == 1
    assert (relations[0].subject_lineage_id, relations[0].object_lineage_id, relations[0].confirmed, relations[0].provenance) == (SECOND, FIRST, True, "human")
    assert relations[0].evidence is None   # the words are an internal note: they are not copied onto the public snapshot


def test_the_link_stays_out_of_the_cyclotron_link_examples_and_the_suggestion_cuts():
    assert decided_suggestions([ROW]) == {"reference": [], "concept": []}
    client = SimpleNamespace(list_by_index=lambda index, key: [ROW], list_records=lambda model: [])
    assert load_link_examples(client, "corpus-1") == []


def test_a_rejected_link_has_no_words_for_any_reader():
    rejected = {**ROW, "relationState": "rejected", "metadata": json.dumps({**json.loads(ROW["metadata"]), "decision": "rejected"})}
    assert _link_explanation_text(rejected) == ""
    assert concept_links(situation([rejected]), FIRST) == []


def test_the_row_says_it_was_made_through_the_cli():
    metadata = json.loads(ROW["metadata"])
    assert (metadata["addedVia"], metadata["decidedVia"], metadata["kind"], metadata["confirmed"]) == ("cli", "cli", "concept.link", True)
