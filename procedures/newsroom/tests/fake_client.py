"""In-memory stand-in for PapyrusGraphQLAuthoringClient, shared by newsroom tests."""

from __future__ import annotations

import copy
import re
from typing import Any

from papyrus_content.graphql_authoring import INDEX_DEFINITIONS

INDEX_MODELS = {
    "referencesByCorpusAndExternalItem": "Reference",
    "knowledgeCorporaByRoleAndName": "KnowledgeCorpus",
    "itemBySlug": "Item",
    "itemsByLineageAndVersion": "Item",
    "itemScheduleByLineage": "Item",
    "mediaAssetsByItemAndSortKey": "MediaAsset",
    "publishedMediaAssetsByItemAndSortKey": "PublishedMediaAsset",
    "modelAttachmentsByOwnerRoleAndSortKey": "ModelAttachment",
    "messagesByThreadAndSequence": "Message",
    "messageThreadsByAnchor": "MessageThread",
    "referenceAttachmentsByReferenceLineageAndSortKey": "ReferenceAttachment",
    "semanticRelationsBySubjectState": "SemanticRelation",
    "semanticRelationsByObjectState": "SemanticRelation",
    "referencesByLineageAndVersion": "Reference",
    "assignmentsByItemLineageAndCreatedAt": "Assignment",
    "itemsByParent": "Item",
    "itemsByStage": "Item",
    "itemsByHeadStage": "Item",
    "itemHeadFieldsByStage": "Item",
    "itemHeadFieldsWithKeyByStage": "Item",
    "itemsByLanguageGroup": "Item",
    "itemLanguageFieldsByVersionState": "Item",
    "publishedItemsByTypeStatus": "PublishedItem",
}


#: Every fake made since the last reset: features_backend/environment.py checks the head stage key invariant on each after every scenario.
INSTANCES: list["FakeAuthoringClient"] = []


def head_stage_key_violations(client: "FakeAuthoringClient") -> list[str]:
    """The story lineages written through this fake that break the head stage key rule (docs/plans/story-head-stage-index.md): a lineage has at
    most one row carrying ``headStageKey``, that row is not superseded and the key names its stage (after any tenant prefix), and a lineage in
    which the scenario created or saved a row, and that has a row not superseded with a stage, has exactly one head."""
    items = client.tables.get("Item", {})
    written = {call[2] for call in client.calls if call[1] == "Item" and call[0] in ("create", "upsert", "update")}
    created = {call[2] for call in client.calls if call[1] == "Item" and call[0] in ("create", "upsert")}
    lineages = {str(items[row_id].get("lineageId") or row_id) for row_id in written if row_id in items}
    # A lineage that only had rows seeded before the head stage key existed and was then only updated (a metadata change) may have no head yet:
    # the backfill gives it one. A lineage this scenario created or saved a row in must have one.
    strict = {str(items[row_id].get("lineageId") or row_id) for row_id in created if row_id in items}
    problems = []
    for lineage in sorted(lineages):
        rows = [row for row in items.values() if str(row.get("lineageId") or row["id"]) == lineage]
        heads = [row for row in rows if row.get("headStageKey")]
        if len(heads) > 1:
            problems.append(f"{lineage}: {len(heads)} rows carry headStageKey ({', '.join(row['id'] for row in heads)})")
        for row in heads:
            if row.get("versionState") == "superseded":
                problems.append(f"{lineage}: superseded row {row['id']} carries headStageKey {row['headStageKey']!r}")
            elif str(row["headStageKey"]).rsplit("#", 1)[-1] != row.get("stage"):
                problems.append(f"{lineage}: {row['id']} has headStageKey {row['headStageKey']!r} but stage {row.get('stage')!r}")
        if not heads and lineage in strict and any(row.get("stage") and row.get("versionState") != "superseded" for row in rows):
            problems.append(f"{lineage}: no row carries headStageKey, though {', '.join(row['id'] for row in rows if row.get('stage') and row.get('versionState') != 'superseded')} is not superseded")
    return problems


