"""An agent's note on a Story: a ``ModelAttachment`` owned by the Story, labelled as AI. It is never a ``Message``.

Messages come only from people (AGENTS.md). What an agent says while it works on a Story is kept as one small JSON attachment per note,
role ``agent_note``, owned by the Story's first version record (``ownerKind`` ``item``, ``ownerLineageId`` the lineage), so every
version of the Story reads the same notes. The body holds the agent's name as a label, who ran it (the sub of the signed-in editor, or
``operator`` on the IAM lane), when, the summary and the text. Nothing else is written: no Message, no thread, no new model.

``stories agent-note`` saves one (through the ``addStoryAgentNote`` mutation on the signed-in lane); ``stories show`` and the Story's
Reporting trail read them back.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from .ids import hash_short
from .model_attachments import build_json_model_payload_attachment, download_attachment_buffer, upload_attachment_body
from .publishing import utc_now_iso
from .story_reporting import story_versions

AGENT_NOTE_ROLE = "agent_note"
AGENT_NOTE_KIND = "story.agent_note"
AGENT_NOTE_OWNER_KIND = "item"


def clean_agent_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "")).strip()
    if not name:
        raise ValueError("An agent note needs the agent's name.")
    return name


def story_note_owner(client, lineage_id: str) -> dict[str, Any]:
    """The record that owns the Story's agent notes: its first version. Raises when there is no such Story."""
    versions = story_versions(client, lineage_id)
    if not versions:
        raise ValueError(f"No story found for lineage {lineage_id}.")
    return min(versions, key=lambda row: int(row.get("versionNumber") or 0))


def save_agent_note(
    client,
    lineage_id: str,
    *,
    agent: str,
    body: str,
    summary: str | None = None,
    reference_lineage_id: str | None = None,
    version_number: int | None = None,
    by_sub: str | None = None,
    by_kind: str = "user",
    now: str | None = None,
) -> dict[str, Any]:
    """Saves one agent note on the Story and returns ``{attachmentId, sortKey, createdAt, agent}``.

    ``by_sub`` is who ran the agent, from the backend's own identity: the caller never supplies it. ``agent`` is only a label."""
    agent = clean_agent_name(agent)
    text = (body or "").strip()
    if not text:
        raise ValueError("An agent note cannot be empty.")
    owner = story_note_owner(client, lineage_id)
    if version_number is not None and not any(int(row.get("versionNumber") or 0) == version_number for row in story_versions(client, lineage_id)):
        raise ValueError(f"Story {lineage_id} has no version {version_number}.")
    now = now or utc_now_iso()
    sort_key = f"{re.sub(r'[^0-9A-Za-z]', '', now)}-{hash_short([lineage_id, agent, now, text])[:8]}"
    content = {
        "kind": AGENT_NOTE_KIND,
        "ai": True,
        "storyLineageId": lineage_id,
        "agent": agent,
        "summary": (summary or "").strip() or text.splitlines()[0][:140],
        "body": text,
        "referenceLineageId": reference_lineage_id or None,
        "versionNumber": version_number,
        "runBy": {"kind": by_kind, "sub": by_sub},
        "createdAt": now,
    }
    built = build_json_model_payload_attachment({
        "ownerKind": AGENT_NOTE_OWNER_KIND, "ownerId": owner["id"], "ownerLineageId": lineage_id,
        "role": AGENT_NOTE_ROLE, "sortKey": sort_key, "filename": f"agent-note-{sort_key}.json", "content": content, "now": now,
    })
    upload_attachment_body(client, built["attachment"], built["body"])
    return {"attachmentId": built["attachment"]["id"], "sortKey": sort_key, "createdAt": now, "agent": agent, "ownerId": owner["id"]}


def story_agent_notes(client, lineage_id: str, *, read_body: Callable[[dict[str, Any]], bytes | None] | None = None) -> list[dict[str, Any]]:
    """Every agent note of the Story, oldest first: ``agent``, ``summary``, ``body``, ``createdAt``, ``referenceLineageId``, ``versionNumber``, ``attachmentId``.

    A note whose body cannot be read is listed with ``body`` None and ``error`` set, so it is never silently missing."""
    owner = story_note_owner(client, lineage_id)
    read = read_body or (lambda attachment: download_attachment_buffer(client, attachment))
    rows = [
        row for row in client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", owner["id"])
        if row.get("ownerKind") == AGENT_NOTE_OWNER_KIND and row.get("role") == AGENT_NOTE_ROLE and (row.get("status") or "active") == "active"
    ]
    notes: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("sortKey") or "")):
        try:
            payload = json.loads((read(row) or b"{}").decode("utf-8"))
        except Exception as error:  # noqa: BLE001
            notes.append({"attachmentId": row["id"], "agent": None, "summary": None, "body": None, "createdAt": row.get("createdAt"), "error": str(error)})
            continue
        notes.append({
            "attachmentId": row["id"], "agent": payload.get("agent"), "summary": payload.get("summary"), "body": payload.get("body"),
            "createdAt": payload.get("createdAt") or row.get("createdAt"), "referenceLineageId": payload.get("referenceLineageId"),
            "versionNumber": payload.get("versionNumber"),
        })
    return notes
