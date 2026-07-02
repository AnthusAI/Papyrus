from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .env import PAPYRUS_ROOT, storage_bucket_from_amplify_outputs
from .graphql_authoring import PapyrusGraphQLAuthoringClient, strip_unsupported_payload_fields
from .ids import hash_short, safe_id

MODEL_ATTACHMENT_OWNER_MODELS = {
    "assignment": "Assignment",
    "assignmentEvent": "AssignmentEvent",
    "item": "Item",
    "knowledgeRawPayload": "KnowledgeRawPayload",
    "message": "Message",
    "publishedItem": "PublishedItem",
    "procedureVersion": "ProcedureVersion",
    "reference": "Reference",
    "semanticNode": "SemanticNode",
    "semanticRelation": "SemanticRelation",
}


def model_payload_storage_path(owner_kind: str, owner_id: str, role: str, filename: str) -> str:
    root_prefix = "media/payloads" if owner_kind == "publishedItem" else "newsroom/payloads"
    return f"{root_prefix}/{safe_id(owner_kind)}/{safe_id(owner_id)}/{safe_id(role)}/{filename}"


def model_attachment_id(owner_kind: str, owner_id: str, role: str, sort_key: str) -> str:
    return f"model-attachment-{safe_id(owner_kind)}-{safe_id(owner_id)}-{safe_id(role)}-{safe_id(sort_key)}"


def build_text_model_payload_attachment(input_payload: dict[str, Any]) -> dict[str, Any]:
    content = str(input_payload.get("content") or "")
    filename = input_payload.get("filename") or f"{safe_id(input_payload.get('sortKey') or input_payload.get('role'))}.txt"
    media_type = input_payload.get("mediaType") or "text/plain"
    return build_model_payload_attachment(
        {
            **input_payload,
            "filename": filename,
            "mediaType": media_type,
            "content": content,
        }
    )


def build_json_model_payload_attachment(input_payload: dict[str, Any]) -> dict[str, Any]:
    content = input_payload.get("content") or {}
    return build_text_model_payload_attachment(
        {
            **input_payload,
            "filename": input_payload.get("filename") or "metadata.json",
            "mediaType": "application/json",
            "content": f"{json.dumps(content, indent=2, sort_keys=True)}\n",
        }
    )


def build_model_payload_attachment(input_payload: dict[str, Any]) -> dict[str, Any]:
    content = input_payload.get("content")
    if isinstance(content, str):
        body = content.encode("utf-8")
    elif isinstance(content, (bytes, bytearray)):
        body = bytes(content)
    else:
        body = json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    owner_kind = input_payload["ownerKind"]
    owner_id = input_payload["ownerId"]
    role = input_payload["role"]
    sort_key = input_payload.get("sortKey") or role
    filename = input_payload["filename"]
    now = input_payload.get("now")
    attachment = {
        "id": model_attachment_id(owner_kind, owner_id, role, sort_key),
        "ownerKind": owner_kind,
        "ownerId": owner_id,
        "ownerLineageId": input_payload.get("ownerLineageId") or owner_id,
        "ownerVersionNumber": input_payload.get("ownerVersionNumber"),
        "ownerVersionKey": input_payload.get("ownerVersionKey"),
        "role": role,
        "sortKey": sort_key,
        "storagePath": model_payload_storage_path(owner_kind, owner_id, role, filename),
        "filename": filename,
        "mediaType": input_payload.get("mediaType") or "application/octet-stream",
        "byteSize": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "etag": None,
        "importRunId": input_payload.get("importRunId"),
        "createdAt": now,
        "updatedAt": now,
        "status": input_payload.get("status") or "ready",
    }
    return {"attachment": attachment, "body": body}


def attachment_record(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelName": "ModelAttachment",
        "expected": entry["attachment"],
        "attachmentBody": entry["body"],
    }


