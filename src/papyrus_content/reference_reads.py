"""Indexed reads of References, their attachments and their relations: never a whole table to touch a few rows.

A command that works on one Reference, a few, or one corpus asks for exactly those rows through the indexes in ``amplify/data/resource.ts``:

* a Reference by id (``get_record``) or by lineage (``referencesByLineageAndVersion``);
* a Reference by the item id it has in its corpus (``referencesByCorpusAndExternalItem``);
* a Reference's attachments by lineage (``referenceAttachmentsByReferenceLineageAndSortKey``);
* a Reference's relations by the state key of either end (``semanticRelationsBySubjectState`` and ``semanticRelationsByObjectState``),
  which hold the relations in the ``current`` state, the only ones a command acts on.

Where a code path needs a whole table only sometimes (a citation graph that looks a cited paper up among every Reference), pass
``DeferredRows``: the table is read on the first look at it and not before, so a run that never looks never pays.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Iterable

REFERENCE_BY_LINEAGE = "referencesByLineageAndVersion"
REFERENCE_BY_CORPUS_AND_ITEM = "referencesByCorpusAndExternalItem"
REFERENCE_BY_CURATION_STATUS = "referencesByCurationStatusKey"
ATTACHMENTS_BY_LINEAGE = "referenceAttachmentsByReferenceLineageAndSortKey"
RELATIONS_BY_SUBJECT_STATE = "semanticRelationsBySubjectState"
RELATIONS_BY_OBJECT_STATE = "semanticRelationsByObjectState"


def reference_state_key(lineage_id: str) -> str:
    return f"reference#{lineage_id}#current"


def _unique_by_id(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for row in rows:
        seen.setdefault(str(row.get("id")), row)
    return list(seen.values())


def references_for_tokens(client: Any, tokens: Iterable[str]) -> list[dict[str, Any]]:
    """The Reference rows a command names by id or lineage id (every version of a named lineage): two lookups per token, however large the table."""
    rows: list[dict[str, Any]] = []
    for token in dict.fromkeys(str(token) for token in tokens if token):
        row = client.get_record("Reference", token)
        if row:
            rows.append(row)
        rows.extend(client.list_by_index(REFERENCE_BY_LINEAGE, token))
    return _unique_by_id(rows)


def references_for_external_items(client: Any, corpus_id: str, external_item_ids: Iterable[str]) -> list[dict[str, Any]]:
    """The Reference rows with these item ids in one corpus (all versions): one key-condition query per item id."""
    rows: list[dict[str, Any]] = []
    for item_id in dict.fromkeys(str(item) for item in external_item_ids if item):
        rows.extend(client.list_by_index(REFERENCE_BY_CORPUS_AND_ITEM, corpus_id, sort_eq=item_id))
    return _unique_by_id(rows)


def reference_by_token(client: Any, token: str, *, corpus_id: str | None = None) -> list[dict[str, Any]]:
    """Rows a person's token names: an id, a lineage id, or an item id (in the given corpus, else in the site's canonical publication corpus). Empty when none."""
    rows = references_for_tokens(client, [token])
    if not rows:
        from .editorial_context import hosted_publication
        corpus_ids = [corpus_id] if corpus_id else [hosted_publication(client)["corpusId"]]   # the site's canonical publication corpus, through its role index
        for candidate in corpus_ids:
            rows.extend(references_for_external_items(client, candidate, [token]))
    return rows


def lineage_ids(references: Iterable[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(row.get("lineageId") or row["id"]) for row in references))


def attachments_for_references(client: Any, references: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every attachment of the lineages of these References (all versions' attachments are keyed by lineage too)."""
    rows: list[dict[str, Any]] = []
    for lineage in lineage_ids(references):
        rows.extend(client.list_by_index(ATTACHMENTS_BY_LINEAGE, lineage))
    return _unique_by_id(rows)


