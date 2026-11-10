"""Concepts and the links between them, from the signed-in CLI: the commands send the site's own mutations and nothing else."""

from __future__ import annotations

import contextlib
import io
import json
from typing import Any
from unittest import mock

import pytest

from papyrus_content import section_concepts, signed_in_concepts
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
from papyrus_content.knowledge_snapshot import commands
from papyrus_content.knowledge_snapshot.actors import Actor, ReviewMarks, decode_review, make_actor
from papyrus_content.knowledge_snapshot.entity_review import EntityReviewError, accept_description_patches
from papyrus_content.operator_errors import GraphQLRequestError
from papyrus_content.signed_in_concepts import (
    apply_review_patches,
    display_name_for,
    knowledge_entities_link,
    on_signed_in_lane,
    references_link,
    run_mutation,
)

NODES = [
    {"id": "semantic-node-editor_concept--containment-v1", "lineageId": "semantic-node-editor_concept--containment", "versionState": "current",
     "nodeKey": "editor_concept--containment", "nodeKind": "editor_concept", "displayName": "containment", "status": "accepted", "aliases": []},
    {"id": "semantic-node-editor_concept--confinement-problem-v1", "lineageId": "semantic-node-editor_concept--confinement-problem", "versionState": "current",
     "nodeKey": "editor_concept--confinement-problem", "nodeKind": "editor_concept", "displayName": "confinement problem", "status": "accepted", "aliases": ["boxing"]},
    {"id": "semantic-node-editor_concept--spam-v1", "lineageId": "semantic-node-editor_concept--spam", "versionState": "current",
     "nodeKey": "editor_concept--spam", "nodeKind": "editor_concept", "displayName": "Spam", "status": "rejected", "aliases": []},
]


