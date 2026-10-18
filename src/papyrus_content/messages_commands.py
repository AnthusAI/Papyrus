from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .assignments_workflow import load_message_metadata_payload, research_packet_body
from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .ids import hash_short
from .message_contract import build_canonical_message_expected
from .model_attachments import (
    _message_body_attachment_for_expected,
    download_attachment_buffer,
    parse_jsonish,
    semantic_version_key,
)
from .options import (
    normalize_non_negative_integer,
    normalize_string,
    parse_boolean_option,
    parse_options,
    resolve_mutation_apply,
)
from .records import apply_record_changes, build_record_changes
from .relation_types import semantic_relation_type_fields_for_predicate
from .relations_commands import print_category_import_summary, write_json_file

LIST_LEGACY_KNOWLEDGE_COMMENTS_QUERY = """
query ListLegacyKnowledgeComments($limit: Int, $nextToken: String) {
  listKnowledgeComments(limit: $limit, nextToken: $nextToken) {
    items {
      id subjectKind subjectId subjectLineageId subjectVersionNumber subjectVersionKey subjectStateKey
      commentKind body status source importRunId authorSub authorUserProfileId authorLabel metadata createdAt
    }
    nextToken
  }
}
"""


def messages_export_legacy_comments(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("messages export-legacy-comments requires --output.")
    client, _ = create_authoring_client()
    comments: list[dict[str, Any]] = []
    next_token = None
    while True:
        result = client.graphql(LIST_LEGACY_KNOWLEDGE_COMMENTS_QUERY, {"limit": 100, "nextToken": next_token})
        page = result.get("listKnowledgeComments") or {}
        comments.extend(entry for entry in page.get("items") or [] if entry)
        next_token = page.get("nextToken")
        if not next_token:
            break
    write_json_file(
        options["output"],
        {
            "schemaVersion": 1,
            "exportKind": "legacy-knowledge-comments",
            "generatedAt": _utc_now(),
            "comments": comments,
        },
    )
    print(f"messages\texport-legacy-comments\t{len(comments)}\t{options['output']}")


def messages_import_legacy_comments(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("input"):
        raise ValueError("messages import-legacy-comments requires --input.")
    payload = load_json_file(options["input"])
    comments = payload.get("comments") if isinstance(payload.get("comments"), list) else payload.get("items")
    if not isinstance(comments, list):
        comments = []
    records: list[dict[str, Any]] = []
    for comment in comments:
        records.extend(legacy_knowledge_comment_records(comment))
    client, _ = create_authoring_client()
    changes = build_record_changes(client, records)
    apply_record_changes(client, changes)
    print_category_import_summary("legacy-messages", Path(options["input"]).name, changes)


def legacy_knowledge_comment_records(comment: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not comment or not isinstance(comment, dict):
        return []
    created_at = comment.get("createdAt") or _utc_now()
    message_kind = comment.get("commentKind") or "comment"
    message_id = f"message-legacy-{hash_short([comment.get('id'), message_kind, created_at])}"
    body = comment.get("body") or ""
    metadata = parse_jsonish(comment.get("metadata"))
    message = build_canonical_message_expected(
        {
            "id": message_id,
            "messageKind": message_kind,
            "messageDomain": "commentary",
            "status": comment.get("status") or "active",
            "body": body,
            "summary": body if len(body) <= 140 else f"{body[:137]}...",
            "source": comment.get("source") or "legacy-knowledge-comment",
            "importRunId": comment.get("importRunId"),
            "authorSub": comment.get("authorSub"),
            "authorUserProfileId": comment.get("authorUserProfileId"),
            "authorLabel": comment.get("authorLabel"),
            "createdAt": created_at,
            "updatedAt": created_at,
            "metadata": {
                "legacyModel": "KnowledgeComment",
                "legacyId": comment.get("id"),
                **(metadata if isinstance(metadata, dict) else {}),
            },
            "responseTarget": "none",
            "responseStatus": "COMPLETED",
            "responseOwner": "legacy-import",
        },
        default_source="legacy-knowledge-comment",
        default_author_label="legacy-knowledge-comment",
        default_response_owner="legacy-import",
    )
    target_kind = comment.get("subjectKind")
    target_id = comment.get("subjectId")
    target_lineage_id = comment.get("subjectLineageId")
    if not target_kind or not target_id or not target_lineage_id:
        return [{"modelName": "Message", "expected": message}]
    relation_type = semantic_relation_type_fields_for_predicate("comment")
    subject_version_key = semantic_version_key("message", message_id)
    object_version_key = semantic_version_key(str(target_kind), str(target_id))
    object_state_key = semantic_state_key(str(target_kind), str(target_lineage_id))
    return [
        {"modelName": "Message", "expected": message},
        {
            "modelName": "SemanticRelation",
            "expected": {
                "id": f"semantic-relation-{hash_short([subject_version_key, 'comment', object_version_key, comment.get('id')])}",
                "relationState": "current",
                "predicate": "comment",
                **relation_type,
                "subjectKind": "message",
                "subjectId": message_id,
                "subjectLineageId": message_id,
                "subjectVersionNumber": 1,
                "objectKind": target_kind,
                "objectId": target_id,
                "objectLineageId": target_lineage_id,
                "objectVersionNumber": comment.get("subjectVersionNumber"),
                "subjectStateKey": semantic_state_key("message", message_id),
                "objectStateKey": object_state_key,
                "objectSubjectStateKey": f"{object_state_key}#message",
                "predicateObjectStateKey": f"comment#{object_state_key}",
                "subjectVersionKey": subject_version_key,
                "objectVersionKey": object_version_key,
                "score": 1,
                "confidence": None,
                "rank": 1,
                "classifierId": None,
                "modelVersion": None,
                "reviewRecommended": False,
                "sourceSnapshotId": None,
                "importRunId": comment.get("importRunId"),
                "importedAt": created_at,
                "metadata": json.dumps(
                    {
                        "legacyModel": "KnowledgeComment",
                        "legacyId": comment.get("id"),
                        "messageKind": message_kind,
                    }
                ),
            },
        },
    ]


def semantic_state_key(kind: str, lineage_id: str) -> str:
    return f"{kind}#{lineage_id}#current"


LEGACY_MESSAGE_KIND = "insight"
MIGRATED_MESSAGE_KIND = "note"
LEGACY_RELATION_PREDICATE = "insight_about"
MIGRATED_RELATION_PREDICATE = "note_about"
LEGACY_TO_MIGRATED_METADATA_KINDS = {
    "reference.insight.created": "reference.note.created",
    "reference.insight": "reference.note",
    "research.tavily.insight": "research.tavily.note",
}


def messages_migrate_insights_to_notes(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "messages migrate-insights-to-notes")
    client, _ = create_authoring_client()

    message_updates, messages_scanned = plan_legacy_message_updates(client)
    relation_migrations, relations_scanned = plan_legacy_relation_migrations(client)

    counts = {
        "messagesScanned": messages_scanned,
        "messageKindsRewritten": sum(1 for update in message_updates if "messageKind" in update),
        "messageMetadataKindsRewritten": sum(1 for update in message_updates if "metadata" in update),
        "relationsScanned": relations_scanned,
        "relationsCreated": sum(1 for migration in relation_migrations if migration["create"] is not None),
        "relationsDeleted": len(relation_migrations),
    }

    if apply:
        for update in message_updates:
            client.update_record("Message", update)
        for migration in relation_migrations:
            if migration["create"] is not None:
                client.create_record("SemanticRelation", migration["create"])
            client.delete_record("SemanticRelation", migration["deleteId"])

    if options.get("json"):
        print(json.dumps({"ok": True, "command": "messages migrate-insights-to-notes", "apply": apply, **counts}, indent=2))
        return
    mode = "applied" if apply else "dry-run"
    for name, value in counts.items():
        print(f"messages\tmigrate-insights-to-notes\t{mode}\t{name}\t{value}")


def plan_legacy_message_updates(client: PapyrusGraphQLAuthoringClient) -> tuple[list[dict[str, Any]], int]:
    updates: list[dict[str, Any]] = []
    scanned = 0
    next_token: str | None = None
    while True:
        rows, next_token = client.list_messages_safe(limit=100, next_token=next_token)
        for row in rows:
            if str(row.get("messageKind") or "") not in {LEGACY_MESSAGE_KIND, MIGRATED_MESSAGE_KIND}:
                continue
            scanned += 1
            message = client.get_record("Message", str(row["id"]))
            if not message:
                continue
            update = legacy_message_update(message)
            if update:
                updates.append(update)
        if not next_token:
            break
    return updates, scanned


def legacy_message_update(message: dict[str, Any]) -> dict[str, Any] | None:
    update: dict[str, Any] = {"id": message["id"]}
    if str(message.get("messageKind") or "") == LEGACY_MESSAGE_KIND:
        update["messageKind"] = MIGRATED_MESSAGE_KIND
    raw_metadata = message.get("metadata")
    metadata = parse_jsonish(raw_metadata)
    if isinstance(metadata, dict):
        migrated_kind = LEGACY_TO_MIGRATED_METADATA_KINDS.get(str(metadata.get("kind") or ""))
        if migrated_kind:
            update["metadata"] = json.dumps({**metadata, "kind": migrated_kind})
    if len(update) == 1:
        return None
    update["updatedAt"] = message.get("updatedAt") or message.get("createdAt") or _utc_now()
    return update


def plan_legacy_relation_migrations(client: PapyrusGraphQLAuthoringClient) -> tuple[list[dict[str, Any]], int]:
    relations = client.list_records("SemanticRelation")
    existing_ids = {str(relation.get("id")) for relation in relations}
    migrations: list[dict[str, Any]] = []
    for relation in relations:
        if str(relation.get("predicate") or "") != LEGACY_RELATION_PREDICATE:
            continue
        migrated = migrated_relation_record(relation)
        already_exists = migrated["id"] in existing_ids
        migrations.append({"deleteId": relation["id"], "create": None if already_exists else migrated})
        existing_ids.add(migrated["id"])
    return migrations, len(relations)


def migrated_relation_record(relation: dict[str, Any]) -> dict[str, Any]:
    object_state_key = str(relation.get("objectStateKey") or "")
    migrated = {key: value for key, value in relation.items() if value is not None}
    migrated.update(
        {
            "id": "semantic-relation-"
            + hash_short(
                [
                    relation.get("subjectVersionKey"),
                    MIGRATED_RELATION_PREDICATE,
                    relation.get("objectVersionKey"),
                ]
            ),
            "predicate": MIGRATED_RELATION_PREDICATE,
            "relationTypeKey": MIGRATED_RELATION_PREDICATE,
            "relationTypeId": "semantic-relation-type-note-about",
            "predicateObjectStateKey": f"{MIGRATED_RELATION_PREDICATE}#{object_state_key}",
        }
    )
    metadata = parse_jsonish(relation.get("metadata"))
    if isinstance(metadata, dict):
        migrated_kind = LEGACY_TO_MIGRATED_METADATA_KINDS.get(str(metadata.get("kind") or ""))
        if migrated_kind:
            migrated["metadata"] = json.dumps({**metadata, "kind": migrated_kind})
    return migrated


def messages_backfill_note_message_body(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "messages backfill-note-message-body")
    message_id = normalize_string(options.get("message-id"))
    assignment_id = normalize_string(options.get("assignment-id"))
    tavily_only = parse_boolean_option(options.get("tavily-only"), True, "--tavily-only")
    max_scan_option = normalize_non_negative_integer(options.get("max-scan"), "--max-scan")
    max_scan = max_scan_option if max_scan_option is not None else (None if apply else 500)
    client, _ = create_authoring_client()

    candidates = _note_messages_for_backfill(
        client,
        message_id=message_id,
        assignment_id=assignment_id,
        tavily_only=tavily_only,
        max_scan=max_scan,
    )
    planned: list[dict[str, Any]] = []
    for message in candidates:
        body_text = _resolve_note_body_text(client, message)
        if not body_text.strip():
            planned.append({"messageId": message["id"], "action": "skip", "reason": "no-body-source"})
            continue
        if _message_has_active_message_body(client, str(message["id"])):
            planned.append({"messageId": message["id"], "action": "noop", "reason": "message_body-exists"})
            continue
        planned.append(
            {
                "messageId": message["id"],
                "action": "create-message_body",
                "byteSize": len(body_text.encode("utf-8")),
                "bodyPreview": body_text[:120],
            }
        )

    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "messages backfill-note-message-body",
                    "apply": apply,
                    "scanned": len(candidates),
                    "planned": planned,
                },
                indent=2,
            )
        )
    else:
        for row in planned:
            print(
                "messages\tbackfill-note-message-body\t"
                f"{row['messageId']}\t{row['action']}\t{row.get('reason') or row.get('byteSize')}"
            )

    if not apply:
        return

    created = 0
    for message in candidates:
        message_id_value = str(message["id"])
        if any(row["messageId"] == message_id_value and row["action"] != "create-message_body" for row in planned):
            continue
        body_text = _resolve_note_body_text(client, message)
        now = message.get("updatedAt") or message.get("createdAt") or _utc_now()
        attachment_entry = _message_body_attachment_for_expected(
            {"id": message_id_value, "content": body_text, "importRunId": message.get("importRunId")},
            now=now,
        )
        if not attachment_entry:
            continue
        changes = build_record_changes(client, [attachment_entry])
        apply_record_changes(client, changes)
        created += 1
        thread_updates = _note_thread_id_updates(message)
        if thread_updates:
            client.update_record("Message", thread_updates)

    if not options.get("json"):
        print(f"messages\tbackfill-note-message-body\tcreated\t{created}")


