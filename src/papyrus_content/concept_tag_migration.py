"""Moves concept tags from the legacy ``related_to`` to ``tagged_with`` (``papyrus relations migrate-concept-tags``; docs/operator-cli.md, docs/story-reporting.md).

Ryan, 2026-11-09: one predicate, one meaning. A story or a Reference tagged with a concept is ``tagged_with``; ``related_to`` stays generic (two References, two concepts).
Every writer now writes ``tagged_with`` and every reader accepts both names, so this migration is the last step: for each legacy ``related_to`` edge whose subject is an
item (a story) or a Reference and whose object is a ``semanticNode``, in any of the states ``current``, ``suggested`` and ``rejected``:

1. write the equivalent ``tagged_with`` row: the same two ends, state, score, confidence, classifier and metadata (provenance, who added it and when, who decided and
   when, the decision, the reason, the note, the explanation), plus ``migratedFromRelationId``; the id is ``reference_link_relation_id("tagged_with", ...)``, so it
   cannot collide with the legacy row. A rejected tag becomes a rejected ``tagged_with`` row, so the rejection is kept and the writers' never-revive rule keeps working;
2. then retire the legacy row by moving it out of every reader's view: ``relationState`` ``superseded`` and the four state keys rewritten with that state (readers
   query ``...#current``, ``...#suggested`` or ``...#rejected``), ``supersededBy`` and ``supersededAt`` in its metadata. Nothing is deleted.

Idempotent and resumable: a retired row is no longer found; a pair whose ``tagged_with`` row exists (a crash between the two steps, or a tag made after the rename) only
has its legacy row retired. The legacy rows are found by the ``semanticRelationsByObjectState`` index, three keys (one per state) for each concept, 25 keys to a request;
the concept list is the one read of the SemanticNode table. No relation scan. Dry run is the default.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .publishing import utc_now_iso
from .reference_links import (
    CONCEPT_TAG_PREDICATE,
    ITEM_CONCEPT_KIND,
    LEGACY_CONCEPT_TAG_PREDICATE,
    REFERENCE_CONCEPT_KIND,
    reference_link_relation_id,
    relation_state_keys,
)
from .relation_types import semantic_relation_type_fields_for_predicate

SUPERSEDED = "superseded"
STATES = ("current", "suggested", "rejected")
SUBJECT_KINDS = ("item", "reference")
KIND_FOR_SUBJECT = {"item": ITEM_CONCEPT_KIND, "reference": REFERENCE_CONCEPT_KIND}
CONCEPTS_PER_BATCH = 50          # 150 index keys, six requests
SAMPLE_SIZE = 10
# Fields of the legacy row the tagged_with row carries over unchanged. `createdAt` and the state keys are not among them (the service sets the first, this module the second).
CARRIED_FIELDS = (
    "relationState", "subjectKind", "subjectId", "subjectLineageId", "subjectVersionNumber", "objectKind", "objectId", "objectLineageId", "objectVersionNumber",
    "subjectVersionKey", "objectVersionKey", "score", "confidence", "rank", "classifierId", "modelVersion", "reviewRecommended", "sourceSnapshotId", "importRunId",
    "importedAt", "newsroomFeedKey",
)


def _metadata(row: dict[str, Any] | None) -> dict[str, Any]:
    raw = (row or {}).get("metadata")
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw or {})


def is_legacy_tag(row: dict[str, Any]) -> bool:
    return (row.get("predicate") == LEGACY_CONCEPT_TAG_PREDICATE and row.get("subjectKind") in SUBJECT_KINDS and row.get("objectKind") == "semanticNode"
            and row.get("relationState") in STATES)


def _index_rows(client: Any, keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    if hasattr(client, "index_many"):
        return client.index_many("semanticRelationsByObjectState", keys)
    return {key: client.list_by_index("semanticRelationsByObjectState", key) for key in keys}


def find_legacy_tags(client: Any, nodes: list[dict[str, Any]], *, limit: int | None = None) -> list[dict[str, Any]]:
    """The legacy ``related_to`` tags (item or Reference to concept) of these concepts, in id order, at most ``limit``. Index reads only."""
    lineages = sorted({str(node.get("lineageId") or node["id"]) for node in nodes})
    found: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(lineages), CONCEPTS_PER_BATCH):
        keys = [f"semanticNode#{lineage}#{state}" for lineage in lineages[offset:offset + CONCEPTS_PER_BATCH] for state in STATES]
        for rows in _index_rows(client, keys).values():
            for row in rows:
                if is_legacy_tag(row):
                    found[str(row["id"])] = row
        if limit is not None and len(found) >= limit:
            break
    ordered = [found[key] for key in sorted(found)]
    return ordered[:limit] if limit is not None else ordered


def target_id_of(row: dict[str, Any]) -> str:
    return reference_link_relation_id(CONCEPT_TAG_PREDICATE, str(row["subjectLineageId"]), str(row["objectLineageId"]))


def tagged_with_record(legacy: dict[str, Any], *, now: str) -> dict[str, Any]:
    """The ``tagged_with`` row equivalent to a legacy ``related_to`` row."""
    state = legacy["relationState"]
    metadata = {**_metadata(legacy), "kind": KIND_FOR_SUBJECT[legacy["subjectKind"]], "migratedFromRelationId": legacy["id"]}
    record: dict[str, Any] = {
        "id": target_id_of(legacy),
        "predicate": CONCEPT_TAG_PREDICATE,
        **semantic_relation_type_fields_for_predicate(CONCEPT_TAG_PREDICATE),
        **{field: legacy.get(field) for field in CARRIED_FIELDS if legacy.get(field) is not None or field == "confidence"},
        **relation_state_keys(legacy["subjectKind"], str(legacy["subjectLineageId"]), "semanticNode", str(legacy["objectLineageId"]), CONCEPT_TAG_PREDICATE, state),
        "updatedAt": now,
        "metadata": json.dumps(metadata, sort_keys=True),
    }
    if record.get("score") is None:   # score sorts two indexes and DynamoDB refuses a null index key
        record["score"] = 1
    return record


def retire_patch(legacy: dict[str, Any], *, superseded_by: str, now: str) -> dict[str, Any]:
    """The update that moves a legacy row out of every reader's view and says where it went."""
    metadata = {**_metadata(legacy), "supersededBy": superseded_by, "supersededAt": now}
    return {
        "id": legacy["id"],
        "relationState": SUPERSEDED,
        **relation_state_keys(legacy["subjectKind"], str(legacy["subjectLineageId"]), "semanticNode", str(legacy["objectLineageId"]), LEGACY_CONCEPT_TAG_PREDICATE, SUPERSEDED),
        "reviewRecommended": False,
        "updatedAt": now,
        "metadata": json.dumps(metadata, sort_keys=True),
    }