def upload_attachment_body(
    client: PapyrusGraphQLAuthoringClient,
    attachment: dict[str, Any],
    body: bytes | str,
) -> dict[str, Any]:
    buffer = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
    slot = client.create_model_attachment_upload(attachment)
    headers = {str(key): str(value) for key, value in (slot.get("requiredHeaders") or {}).items()}
    request = urllib.request.Request(
        slot["uploadUrl"],
        data=buffer,
        headers=headers,
        method=slot.get("method") or "PUT",
    )
    try:
        with urllib.request.urlopen(request) as response:
            if response.status >= 400:
                raise RuntimeError(f"Upload failed with status {response.status}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Failed to upload ModelAttachment {attachment['id']} to {slot.get('storagePath')}: "
            f"{error.code} {error.reason} {detail[:240]}"
        ) from error
    completed = client.complete_model_attachment_upload(slot["uploadId"], attachment)
    if isinstance(completed, dict):
        completed_status = str(completed.get("status") or "").strip().lower()
        normalized_status = "active" if completed_status in {"", "ready"} else completed_status
        return {
            **attachment,
            **completed,
            "storagePath": slot.get("storagePath") or attachment.get("storagePath"),
            "status": normalized_status,
        }
    return {
        **attachment,
        "storagePath": slot.get("storagePath") or attachment.get("storagePath"),
        "status": "active",
    }


def _message_body_attachment_for_expected(expected: dict[str, Any], *, now: Any) -> dict[str, Any] | None:
    body = ""
    if "body" in expected:
        body = str(expected.pop("body"))
    elif "content" in expected:
        body = str(expected.pop("content") or "")
    else:
        body = str(expected.get("content") or "")
    body = body.strip()
    if not body:
        return None
    if body.startswith("{") or body.startswith("["):
        filename = "message.json"
        media_type = "application/json"
    elif body.startswith("#") or "\n#" in body or "**" in body:
        filename = "message.md"
        media_type = "text/markdown"
    else:
        filename = "message.txt"
        media_type = "text/plain"
    return attachment_record(
        build_text_model_payload_attachment(
            {
                "ownerKind": "message",
                "ownerId": expected["id"],
                "ownerLineageId": expected["id"],
                "role": "message_body",
                "sortKey": "message",
                "filename": filename,
                "mediaType": media_type,
                "content": body,
                "importRunId": expected.get("importRunId"),
                "now": now,
            }
        )
    )


def _item_payload_attachments_for_expected(model_name: str, expected: dict[str, Any], *, now: Any) -> list[dict[str, Any]]:
    if model_name not in {"Item", "PublishedItem"}:
        return []

    owner_kind = "item" if model_name == "Item" else "publishedItem"
    body_role = "item_body" if model_name == "Item" else "published_item_body"
    excerpt_role = "item_excerpt" if model_name == "Item" else "published_item_excerpt"
    owner_id = str(expected.get("id") or "").strip()
    if not owner_id:
        return []
    owner_lineage_id = (
        str(expected.get("lineageId") or "").strip()
        if model_name == "Item"
        else str(expected.get("itemLineageId") or expected.get("sourceItemId") or "").strip()
    ) or owner_id
    owner_version_number = expected.get("versionNumber")
    owner_version_key = semantic_version_key(owner_kind, owner_id)

    attachments: list[dict[str, Any]] = []
    body_text = _normalize_body_text(expected.pop("body", None))
    if body_text:
        body_attachment = build_text_model_payload_attachment(
            {
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "ownerLineageId": owner_lineage_id,
                "ownerVersionNumber": owner_version_number,
                "ownerVersionKey": owner_version_key,
                "role": body_role,
                "sortKey": "body",
                "filename": "body.md",
                "mediaType": "text/markdown",
                "content": body_text,
                "importRunId": expected.get("importRunId"),
                "now": now,
            }
        )
        attachments.append(attachment_record(body_attachment))
        _set_content_attachment_pointer(expected, "body", body_attachment["attachment"])

    excerpt_text = _extract_editorial_excerpt(expected)
    if excerpt_text:
        excerpt_attachment = build_text_model_payload_attachment(
            {
                "ownerKind": owner_kind,
                "ownerId": owner_id,
                "ownerLineageId": owner_lineage_id,
                "ownerVersionNumber": owner_version_number,
                "ownerVersionKey": owner_version_key,
                "role": excerpt_role,
                "sortKey": "excerpt",
                "filename": "excerpt.txt",
                "mediaType": "text/plain",
                "content": excerpt_text,
                "importRunId": expected.get("importRunId"),
                "now": now,
            }
        )
        attachments.append(attachment_record(excerpt_attachment))
        _set_content_attachment_pointer(expected, "excerpt", excerpt_attachment["attachment"])

    return attachments


def _normalize_body_text(value: Any) -> str:
    if isinstance(value, list):
        parts = [str(part).strip() for part in value if str(part).strip()]
        return "\n\n".join(parts).strip()
    if value is None:
        return ""
    return str(value).strip()


