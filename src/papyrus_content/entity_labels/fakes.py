"""An in-memory site for the concept label tests and specs. It answers only the index queries the label code makes, counts every whole-table list
(``scans``) so a test can prove a lookup read none, and applies partial updates the way the data API does (a ``None`` removes the field)."""
from __future__ import annotations

import copy
from typing import Any

INDEXES = {
    "entityLabelsByEntity": ("EntityLabel", "entityKey"),
    "entityLabelsByName": ("EntityLabel", "nameKey"),
    "entityLabelsByWork": ("EntityLabel", "workKey"),
    "semanticNodesByLineage": ("SemanticNode", "lineageId"),
    "semanticNodesByNodeKey": ("SemanticNode", "nodeKey"),
}


class FakeSite:
    def __init__(self, primary: str = "en", tenant_id: str | None = None):
        self.tables: dict[str, dict[str, dict[str, Any]]] = {"SemanticNode": {}, "EntityLabel": {}}
        self.primary = primary
        self.tenant_id = tenant_id
        self.scans = 0
        self.queries: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str, str]] = []

    def primary_language(self) -> str:
        return self.primary

    def add_node(self, lineage: str, key: str, name: str, *, aliases: list[str] | None = None, description: str = "", status: str = "accepted", language: str | None = None) -> dict:
        row = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "nodeKey": key, "nodeKind": key.split("--")[0],
               "displayName": name, "aliases": aliases or [], "description": description, "status": status, **({"language": language} if language else {})}
        self.tables["SemanticNode"][row["id"]] = row
        return row

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        assert "listSemanticNodes" in query
        return {"listSemanticNodes": {"items": copy.deepcopy(list(self.tables["SemanticNode"].values())), "nextToken": None}}

    def list_by_index(self, index: str, key: str, **_: Any) -> list[dict]:
        model, field = INDEXES[index]
        self.queries.append((index, key))
        return copy.deepcopy([row for row in self.tables[model].values() if row.get(field) == key])

    def get_record(self, model: str, record_id: str) -> dict | None:
        return copy.deepcopy(self.tables[model].get(record_id))

    def create_record(self, model: str, row: dict) -> None:
        assert row["id"] not in self.tables[model], f"{model} {row['id']} exists"
        self.writes.append(("create", model, row["id"]))
        self.tables[model][row["id"]] = copy.deepcopy({k: v for k, v in row.items() if v is not None})

    def update_record(self, model: str, row: dict) -> None:
        self.writes.append(("update", model, row["id"]))
        stored = self.tables[model][row["id"]]
        for name, value in row.items():
            if value is None:
                stored.pop(name, None)
            else:
                stored[name] = copy.deepcopy(value)

    def delete_record(self, model: str, record_id: str) -> None:
        self.writes.append(("delete", model, record_id))
        del self.tables[model][record_id]

    def list_records(self, model: str, **_: Any) -> list[dict]:
        self.scans += 1
        return copy.deepcopy(list(self.tables[model].values()))

    safe_list_records = list_records