def messages_backfill_message_body(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "messages backfill-message-body")
    message_id = normalize_string(options.get("message-id"))
    message_kind = normalize_string(options.get("message-kind"))
    max_scan = normalize_non_negative_integer(options.get("max-scan"), "--max-scan")
    client, _ = create_authoring_client()

    rows = client.list_records("Message")
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if message_id and str(row.get("id") or "") != message_id:
            continue
        if message_kind and str(row.get("messageKind") or "") != message_kind:
            continue
        candidates.append(row)
    if max_scan is not None:
        candidates = candidates[:max_scan]

    planned: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    for message in candidates:
        message_id_value = str(message.get("id") or "")
        direct = normalize_string(message.get("content")) or ""
        if not direct:
            planned.append({"messageId": message_id_value, "action": "skip", "reason": "no-inline-content"})
            continue
        if _message_has_active_message_body(client, message_id_value):
            planned.append({"messageId": message_id_value, "action": "noop", "reason": "message_body-exists"})
            continue
        now = message.get("updatedAt") or message.get("createdAt") or _utc_now()
        attachment_entry = _message_body_attachment_for_expected(
            {"id": message_id_value, "content": direct, "importRunId": message.get("importRunId")},
            now=now,
        )
        if not attachment_entry:
            planned.append({"messageId": message_id_value, "action": "skip", "reason": "attachment-empty"})
            continue
        attachments.append(attachment_entry)
        planned.append(
            {
                "messageId": message_id_value,
                "action": "create-message_body",
                "byteSize": len(direct.encode("utf-8")),
            }
        )

    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "messages backfill-message-body",
                    "apply": apply,
                    "scanned": len(candidates),
                    "planned": planned,
                    "plannedAttachments": len(attachments),
                },
                indent=2,
            )
        )
    else:
        for row in planned:
            print(
                "messages\tbackfill-message-body\t"
                f"{row['messageId']}\t{row['action']}\t{row.get('reason') or row.get('byteSize') or ''}"
            )

    if not apply:
        return
    if attachments:
        changes = build_record_changes(client, attachments)
        apply_record_changes(client, changes)
    if not options.get("json"):
        print(f"messages\tbackfill-message-body\tcreated\t{len(attachments)}")


