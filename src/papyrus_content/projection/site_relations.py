"""What the published Stories say about other things, read once per projection so a page can keep readers on the site.

Three facts about a Story live in ``SemanticRelation`` rows, not in its front matter, and a page wants them:

* **Which References it points a reader to.** ``see_also`` relations from the Story (an item) to an accepted Reference: "read this source too", looser than
  citing or consulting it (the ``uses_evidence`` relations are the reporting trail and are not shown here). ``SiteRelations.references``.

* **Which Reference a Story is based on.** A ``uses_evidence`` relation whose metadata ``role`` is ``based_on`` points from the Story to an
  accepted Reference. A citation in another Story's list whose address matches that Reference's ``sourceUri`` links to our Story instead of the
  outside page (``markus_renderer/citations.py``, the ``internalUrl`` field).
* **Which concepts a Story is about.** ``mentions`` and ``related_to`` relations point from the Story to a ``SemanticNode`` whose ``nodeKey`` is
  ``editor_concept--<slug>``. When a published wiki page has that slug as its ``entityKey`` the Story page links to it.

The read is bounded and goes through indexes only: the relations of the published Stories by ``semanticRelationsBySubjectState`` (25 Stories to a
request), the Reference rows of the ``based_on`` and ``see_also`` relations, one fetch for their union (25 to a request), and the SemanticNode rows of the concepts that have a public page
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
    #: ``{item id: references}`` of the accepted References each published Story points a reader to with a current ``see_also`` edge, newest linked first, each a
    #: plain mapping (:func:`_reference_entry`): never the captured text, never a Reference that is not accepted.
    references: Mapping[str, tuple[Mapping[str, Any], ...]] = field(default_factory=dict)

    def digest_input(self) -> list:
        return [
            sorted((key, list(ids)) for key, ids in self.based_on.items()),
            sorted((item, list(slugs)) for item, slugs in self.concepts.items()),
            sorted((item, list(ids)) for item, ids in self.related.items()),
            sorted((item, [sorted(entry.items()) for entry in found]) for item, found in self.references.items()),
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


def can_read_relations(client: Any) -> bool:
    """True for a client that answers the relation indexes (the authoring client, a test double). A snapshot, a fixture or an offline build has none:
    it gets no relations, and no error."""
    return hasattr(client, "index_many") or (
        hasattr(client, "list_semantic_relations_by_subject_state") and hasattr(client, "list_semantic_relations_by_object_state")
    )


def _relations_of(client: Any, keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    if hasattr(client, "index_many"):
        return client.index_many("semanticRelationsBySubjectState", keys)
    return {key: list(client.list_semantic_relations_by_subject_state(key)) for key in keys}


def _rows_by_id(client: Any, model: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """The rows of ``ids`` (`get_many`, else one `get_record` each); none for a client that reads neither."""
    wanted = [value for value in dict.fromkeys(ids) if value]
    if hasattr(client, "get_many"):
        return client.get_many(model, wanted)
    if hasattr(client, "get_record"):
        return {value: row for value in wanted if (row := client.get_record(model, value))}
    return {}


def read_site_relations(client: Any, stories: Iterable[tuple[str, str | None, str | None]], page_slugs: Iterable[str]) -> SiteRelations:
    """``stories`` are ``(item id, lineage id, published at)`` of the published Stories; ``page_slugs`` the ``entityKey`` of every published wiki page.

    Stories are ordered newest first inside each address, so the first item id is the one a citation links to.
    """
    published = {lineage: (item_id, published_at or "") for item_id, lineage, published_at in stories if lineage}
    wanted = set(page_slugs)
    if not published or not can_read_relations(client):
        return EMPTY
    rows = _relations_of(client, [f"item#{lineage}#current" for lineage in published])
    based_pairs: list[tuple[str, str]] = []
    concept_pairs: list[tuple[str, str, str]] = []   # (story lineage, slug, node row id)
    see_also: list[tuple[str, str, str, str]] = []   # (story lineage, reference row id, linked at, note)
    for lineage, (item_id, _) in published.items():
        for relation in rows.get(f"item#{lineage}#current") or []:
            if relation.get("relationState") not in (None, "current"):
                continue
            predicate = relation.get("predicate")
            if predicate == STORY_REFERENCE_PREDICATE and relation.get("objectKind") == "reference":
                if _metadata(relation).get("role") == BASED_ON and relation.get("objectId"):
                    based_pairs.append((lineage, str(relation["objectId"])))
            elif predicate == SEE_ALSO and relation.get("objectKind") == "reference" and relation.get("subjectLineageId") in (None, lineage) and relation.get("objectId"):
                metadata = _metadata(relation)
                see_also.append((lineage, str(relation["objectId"]), str(metadata.get("addedAt") or ""), str(metadata.get("note") or "")))
            elif predicate in CONCEPT_LINK_PREDICATES and relation.get("objectKind") == CONCEPT_KIND:
                slug = concept_slug(relation.get("objectLineageId"))
                if slug and slug in wanted and relation.get("objectId"):
                    concept_pairs.append((lineage, slug, str(relation["objectId"])))

    by_address: dict[str, list[tuple[str, str]]] = {}
    references: dict[str, dict[str, Any]] = {}
    if based_pairs or see_also:   # one fetch for the union, 25 to a request
        references = references_by_id(client, [reference_id for _, reference_id in based_pairs] + [reference_id for _, reference_id, _, _ in see_also])
    if based_pairs:
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
        references=_see_also_references(published, see_also, references),
    )


def _see_also_references(published: Mapping[str, tuple[str, str]], links: list[tuple[str, str, str, str]], rows: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[dict, ...]]:
    """The accepted References each published Story points to, newest linked first (ties by Reference id), once per Reference."""
    found: dict[str, dict[str, tuple[str, str, Mapping[str, Any]]]] = {}
    for lineage, reference_id, linked_at, note in links:
        row = rows.get(reference_id)
        if row is not None and str(row.get("curationStatus") or "") == ACCEPTED:
            found.setdefault(published[lineage][0], {})[reference_id] = (linked_at, note, row)
    return {
        item: tuple(_reference_entry(row, note) for _, _, note, row in sorted(((at, ref, note, row) for ref, (at, note, row) in entries.items()), key=lambda e: (e[0], e[1]), reverse=True))
        for item, entries in found.items()
    }


def _reference_entry(row: Mapping[str, Any], note: str) -> dict[str, Any]:
    """One Reference as a page shows it: public card fields only, never the captured text."""
    from ..home_page.export import displayed_title, host_of
    from ..public_text import public_url

    address = public_url(row.get("sourceUri"))
    return {
        "referenceId": row.get("id"),
        "lineageId": row.get("lineageId"),
        "title": displayed_title(row, address, None),
        "url": address,
        "host": row.get("cardSiteName") or host_of(address),
        "image": row.get("cardImage") or None,
        "summary": row.get("cardSummary") or None,
        "medium": row.get("medium") or None,
        "acceptedAt": row.get("curationStatusUpdatedAt"),
        "note": note or None,
    }


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
    return _rows_by_id(client, "SemanticNode", node_ids)