def _entry(legacy: dict[str, Any], action: str) -> dict[str, Any]:
    return {"legacyId": legacy["id"], "targetId": target_id_of(legacy), "action": action, "subjectKind": legacy["subjectKind"], "subjectLineageId": legacy["subjectLineageId"],
            "objectLineageId": legacy["objectLineageId"], "state": legacy["relationState"], "provenance": _metadata(legacy).get("provenance")}


def _in_corpora(client: Any, rows: list[dict[str, Any]], corpus_ids: set[str]) -> list[dict[str, Any]]:
    """Keeps the stories' tags and the tags of the References that sit in these corpora (one batched read of the References)."""
    reference_ids = [str(row["subjectId"]) for row in rows if row["subjectKind"] == "reference"]
    references = client.get_records_by_id("Reference", reference_ids) if reference_ids else {}
    return [row for row in rows if row["subjectKind"] != "reference" or str((references.get(str(row["subjectId"])) or {}).get("corpusId")) in corpus_ids]


def migrate_concept_tags(client: Any, nodes: list[dict[str, Any]], *, apply: bool = False, limit: int | None = None, corpus_ids: set[str] | None = None,
                         now: str | None = None) -> dict[str, Any]:
    """Finds the legacy tags and, when ``apply`` is true, migrates them. Returns the report: ``counts`` by (subject kind, state, provenance), ``actions``, a ``sample``
    and one entry per edge. Writing stops at the first error and the report says how far it got (run it again to go on)."""
    now = now or utc_now_iso()
    legacy_rows = find_legacy_tags(client, nodes, limit=limit)
    if corpus_ids:
        legacy_rows = _in_corpora(client, legacy_rows, corpus_ids)
    existing = client.get_records_by_id("SemanticRelation", [target_id_of(row) for row in legacy_rows]) if legacy_rows else {}
    entries = []
    for legacy in legacy_rows:
        present = existing.get(target_id_of(legacy))
        action = "migrate" if present is None else ("resume" if _metadata(present).get("migratedFromRelationId") == legacy["id"] else "retire-only")
        entries.append(_entry(legacy, action))
    report: dict[str, Any] = {
        "generatedAt": now, "apply": apply, "limit": limit, "found": len(entries),
        "counts": [{"subjectKind": kind, "state": state, "provenance": provenance, "count": count}
                   for (kind, state, provenance), count in sorted(Counter((e["subjectKind"], e["state"], str(e["provenance"])) for e in entries).items())],
        "actions": dict(Counter(e["action"] for e in entries)),
        "sample": entries[:SAMPLE_SIZE], "edges": entries, "written": 0, "retired": 0, "error": None,
    }
    if not apply:
        return report
    for legacy, entry in zip(legacy_rows, entries):
        try:
            if entry["action"] == "migrate":
                client.upsert("SemanticRelation", tagged_with_record(legacy, now=now))
                report["written"] += 1
            client.update_record("SemanticRelation", retire_patch(legacy, superseded_by=entry["targetId"], now=now))
            report["retired"] += 1
        except Exception as error:   # noqa: BLE001 - the report must say how far the run got
            report["error"] = f"{legacy['id']}: {error}"
            break
    return report


def write_report(report: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "migration-report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path