def messages_scrub_inline_content(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "messages scrub-inline-content")
    message_id = normalize_string(options.get("message-id"))
    message_kind = normalize_string(options.get("message-kind"))
    max_scan = normalize_non_negative_integer(options.get("max-scan"), "--max-scan")
    client, _ = create_authoring_client()

    rows = client.list_records("Message")
    candidates: list[dict[str, Any]] = []
    for row in rows:
        if message_id and str(row.get("id") or "") != message_id:
            continue
        if message_kind and str(row.get("messageKind") or "") != message_kind:
            continue
        candidates.append(row)
    if max_scan is not None:
        candidates = candidates[:max_scan]

    planned: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    for message in candidates:
        message_id_value = str(message.get("id") or "")
        direct = normalize_string(message.get("content")) or ""
        if not direct:
            planned.append({"messageId": message_id_value, "action": "noop", "reason": "already-scrubbed"})
            continue
        if not _message_has_active_message_body(client, message_id_value):
            planned.append({"messageId": message_id_value, "action": "skip", "reason": "missing-message_body"})
            continue
        now = message.get("updatedAt") or message.get("createdAt") or _utc_now()
        updates.append({"id": message_id_value, "content": None, "updatedAt": now})
        planned.append({"messageId": message_id_value, "action": "scrub"})

    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "messages scrub-inline-content",
                    "apply": apply,
                    "scanned": len(candidates),
                    "planned": planned,
                    "plannedUpdates": len(updates),
                },
                indent=2,
            )
        )
    else:
        for row in planned:
            print(
                "messages\tscrub-inline-content\t"
                f"{row['messageId']}\t{row['action']}\t{row.get('reason') or ''}"
            )

    if not apply:
        return
    for update in updates:
        client.update_record("Message", update)
    if not options.get("json"):
        print(f"messages\tscrub-inline-content\tupdated\t{len(updates)}")


