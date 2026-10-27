"""Where curation-before-review keeps its outputs on a Reference, and the editor's way to correct them.

Nothing here changes a model. A Reference's curation lives in two existing places (``docs/reference-curation-pipeline.md`` has the
shapes, for the UI):

* **The curation card**: one ``ReferenceAttachment`` per Reference (role ``curation``, sort key ``003-curation``), like the feed's
  ``preview`` card. Its ``metadata`` is JSON: status, completeness signals, the summary, the paper/GROBID facts, the editor edits and
  the labels they leave. The newsroom already loads every ReferenceAttachment with the References, so a list needs no extra request.
* **The bodies**: ``ModelAttachment`` rows owned by the Reference version (role ``metadata``, sort keys ``curation-*``): the captured
  text, the GROBID fields and TEI, and one new body per editor correction. Corrections never overwrite the machine capture.

This module imports no network or PDF code so the content-actions Lambda can use ``apply_editor_correction`` as it is.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from .ids import hash_short
from .model_attachments import build_model_payload_attachment, download_attachment_buffer, model_attachment_id, upload_attachment_body

PIPELINE_VERSION = "reference-curation-v1"
CARD_SCHEMA_VERSION = 1
CARD_ATTACHMENT_TYPE = "curation"
CARD_SORT_KEY = "003-curation"
BODY_ROLE = "metadata"
TEXT_SORT_KEY = "curation-text"
GROBID_SORT_KEY = "curation-grobid"
GROBID_TEI_SORT_KEY = "curation-grobid-tei"
METADATA_SORT_KEY = "metadata"
EDITOR_PROVENANCE = "edited by editor"
ASSESSMENTS = ("complete", "incomplete", "incorrect")
GROBID_FIELD_NAMES = ("title", "authors", "abstract", "doi", "keywords", "sections", "references")
LEASE_SECONDS = 30 * 60

STATUS_RUNNING = "running"
STATUS_READY = "ready"
STATUS_DEGRADED = "degraded"
STATUS_CAPTURE_FAILED = "capture_failed"


class CurationError(ValueError):
    """A request the curation store refuses (an unknown Reference, a malformed correction)."""


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def edit_sort_key(number: int, kind: str) -> str:
    return f"curation-edit-{number:04d}-{kind}"


# --- the card --------------------------------------------------------------------------------------------------------


def card_id(reference: dict[str, Any]) -> str:
    return f"reference-attachment-{hash_short([f'reference#{reference['id']}', CARD_ATTACHMENT_TYPE, CARD_SORT_KEY])}"


def new_card(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "reference-curation", "schemaVersion": CARD_SCHEMA_VERSION, "pipelineVersion": PIPELINE_VERSION,
        "referenceId": reference["id"], "referenceLineageId": reference.get("lineageId") or reference["id"],
        "status": STATUS_DEGRADED, "capture": {"status": "not_run"}, "signals": {}, "paper": {}, "summary": {"status": "not_run"},
        "grobid": {"status": "not_run"}, "current": {}, "edits": [], "labels": [],
    }


def read_card(client: Any, reference: dict[str, Any]) -> dict[str, Any] | None:
    row = client.get_record("ReferenceAttachment", card_id(reference))
    if not row:
        return None
    try:
        card = json.loads(row.get("metadata") or "{}")
    except (TypeError, ValueError):
        return None
    return card if isinstance(card, dict) and card.get("kind") == "reference-curation" else None


def write_card(client: Any, reference: dict[str, Any], card: dict[str, Any], now: datetime) -> None:
    version_key = f"reference#{reference['id']}"
    card["updatedAt"] = iso(now)
    client.upsert("ReferenceAttachment", {
        "id": card_id(reference), "referenceId": reference["id"], "referenceLineageId": reference.get("lineageId") or reference["id"],
        "referenceVersionNumber": reference.get("versionNumber"), "referenceVersionKey": version_key,
        "role": CARD_ATTACHMENT_TYPE, "sortKey": CARD_SORT_KEY, "sourceUri": None, "filename": "curation.json", "mediaType": "application/json",
        "importedAt": iso(now), "metadata": json.dumps(card, sort_keys=True),
    })


def compute_status(card: dict[str, Any]) -> str:
    """ready: there is text (captured or pasted by an editor) and a summary of it. capture_failed: there is no text at all.
    degraded: there is text but a stage that was needed has not finished (the summary, usually)."""
    current = card.get("current") or {}
    has_text = (card.get("capture") or {}).get("status") == "completed" or bool(current.get("textSortKey"))
    if not has_text:
        return STATUS_CAPTURE_FAILED if (card.get("capture") or {}).get("status") == "failed" else STATUS_DEGRADED
    summary = card.get("summary") or {}
    return STATUS_READY if summary.get("text") else STATUS_DEGRADED


def has_text_edit(card: dict[str, Any]) -> bool:
    return any(edit.get("kind") == "text" for edit in card.get("edits") or [])


# --- the bodies ------------------------------------------------------------------------------------------------------


class AttachmentStore:
    """Reads and writes the ``curation-*`` bodies (and the Reference's ``metadata.json``) as ModelAttachments of the Reference version."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def write(self, reference: dict[str, Any], sort_key: str, filename: str, media_type: str, content: str, now: datetime) -> dict[str, Any]:
        entry = build_model_payload_attachment({
            "ownerKind": "reference", "ownerId": reference["id"], "ownerLineageId": reference.get("lineageId") or reference["id"],
            "ownerVersionNumber": reference.get("versionNumber"), "ownerVersionKey": f"reference#{reference['id']}",
            "role": BODY_ROLE, "sortKey": sort_key, "filename": filename, "mediaType": media_type, "content": content,
            "importRunId": reference.get("importRunId"), "now": iso(now), "status": "active"})
        upload_attachment_body(self.client, entry["attachment"], entry["body"])
        return entry["attachment"]

    def read(self, reference: dict[str, Any], sort_key: str) -> bytes | None:
        attachment = self.client.get_record("ModelAttachment", model_attachment_id("reference", reference["id"], BODY_ROLE, sort_key))
        return download_attachment_buffer(self.client, attachment) if attachment else None

    def read_text(self, reference: dict[str, Any], sort_key: str) -> str | None:
        body = self.read(reference, sort_key)
        return body.decode("utf-8") if body is not None else None

    def read_json(self, reference: dict[str, Any], sort_key: str) -> dict[str, Any] | None:
        text = self.read_text(reference, sort_key)
        try:
            parsed = json.loads(text) if text else None
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None


def current_text(card: dict[str, Any], reference: dict[str, Any], store: AttachmentStore) -> str | None:
    sort_key = (card.get("current") or {}).get("textSortKey")
    return store.read_text(reference, sort_key) if sort_key else None


# --- editor corrections ----------------------------------------------------------------------------------------------


def _validated_grobid_fields(fields: Any) -> dict[str, Any]:
    if not isinstance(fields, dict) or not fields:
        raise CurationError("grobid must be an object with at least one field.")
    unknown = sorted(set(fields) - set(GROBID_FIELD_NAMES))
    if unknown:
        raise CurationError(f"Unsupported GROBID field(s): {', '.join(unknown)}.")
    for name, value in fields.items():
        if name in {"title", "abstract", "doi"} and not isinstance(value, str):
            raise CurationError(f"{name} must be text.")
        if name in {"authors", "keywords", "sections", "references"} and not isinstance(value, list):
            raise CurationError(f"{name} must be a list.")
        if name in {"authors", "sections", "references"} and any(not isinstance(item, dict) for item in value):
            raise CurationError(f"Every entry of {name} must be an object.")
        if name == "keywords" and any(not isinstance(item, str) for item in value):
            raise CurationError("Every keyword must be text.")
    return fields


def apply_editor_correction(
    client: Any,
    reference: dict[str, Any],
    *,
    editor: str,
    text: str | None = None,
    grobid: dict[str, Any] | None = None,
    assessment: str | None = None,
    note: str = "",
    now: datetime | None = None,
    store: AttachmentStore | None = None,
) -> dict[str, Any]:
    """Store an editor's correction as a new version, keep the original, and record the label it gives.

    ``text`` is the corrected or pasted full text. ``grobid`` holds corrected fields (any of ``GROBID_FIELD_NAMES``); they replace the
    same-named fields of the current extraction. ``assessment`` says whether the *machine capture* was ``complete``, ``incomplete`` or
    ``incorrect``; it is required with ``text`` because replacing the text is itself a judgment of the capture, and it is the training
    label for the future completeness classifier. A correction appends to ``edits`` and ``labels``; it never edits or deletes an earlier
    body. The summary of replaced text is marked ``stale`` and is rewritten by the next ``papyrus references curate`` run.
    """
    editor = (editor or "").strip()
    if not editor:
        raise CurationError("A correction needs the editor who made it.")
    if text is None and grobid is None and assessment is None:
        raise CurationError("Provide corrected text, corrected GROBID fields or an assessment of the capture.")
    if assessment is not None and assessment not in ASSESSMENTS:
        raise CurationError(f"assessment must be one of {', '.join(ASSESSMENTS)}.")
    if text is not None and (not isinstance(text, str) or not text.strip()):
        raise CurationError("Corrected text must not be empty.")
    if text is not None and assessment is None:
        raise CurationError("Replacing the text needs an assessment of the original capture (complete, incomplete or incorrect).")
    fields = _validated_grobid_fields(grobid) if grobid is not None else None
    now = now or utc_now()
    store = store or AttachmentStore(client)
    card = read_card(client, reference) or new_card(reference)
    card.setdefault("edits", [])
    card.setdefault("labels", [])
    card.setdefault("current", {})
    stamp = iso(now)
    number = 1 + max([int(edit.get("n") or 0) for edit in card["edits"]] or [0])
    original_text_sha = (card.get("capture") or {}).get("textSha256")
    made: list[dict[str, Any]] = []

    if text is not None:
        sort_key = edit_sort_key(number, "text")
        store.write(reference, sort_key, f"{sort_key}.md", "text/markdown", text, now)
        made.append({"n": number, "kind": "text", "sortKey": sort_key, "editedBy": editor, "editedAt": stamp, "provenance": EDITOR_PROVENANCE,
                     "basedOn": card["current"].get("textSortKey"), "originalSortKey": TEXT_SORT_KEY if original_text_sha else None,
                     "sha256": sha256_text(text), "note": note})
        card["current"]["textSortKey"] = sort_key
        from .reference_capture import completeness_signals

        card["editedSignals"] = {**completeness_signals(text), "editedAt": stamp}
        summary = card.get("summary") or {}
        if summary.get("text"):
            card["summary"] = {**summary, "stale": True, "staleSince": stamp}
        number += 1

    if fields is not None:
        base = store.read_json(reference, card["current"].get("grobidSortKey") or GROBID_SORT_KEY) or {}
        merged = {**base, **fields}
        sort_key = edit_sort_key(number, "grobid")
        store.write(reference, sort_key, f"{sort_key}.json", "application/json", json.dumps(merged, indent=2, sort_keys=True) + "\n", now)
        made.append({"n": number, "kind": "grobid", "sortKey": sort_key, "editedBy": editor, "editedAt": stamp, "provenance": EDITOR_PROVENANCE,
                     "basedOn": card["current"].get("grobidSortKey"), "correctedFields": sorted(fields), "note": note})
        card["current"]["grobidSortKey"] = sort_key
        grobid_card = dict(card.get("grobid") or {})
        grobid_card.update({"status": "completed", "editedByEditor": True})
        from .reference_grobid import summarize_fields

        grobid_card.update(summarize_fields(merged))
        card["grobid"] = grobid_card

    if assessment is not None:
        capture = card.get("capture") or {}
        card["labels"].append({
            "kind": "capture_completeness", "assessment": assessment, "labeledBy": editor, "labeledAt": stamp, "note": note,
            "textReplaced": text is not None, "originalCaptureStatus": capture.get("status"), "originalFailure": capture.get("reason"),
            "originalSourceKind": capture.get("sourceKind"), "originalTextSortKey": TEXT_SORT_KEY if original_text_sha else None,
            "originalTextSha256": original_text_sha, "originalSignals": card.get("signals") or {},
            "originalPaper": (card.get("paper") or {}).get("isPaper"), "editSortKeys": [edit["sortKey"] for edit in made]})
    card["edits"].extend(made)
    card["status"] = compute_status(card)
    write_card(client, reference, card, now)
    return {"referenceId": reference["id"], "status": card["status"], "edits": made, "label": card["labels"][-1] if assessment is not None else None,
            "summaryStale": bool((card.get("summary") or {}).get("stale"))}


def find_reference(client: Any, reference_id: str) -> dict[str, Any]:
    reference = client.get_record("Reference", reference_id)
    if not reference:
        raise CurationError("The Reference was not found.")
    return reference


_REFERENCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,300}$")


