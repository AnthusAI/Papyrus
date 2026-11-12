"""An in-memory backend for the guideline store tests and specs. It serves only the indexes the store and the operations read (the two below and the publication's corpus) and fails on anything else, so a
test proves that no read lists or scans a table. No network, no AWS."""
from __future__ import annotations

import copy
from typing import Any

from papyrus_content.upload_rules_fake import assert_upload_accepted


class FakePolicies:
    """The editorial policies of the fake site, with the store calls the derived-policy sync makes. Nothing else is reachable."""

    def __init__(self):
        self.rows: list[dict] = []
        self.writes: list[tuple[str, str]] = []

    def list_policies(self) -> list[dict]:
        return copy.deepcopy(self.rows)

    def create_policy(self, record: dict) -> None:
        self.writes.append(("create", record["id"]))
        self.rows.append(copy.deepcopy(record))

    def update_policy(self, record: dict) -> None:
        self.writes.append(("update", record["id"]))
        next(row for row in self.rows if row["id"] == record["id"]).update(copy.deepcopy(record))


class FakeBackend:
    def __init__(self, *, tenant_id: str | None = None, publication: str = "example"):
        self.tenant_id = tenant_id
        self.endpoint = None
        self.policies = FakePolicies()
        self.corpora = [{"id": f"knowledge-corpus-{publication}", "name": publication.title(), "role": "canonical"}]
        self.items: list[dict] = []
        self.attachments: list[dict] = []
        self.bodies: dict[str, bytes] = {}
        self.writes: list[tuple[str, str, dict]] = []
        self.reads: list[tuple[str, str]] = []

    # the index queries the store may make
    def list_by_index(self, index: str, key: str, **_: Any) -> list[dict]:
        self.reads.append((index, key))
        if index == "knowledgeCorporaByRoleAndName":
            return copy.deepcopy(self.corpora)
        if index == "itemBySlug":
            return copy.deepcopy([row for row in self.items if row.get("slug") == key])
        if index == "modelAttachmentsByOwnerRoleAndSortKey":
            return copy.deepcopy([row for row in self.attachments if row.get("ownerId") == key])
        raise AssertionError(f"unexpected index {index}")

    def create_record(self, model: str, record: dict) -> None:
        assert model == "Item"
        self.writes.append(("create", model, copy.deepcopy(record)))
        self.items.append({**copy.deepcopy(record), "tenantId": self.tenant_id})

    def update_record(self, model: str, record: dict) -> None:
        assert model == "Item"
        self.writes.append(("update", model, copy.deepcopy(record)))
        next(row for row in self.items if row["id"] == record["id"]).update(copy.deepcopy(record))

    # any list or scan is a failure
    def safe_list_records(self, model: str):
        raise AssertionError(f"scanned {model}")

    list_records = safe_list_records


class FakeFiles:
    """The S3 side: what the upload function does with an attachment (it creates the ModelAttachment row) and what a download returns."""

    def __init__(self, backend: FakeBackend):
        self.backend = backend

    def put(self, attachment: dict, body: bytes) -> dict:
        assert_upload_accepted(attachment)
        self.backend.attachments.append(copy.deepcopy(attachment))
        self.backend.bodies[attachment["storagePath"]] = bytes(body)
        return attachment

    def get(self, attachment: dict) -> bytes | None:
        return self.backend.bodies.get(attachment["storagePath"])
