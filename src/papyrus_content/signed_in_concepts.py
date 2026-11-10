"""Concepts and the links between them, from the CLI on a signed-in session (no AWS login).

An editor's token may read the semantic graph and write nothing in it directly (the model rules allow AWS credentials only), so these go through
the site's own mutations, which check the caller is an editor and stamp where the decision was made (``cli``), never trusting what the command says:

* ``createEditorConcept(name, displayName)``: the concept an editor invents; ``displayName`` keeps the capitalisation the person typed.
* ``createReferenceLink(...)``: a link from a Reference to a Reference or to a concept, with the editor's words.
* ``createConceptLink(...)``: a link between two concepts, with the editor's words (required).
* ``applyKnowledgeReview(patches)``: the review patches of ``papyrus knowledge entities`` (accept, reject, rename, alias, describe,
  accept-description), checked against what a review may change.

``papyrus references link`` and ``papyrus knowledge entities link`` are the commands for the two links.
"""

from __future__ import annotations

import json
from typing import Any

from .operator_errors import GraphQLRequestError
from .options import normalize_string, parse_options, resolve_mutation_apply
from .section_concepts import (
    concept_label,
    concept_slug,
    current_concept_nodes,
    display_name_for,
    editor_concept_lineage_id,
    resolve_concept,
)

CREATE_EDITOR_CONCEPT_MUTATION = (
    "mutation CreateEditorConcept($name: String!, $displayName: String) "
    "{ createEditorConcept(name: $name, displayName: $displayName) { ok lineageId nodeKey displayName nodeKind } }"
)
CREATE_REFERENCE_LINK_MUTATION = (
    "mutation CreateReferenceLink($subjectLineageId: ID!, $objectKind: String!, $objectLineageId: ID!, $predicate: String!, $note: String) "
    "{ createReferenceLink(subjectLineageId: $subjectLineageId, objectKind: $objectKind, objectLineageId: $objectLineageId, predicate: $predicate, note: $note) "
    "{ ok relationId relationState outcome decision } }"
)
CREATE_CONCEPT_LINK_MUTATION = (
    "mutation CreateConceptLink($subjectLineageId: ID!, $objectLineageId: ID!, $note: String!) "
    "{ createConceptLink(subjectLineageId: $subjectLineageId, objectLineageId: $objectLineageId, note: $note) { ok relationId relationState outcome decision } }"
)
APPLY_KNOWLEDGE_REVIEW_MUTATION = (
    "mutation ApplyKnowledgeReview($patches: AWSJSON!) { applyKnowledgeReview(patches: $patches) { ok applied origin } }"
)
REFERENCE_LINK_PREDICATES = ("related_to", "cites", "supports", "contradicts", "tagged_with")   # tagged_with: only to a concept
PATCHES_PER_CALL = 200


def _fail(error: Exception) -> ValueError:
    text = str(error).splitlines()[0] if str(error) else error.__class__.__name__
    return ValueError(text.removeprefix("GraphQL request failed: "))


def run_mutation(client: Any, query: str, variables: dict[str, Any], field: str) -> dict[str, Any]:
    """One mutation on the signed-in session; a refusal comes back as one line in the site's own words."""
    try:
        data = client.graphql(query, variables)
    except GraphQLRequestError as error:
        raise _fail(error) from None
    answer = (data or {}).get(field)
    if not isinstance(answer, dict) or not answer.get("ok"):
        raise ValueError(f"The site did not confirm {field}.")
    return answer


def create_editor_concept(client: Any, typed: str, display_name: str | None = None) -> dict[str, Any]:
    return run_mutation(client, CREATE_EDITOR_CONCEPT_MUTATION, {"name": typed, "displayName": display_name_for(typed, display_name)}, "createEditorConcept")


def create_reference_link(client: Any, *, reference: str, object_kind: str, object_id: str, predicate: str, note: str | None) -> dict[str, Any]:
    variables = {"subjectLineageId": reference, "objectKind": object_kind, "objectLineageId": object_id, "predicate": predicate, "note": note}
    return run_mutation(client, CREATE_REFERENCE_LINK_MUTATION, variables, "createReferenceLink")


