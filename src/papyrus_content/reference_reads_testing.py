"""Test doubles for the indexed reads in ``reference_reads``: answer ``list_by_index`` from a fake client's ``list_records``."""
from __future__ import annotations

from typing import Any, Callable

#: index name -> (model, partition field, sort field or None). The indexes ``reference_reads`` queries.
INDEX_FIELDS = {
    "referencesByLineageAndVersion": ("Reference", "lineageId", None),
    "referencesByCorpusAndExternalItem": ("Reference", "corpusId", "externalItemId"),
    "referencesByCurationStatusKey": ("Reference", "curationStatusKey", None),
    "referenceAttachmentsByReferenceLineageAndSortKey": ("ReferenceAttachment", "referenceLineageId", None),
    "referenceAttachmentsByReferenceVersionAndSortKey": ("ReferenceAttachment", "referenceVersionKey", None),
    "semanticRelationsBySubjectState": ("SemanticRelation", "subjectStateKey", None),
    "semanticRelationsByObjectState": ("SemanticRelation", "objectStateKey", None),
}


def list_by_index_from_records(list_records: Callable[[str], list[dict[str, Any]]], index_name: str, key_value: str, sort_eq: str | None = None) -> list[dict[str, Any]]:
    model, partition, sort = INDEX_FIELDS[index_name]
    return [
        row for row in list_records(model)
        if row.get(partition) == key_value and (sort_eq is None or row.get(sort) == sort_eq)
    ]
