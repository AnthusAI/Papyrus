from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .model_attachments import (
    _item_payload_attachments_for_expected,
    parse_jsonish,
)
from .options import (
    normalize_non_negative_integer,
    normalize_string,
    parse_options,
    resolve_mutation_apply,
)
from .records import apply_record_changes, build_record_changes


def content_backfill_item_body_attachments(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "content backfill-item-body-attachments")
    include_items = _parse_include_option(options, "items", default=True)
    include_published = _parse_include_option(options, "published-items", default=True)
    max_scan = normalize_non_negative_integer(options.get("max-scan"), "--max-scan")
    client, _ = create_authoring_client()

    targets: list[tuple[str, str]] = []
    if include_items:
        targets.append(("Item", "item_body"))
    if include_published:
        targets.append(("PublishedItem", "published_item_body"))
    if not targets:
        raise ValueError("Nothing to backfill. Enable --items and/or --published-items.")

    planned: list[dict[str, Any]] = []
    attachment_records: list[dict[str, Any]] = []
    editorial_updates: list[tuple[str, dict[str, Any]]] = []
    scanned = 0
    truncated = False
    for model_name, body_role in targets:
        for record in client.list_records(model_name):
            if max_scan is not None and scanned >= max_scan:
                truncated = True
                break
            scanned += 1
            body_text = _normalize_body_text(record.get("body"))
            if not body_text:
                planned.append({"model": model_name, "id": record.get("id"), "action": "skip", "reason": "no-inline-body"})
                continue
            owner_id = str(record.get("id") or "")
            active_roles = _active_attachment_roles(client, owner_id)
            if body_role in active_roles:
                planned.append({"model": model_name, "id": owner_id, "action": "noop", "reason": "body-attachment-exists"})
                continue
            expected = {
                "id": owner_id,
                "versionNumber": record.get("versionNumber"),
                "lineageId": record.get("lineageId"),
                "itemLineageId": record.get("itemLineageId"),
                "sourceItemId": record.get("sourceItemId"),
                "importRunId": record.get("importRunId"),
                "body": record.get("body"),
                "editorial": record.get("editorial"),
            }
            now = record.get("updatedAt") or record.get("createdAt") or _utc_now()
            generated = _item_payload_attachments_for_expected(model_name, expected, now=now)
            generated_body = [
                entry
                for entry in generated
                if (entry.get("expected") or {}).get("role") == body_role
            ]
            generated_other = [
                entry
                for entry in generated
                if (entry.get("expected") or {}).get("role") != body_role
                and (entry.get("expected") or {}).get("role") not in active_roles
            ]
            if not generated_body:
                planned.append({"model": model_name, "id": owner_id, "action": "skip", "reason": "body-not-generated"})
                continue
            attachment_records.extend(generated_body)
            attachment_records.extend(generated_other)
            if _jsonish_changed(record.get("editorial"), expected.get("editorial")):
                editorial_updates.append((model_name, {"id": owner_id, "editorial": expected.get("editorial"), "updatedAt": now}))
            planned.append(
                {
                    "model": model_name,
                    "id": owner_id,
                    "action": "create-attachment",
                    "roles": [
                        (entry.get("expected") or {}).get("role")
                        for entry in [*generated_body, *generated_other]
                    ],
                    "byteSize": sum(int((entry.get("expected") or {}).get("byteSize") or 0) for entry in [*generated_body, *generated_other]),
                }
            )
        if truncated:
            break

    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "content backfill-item-body-attachments",
                    "apply": apply,
                    "scanned": scanned,
                    "truncated": truncated,
                    "planned": planned,
                    "plannedAttachmentCount": len(attachment_records),
                    "plannedEditorialUpdates": len(editorial_updates),
                },
                indent=2,
            )
        )
    else:
        for row in planned:
            print(
                "content\tbackfill-item-body-attachments\t"
                f"{row.get('model')}\t{row.get('id')}\t{row.get('action')}\t{row.get('reason') or row.get('byteSize') or ''}"
            )

    if not apply:
        return
    if attachment_records:
        changes = build_record_changes(client, attachment_records)
        apply_record_changes(client, changes)
    for model_name, update in editorial_updates:
        client.update_record(model_name, update)
    if not options.get("json"):
        print(
            "content\tbackfill-item-body-attachments\tapplied\t"
            f"attachments={len(attachment_records)}\teditorialUpdates={len(editorial_updates)}"
        )


def content_scrub_item_inline_body(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "content scrub-item-inline-body")
    include_items = _parse_include_option(options, "items", default=True)
    include_published = _parse_include_option(options, "published-items", default=True)
    max_scan = normalize_non_negative_integer(options.get("max-scan"), "--max-scan")
    client, _ = create_authoring_client()

    targets: list[tuple[str, str]] = []
    if include_items:
        targets.append(("Item", "item_body"))
    if include_published:
        targets.append(("PublishedItem", "published_item_body"))
    if not targets:
        raise ValueError("Nothing to scrub. Enable --items and/or --published-items.")

    planned: list[dict[str, Any]] = []
    updates: list[tuple[str, dict[str, Any]]] = []
    scanned = 0
    truncated = False
    for model_name, body_role in targets:
        for record in client.list_records(model_name):
            if max_scan is not None and scanned >= max_scan:
                truncated = True
                break
            scanned += 1
            owner_id = str(record.get("id") or "")
            body_text = _normalize_body_text(record.get("body"))
            if not body_text:
                planned.append({"model": model_name, "id": owner_id, "action": "noop", "reason": "already-scrubbed"})
                continue
            active_roles = _active_attachment_roles(client, owner_id)
            if body_role not in active_roles:
                planned.append({"model": model_name, "id": owner_id, "action": "skip", "reason": "missing-body-attachment"})
                continue
            now = record.get("updatedAt") or record.get("createdAt") or _utc_now()
            updates.append((model_name, {"id": owner_id, "body": [], "updatedAt": now}))
            planned.append({"model": model_name, "id": owner_id, "action": "scrub"})
        if truncated:
            break

    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "content scrub-item-inline-body",
                    "apply": apply,
                    "scanned": scanned,
                    "truncated": truncated,
                    "planned": planned,
                    "plannedUpdates": len(updates),
                },
                indent=2,
            )
        )
    else:
        for row in planned:
            print(
                "content\tscrub-item-inline-body\t"
                f"{row.get('model')}\t{row.get('id')}\t{row.get('action')}\t{row.get('reason') or ''}"
            )

    if not apply:
        return
    for model_name, update in updates:
        client.update_record(model_name, update)
    if not options.get("json"):
        print(f"content\tscrub-item-inline-body\tapplied\t{len(updates)}")


def _active_attachment_roles(client: PapyrusGraphQLAuthoringClient, owner_id: str) -> set[str]:
    attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", owner_id, limit=100)
    return {
        str(entry.get("role") or "")
        for entry in attachments
        if str(entry.get("status") or "").strip().lower() not in {"deleted", "aborted"}
    }


def _normalize_body_text(value: Any) -> str:
    if isinstance(value, list):
        parts = [str(entry).strip() for entry in value if str(entry).strip()]
        return "\n\n".join(parts).strip()
    if value is None:
        return ""
    return str(value).strip()


def _parse_include_option(options: dict[str, Any], key: str, *, default: bool) -> bool:
    value = normalize_string(options.get(key))
    if not value:
        return default
    lowered = value.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"--{key} must be true/false")


def _jsonish_changed(current: Any, expected: Any) -> bool:
    return parse_jsonish(current) != parse_jsonish(expected)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