def relations_for_references(client: Any, references: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The current relations that start or end at these References: two queries per lineage."""
    rows: list[dict[str, Any]] = []
    for lineage in lineage_ids(references):
        key = reference_state_key(lineage)
        rows.extend(client.list_by_index(RELATIONS_BY_SUBJECT_STATE, key))
        rows.extend(client.list_by_index(RELATIONS_BY_OBJECT_STATE, key))
    return _unique_by_id(rows)


def subject_relations_for_references(client: Any, references: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The current relations that start at these References (one query per lineage)."""
    rows: list[dict[str, Any]] = []
    for lineage in lineage_ids(references):
        rows.extend(client.list_by_index(RELATIONS_BY_SUBJECT_STATE, reference_state_key(lineage)))
    return _unique_by_id(rows)


def references_with_status(client: Any, corpus_id: str, status: str) -> list[dict[str, Any]]:
    """The References of one corpus in one curation status (``<corpus>#<status>`` partition), every version; callers keep the current ones."""
    return client.list_by_index(REFERENCE_BY_CURATION_STATUS, f"{corpus_id}#{status}")


class DeferredRows(list):
    """A list whose rows are read the first time anything looks at them.

    For a table that only some runs need (every Reference, for a citation that must be found among them): a run that never looks never pays.
    ``loaded`` says whether the read happened.
    """

    def __init__(self, loader: Callable[[], list[dict[str, Any]]], *, on_load: Callable[[], None] | None = None):
        super().__init__()
        self._loader = loader
        self._on_load = on_load
        self.loaded = False

    def _load(self) -> None:
        if not self.loaded:
            self.loaded = True
            if self._on_load:
                self._on_load()
            super().extend(self._loader())

    def __iter__(self):
        self._load()
        return super().__iter__()

    def __len__(self):
        self._load()
        return super().__len__()

    def __bool__(self):
        self._load()
        return super().__len__() > 0

    def __getitem__(self, index):
        self._load()
        return super().__getitem__(index)

    def __contains__(self, item):
        self._load()
        return super().__contains__(item)

    def __reversed__(self):
        self._load()
        return super().__reversed__()

    def __add__(self, other):
        self._load()
        return list(super().__iter__()) + list(other)

    def __radd__(self, other):
        self._load()
        return list(other) + list(super().__iter__())


def targeted_scope(
    client: Any,
    *,
    reference_ids: Iterable[str] | None = None,
    external_item_ids: Iterable[str] | None = None,
    corpus_id: str | None = None,
) -> dict[str, Any] | None:
    """What a "process these References" command needs when the person named them (``--reference`` or ``--external-item-id`` with a corpus).

    ``references`` and ``attachments`` are those rows only. ``all_references`` and ``relations`` are ``DeferredRows`` over the whole tables: only a
    citation graph or a duplicate merge reads them. None when the command is not targeted (it then sweeps a corpus and reads what it did before).
    """
    reference_ids = [token for token in (reference_ids or []) if token]
    external_item_ids = [item for item in (external_item_ids or []) if item]
    if reference_ids:
        references = references_for_tokens(client, reference_ids)
    elif external_item_ids and corpus_id:
        references = references_for_external_items(client, corpus_id, external_item_ids)
    else:
        return None
    return {
        "references": references,
        "attachments": attachments_for_references(client, references),
        "all_references": DeferredRows(lambda: client.list_records("Reference")),
        "relations": DeferredRows(lambda: client.list_records("SemanticRelation")),
    }


def announce_full_read(command: str, model: str, *, why: str) -> None:
    """Say, in the command's output, that it deliberately reads every row of a table (a backfill, an export, an audit). Goes to stderr: stdout stays parseable."""
    print(f"{command}\tfull-table-read\t{model}\t{why}", file=sys.stderr)


def list_every_row(client: Any, model: str, *, command: str, why: str) -> list[dict[str, Any]]:
    """``list_records`` for a command that must visit every row: pages through the table and says so."""
    announce_full_read(command, model, why=why)
    return client.list_records(model)