def _note_messages_for_backfill(
    client: PapyrusGraphQLAuthoringClient,
    *,
    message_id: str | None,
    assignment_id: str | None,
    tavily_only: bool,
    max_scan: int | None,
) -> list[dict[str, Any]]:
    if message_id:
        message = client.get_record("Message", message_id)
        if not message or str(message.get("messageKind") or "") != "note":
            raise ValueError(f"Note message not found: {message_id}")
        return [message]

    scanned = 0
    truncated = False
    candidates: list[dict[str, Any]] = []
    next_token: str | None = None
    while True:
        rows, next_token = client.list_messages_safe(limit=100, next_token=next_token)
        if max_scan is not None and scanned + len(rows) > max_scan:
            rows = rows[: max(0, max_scan - scanned)]
            truncated = True
        scanned += len(rows)
        for row in rows:
            if str(row.get("messageKind") or "") != "note":
                continue
            metadata = load_message_metadata_payload(client, row)
            if assignment_id and normalize_string(metadata.get("assignmentId")) != assignment_id:
                continue
            if tavily_only and normalize_string(metadata.get("kind")) != "research.tavily.note":
                continue
            candidates.append({**row, "_metadata": metadata})
        if truncated or not next_token:
            break
    return candidates


def _message_has_active_message_body(client: PapyrusGraphQLAuthoringClient, message_id: str) -> bool:
    attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", message_id, limit=20)
    return any(
        normalize_string(entry.get("role")) == "message_body"
        and normalize_string(entry.get("status")) not in {"deleted", "aborted"}
        for entry in attachments
    )


