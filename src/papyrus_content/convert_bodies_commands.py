"""One-time conversion of legacy ``body[]`` content to Markus (PPY-cddfb8).

``papyrus content convert-bodies`` writes ``bodyMarkus`` and ``bodyIr`` for every
Item/PublishedItem that has neither, deriving them from the legacy paragraph
list (inline ``body`` or the body attachment). A record is only written when
the derived IR reproduces the original paragraphs exactly.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .markus_renderer.derive import derive_body, plain_paragraphs
from .model_attachments import download_attachment_buffer, parse_jsonish
from .options import parse_boolean_option, parse_comma_list, parse_options

PARAGRAPH_SEPARATOR = "\n\n"
CONVERTIBLE_MODELS = {"Item": "item_body", "PublishedItem": "published_item_body"}
INACTIVE_ATTACHMENT_STATUSES = {"deleted", "aborted"}

_ESCAPED_CHARACTERS_RE = re.compile(r"([\\`*_\[\]<>~|])")
_LINE_START_MARKER_RE = re.compile(r"^(#|\+|-|:)")
_LINE_START_ORDERED_LIST_RE = re.compile(r"^(\d+)([.)])")
_BLANK_LINE_RE = re.compile(r"\n{2,}")


def escape_markdown(paragraph: str) -> str:
    escaped_lines = []
    for line in paragraph.split("\n"):
        escaped = _ESCAPED_CHARACTERS_RE.sub(r"\\\1", line)
        escaped = _LINE_START_ORDERED_LIST_RE.sub(r"\1\\\2", escaped)
        escaped = _LINE_START_MARKER_RE.sub(r"\\\1", escaped)
        escaped_lines.append(escaped)
    return "\n".join(escaped_lines)


def paragraphs_to_markus(paragraphs: list[str]) -> str:
    return PARAGRAPH_SEPARATOR.join(escape_markdown(paragraph) for paragraph in paragraphs)


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def split_paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n")
    return [part.strip() for part in _BLANK_LINE_RE.split(normalized) if part.strip()]


def derive_from_paragraphs(paragraphs: list[str]) -> tuple[str, dict | None, str | None]:
    """Return (bodyMarkus, bodyIr, skip reason); the IR is None when the skip reason is set."""
    body_markus = paragraphs_to_markus(paragraphs)
    derivation = derive_body(None, body_markus)
    if not derivation.ok:
        codes = ",".join(error.code for error in derivation.errors)
        return body_markus, None, f"derive-failed:{codes}"
    expected = [normalize_whitespace(paragraph) for paragraph in paragraphs]
    derived = [normalize_whitespace(paragraph) for paragraph in plain_paragraphs(derivation.body_ir)]
    if derived != expected:
        return body_markus, None, "not-lossless"
    return body_markus, derivation.body_ir, None


def to_aws_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _inline_paragraphs(record: dict[str, Any]) -> list[str]:
    body = record.get("body") or []
    return [str(entry).strip() for entry in body if entry is not None and str(entry).strip()]


def _attachment_paragraphs(
    client: PapyrusGraphQLAuthoringClient, record: dict[str, Any], role: str
) -> list[str] | None:
    attachments = client.list_by_index("modelAttachmentsByOwnerRoleAndSortKey", str(record["id"]), limit=100)
    for attachment in attachments:
        if str(attachment.get("role") or "") != role:
            continue
        if str(attachment.get("status") or "").strip().lower() in INACTIVE_ATTACHMENT_STATUSES:
            continue
        buffer = download_attachment_buffer(client, attachment)
        if buffer is not None:
            return split_paragraphs(buffer.decode("utf-8"))
    return None


def plan_record_conversion(
    client: PapyrusGraphQLAuthoringClient, model_name: str, record: dict[str, Any]
) -> dict[str, Any]:
    row = {"model": model_name, "id": record.get("id"), "slug": record.get("slug")}
    if record.get("bodyMarkus") is not None:
        return {**row, "status": "already-converted"}
    paragraphs = _inline_paragraphs(record)
    if not paragraphs:
        attached = _attachment_paragraphs(client, record, CONVERTIBLE_MODELS[model_name])
        paragraphs = attached or []
    body_markus, body_ir, skip_reason = derive_from_paragraphs(paragraphs)
    if skip_reason:
        return {**row, "status": f"skipped:{skip_reason}"}
    return {
        **row,
        "status": "convertible",
        "paragraphCount": len(paragraphs),
        "_update": {
            "id": record["id"],
            "bodyMarkus": body_markus,
            "bodyIr": to_aws_json(body_ir),
            "metadata": to_aws_json({**(parse_jsonish(record.get("metadata")) or {}), "convertedFrom": "body[]"}),
        },
    }


def convert_bodies(
    client: PapyrusGraphQLAuthoringClient, model_names: list[str], *, apply: bool
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for model_name in model_names:
        for record in client.list_records(model_name):
            plan = plan_record_conversion(client, model_name, record)
            update = plan.pop("_update", None)
            if update is not None and apply:
                client.update_record(model_name, update)
                plan["status"] = "converted"
            rows.append(plan)
    return rows


def content_convert_bodies(flags: list[str]) -> None:
    options = parse_options(flags)
    dry_run = parse_boolean_option(options.get("dry-run"), default=False, label="--dry-run")
    apply = parse_boolean_option(options.get("apply"), default=False, label="--apply")
    if dry_run and apply:
        raise ValueError("Pass either --dry-run or --apply, not both.")
    model_names = parse_comma_list(options.get("models")) or list(CONVERTIBLE_MODELS)
    unsupported = [name for name in model_names if name not in CONVERTIBLE_MODELS]
    if unsupported:
        raise ValueError(f"--models accepts only {', '.join(CONVERTIBLE_MODELS)}; got {', '.join(unsupported)}.")

    client, _ = create_authoring_client()
    rows = convert_bodies(client, model_names, apply=apply)

    if options.get("json"):
        print(json.dumps({"ok": True, "command": "content convert-bodies", "apply": apply, "records": rows}, indent=2))
    else:
        for row in rows:
            print(f"content\tconvert-bodies\t{row['model']}\t{row['id']}\t{row['slug']}\t{row['status']}")
        if not apply:
            print("content\tconvert-bodies\tdry-run\tpass --apply to write")
