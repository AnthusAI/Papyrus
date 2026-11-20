"""A run's bodies live in S3, not in the catalog (PPY-8b131e, slice A4 of docs/design/always-on-agents-architecture.md).

`ProcedureRun` is a catalog row: keys and short summaries. What a run was given and what it made (its input, its normalized input, its output and its error) can
be whole documents, and text does not belong in DynamoDB. One run has one attachment, a `ModelAttachment` of owner kind `procedureRun` and role `run_body`: a JSON
file holding those four, each present or null. This module is the one place that writes and reads it.

Reading a run whose attachment is missing raises `RunBodyMissing` and says which run: it never returns an empty body in its place.
"""
from __future__ import annotations

import json
from typing import Any

from .model_attachments import build_model_payload_attachment, download_attachment_buffer, upload_attachment_body

OWNER_KIND = "procedureRun"
ROLE = "run_body"
SORT_KEY = "body"
FILENAME = "run-body.json"
BODY_FIELDS = ("input", "normalizedInput", "output", "error")
ATTACHMENTS_BY_OWNER_INDEX = "modelAttachmentsByOwnerRoleAndSortKey"


class RunBodyMissing(LookupError):
    """A run whose body attachment does not exist (or is not ready)."""


def body_of(fields: dict[str, Any]) -> dict[str, Any]:
    """The four bodies from whatever the caller holds: a field that is absent is stored as null."""
    unknown = sorted(set(fields) - set(BODY_FIELDS))
    if unknown:
        raise ValueError(f"a run body holds {', '.join(BODY_FIELDS)}; not {', '.join(unknown)}")
    return {name: fields.get(name) for name in BODY_FIELDS}


def write_run_body(client, run_id: str, fields: dict[str, Any], *, now: str) -> dict[str, Any]:
    """Store the run's bodies as its one attachment, replacing the earlier body of the same run (the attachment's id is made from the run's id)."""
    content = json.dumps(body_of(fields), sort_keys=True, separators=(",", ":"), default=str)
    built = build_model_payload_attachment({
        "ownerKind": OWNER_KIND, "ownerId": run_id, "ownerLineageId": run_id, "role": ROLE, "sortKey": SORT_KEY, "filename": FILENAME,
        "mediaType": "application/json", "content": content, "status": "active", "now": now})
    return upload_attachment_body(client, built["attachment"], built["body"])


def read_run_body(client, run_id: str) -> dict[str, Any]:
    found = [attachment for attachment in client.list_by_index(ATTACHMENTS_BY_OWNER_INDEX, run_id, limit=100)
             if attachment.get("ownerKind") == OWNER_KIND and attachment.get("role") == ROLE and attachment.get("status") == "active"]
    if not found:
        raise RunBodyMissing(f"run {run_id} has no stored body: its {ROLE} attachment does not exist")
    buffer = download_attachment_buffer(client, found[0])
    if buffer is None:
        raise RunBodyMissing(f"run {run_id} has no stored body: its {ROLE} attachment holds no file")
    return body_of(json.loads(buffer.decode("utf-8")))