class Site:
    """A stand-in for the site: records each mutation the command sends and answers as the site's mutation does."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: str | None = None

    def list_records(self, model: str) -> list[dict[str, Any]]:
        assert model == "SemanticNode"
        return [dict(row) for row in NODES]

    safe_list_records = list_records

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        field = query.split("{", 1)[1].split("(", 1)[0].strip()
        self.calls.append((field, dict(variables or {})))
        if self.fail:
            raise GraphQLRequestError(f"GraphQL request failed: {self.fail}\nsecond line", status_code=200)
        if field == "createEditorConcept":
            return {field: {"ok": True, "lineageId": f"semantic-node-editor_concept--{section_concepts.concept_slug(variables['name'])}", "displayName": variables["displayName"]}}
        if field == "applyKnowledgeReview":
            return {field: {"ok": True, "applied": len(json.loads(variables["patches"])), "origin": "cli"}}
        return {field: {"ok": True, "relationId": "rel-1", "relationState": "current", "outcome": "created"}}


def run(function, flags, site: Site) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        function(flags, client=site)
    return out.getvalue()


def test_a_name_keeps_the_capitals_the_person_typed_and_a_hashtag_reads_with_spaces():
    assert display_name_for("Information flow control") == "Information flow control"
    assert display_name_for("Non-interference") == "Non-interference"
    assert display_name_for("#fake-website-networks") == "fake website networks"
    assert display_name_for("non-interference", "Non-interference") == "Non-interference"
    with pytest.raises(ValueError, match="not the same words"):
        display_name_for("Containment", "Something else")
    with pytest.raises(ValueError, match="needs a name"):
        display_name_for("#")


def test_a_refusal_comes_back_as_the_sites_own_first_line():
    site = Site()
    site.fail = "Not Authorized to access createEditorConcept on type Mutation"
    with pytest.raises(ValueError) as caught:
        run_mutation(site, "mutation X { createEditorConcept(name: 1) { ok } }", {}, "createEditorConcept")
    assert str(caught.value) == "Not Authorized to access createEditorConcept on type Mutation"


def test_a_reference_is_linked_to_a_concept_and_a_dry_run_sends_nothing():
    site = Site()
    out = run(references_link, ["--reference", "ref-1", "--concept", "boxing", "--note", "The sibling problem", "--dry-run"], site)
    assert site.calls == [] and "dry run" in out
    out = run(references_link, ["--reference", "ref-1", "--concept", "boxing", "--note", "The sibling problem"], site)
    assert site.calls == [("createReferenceLink", {
        "subjectLineageId": "ref-1", "objectKind": "semanticNode", "objectLineageId": "semantic-node-editor_concept--confinement-problem",
        "predicate": "tagged_with", "note": "The sibling problem"})]
    assert "created\trel-1" in out


def test_a_reference_is_linked_to_another_reference_with_a_predicate():
    site = Site()
    run(references_link, ["--reference", "ref-1", "--to-reference", "ref-2", "--predicate", "supports"], site)
    assert site.calls == [("createReferenceLink", {"subjectLineageId": "ref-1", "objectKind": "reference", "objectLineageId": "ref-2", "predicate": "supports", "note": None})]


def test_an_unknown_concept_is_made_only_when_asked_and_keeps_the_typed_capitals():
    site = Site()
    with pytest.raises(ValueError, match="add --create"):
        run(references_link, ["--reference", "ref-1", "--concept", "Information flow control"], site)
    assert site.calls == []
    run(references_link, ["--reference", "ref-1", "--concept", "Information flow control", "--create", "--dry-run"], site)
    assert site.calls == []
    run(references_link, ["--reference", "ref-1", "--concept", "Information flow control", "--create"], site)
    assert [call[0] for call in site.calls] == ["createEditorConcept", "createReferenceLink"]
    assert site.calls[0][1] == {"name": "Information flow control", "displayName": "Information flow control"}
    assert site.calls[1][1]["objectLineageId"] == "semantic-node-editor_concept--information-flow-control"


def test_a_reference_link_needs_one_target_a_known_predicate_and_a_concept_that_was_not_rejected():
    site = Site()
    for flags, message in (
        (["--to-reference", "ref-2"], "requires --reference"),
        (["--reference", "ref-1"], "exactly one of"),
        (["--reference", "ref-1", "--to-reference", "ref-2", "--concept", "boxing"], "exactly one of"),
        (["--reference", "ref-1", "--to-reference", "ref-2", "--predicate", "likes"], "--predicate must be"),
        (["--reference", "ref-1", "--concept", "boxing", "--predicate", "cites"], "tagged_with"),
        (["--reference", "ref-1", "--to-reference", "ref-2", "--predicate", "tagged_with"], "tags a Reference with a concept"),
        (["--reference", "ref-1", "--concept", "Spam", "--create"], "was rejected"),
        (["--apply", "--reference", "ref-1", "--to-reference", "ref-2"], "no longer accepts --apply"),
    ):
        with pytest.raises(ValueError, match=message):
            run(references_link, flags, site)
    assert site.calls == []


def test_help_sends_nothing_and_does_not_run_the_command():
    for function in (references_link, knowledge_entities_link):
        site = Site()
        out = run(function, ["--help"], site)
        assert site.calls == [] and "Writes unless --dry-run" in out


def test_two_concepts_are_linked_with_their_explanation():
    site = Site()
    flags = ["--key", "editor_concept--containment", "--to", "editor_concept--confinement-problem", "--note", "Two sides of one fence"]
    out = run(knowledge_entities_link, [*flags, "--dry-run"], site)
    assert site.calls == [] and "dry run" in out
    run(knowledge_entities_link, flags, site)
    assert site.calls == [("createConceptLink", {
        "subjectLineageId": "semantic-node-editor_concept--containment", "objectLineageId": "semantic-node-editor_concept--confinement-problem", "note": "Two sides of one fence"})]


def test_a_link_between_concepts_needs_its_words_two_different_concepts_and_none_rejected():
    site = Site()
    base = ["--key", "editor_concept--containment", "--to", "editor_concept--confinement-problem"]
    for flags, message in (
        (base, "requires --note"),
        ([*base, "--note", "   "], "requires --note"),
        (["--key", "editor_concept--containment", "--note", "x"], "requires --key CONCEPT and --to CONCEPT"),
        (["--key", "editor_concept--containment", "--to", "editor_concept--containment", "--note", "x"], "itself"),
        (["--key", "editor_concept--containment", "--to", "editor_concept--spam", "--note", "x"], "was rejected"),
        (["--key", "editor_concept--containment", "--to", "editor_concept--nope", "--note", "x"], "No entity"),
    ):
        with pytest.raises(ValueError, match=message):
            run(knowledge_entities_link, flags, site)
    assert site.calls == []


def test_review_patches_go_to_the_site_in_calls_of_at_most_two_hundred():
    site = Site()
    patches = [{"modelName": "SemanticNode", "expected": {"id": f"n{index}", "displayName": "X"}} for index in range(201)]
    assert apply_review_patches(site, patches) == {"applied": 201, "origin": "cli"}
    assert [len(json.loads(variables["patches"])) for _field, variables in site.calls] == [200, 1]


def test_a_signed_in_client_sends_review_patches_through_the_site_and_an_aws_client_writes_the_models():
    signed_in = PapyrusGraphQLAuthoringClient(endpoint="https://example.test/graphql", header_factory=lambda _payload: {"authorization": "token"}, site_tenant=False)
    assert on_signed_in_lane(signed_in) is True
    assert on_signed_in_lane(Site()) is False
    patches = [{"modelName": "SemanticNode", "expected": {"id": "n1", "displayName": "Containment"}}]
    sent: list[tuple[str, dict[str, Any]]] = []
    with mock.patch.object(PapyrusGraphQLAuthoringClient, "graphql", lambda self, query, variables=None: sent.append((query, variables)) or {"applyKnowledgeReview": {"ok": True, "applied": 1, "origin": "cli"}}):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            commands.write_patches(signed_in, patches)
    assert len(sent) == 1 and "applyKnowledgeReview" in sent[0][0] and "via cli" in out.getvalue()
    direct: list[Any] = []
    with mock.patch.object(commands, "apply_record_changes", lambda client, changes: direct.append(changes)):
        commands.write_patches(Site(), patches)
    assert direct and direct[0][0]["action"] == "update"


def test_accepting_a_description_is_for_a_person_and_changes_only_who_accepted_it():
    node = {**NODES[0], "description": "Keeping a capable system inside its limits.", "changeReason": "Described by an editor"}
    person = make_actor("human", "Ada Reader", "2026-11-05")
    patch = accept_description_patches(node, actor=person, now="2026-11-05T12:00:00Z")
    assert len(patch) == 1 and set(patch[0]["expected"]) == {"id", "changeReason", "updatedAt"}
    assert decode_review(patch[0]["expected"]["changeReason"]).description_edited_by == person
    again = {**node, "changeReason": patch[0]["expected"]["changeReason"]}
    assert accept_description_patches(again, actor=person, now="2026-11-06T12:00:00Z") == []
    with pytest.raises(EntityReviewError, match="Only a person"):
        accept_description_patches(node, actor=make_actor("ai", "Wiki agent", "2026-11-05"), now="x")
    with pytest.raises(EntityReviewError, match="no description"):
        accept_description_patches(NODES[0], actor=person, now="x")


def test_where_a_decision_was_made_survives_being_read_and_written_again():
    marks = ReviewMarks(accepted_by=Actor("human", "Ada Reader", "2026-11-05", via="cli"))
    again = decode_review(marks.encode())
    assert again.accepted_by is not None and again.accepted_by.via == "cli"
    plain = ReviewMarks(accepted_by=Actor("human", None, "2026-11-05")).encode()
    assert plain == 'papyrus-knowledge-review@1:{"acceptedBy":{"actor":"human","name":null,"on":"2026-11-05"},"descriptionEditedBy":null,"rejectedBy":null}'   # no via: unchanged bytes


def test_sections_concepts_create_keeps_the_typed_capitals_and_uses_the_sites_mutation():
    site = Site()
    section = {"id": "security", "coreConcepts": None}
    updates: list[tuple[str, dict[str, Any]]] = []
    site.update_record = lambda model, payload: updates.append((model, payload))   # type: ignore[attr-defined]
    with mock.patch.object(section_concepts, "create_authoring_client", return_value=(site, None)), mock.patch.object(section_concepts, "find_section", return_value=section):
        with contextlib.redirect_stdout(io.StringIO()):
            section_concepts.sections_concepts(["add", "--section", "security", "--concept", "Non-interference", "--create"])
    assert [call[0] for call in site.calls] == ["createEditorConcept"]
    assert site.calls[0][1] == {"name": "Non-interference", "displayName": "Non-interference"}
    assert updates and json.loads(updates[0][1]["coreConcepts"])[0]["conceptLineageId"] == "semantic-node-editor_concept--non-interference"
    with mock.patch.object(section_concepts, "create_authoring_client", return_value=(site, None)), mock.patch.object(section_concepts, "find_section", return_value=section):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            section_concepts.sections_concepts(["add", "--help"])
    assert "--display-name" in out.getvalue() and len(site.calls) == 1
