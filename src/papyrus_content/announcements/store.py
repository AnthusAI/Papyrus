"""Where announcements are kept: catalog rows in DynamoDB, the text in S3.

``Announcement`` rows have a deterministic id, ``<accountId>#<lineageId>``, created with a condition so a second event for the same Story and account finds the
row instead of making another. A row is the audit record: who (the actor), what (the Story version and the checks), when (the state history), the post id, what each
call cost, the mode and the outcome. The post's text, the link and every check's detail are one JSON document in S3 (a ModelAttachment owned by the row), never in
DynamoDB. The rows of one account are read through the one index (``accountId`` + ``createdAt``), newest first; nothing lists a table.

``AnnouncementSettings`` is one row, id ``settings``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Protocol

from . import budget as budget_module
from . import settings as settings_module

ANNOUNCEMENT_MODEL = "Announcement"
SPEND_MODEL = "AnnouncementSpend"
INDEX = "announcementsByAccountAndCreatedAt"
OWNER_KIND = "announcement"
ROLE = "announcement_document"

# States. ``posting``: handed to Caducus, not yet delivered. ``blocked`` carries a reason. ``dry_run``, ``posted``, ``failed`` and ``withdrawn`` are final until an editor acts.
POSTING, POSTED, FAILED, BLOCKED, DRY_RUN, WITHDRAWN = "posting", "posted", "failed", "blocked", "dry_run", "withdrawn"
STATES = (POSTING, POSTED, FAILED, BLOCKED, DRY_RUN, WITHDRAWN)
STATE_LABELS = {POSTING: "Posting", POSTED: "Posted", FAILED: "Failed", BLOCKED: "Blocked", DRY_RUN: "Dry run: not sent", WITHDRAWN: "Withdrawn"}

PAUSED, BUDGET_REACHED, ACCOUNT_NEEDS_RECONNECTING, CHECK_FAILED = "paused", "budget_reached", "account_needs_reconnecting", "check_failed"
BLOCK_LABELS = {
    PAUSED: "Blocked: paused",
    BUDGET_REACHED: "Blocked: budget reached",
    ACCOUNT_NEEDS_RECONNECTING: "Blocked: account needs reconnecting",
    CHECK_FAILED: "Blocked: check failed",
}


class AlreadyAnnounced(Exception):
    """A row for this account and Story lineage exists. ``row`` is it."""

    def __init__(self, row: Mapping[str, Any]):
        super().__init__(f"{row.get('id')} already exists")
        self.row = dict(row)


def announcement_id(account_id: str, lineage_id: str) -> str:
    return f"{account_id}#{lineage_id}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DocumentFiles(Protocol):
    def put(self, row_id: str, document: Mapping[str, Any], *, now: str) -> None: ...

    def get(self, row_id: str) -> dict[str, Any] | None: ...


class AttachmentFiles:
    """The announcement document as a ModelAttachment of the row (``newsroom/payloads/announcement/<id>/announcement-document/announcement.json``)."""

    def __init__(self, client: Any):
        self.client = client

    def put(self, row_id: str, document: Mapping[str, Any], *, now: str) -> None:
        from papyrus_content.model_attachments import build_json_model_payload_attachment, upload_attachment_body

        entry = build_json_model_payload_attachment(
            {"ownerKind": OWNER_KIND, "ownerId": row_id, "role": ROLE, "sortKey": "announcement", "filename": "announcement.json", "content": dict(document), "now": now}
        )
        upload_attachment_body(self.client, entry["attachment"], entry["body"])

    def get(self, row_id: str) -> dict[str, Any] | None:
        from papyrus_content.model_attachments import download_attachment_buffer

        wanted = [a for a in self.client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", row_id, limit=100)
                  if a.get("role") == ROLE and str(a.get("status") or "active").lower() not in {"deleted", "aborted"}]
        if not wanted:
            return None
        body = download_attachment_buffer(self.client, wanted[0])
        return json.loads(body.decode("utf-8")) if body is not None else None


class AnnouncementStore:
    def __init__(self, client: Any, files: DocumentFiles | None = None):
        self.client = client
        self.files = files or AttachmentFiles(client)

    # --- settings -----------------------------------------------------------------------------------------------------------------------------------

    def settings(self) -> dict[str, Any]:
        row = self.client.get_record(settings_module.MODEL, settings_module.SETTINGS_ID)
        return dict(row) if row else settings_module.blank()

    def save_settings(self, values: Mapping[str, Any], *, actor: str, now: str | None = None) -> dict[str, Any]:
        """Write the settings row whole (create the first time). ``values`` are already checked."""
        existing = self.client.get_record(settings_module.MODEL, settings_module.SETTINGS_ID)
        record = {**{key: value for key, value in values.items() if value is not None}, "id": settings_module.SETTINGS_ID, "updatedBy": actor, "updatedAt": now or now_iso()}
        (self.client.update_record if existing else self.client.create_record)(settings_module.MODEL, record)
        return record

    # --- announcements ------------------------------------------------------------------------------------------------------------------------------

    def get(self, account_id: str, lineage_id: str) -> dict[str, Any] | None:
        row = self.client.get_record(ANNOUNCEMENT_MODEL, announcement_id(account_id, lineage_id))
        return dict(row) if row else None

    def get_by_id(self, row_id: str) -> dict[str, Any] | None:
        row = self.client.get_record(ANNOUNCEMENT_MODEL, row_id)
        return dict(row) if row else None

    def create(self, row: Mapping[str, Any], document: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Take the row for this account and Story, or raise ``AlreadyAnnounced`` with the row that holds it. The row comes first (the upload function refuses a
        document whose owner does not exist), then the document (text, link, checks)."""
        found = self.get_by_id(row["id"])
        if found:
            raise AlreadyAnnounced(found)
        try:
            self.client.create_record(ANNOUNCEMENT_MODEL, dict(row))
        except RuntimeError as error:
            if "conditional" in str(error).lower():
                raise AlreadyAnnounced(self.get_by_id(row["id"]) or row) from error
            raise
        if document is not None:
            self.files.put(row["id"], document, now=row["createdAt"])
        return dict(row)

    def update(self, row: Mapping[str, Any], changes: Mapping[str, Any], *, note: str, by: str, now: str | None = None, document: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Change a row and add one line to its state history: when, by whom, the state it moved to and why. The history is never rewritten."""
        now = now or now_iso()
        state = changes.get("state", row.get("state"))
        history = [*(_json_list(row.get("history"))), {"at": now, "by": by, "state": state, "note": note}]
        updated = {**row, **changes, "history": history, "updatedAt": now}
        if document is not None:
            self.files.put(row["id"], document, now=now)
        self.client.update_record(ANNOUNCEMENT_MODEL, {"id": row["id"], **{key: value for key, value in updated.items() if key != "id" and value is not None}})
        return updated

    # --- spend --------------------------------------------------------------------------------------------------------------------------------------

    def spent(self, account_id: str, start: Any) -> Any:
        row = self.client.get_record(SPEND_MODEL, budget_module.spend_id(account_id, start))
        return (row or {}).get("total")

    def add_spend(self, account_id: str, start: Any, amount: Any, *, now: str | None = None) -> str:
        """Raise the cycle's counter by ``amount`` and return the new total. Charges arrive one at a time (see ``budget``)."""
        row_id = budget_module.spend_id(account_id, start)
        row = self.client.get_record(SPEND_MODEL, row_id)
        total = str(budget_module.money_sum((row or {}).get("total"), amount))
        record = {"id": row_id, "accountId": account_id, "cycleStart": start.isoformat(), "total": total, "updatedAt": now or now_iso()}
        (self.client.update_record if row else self.client.create_record)(SPEND_MODEL, record)
        return total

    def document(self, row_id: str) -> dict[str, Any] | None:
        return self.files.get(row_id)

    def recent(self, account_id: str) -> Iterator[dict[str, Any]]:
        """The account's rows, newest first, one page at a time. Stop reading and no further page is fetched."""
        yield from (dict(row) for row in self.client.iterate_newest_first(INDEX, account_id))

    def since(self, account_id: str, since_iso: str) -> list[dict[str, Any]]:
        """The account's rows created at or after ``since_iso``, newest first; the read stops at the first older row."""
        rows = []
        for row in self.recent(account_id):
            if str(row.get("createdAt") or "") < since_iso:
                break
            rows.append(row)
        return rows


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if isinstance(value, list) else []