class FakeAuthoringClient:
    tenant_id: str | None = None   # the real client always has one; None is a backend with no tenant

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """The only query a fake answers is the schema question of the deploy render: a backend that serves every field the tools select."""
        from papyrus_content.live_schema import selected_fields
        selected = selected_fields()
        asked = re.findall(r'(t\d+): __type\(name: "(\w+)"\)', query)
        return {alias: {"fields": [{"name": field} for field in sorted(selected[name])]} for alias, name in asked}

    def __init__(
        self,
        records: dict[str, list[dict[str, Any]]] | None = None,
        attachments: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        INSTANCES.append(self)
        self.updates: list[tuple[str, dict[str, Any]]] = []
        self.tables: dict[str, dict[str, dict[str, Any]]] = {}
        self.calls: list[tuple[str, str, Any]] = []
        self.fail_after: tuple[str, str] | None = None
        for model, rows in (records or {}).items():
            for row in rows:
                self.tables.setdefault(model, {})[row["id"]] = copy.deepcopy(row)
        for owner_id, rows in (attachments or {}).items():
            for row in rows:
                self.tables.setdefault("ModelAttachment", {})[row["id"]] = {**copy.deepcopy(row), "ownerId": owner_id}

    def _table(self, model_name: str) -> dict[str, dict[str, Any]]:
        return self.tables.setdefault(model_name, {})

    def _maybe_fail(self, operation: str, model_name: str) -> None:
        if self.fail_after == (operation, model_name):
            self.fail_after = None
            raise RuntimeError(f"injected failure after {operation} {model_name}")

    def get_record(self, model_name: str, record_id: str) -> dict[str, Any] | None:
        self.calls.append(("get", model_name, record_id))
        row = self._table(model_name).get(record_id)
        return copy.deepcopy(row) if row is not None else None

    def list_records(self, model_name: str) -> list[dict[str, Any]]:
        self.calls.append(("list", model_name, None))
        return [copy.deepcopy(row) for row in self._table(model_name).values()]

    def list_published_item_summaries(self) -> list[dict[str, Any]]:
        self.calls.append(("list", "PublishedItemSummary", None))
        summary_fields = (
            "id sourceItemId itemLineageId versionNumber type status slug section title aliases publishedAt versionPublishedAt versionPublishedBy metadata"
        ).split()
        return [
            {name: copy.deepcopy(row.get(name)) for name in summary_fields}
            for row in self._table("PublishedItem").values()
        ]

    def list_by_index(self, index_name: str, key_value: str, *, sort_eq: str | None = None, **_kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("list_by_index", index_name, key_value))
        partition_key = INDEX_DEFINITIONS[index_name]["partitionKey"]
        sort_key = INDEX_DEFINITIONS[index_name].get("sortKey") if sort_eq is not None else None
        model_name = INDEX_MODELS[index_name]
        return [copy.deepcopy(row) for row in self._table(model_name).values()
                if row.get(partition_key) == key_value and (sort_key is None or row.get(sort_key) == sort_eq)]

    def get_records_by_id(self, model_name: str, record_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {record_id: copy.deepcopy(row) for record_id in record_ids if (row := self._table(model_name).get(record_id)) is not None}

    def iterate_newest_first(self, index_name: str, key_value: str, *, page_size: int = 50):
        rows = self.list_by_index(index_name, key_value)
        yield from sorted(rows, key=lambda row: str(row.get("updatedAt") or ""), reverse=True)

    def list_reference_attachments_by_lineage(self, reference_lineage_id: str) -> list[dict[str, Any]]:
        return self.list_by_index("referenceAttachmentsByReferenceLineageAndSortKey", reference_lineage_id)

    def list_semantic_relations_by_subject_state(self, key: str) -> list[dict[str, Any]]:
        return self.list_by_index("semanticRelationsBySubjectState", key)

    def list_semantic_relations_by_object_state(self, key: str) -> list[dict[str, Any]]:
        return self.list_by_index("semanticRelationsByObjectState", key)

    def recent_procedure_runs(self, procedure_key: str, limit: int = 25) -> list[dict[str, Any]]:
        self.calls.append(("recent_procedure_runs", "ProcedureRun", procedure_key))
        rows = [row for row in self._table("ProcedureRun").values() if row.get("procedureKey") == procedure_key]
        rows.sort(key=lambda row: str(row.get("requestedAt") or ""), reverse=True)
        return [copy.deepcopy(row) for row in rows[:limit]]

    def upsert(self, model_name: str, payload: dict[str, Any]) -> str:
        self.calls.append(("upsert", model_name, payload["id"]))
        existed = payload["id"] in self._table(model_name)
        self._table(model_name)[payload["id"]] = copy.deepcopy(payload)
        self._maybe_fail("upsert", model_name)
        return "updated" if existed else "created"

    def create_record(self, model_name: str, payload: dict[str, Any]) -> None:
        self.calls.append(("create", model_name, payload["id"]))
        if payload["id"] in self._table(model_name):
            raise ValueError(f"{model_name} {payload['id']} already exists")
        self._table(model_name)[payload["id"]] = copy.deepcopy(payload)

    def update_record(self, model_name: str, payload: dict[str, Any]) -> None:
        self.calls.append(("update", model_name, payload["id"]))
        self.updates.append((model_name, payload))
        row = self._table(model_name).setdefault(payload["id"], {})
        row.update(copy.deepcopy(payload))
        self._maybe_fail("update", model_name)

    def has_schedule_fields(self) -> bool:
        return True

    def update_record_if(self, model_name: str, payload: dict[str, Any], condition: dict[str, Any]) -> bool:
        """A conditional update as AppSync does it: the whole write or nothing, decided on the stored row (``eq``, ``ne``, ``attributeExists``, ``or``)."""
        row = self._table(model_name).get(payload["id"], {})

        def holds(rule: dict[str, Any]) -> bool:
            for name, test in rule.items():
                if name == "or":
                    if not any(holds(option) for option in test):
                        return False
                elif name == "and":
                    if not all(holds(option) for option in test):
                        return False
                else:
                    value = row.get(name)
                    for operator, expected in test.items():
                        if operator == "eq" and value != expected:
                            return False
                        if operator == "ne" and value == expected:
                            return False
                        if operator == "attributeExists" and (value is not None) != expected:
                            return False
            return True

        self.calls.append(("conditional-update", model_name, payload["id"]))
        if not holds(condition):
            return False
        self.update_record(model_name, payload)
        return True

    def list_schedule(self, state: str, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(("list_schedule", state, (start, end)))
        return [copy.deepcopy(row) for row in self._table("Item").values()
                if row.get("scheduleState") == state and (start is None or row["scheduledPublishAt"] >= start) and (end is None or row["scheduledPublishAt"] <= end)]

    def delete_record(self, model_name: str, record_id: str) -> None:
        self.calls.append(("delete", model_name, record_id))
        self._table(model_name).pop(record_id, None)
        self._maybe_fail("delete", model_name)

    def write_calls(self) -> list[tuple[str, str, Any]]:
        return [call for call in self.calls if call[0] in ("create", "upsert", "update", "delete")]
