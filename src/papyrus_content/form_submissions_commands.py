"""``papyrus messages list`` and ``papyrus messages handle``: triage public form submissions from the CLI.

Public forms land as ``Message`` rows of kind ``form_submission`` (see docs/public-forms.md). The Message model is
append-only for editors, so "handled" is recorded the same way everything else in the feed is: as a new
``form_submission_handled`` Message whose ``parentMessageId`` is the submission. A submission is handled when such a
row exists for it.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .graphql_authoring import create_authoring_client
from .message_contract import build_canonical_message_expected
from .model_attachments import parse_jsonish
from .options import normalize_non_negative_integer, normalize_string, parse_options, resolve_mutation_apply

FORM_SUBMISSION_KIND = "form_submission"
HANDLED_KIND = "form_submission_handled"

LIST_BY_KIND_QUERY = """
query ListMessagesByKind($messageKind: String!, $limit: Int, $nextToken: String) {
  listMessagesByKindAndCreatedAt(messageKind: $messageKind, sortDirection: DESC, limit: $limit, nextToken: $nextToken) {
    items { id messageKind messageType status summary authorLabel content metadata parentMessageId createdAt }
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


def submission_row(message: dict[str, Any], handled_ids: set[str]) -> dict[str, Any]:
    metadata = parse_jsonish(message.get("metadata"))
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "id": message.get("id"),
        "formId": metadata.get("formId"),
        "kind": message.get("messageType") or message.get("messageKind"),
        "status": "handled" if message.get("id") in handled_ids else "open",
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
    handled_ids: set[str] = set()
    if kind == FORM_SUBMISSION_KIND:
        handled_ids = {str(row["parentMessageId"]) for row in list_messages_of_kind(client, HANDLED_KIND) if row.get("parentMessageId")}
    rows = [submission_row(message, handled_ids) for message in messages]
    rows = [row for row in rows if (status == "all" or row["status"] == status) and (not form or row["formId"] == form)]
    if limit is not None:
        rows = rows[:limit]
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "messages list", "kind": kind, "count": len(rows), "messages": rows}, indent=2))
        return
    for row in rows:
        print("\t".join(str(row[key] or "") for key in ("id", "status", "formId", "createdAt", "from", "summary")))


def handled_event(message: dict[str, Any], *, note: str | None, author: str, now: str) -> dict[str, Any]:
    return build_canonical_message_expected(
        {
            "id": f"{message['id']}-handled",
            "messageKind": HANDLED_KIND,
            "messageDomain": message.get("messageDomain") or "inbox",
            "status": "active",
            "summary": f"Handled: {message.get('summary') or message['id']}"[:200],
            "content": note,
            "source": "cli",
            "authorLabel": author,
            "parentMessageId": message["id"],
            "searchVisibility": "private",
            "responseTarget": "none",
            "metadata": {"handledAt": now, "note": note},
            "createdAt": now,
            "newsroomFeedKey": message.get("newsroomFeedKey") or "messages",
        },
        default_source="cli",
        default_author_label=author,
        default_response_owner="cli",
    )


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
    already = any(row.get("parentMessageId") == message_id for row in list_messages_of_kind(client, HANDLED_KIND))
    if already:
        action = "noop"
    else:
        action = "mark-handled"
        if apply:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            client.create_record("Message", handled_event(message, note=note, author=author, now=now))
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "messages handle", "apply": apply, "messageId": message_id, "action": action}, indent=2))
    else:
        print(f"messages\thandle\t{message_id}\t{action}\t{'applied' if apply else 'dry-run'}")
