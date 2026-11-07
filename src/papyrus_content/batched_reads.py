"""Reads for many References at once: 25 to a request through the client's aliased helpers (`get_many`, `index_many`).

A loop that reads one index per row costs one AppSync request per row; these cost one per 25 rows. The results are the ones the
per-row reads return, so a caller changes from `for row in rows: read(row)` to `for chunk in chunks(rows): read_many(chunk)`
without changing what it does with them. A client with no batch methods (a test double) is read one key at a time.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Mapping, Sequence

from .graphql_authoring import ALIAS_BATCH_SIZE


def chunks(rows: Sequence[Any], size: int = ALIAS_BATCH_SIZE) -> Iterator[Sequence[Any]]:
    for offset in range(0, len(rows), size):
        yield rows[offset:offset + size]


def current_relation_key(reference: Mapping[str, Any]) -> str | None:
    lineage = reference.get("lineageId")
    return f"reference#{lineage}#current" if lineage else None


def current_relations_of_many(client: Any, references: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The current relations whose subject is each Reference (as `ideas.digest.relations_of` reads them), keyed by the Reference's lineage id.
    A Reference with no lineage id has none."""
    keys = {key: str(reference["lineageId"]) for reference in references if (key := current_relation_key(reference))}
    if not keys:
        return {}
    if hasattr(client, "index_many"):
        found = client.index_many("semanticRelationsBySubjectState", list(keys))
    else:
        found = {key: list(client.list_semantic_relations_by_subject_state(key)) for key in keys}
    return {lineage: list(found.get(key) or []) for key, lineage in keys.items()}


def attachments_of_many(client: Any, lineage_ids: Iterable[str]) -> dict[str, list[dict[str, Any]]]:
    """The attachments of each Reference lineage (as `list_reference_attachments_by_lineage` reads them), keyed by lineage id."""
    ids = [lineage for lineage in dict.fromkeys(str(value) for value in lineage_ids if value)]
    if not ids:
        return {}
    if hasattr(client, "index_many"):
        return {lineage: list(rows) for lineage, rows in client.index_many("referenceAttachmentsByReferenceLineageAndSortKey", ids).items()}
    return {lineage: list(client.list_reference_attachments_by_lineage(lineage)) for lineage in ids}


def references_by_id(client: Any, reference_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """The current rows of the Reference ids that exist (`get_record` for each, 25 to a request)."""
    ids = [value for value in dict.fromkeys(reference_ids) if value]
    if not ids:
        return {}
    if hasattr(client, "get_many"):
        return client.get_many("Reference", ids)
    return {value: row for value in ids if (row := client.get_record("Reference", value))}
