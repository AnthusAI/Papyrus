"""In-memory stand-in for PapyrusGraphQLAuthoringClient, shared by newsroom tests."""

from __future__ import annotations

import copy
from typing import Any

from papyrus_content.graphql_authoring import INDEX_DEFINITIONS

INDEX_MODELS = {
    "itemBySlug": "Item",
    "mediaAssetsByItemAndSortKey": "MediaAsset",
    "publishedMediaAssetsByItemAndSortKey": "PublishedMediaAsset",
    "modelAttachmentsByOwnerRoleAndSortKey": "ModelAttachment",
}


class FakeAuthoringClient:
    def __init__(
        self,
        records: dict[str, list[dict[str, Any]]] | None = None,
        attachments: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
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

    def list_by_index(self, index_name: str, key_value: str, **_kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("list_by_index", index_name, key_value))
        partition_key = INDEX_DEFINITIONS[index_name]["partitionKey"]
        model_name = INDEX_MODELS[index_name]
        return [copy.deepcopy(row) for row in self._table(model_name).values() if row.get(partition_key) == key_value]

    def upsert(self, model_name: str, payload: dict[str, Any]) -> str:
        self.calls.append(("upsert", model_name, payload["id"]))
        existed = payload["id"] in self._table(model_name)
        self._table(model_name)[payload["id"]] = copy.deepcopy(payload)
        self._maybe_fail("upsert", model_name)
        return "updated" if existed else "created"

    def update_record(self, model_name: str, payload: dict[str, Any]) -> None:
        self.calls.append(("update", model_name, payload["id"]))
        self.updates.append((model_name, payload))
        row = self._table(model_name).setdefault(payload["id"], {})
        row.update(copy.deepcopy(payload))
        self._maybe_fail("update", model_name)

    def delete_record(self, model_name: str, record_id: str) -> None:
        self.calls.append(("delete", model_name, record_id))
        self._table(model_name).pop(record_id, None)
        self._maybe_fail("delete", model_name)

    def write_calls(self) -> list[tuple[str, str, Any]]:
        return [call for call in self.calls if call[0] in ("upsert", "update", "delete")]
