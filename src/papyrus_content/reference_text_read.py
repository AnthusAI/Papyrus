"""Read a Reference's captured text (the `curation-text` body, or the editor's newest corrected text) as a slice, with what a reviewer needs to trust it.

Read only. The text lives in a ModelAttachment body that the signed download slot serves (the same path the console uses); nothing here guesses a bucket.
"""
from __future__ import annotations

from typing import Any

from .reference_capture_state import completeness_flags
from .reference_curation_store import AttachmentStore, current_text, read_card
from .story_reporting import current_reference

DEFAULT_LIMIT = 20_000


class NoCapturedText(Exception):
    """The Reference exists but holds no captured text; ``details`` says what the curation card recorded."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


def read_reference_text(client: Any, reference_id: str, *, offset: int = 0, limit: int | None = DEFAULT_LIMIT) -> dict[str, Any]:
    """The slice ``[offset, offset + limit)`` of the stored text and its facts. ``limit`` of None or 0 returns everything from ``offset``."""
    if offset < 0 or (limit is not None and limit < 0):
        raise ValueError("--offset and --limit must be zero or more.")
    reference = current_reference(client, reference_id)
    if reference is None:
        raise ValueError(f"Reference not found: {reference_id}. Pass an id or lineage id that `papyrus stories show` or `references list` prints.")
    card = read_card(client, reference)
    capture = (card or {}).get("capture") or {}
    signals = (card or {}).get("signals") or {}
    text = current_text(card, reference, AttachmentStore(client)) if card else None
    facts = {"referenceId": reference["id"], "lineage": reference.get("lineageId") or reference["id"], "url": reference.get("sourceUri") or "",
             "captureStatus": capture.get("status") or "none", "captureReason": capture.get("reason")}
    if not text:
        raise NoCapturedText("no captured text", facts)
    edited = any(edit.get("kind") == "text" for edit in (card or {}).get("edits") or [])
    end = len(text) if not limit else min(len(text), offset + limit)
    piece = text[offset:end]
    return {
        **facts,
        "text": piece,
        "totalCharacters": len(text), "offset": offset, "returnedCharacters": len(piece),
        "nextOffset": end if end < len(text) else None,
        "source": "edited by editor" if edited else (capture.get("textVia") or capture.get("via") or capture.get("sourceKind") or "capture"),
        "sourceKind": capture.get("sourceKind"), "capturedAt": capture.get("capturedAt"),
        "destinationUrl": capture.get("destinationUrl"),
        # `truncated` is true when the capture itself was cut at the reader's size guard; it says nothing about this slice (see nextOffset).
        "truncated": bool(signals.get("responseTruncated")),
        "pdfPageCount": signals.get("pdfPageCount"),
        "flags": completeness_flags(signals),
    }