def create_concept_link(client: Any, *, subject: str, object_: str, note: str) -> dict[str, Any]:
    return run_mutation(client, CREATE_CONCEPT_LINK_MUTATION, {"subjectLineageId": subject, "objectLineageId": object_, "note": note}, "createConceptLink")


def apply_review_patches(client: Any, patches: list[dict[str, Any]]) -> dict[str, int | str]:
    """Send review patches (``{modelName, expected}``) through ``applyKnowledgeReview``, at most ``PATCHES_PER_CALL`` at a time."""
    applied, origin = 0, ""
    for start in range(0, len(patches), PATCHES_PER_CALL):
        answer = run_mutation(client, APPLY_KNOWLEDGE_REVIEW_MUTATION, {"patches": json.dumps(patches[start:start + PATCHES_PER_CALL])}, "applyKnowledgeReview")
        applied += int(answer.get("applied") or 0)
        origin = str(answer.get("origin") or origin)
    return {"applied": applied, "origin": origin}


def on_signed_in_lane(client: Any) -> bool:
    """Whether ``client`` sends a signed-in person's token (the lane that cannot write the graph directly), as opposed to AWS credentials."""
    from .graphql_authoring import PapyrusGraphQLAuthoringClient

    if not isinstance(client, PapyrusGraphQLAuthoringClient):
        return False
    try:
        from .user_auth_mode import user_auth_requested

        if client.header_factory is not None:
            return True
        if not user_auth_requested():
            return False
        from .cli_user_auth import selected_headers

        return selected_headers(client.endpoint) is not None
    except Exception:   # noqa: BLE001 - no readable session is the AWS-credentials lane
        return False


def _concept_in(nodes: list[dict[str, Any]], text: str) -> dict[str, Any]:
    node = resolve_concept(nodes, text)
    if node is None:
        raise ValueError(f"No concept is named {text!r}. Name an existing concept by its name, alias, #hashtag or node key.")
    return node


def _lineage(node: dict[str, Any]) -> str:
    return str(node.get("lineageId") or node["id"])


def _wants_help(options: dict[str, Any]) -> bool:
    return options.get("help") is True or options.get("h") is True


def _flag(options: dict[str, Any], name: str) -> bool:
    return options.get(name) is True or str(options.get(name)).lower() in ("true", "yes", "1")


REFERENCES_LINK_USAGE = (
    "papyrus references link --reference REF (--to-reference REF | --concept NAME [--create [--display-name TEXT]]) [--predicate related_to|cites|supports|contradicts]\n"
    "                        [--note TEXT] [--dry-run]\n"
    "  Links a Reference to another Reference or to a concept, as the Related section does, with the words that say why. REF is a Reference id or lineage id.\n"
    "  NAME is a concept's name, alias, #hashtag or node key; with --create an unknown name makes a concept (the capitals you type are kept). A concept is\n"
    "  tagged with tagged_with (related_to is accepted for it and means the same). Writes unless --dry-run; the site records that the link was made from the CLI."
)
KNOWLEDGE_ENTITIES_LINK_USAGE = (
    "papyrus knowledge entities link --key CONCEPT --to CONCEPT --note TEXT [--dry-run]\n"
    "  Links two concepts with a related_to link and the words that say how they relate (required: the explanation is the meaning). CONCEPT is a node key,\n"
    "  node id or lineage id (see `knowledge entities list`). One link per pair; running it again replaces the words. Writes unless --dry-run; the site\n"
    "  records that the link was made from the CLI."
)


