"""What the published Stories say about other things, read once per projection so a page can keep readers on the site.

Two facts about a Story live in ``SemanticRelation`` rows, not in its front matter, and a page wants both:

* **Which Reference a Story is based on.** A ``uses_evidence`` relation whose metadata ``role`` is ``based_on`` points from the Story to an
  accepted Reference. A citation in another Story's list whose address matches that Reference's ``sourceUri`` links to our Story instead of the
  outside page (``markus_renderer/citations.py``, the ``internalUrl`` field).
* **Which concepts a Story is about.** ``mentions`` and ``related_to`` relations point from the Story to a ``SemanticNode`` whose ``nodeKey`` is
  ``editor_concept--<slug>``. When a published wiki page has that slug as its ``entityKey`` the Story page links to it.

The read is bounded and goes through indexes only: the relations of the published Stories by ``semanticRelationsBySubjectState`` (25 Stories to a
request), the Reference rows of the ``based_on`` relations (25 to a request), and the SemanticNode rows of the concepts that have a public page
(25 to a request, to skip a rejected one). Machines on Machines (122 published Stories) costs about ten requests. No table is scanned.

The result rides on the :class:`~papyrus_content.projection.model.SiteIndex` and is part of the projector's shared inputs, so a Story published
or withdrawn, a Reference accepted, or a concept page added changes the digest and the item pages are rendered again; a page whose bytes do not
change is not written.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..batched_reads import references_by_id
from ..concept_link_predicates import CONCEPT_KIND, CONCEPT_LINK_PREDICATES
from ..story_from_reference import url_key
from ..story_reporting import BASED_ON, STORY_REFERENCE_PREDICATE

CONCEPT_NODE_PREFIX = "editor_concept--"
STATE_REJECTED = "rejected"
ACCEPTED = "accepted"


@dataclass(frozen=True)
class SiteRelations:
    """``based_on``: ``{url_key: item ids}`` of the published Stories based on the accepted Reference at that address.
    ``concepts``: ``{item id: concept slugs}`` of the concepts each published Story mentions or is related to, for slugs that have a published page."""

    based_on: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    concepts: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: ``{item id: item ids}`` of the published Stories each published Story is related to (``see_also`` between two Stories, read in both directions).
    related: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def digest_input(self) -> list:
        return [
            sorted((key, list(ids)) for key, ids in self.based_on.items()),
            sorted((item, list(slugs)) for item, slugs in self.concepts.items()),
            sorted((item, list(ids)) for item, ids in self.related.items()),
        ]


EMPTY = SiteRelations()


def concept_slug(node_key_or_lineage: Any) -> str | None:
    """The slug of a concept node: what follows ``--`` in ``editor_concept--<slug>`` (or in the node's lineage id)."""
    text = str(node_key_or_lineage or "")
    marker = text.find(CONCEPT_NODE_PREFIX)
    return text[marker + len(CONCEPT_NODE_PREFIX):] or None if marker >= 0 else None


def _metadata(relation: Mapping[str, Any]) -> dict:
    value = relation.get("metadata")
    if isinstance(value, str) and value:
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _relations_of(client: Any, keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    if hasattr(client, "index_many"):
        return client.index_many("semanticRelationsBySubjectState", keys)
    return {key: list(client.list_semantic_relations_by_subject_state(key)) for key in keys}


def read_site_relations(client: Any, stories: Iterable[tuple[str, str | None, str | None]], page_slugs: Iterable[str]) -> SiteRelations:
    """``stories`` are ``(item id, lineage id, published at)`` of the published Stories; ``page_slugs`` the ``entityKey`` of every published wiki page.

    Stories are ordered newest first inside each address, so the first item id is the one a citation links to.
    """
    published = {lineage: (item_id, published_at or "") for item_id, lineage, published_at in stories if lineage}
    wanted = set(page_slugs)
    if not published:
        return EMPTY
    rows = _relations_of(client, [f"item#{lineage}#current" for lineage in published])
    based_pairs: list[tuple[str, str]] = []
    concept_pairs: list[tuple[str, str, str]] = []   # (story lineage, slug, node row id)
    for lineage, (item_id, _) in published.items():
        for relation in rows.get(f"item#{lineage}#current") or []:
            if relation.get("relationState") not in (None, "current"):
                continue
            predicate = relation.get("predicate")
            if predicate == STORY_REFERENCE_PREDICATE and relation.get("objectKind") == "reference":
                if _metadata(relation).get("role") == BASED_ON and relation.get("objectId"):
                    based_pairs.append((lineage, str(relation["objectId"])))
            elif predicate in CONCEPT_LINK_PREDICATES and relation.get("objectKind") == CONCEPT_KIND:
                slug = concept_slug(relation.get("objectLineageId"))
                if slug and slug in wanted and relation.get("objectId"):
                    concept_pairs.append((lineage, slug, str(relation["objectId"])))

    by_address: dict[str, list[tuple[str, str]]] = {}
    if based_pairs:
        references = references_by_id(client, [reference_id for _, reference_id in based_pairs])
        for lineage, reference_id in based_pairs:
            reference = references.get(reference_id) or {}
            if str(reference.get("curationStatus") or "") != ACCEPTED:
                continue
            key = url_key(str(reference.get("sourceUri") or ""))
            if key:
                item_id, published_at = published[lineage]
                by_address.setdefault(key, []).append((published_at, item_id))
    based_on = {key: tuple(item_id for _, item_id in sorted(set(found), reverse=True)) for key, found in by_address.items()}

    concepts: dict[str, list[str]] = {}
    if concept_pairs:
        nodes = _nodes_by_id(client, [node_id for _, _, node_id in concept_pairs])
        for lineage, slug, node_id in concept_pairs:
            if str((nodes.get(node_id) or {}).get("status") or "") == STATE_REJECTED:
                continue
            slugs = concepts.setdefault(published[lineage][0], [])
            if slug not in slugs:
                slugs.append(slug)
    return SiteRelations(
        based_on=based_on,
        concepts={item: tuple(slugs) for item, slugs in concepts.items()},
        related=_related_stories(client, published, rows),
    )


ITEM_KIND = "item"
SEE_ALSO = "see_also"  # the one story-to-story relation: symmetric, written by `papyrus stories link-story`


def _related_stories(client: Any, published: Mapping[str, tuple[str, str]], outgoing: Mapping[str, list[dict[str, Any]]]) -> dict[str, tuple[str, ...]]:
    """``see_also`` between two published Stories, symmetric: the rows from each Story (already read) and the rows that point at it (one more index query per 25 Stories)."""
    pairs: dict[str, dict[str, None]] = {}

    def link(lineage: str, other: str) -> None:
        if other in published and other != lineage:
            pairs.setdefault(published[lineage][0], {})[published[other][0]] = None
            pairs.setdefault(published[other][0], {})[published[lineage][0]] = None

    for lineage in published:
        for relation in outgoing.get(f"item#{lineage}#current") or []:
            if relation.get("predicate") == SEE_ALSO and relation.get("objectKind") == ITEM_KIND and relation.get("relationState") in (None, "current"):
                link(lineage, str(relation.get("objectLineageId") or ""))
    keys = [f"item#{lineage}#current" for lineage in published]
    if hasattr(client, "index_many"):
        incoming = client.index_many("semanticRelationsByObjectState", keys)
    else:
        incoming = {key: list(client.list_semantic_relations_by_object_state(key)) for key in keys}
    for lineage in published:
        for relation in incoming.get(f"item#{lineage}#current") or []:
            if relation.get("predicate") == SEE_ALSO and relation.get("subjectKind") == ITEM_KIND and relation.get("relationState") in (None, "current"):
                link(lineage, str(relation.get("subjectLineageId") or ""))
    return {item: tuple(others) for item, others in pairs.items()}


def _nodes_by_id(client: Any, node_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [value for value in dict.fromkeys(node_ids) if value]
    if hasattr(client, "get_many"):
        return client.get_many("SemanticNode", ids)
    return {value: row for value in ids if (row := client.get_record("SemanticNode", value))}
