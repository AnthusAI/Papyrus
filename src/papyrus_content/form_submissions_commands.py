"""``papyrus messages list`` and ``papyrus messages handle``: triage public form submissions from the CLI.

Public forms land as ``Message`` rows of kind ``form_submission`` (see docs/public-forms.md). A submission is a
message from a person, and "handled" is recorded on that same Message: its ``status`` becomes ``handled`` and its
metadata keeps when, by whom and the note. Nothing writes a second Message, because Messages come only from people.
Updating a Message needs operator credentials: the Message model is append-only for editor sessions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .graphql_authoring import create_authoring_client
from .model_attachments import parse_jsonish
from .options import normalize_non_negative_integer, normalize_string, parse_options, resolve_mutation_apply

FORM_SUBMISSION_KIND = "form_submission"
HANDLED_STATUS = "handled"

LIST_BY_KIND_QUERY = """
query ListMessagesByKind($messageKind: String!, $limit: Int, $nextToken: String) {
  listMessagesByKindAndCreatedAt(messageKind: $messageKind, sortDirection: DESC, limit: $limit, nextToken: $nextToken) {
    items { id messageKind messageType status summary authorLabel content metadata createdAt }
    nextToken
  }
}
"""


def list_messages_of_kind(client: Any, kind: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_token = None
    while True:
        result = client.graphql(LIST_BY_KIND_QUERY, {"messageKind": kind, "limit": 100, "nextToken": next_token})
        page = result.get("listMessagesByKindAndCreatedAt") or {}
        rows.extend(entry for entry in page.get("items") or [] if entry)
        next_token = page.get("nextToken")
        if not next_token or (limit is not None and len(rows) >= limit):
            break
    return rows


def submission_row(message: dict[str, Any]) -> dict[str, Any]:
    metadata = parse_jsonish(message.get("metadata"))
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "id": message.get("id"),
        "formId": metadata.get("formId"),
        "kind": message.get("messageType") or message.get("messageKind"),
        "status": "handled" if message.get("status") == HANDLED_STATUS else "open",
        "createdAt": message.get("createdAt"),
        "from": message.get("authorLabel"),
        "page": metadata.get("page"),
        "summary": message.get("summary"),
    }


def messages_list(flags: list[str]) -> None:
    options = parse_options(flags)
    kind = normalize_string(options.get("kind"))
    if not kind:
        raise ValueError("messages list requires --kind (for example --kind form_submission).")
    status = normalize_string(options.get("status")) or "open"
    if status not in {"open", "handled", "all"}:
        raise ValueError("messages list --status must be open, handled or all.")
    form = normalize_string(options.get("form"))
    limit = normalize_non_negative_integer(options.get("limit"), "--limit")
    client, _ = create_authoring_client()
    messages = list_messages_of_kind(client, kind)
    rows = [submission_row(message) for message in messages]
    rows = [row for row in rows if (status == "all" or row["status"] == status) and (not form or row["formId"] == form)]
    if limit is not None:
        rows = rows[:limit]
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "messages list", "kind": kind, "count": len(rows), "messages": rows}, indent=2))
        return
    for row in rows:
        print("\t".join(str(row[key] or "") for key in ("id", "status", "formId", "createdAt", "from", "summary")))


def handled_update(message: dict[str, Any], *, note: str | None, author: str, now: str) -> dict[str, Any]:
    """The update that marks a submission handled: its own status, plus who, when and why in its metadata."""
    metadata = parse_jsonish(message.get("metadata"))
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    metadata.update({"handledAt": now, "handledBy": author, "handledNote": note})
    return {"id": message["id"], "status": HANDLED_STATUS, "updatedAt": now, "metadata": json.dumps(metadata, sort_keys=True)}


def messages_handle(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "messages handle")
    message_id = normalize_string(options.get("message-id"))
    if not message_id:
        raise ValueError("messages handle requires --message-id.")
    note = normalize_string(options.get("note"))
    author = normalize_string(options.get("author-label")) or "papyrus-cli"
    client, _ = create_authoring_client()
    message = client.get_record("Message", message_id)
    if not message or message.get("messageKind") != FORM_SUBMISSION_KIND:
        raise ValueError(f"Form submission not found: {message_id}")
    if message.get("status") == HANDLED_STATUS:
        action = "noop"
    else:
        action = "mark-handled"
        if apply:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            client.update_record("Message", handled_update(message, note=note, author=author, now=now))
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "messages handle", "apply": apply, "messageId": message_id, "action": action}, indent=2))
    else:
        print(f"messages\thandle\t{message_id}\t{action}\t{'applied' if apply else 'dry-run'}")