def correct_reference_capture(client: Any, arguments: dict[str, Any], identity: dict[str, Any],
                              now: Callable[[], datetime] = utc_now, store: AttachmentStore | None = None) -> dict[str, Any]:
    """The AppSync action ``correctReferenceCapture`` (content-actions Lambda): validated request in, stored correction out.

    ``arguments`` holds ``referenceId`` and any of ``text``, ``grobid`` (object), ``assessment``, ``note``. The editor recorded is the
    signed-in caller (never a field of the request).
    """
    if set(arguments) - {"referenceId", "text", "grobid", "assessment", "note"}:
        raise CurationError("Unsupported correction fields; the editor is taken from the signed-in session.")
    reference_id = arguments.get("referenceId")
    if not isinstance(reference_id, str) or not _REFERENCE_ID.match(reference_id):
        raise CurationError("referenceId must be a Reference id.")
    editor = str((identity or {}).get("username") or (identity or {}).get("sub") or "").strip()
    note = arguments.get("note") or ""
    if not isinstance(note, str) or len(note) > 4000:
        raise CurationError("note must be text of at most 4000 characters.")
    reference = find_reference(client, reference_id)
    result = apply_editor_correction(client, reference, editor=editor, text=arguments.get("text"), grobid=arguments.get("grobid"),
                                     assessment=arguments.get("assessment"), note=note, now=now(), store=store)
    return {"ok": True, **result}