def references_link(flags: list[str], *, client: Any = None) -> None:
    options = parse_options(flags)
    if _wants_help(options):
        print(REFERENCES_LINK_USAGE)
        return
    apply = resolve_mutation_apply(options, "references link")
    reference = normalize_string(options.get("reference"))
    other_reference = normalize_string(options.get("to-reference"))
    concept = normalize_string(options.get("concept"))
    if not reference or reference is True:
        raise ValueError("references link requires --reference.")
    if bool(other_reference) == bool(concept) or other_reference is True or concept is True:
        raise ValueError("references link requires exactly one of --to-reference REF or --concept NAME.")
    predicate = normalize_string(options.get("predicate")) or "related_to"
    if predicate not in REFERENCE_LINK_PREDICATES:
        raise ValueError(f"--predicate must be one of {', '.join(REFERENCE_LINK_PREDICATES)}.")
    note = normalize_string(options.get("note")) if options.get("note") is not True else None
    mode = "write" if apply else "dry run"
    if client is None:
        from .graphql_authoring import create_authoring_client

        client = create_authoring_client()[0]
    if other_reference:
        if predicate == "tagged_with":
            raise ValueError("tagged_with tags a Reference with a concept; between two References use related_to, cites, supports or contradicts.")
        print(f"references\tlink\t{reference}\t{predicate}\t{other_reference}\t{mode}")
        if apply:
            answer = create_reference_link(client, reference=reference, object_kind="reference", object_id=other_reference, predicate=predicate, note=note)
            print(f"references\tlink\t{answer.get('outcome')}\t{answer.get('relationId')}")
        return
    if predicate not in ("related_to", "tagged_with"):
        raise ValueError("A Reference is tagged with a concept with tagged_with (related_to is accepted and means the same).")
    predicate = "tagged_with"
    nodes = current_concept_nodes(client)
    node = resolve_concept(nodes, concept)
    created = False
    if node is None:
        if not _flag(options, "create"):
            raise ValueError(f"No concept is named {concept!r}. Name an existing concept, or add --create to make it.")
        lineage = editor_concept_lineage_id(concept_slug(concept))
        shown = display_name_for(concept, normalize_string(options.get("display-name")))
        rejected = next((row for row in nodes if _lineage(row) == lineage and row.get("status") == "rejected"), None)
        if rejected is not None:
            raise ValueError(f"The concept {concept_label(rejected)!r} was rejected, so a Reference cannot be linked to it.")
        print(f"references\tlink\tcreate concept\t{shown}\t{lineage}\t{mode}")
        created = True
    else:
        lineage = _lineage(node)
    print(f"references\tlink\t{reference}\t{predicate}\t{concept_label(node) if node else shown}\t{lineage}\t{mode}")
    if not apply:
        return
    if created:
        made = create_editor_concept(client, concept, normalize_string(options.get("display-name")))
        lineage = str(made.get("lineageId") or lineage)
    answer = create_reference_link(client, reference=reference, object_kind="semanticNode", object_id=lineage, predicate=predicate, note=note)
    print(f"references\tlink\t{answer.get('outcome')}\t{answer.get('relationId')}")


def knowledge_entities_link(flags: list[str], *, client: Any = None) -> None:
    options = parse_options(flags)
    if _wants_help(options):
        print(KNOWLEDGE_ENTITIES_LINK_USAGE)
        return
    apply = resolve_mutation_apply(options, "knowledge entities link")
    first_text, second_text = normalize_string(options.get("key")), normalize_string(options.get("to"))
    if not first_text or first_text is True or not second_text or second_text is True:
        raise ValueError("knowledge entities link requires --key CONCEPT and --to CONCEPT.")
    note = normalize_string(options.get("note")) if options.get("note") is not True else None
    if not note:
        raise ValueError("knowledge entities link requires --note: say how the two concepts relate.")
    if client is None:
        from .graphql_authoring import create_authoring_client

        client = create_authoring_client()[0]
    from .knowledge_snapshot.entity_review import EntityReviewError, find_node

    rows = client.list_records("SemanticNode")
    try:
        first, second = find_node(rows, first_text), find_node(rows, second_text)
    except EntityReviewError as error:
        raise ValueError(str(error)) from error
    if _lineage(first) == _lineage(second):
        raise ValueError("A concept cannot be linked to itself.")
    for node in (first, second):
        if node.get("status") == "rejected":
            raise ValueError(f"{node.get('nodeKey')} was rejected, so it cannot be linked.")
    mode = "write" if apply else "dry run"
    print(f"knowledge\tentities\tlink\t{first.get('nodeKey')}\trelated_to\t{second.get('nodeKey')}\t{mode}")
    if not apply:
        return
    answer = create_concept_link(client, subject=_lineage(first), object_=_lineage(second), note=note)
    print(f"knowledge\tentities\tlink\t{answer.get('outcome')}\t{answer.get('relationId')}")