def _extract_editorial_excerpt(expected: dict[str, Any]) -> str:
    editorial = parse_jsonish(expected.get("editorial"))
    if not isinstance(editorial, dict):
        return ""
    excerpt = str(
        editorial.pop("customExcerpt", "")
        or editorial.pop("excerpt", "")
        or ""
    ).strip()
    expected["editorial"] = json.dumps(editorial, separators=(",", ":"))
    return excerpt


def _set_content_attachment_pointer(expected: dict[str, Any], key: str, attachment: dict[str, Any]) -> None:
    editorial = parse_jsonish(expected.get("editorial"))
    if not isinstance(editorial, dict):
        editorial = {}
    content_attachments = editorial.get("contentAttachments")
    if not isinstance(content_attachments, dict):
        content_attachments = {}
    content_attachments[key] = {
        "role": attachment.get("role"),
        "storagePath": attachment.get("storagePath"),
        "mediaType": attachment.get("mediaType"),
        "filename": attachment.get("filename"),
        "byteSize": attachment.get("byteSize"),
        "ownerKind": attachment.get("ownerKind"),
    }
    editorial["contentAttachments"] = content_attachments
    expected["editorial"] = json.dumps(editorial, separators=(",", ":"))


def expand_private_payload_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for record in records:
        expected = dict(record.get("expected") or {})
        now = expected.get("updatedAt") or expected.get("createdAt")
        if record["modelName"] == "Message":
            message_body_attachment = _message_body_attachment_for_expected(expected, now=now)
            if message_body_attachment:
                expanded.append(message_body_attachment)
            if "metadata" in expected:
                metadata = parse_jsonish(expected.pop("metadata"))
                expanded.append(
                    attachment_record(
                        build_json_model_payload_attachment(
                            {
                                "ownerKind": "message",
                                "ownerId": expected["id"],
                                "ownerLineageId": expected["id"],
                                "role": "metadata",
                                "sortKey": "metadata",
                                "content": metadata,
                                "importRunId": expected.get("importRunId"),
                                "now": now,
                            }
                        )
                )
            )
        elif record["modelName"] in {"Item", "PublishedItem"}:
            expanded.extend(_item_payload_attachments_for_expected(record["modelName"], expected, now=now))
        elif record["modelName"] == "Reference" and "metadata" in expected:
            metadata = parse_jsonish(expected.pop("metadata"))
            expanded.append(
                attachment_record(
                    build_json_model_payload_attachment(
                        {
                            "ownerKind": "reference",
                            "ownerId": expected["id"],
                            "ownerLineageId": expected.get("lineageId") or expected["id"],
                            "ownerVersionNumber": expected.get("versionNumber"),
                            "ownerVersionKey": semantic_version_key("reference", expected["id"]),
                            "role": "metadata",
                            "sortKey": "metadata",
                            "content": metadata,
                            "importRunId": expected.get("importRunId"),
                            "now": now,
                        }
                    )
                )
            )
        elif record["modelName"] == "Assignment" and "metadata" in expected:
            metadata = parse_jsonish(expected.pop("metadata"))
            expanded.append(
                attachment_record(
                    build_json_model_payload_attachment(
                        {
                            "ownerKind": "assignment",
                            "ownerId": expected["id"],
                            "ownerLineageId": expected["id"],
                            "role": "metadata",
                            "sortKey": "metadata",
                            "content": metadata,
                            "importRunId": expected.get("importRunId"),
                            "now": now,
                        }
                    )
                )
            )
        elif record["modelName"] == "KnowledgeRawPayload" and "payload" in expected:
            payload = parse_jsonish(expected.pop("payload"))
            expanded.append(
                attachment_record(
                    build_json_model_payload_attachment(
                        {
                            "ownerKind": "knowledgeRawPayload",
                            "ownerId": expected["id"],
                            "ownerLineageId": expected["id"],
                            "role": "raw_payload",
                            "sortKey": expected.get("payloadKind") or "payload",
                            "filename": f"{safe_id(expected.get('payloadKind') or 'payload')}.json",
                            "content": payload,
                            "importRunId": expected.get("importRunId"),
                            "now": now,
                        }
                    )
                )
            )
        expanded.append({**record, "expected": expected})
    return expanded


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def semantic_version_key(kind: str, version_id: str) -> str:
    return f"{kind}#{version_id}"