def _read_message_body_attachment_text(client: PapyrusGraphQLAuthoringClient, message_id: str) -> str:
    attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", message_id, limit=20)
    body_attachments = [
        entry
        for entry in attachments
        if normalize_string(entry.get("role")) == "message_body"
        and normalize_string(entry.get("status")) not in {"deleted", "aborted"}
    ]
    body_attachments.sort(key=lambda entry: str(entry.get("updatedAt") or ""), reverse=True)
    for attachment in body_attachments:
        try:
            payload = download_attachment_buffer(client, attachment)
        except Exception:
            continue
        if payload:
            return payload.decode("utf-8", errors="replace").strip()
    return ""


def _resolve_note_body_text(client: PapyrusGraphQLAuthoringClient, message: dict[str, Any]) -> str:
    message_id = str(message["id"])
    attachment_text = _read_message_body_attachment_text(client, message_id)
    if attachment_text:
        return attachment_text
    direct = normalize_string(message.get("content")) or ""
    if direct:
        return direct
    metadata = message.get("_metadata")
    if not isinstance(metadata, dict):
        metadata = load_message_metadata_payload(client, message)
    packet_message_id = normalize_string(metadata.get("researchPacketMessageId"))
    if packet_message_id:
        packet_message = client.get_record("Message", packet_message_id)
        if packet_message:
            packet_text = normalize_string(packet_message.get("content")) or ""
            if packet_text:
                return packet_text
            packet_attachment = _read_message_body_attachment_text(client, packet_message_id)
            if packet_attachment:
                return packet_attachment
            packet_metadata = load_message_metadata_payload(client, packet_message)
            if isinstance(packet_metadata, dict) and packet_metadata:
                synthesized = research_packet_body(packet_metadata)
                if synthesized.strip():
                    return synthesized
    return ""


def _note_thread_id_updates(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = str(message["id"])
    thread_id = normalize_string(message.get("threadId"))
    sequence_number = message.get("sequenceNumber")
    if thread_id == message_id and sequence_number:
        return None
    now = message.get("updatedAt") or message.get("createdAt") or _utc_now()
    return {
        "id": message_id,
        "threadId": message_id,
        "sequenceNumber": int(sequence_number or 1),
        "updatedAt": now,
    }


def load_json_file(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
