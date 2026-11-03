"""The pieces of the variations an idea run offers (ideas/variations.py, ideas/connections.py; features_backend/idea-variations.feature has the run)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.ideas import connections as rules, variations  # noqa: E402
from papyrus_content.ideas.connections import ConceptOption, Neighbour, StoryOption, build_connections, concept_options, story_options, with_options  # noqa: E402
from papyrus_content.ideas.signal_queue import ConceptInfo  # noqa: E402

NEAR = Neighbour("reference-near", "A tool that checks quotations", "https://near.example", None, "Checks quotations against archives.", "confirmed", None)
CONCEPT = ConceptOption("concept-audits", "source audits", "#source-audits", "Audits where a claim came from.", True, "Both start from the source.")
STORY = StoryOption("item-archives", "How archives keep quotations honest", "Quotations and archives.", "draft", "Rests on A tool that checks quotations")


def extended():
    base = build_connections("Claim checking matters.", [], [NEAR])
    return with_options(base, [STORY], [CONCEPT])


def test_the_other_ways_get_their_own_handles_after_the_ones_the_idea_writer_sees():
    connections = extended()
    assert [(entry.handle, entry.kind) for entry in connections.entries] == [("E1", "acceptReason"), ("R1", "neighbour"), ("S1", "story"), ("C1", "concept")]
    story = connections.by_handle()["S1"]
    assert story.row == {"handle": "S1", "kind": "story", "title": STORY.title, "deck": STORY.deck, "stage": "draft", "link": STORY.via}
    concept = connections.by_handle()["C1"].row
    assert concept["hashtag"] == "#source-audits" and concept["editorsExplanation"] == {"writtenBy": "editor", "text": "Both start from the source."}
    assert rules.is_connection("S1") and rules.is_connection("C12") and not rules.is_connection("Z1")


def test_the_idea_writer_is_never_shown_a_story_or_a_concept():
    plain = build_connections("Claim checking matters.", [], [NEAR])
    assert {entry.kind for entry in plain.entries} == {"acceptReason", "neighbour"}


def test_options_are_every_connection_the_idea_does_not_already_rest_on():
    connections = extended()
    assert [entry.handle for entry in variations.options_for(connections, ["I1", "E1"])] == ["R1", "S1", "C1"]
    assert [entry.handle for entry in variations.options_for(connections, ["I1", "R1"])] == ["S1", "C1"]
    assert variations.options_for(build_connections("Reason.", [], []), ["E1"]) == []


def test_a_connection_is_kept_as_kind_id_title_and_how():
    rows = {entry.handle: variations.connection_row(entry) for entry in extended().entries if variations.kind_of(entry)}
    assert rows["R1"] == {"kind": "reference", "id": "reference-near", "title": NEAR.title, "how": "Linked by an editor"}
    assert rows["S1"] == {"kind": "story", "id": "item-archives", "title": STORY.title, "how": STORY.via}
    assert rows["C1"] == {"kind": "concept", "id": "concept-audits", "title": "#source-audits", "how": "Tagged by an editor"}


def test_a_story_or_a_concept_grounds_no_number_and_a_sentence_must_share_a_word_with_it():
    connections = extended()
    ids, views = rules.citation_views(connections)
    assert views[ids["S1"]] == (set(), set()) and views[ids["C1"]] == (set(), set())
    entry = lambda role, text, *handles: {"where": role, "role": role, "text": text, "handles": list(handles)}  # noqa: E731
    unrelated = [entry("dek", "A toaster is on sale.", "C1"), entry("body", "A toaster is on sale.", "I1", "C1")]
    assert [p["reason"] for p in rules.standard_problems(unrelated, connections, page_readable=True)] == ["connection_ungrounded"]
    related = [entry("dek", "Source audits trace a claim to where it came from.", "C1"), entry("body", "Source audits trace a claim to where it came from.", "I1", "C1")]
    assert rules.standard_problems(related, connections, page_readable=True) == []


class Backend:
    def __init__(self, subject=(), incoming=None, stories=None):
        self.subject, self.incoming, self.stories = list(subject), incoming or {}, stories or {}

    def list_semantic_relations_by_subject_state(self, key):
        return self.subject

    def list_semantic_relations_by_object_state(self, key):
        if key == "reference#boom#current":
            raise RuntimeError("no grant")
        return self.incoming.get(key, [])

    def list_by_index(self, index, key):
        return self.stories.get(key, [])


def tag(concept, predicate="related_to", human=True, state="current"):
    return {"predicate": predicate, "relationState": state, "objectKind": "semanticNode", "objectLineageId": concept, "metadata": json.dumps({"provenance": "human"} if human else {})}


def test_concepts_a_reference_carries_come_editors_tags_first_and_only_when_the_catalogue_knows_them():
    catalogue = {"c-b": ConceptInfo("beta", "concept", "Beta.", "#beta"), "c-a": ConceptInfo("alpha", "concept", "Alpha.", "#alpha")}
    relations = [tag("c-b", "mentions", human=False), tag("c-a"), tag("c-unknown"), tag("c-b", state="rejected"), {**tag("c-a"), "objectKind": "reference"}]
    found = concept_options(Backend(subject=relations), "reference-1", catalogue)
    assert [(option.hashtag, option.by_editor) for option in found] == [("#alpha", True), ("#beta", False)]


def story_row(lineage, stage, title="A story"):
    return {"id": lineage + "-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "versionCreatedAt": "2026-10-01T00:00:00Z", "stage": stage, "headline": title, "deck": "Dek."}


def evidence(lineage):
    return {"predicate": "uses_evidence", "subjectKind": "item", "subjectLineageId": lineage, "relationState": "current"}


def test_stories_are_found_by_a_related_reference_and_a_concept_and_never_twice_or_as_ideas_or_the_idea_itself():
    backend = Backend(
        incoming={"reference#reference-near#current": [evidence("s-draft"), evidence("s-idea"), evidence("s-spiked"), evidence("s-self")],
                  "semanticNode#concept-audits#current": [evidence("s-draft"), {**evidence("s-tagged"), "predicate": "related_to"}]},
        stories={"s-draft": [story_row("s-draft", "draft", "Drafted")], "s-idea": [story_row("s-idea", "idea")], "s-spiked": [story_row("s-spiked", "spiked")],
                 "s-self": [story_row("s-self", "draft")], "s-tagged": [story_row("s-tagged", "published", "Tagged one")]})
    found = story_options(backend, neighbours=[NEAR], concepts=[CONCEPT], exclude=["s-self"])
    assert [(option.lineage_id, option.via) for option in found] == [("s-draft", "Rests on A tool that checks quotations"), ("s-tagged", "Tagged #source-audits")]


def test_a_read_that_fails_leaves_that_way_out_and_a_run_out_of_time_skips_the_concept_reads():
    boom = Neighbour("boom", "Boom", "u", None, "S.", "confirmed")
    backend = Backend(incoming={"semanticNode#concept-audits#current": [{**evidence("s-tagged"), "predicate": "related_to"}]}, stories={"s-tagged": [story_row("s-tagged", "published", "Tagged one")]})
    assert [option.lineage_id for option in story_options(backend, neighbours=[boom], concepts=[CONCEPT])] == ["s-tagged"]
    assert story_options(backend, neighbours=[boom], concepts=[CONCEPT], read_concept_stories=False) == []


def test_the_variation_writer_has_the_idea_writers_rules_and_the_two_handles_only_it_is_shown():
    prompt = variations.system_prompt()
    assert prompt.startswith("You write other versions") and "Rules:\n- Every headline, dek and body sentence" in prompt
    assert "S is another story" in prompt and "C is a concept" in prompt and prompt.count("Rules:") == 1
    assert "desk" not in re.sub(r'Never use the word "desk"\.', "", prompt)


def test_the_router_may_read_a_stories_variations_and_create_them_but_never_change_or_delete_them():
    template = (Path(__file__).resolve().parents[3] / "infra/monitoring/papyrus-monitoring.yaml").read_text()
    start = template.index("  RouterIdeaPolicy:")
    policy = template[start:template.index("\n\n  ", start)]
    granted = set(re.findall(r'apis/\*/types/(Query|Mutation)/fields/(\w+)"', policy))
    assert {("Query", "listStoryVariationsByStoryAndNumber"), ("Mutation", "createStoryVariation")} <= granted
    assert not {field for _, field in granted if field in ("updateStoryVariation", "deleteStoryVariation")}