def download_attachment_buffer(
    client: PapyrusGraphQLAuthoringClient,
    attachment: dict[str, Any],
    *,
    bucket: str | None = None,
) -> bytes | None:
    if not attachment.get("storagePath"):
        return None
    slot = client.create_model_attachment_download(attachment["id"])
    if not slot.get("downloadUrl"):
        raise ValueError(f"ModelAttachment {attachment['id']} download slot did not include a URL.")
    headers = {str(key): str(value) for key, value in (slot.get("requiredHeaders") or {}).items()}
    request = urllib.request.Request(
        slot["downloadUrl"],
        headers=headers,
        method=slot.get("method") or "GET",
    )
    try:
        with urllib.request.urlopen(request) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Failed to download ModelAttachment {attachment['id']} from {slot.get('storagePath')}: "
            f"{error.code} {error.reason} {detail[:240]}"
        ) from error


def list_attachment_storage_paths(*, bucket: str | None = None, prefix: str = "newsroom/payloads/") -> dict[str, Any]:
    resolved_bucket = bucket or storage_bucket_from_amplify_outputs()
    if not resolved_bucket:
        raise ValueError("Could not resolve storage bucket for ModelAttachment listing. Pass --bucket or refresh amplify_outputs.json.")
    keys: list[str] = []
    continuation_token: str | None = None
    while True:
        args = [
            "s3api",
            "list-objects-v2",
            "--bucket",
            resolved_bucket,
            "--prefix",
            prefix,
            "--output",
            "json",
        ]
        if continuation_token:
            args.extend(["--continuation-token", continuation_token])
        result = subprocess.run(
            ["aws", *args],
            cwd=PAPYRUS_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to list ModelAttachment objects in s3://{resolved_bucket}/{prefix}: "
                f"{result.stderr or result.stdout}"
            )
        parsed = json.loads(result.stdout or "{}")
        keys.extend(entry["Key"] for entry in parsed.get("Contents") or [] if entry.get("Key"))
        continuation_token = parsed.get("NextContinuationToken") if parsed.get("IsTruncated") else None
        if not continuation_token:
            break
    return {"bucket": resolved_bucket, "prefix": prefix, "keys": keys}


def delete_attachment_storage_paths(
    storage_paths: list[str],
    *,
    bucket: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    paths = sorted({str(path) for path in storage_paths if path})
    resolved_bucket = bucket or storage_bucket_from_amplify_outputs()
    if not resolved_bucket:
        raise ValueError("Could not resolve storage bucket for ModelAttachment batch delete. Pass --bucket or refresh amplify_outputs.json.")
    if not paths:
        return {"bucket": resolved_bucket, "attempted": 0, "deleted": 0, "chunks": 0, "errors": []}
    if dry_run:
        return {"bucket": resolved_bucket, "attempted": len(paths), "deleted": 0, "chunks": 0, "errors": [], "dryRun": True}
    deleted = 0
    errors: list[dict[str, Any]] = []
    chunks = 0
    for index in range(0, len(paths), 1000):
        chunks += 1
        chunk = paths[index : index + 1000]
        delete_payload = {"Objects": [{"Key": storage_path} for storage_path in chunk], "Quiet": False}
        temp_path = Path(tempfile.gettempdir()) / f"papyrus-delete-objects-{os.getpid()}-{chunks}.json"
        temp_path.write_text(json.dumps(delete_payload), encoding="utf-8")
        try:
            result = subprocess.run(
                [
                    "aws",
                    "s3api",
                    "delete-objects",
                    "--bucket",
                    resolved_bucket,
                    "--delete",
                    f"file://{temp_path}",
                    "--output",
                    "json",
                ],
                cwd=PAPYRUS_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or f"aws s3api delete-objects exited with {result.returncode}")
            parsed = json.loads(result.stdout or "{}")
            deleted += len(parsed.get("Deleted") or chunk)
            for entry in parsed.get("Errors") or []:
                errors.append(
                    {
                        "storagePath": entry.get("Key"),
                        "code": entry.get("Code"),
                        "message": entry.get("Message"),
                    }
                )
        finally:
            temp_path.unlink(missing_ok=True)
    if errors:
        preview = ", ".join(f"{entry.get('storagePath') or 'unknown'}:{entry.get('code') or 'error'}" for entry in errors[:3])
        raise RuntimeError(f"Failed to delete {len(errors)} ModelAttachment S3 object(s): {preview}")
    return {"bucket": resolved_bucket, "attempted": len(paths), "deleted": deleted, "chunks": chunks, "errors": errors}
