"""In-memory stand-ins for the Announcement and Delivery specs: a backend that answers only what the records use, and a store for the Deliveries' words.

The backend reads its indexes from the real ``INDEX_DEFINITIONS``, so a spec fails when an index the code names does not exist or is read with another key. It has no
call that lists a table: a read that is not a get or an index query raises. Rows are kept as AppSync returns them, JSON fields as text. No network, no AWS.
"""
from __future__ import annotations

import copy
from typing import Any, Iterator

from ..graphql_authoring import INDEX_DEFINITIONS
from .deliveries import ROLE, AttachmentFiles

_FIELD_MODEL = {
    "listAnnouncementDecisionsByDedupeKeyAndCreatedAt": "AnnouncementDecision",
    "listAnnouncementDecisionsByStateAndReleaseAt": "AnnouncementDecision",
    "listDeliveriesByAnnouncementAndCreatedAt": "Delivery",
    "listDeliveriesByAccountKeyAndCreatedAt": "Delivery",
    "listDeliveriesByDueKeyAndDueAt": "Delivery",
    "listDeliveriesByExampleKeyAndExampleAt": "Delivery",
    "listSemanticRelationsByObjectState": "SemanticRelation",
    "listSemanticRelationsBySubjectState": "SemanticRelation",
}


class RecordsBackend:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, dict[str, Any]]] = {}
        self.reads: list[tuple[str, str]] = []   # (index, partition value) of every index query
        self.gets: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str, str]] = []   # (operation, model, id)
        self._failures: list[tuple[str, str, str]] = []

    # --- failures a spec asks for -----------------------------------------------------------------------------------------------------------------

    def fail_next(self, operation: str, model: str, message: str = "network is down") -> None:
        """The next ``operation`` ("create", "update") on ``model`` raises, once, as a crash or a lost connection would."""
        self._failures.append((operation, model, message))

    def _maybe_fail(self, operation: str, model: str) -> None:
        for index, (op, name, message) in enumerate(self._failures):
            if (op, name) == (operation, model):
                del self._failures[index]
                raise RuntimeError(message)

    # --- the client's calls -----------------------------------------------------------------------------------------------------------------------

    def get_record(self, model: str, record_id: str) -> dict[str, Any] | None:
        self.gets.append((model, record_id))
        return copy.deepcopy(self.records.get(model, {}).get(record_id))

    def create_record(self, model: str, record: dict[str, Any]) -> None:
        self._maybe_fail("create", model)
        table = self.records.setdefault(model, {})
        if record["id"] in table:
            raise RuntimeError("GraphQL request failed: The conditional request failed")
        table[record["id"]] = copy.deepcopy({key: value for key, value in record.items() if value is not None})
        self.writes.append(("create", model, record["id"]))

    def update_record(self, model: str, record: dict[str, Any]) -> None:
        self._maybe_fail("update", model)
        row = self.records[model][record["id"]]
        for key, value in copy.deepcopy(record).items():
            if value is None:
                row.pop(key, None)   # an explicit null removes the attribute
            else:
                row[key] = value
        self.writes.append(("update", model, record["id"]))

    def update_record_if(self, model: str, record: dict[str, Any], condition: dict[str, Any]) -> bool:
        row = self.records.get(model, {}).get(record["id"])
        if row is None or not _holds(row, condition):
            return False
        self.update_record(model, record)
        return True

    def upsert(self, model: str, record: dict[str, Any]) -> str:
        if record["id"] in self.records.get(model, {}):
            self.update_record(model, record)
            return "updated"
        self.create_record(model, record)
        return "created"

    def list_by_index(self, index: str, key: str, *, limit: int = 100, sort_eq: str | None = None, sort_condition: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        definition = INDEX_DEFINITIONS[index]
        self.reads.append((index, key))
        rows = self._partition(index, definition, key)
        sort_key = definition.get("sortKey")
        condition = {"eq": sort_eq} if sort_eq is not None else sort_condition
        if condition is not None:
            assert sort_key, f"index {index} has no sort key"
            rows = [row for row in rows if _meets(row[sort_key], condition)]
        return copy.deepcopy(sorted(rows, key=lambda row: str(row.get(sort_key) or "")) if sort_key else rows)

    def iterate_newest_first(self, index: str, key: str, *, sort_before: str | None = None, **_: Any) -> Iterator[dict[str, Any]]:
        definition = INDEX_DEFINITIONS[index]
        self.reads.append((index, key))
        rows = self._partition(index, definition, key)
        if sort_before is not None:
            rows = [row for row in rows if str(row[definition["sortKey"]]) < sort_before]
        yield from copy.deepcopy(sorted(rows, key=lambda row: str(row.get(definition["sortKey"]) or ""), reverse=True))

    def _partition(self, index: str, definition: dict[str, Any], key: str) -> list[dict[str, Any]]:
        model = _FIELD_MODEL[definition["field"]]
        partition, sort_key = definition["partitionKey"], definition.get("sortKey")
        # A row is in a sparse index only when it has every key attribute.
        return [row for row in self.records.get(model, {}).values() if row.get(partition) == key and (sort_key is None or row.get(sort_key) is not None)]

    # --- what a spec reads ------------------------------------------------------------------------------------------------------------------------

    def rows(self, model: str) -> list[dict[str, Any]]:
        return list(self.records.get(model, {}).values())


def _meets(value: Any, condition: dict[str, Any]) -> bool:
    for operator, operand in condition.items():
        if operator == "eq" and not value == operand:
            return False
        if operator == "le" and not value <= operand:
            return False
        if operator == "ge" and not value >= operand:
            return False
        if operator == "between" and not operand[0] <= value <= operand[1]:
            return False
    return True


def _holds(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    for field, test in condition.items():
        value = row.get(field)
        for operator, operand in test.items():
            if operator == "eq" and value != operand:
                return False
            if operator == "ne" and value == operand:
                return False
            if operator == "attributeExists" and (value is not None) != operand:
                return False
    return True


class MemoryDeliveryFiles:
    """The Deliveries' files (a version's words ``v<n>``, a candidate's ``c<n>``). Refuses what the upload function refuses (a role or media type it does not allow, an owner
    row that does not exist yet) and a second write of a file that holds other words (a version is never overwritten), and names each file's key and hash exactly as the real
    attachment code does. ``texts`` is keyed by ``MemoryDeliveryFiles.file_key(delivery, name)``."""

    def __init__(self, backend: RecordsBackend | None = None) -> None:
        self.texts: dict[str, str] = {}
        self.backend = backend
        self._real = AttachmentFiles(None)

    @staticmethod
    def file_key(delivery: str, name: str = "v1") -> str:
        return f"{delivery}@{name}"

    def describe(self, delivery: str, text: str, name: str = "v1") -> dict[str, str]:
        return self._real.describe(delivery, text, name)

    def put(self, delivery: str, text: str, *, now: str, name: str = "v1") -> None:
        from ..upload_rules_fake import assert_upload_accepted

        assert_upload_accepted({"role": ROLE, "mediaType": "text/markdown"})
        if self.backend is not None and delivery not in self.backend.records.get("Delivery", {}):
            raise RuntimeError(f"GraphQL request failed: Cannot attach payload to missing Delivery {delivery}.")
        key = self.file_key(delivery, name)
        if key in self.texts and self.texts[key] != text:
            raise AssertionError(f"{key} holds other words already: a version is written once and never overwritten")
        self.texts[key] = text

    def get(self, delivery: str, name: str = "v1") -> str | None:
        return self.texts.get(self.file_key(delivery, name))
