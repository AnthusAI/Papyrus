"""The stored capture state of a Reference (``Reference.captureState``): how much of its content the newsroom holds.

``full``, ``thin``, ``none`` or ``running``; empty means ``none`` (a monitor-discovered Reference has only its address). Only ``full`` counts as
captured. This rule decides today: no capture classifier exists yet (docs/reference-curation-pipeline.md). It is a faithful port of
``storedCaptureState`` / ``captureStatus`` in lib/reference-capture.ts, from the same inputs (the Reference's attachments: the curation card, else
the older extracted-text attachments), tested against the same vectors (scripts/fixtures/capture-state-vectors.json).

* Text a person pasted, corrected or uploaded is ``full`` whatever its length.
* Otherwise an editor's assessment of the capture wins: ``complete`` is ``full``; ``incomplete`` and ``incorrect`` are ``thin`` (it asks for a person again).
* Otherwise the text is ``thin`` when shorter than the teaser line or showing signs of being cut off or paywalled, else ``full``.
* No text is ``none``; a capture still being made with no text yet is ``running``. An assessment cannot create text.

The stored copy always uses ``DEFAULT_TEASER_WORDS``; the browser's cards use the line learned from the site's own corpus and may differ by a few words near it.

``sync_capture_state`` is the one writer helper every path that changes captured text or the curation card calls.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable, Mapping

CAPTURE_STATES = ("full", "thin", "none", "running")
DEFAULT_TEASER_WORDS = 250
AVERAGE_CHARACTERS_PER_WORD = 6
CARD_ATTACHMENT_TYPE = "curation"
CURATION_SORT_KEY = "003-curation"
EXTRACTED_TEXT_ROLES = ("extracted_text", "extracted_text_raw")
CARD_STATUSES = ("ready", "degraded", "capture_failed", "running")
_DOUBT = re.compile(r"ends with|stops with|no longer|not free|cut|declares")


def normalize_capture_state(value: Any) -> str:
    """The stored value as a state: empty, missing or unknown is ``none``."""
    return value if isinstance(value, str) and value in CAPTURE_STATES else "none"


def is_captured(value: Any) -> bool:
    return normalize_capture_state(value) == "full"


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _metadata(attachment: Mapping[str, Any]) -> dict[str, Any]:
    raw = attachment.get("metadata")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _card_of(attachments: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    for row in attachments:
        if row.get("role") == CARD_ATTACHMENT_TYPE and (row.get("sortKey") == CURATION_SORT_KEY or not row.get("sortKey")):
            card = _metadata(row)
            return card if card.get("status") in CARD_STATUSES else None
    return None


def completeness_flags(signals: Mapping[str, Any]) -> list[str]:
    """Plain-words signs the text may be cut off or paywalled (``completenessFlags``)."""
    flags: list[str] = []
    markers = [_object(marker) for marker in signals.get("paywallMarkers")] if isinstance(signals.get("paywallMarkers"), list) else []
    if any(marker.get("inTail") is True for marker in markers):
        flags.append("The text ends with a subscribe or sign-in phrase.")
    elif markers:
        flags.append("The text mentions subscribing or signing in.")
    if signals.get("endingPattern") in ("ellipsis", "truncation_marker"):
        flags.append("The text stops with an ellipsis or a cut-off marker.")
    elif signals.get("endingPattern") == "no_terminal_punctuation":
        flags.append("The text stops mid-sentence.")
    if signals.get("bodyNotLongerThanDescription") is True:
        flags.append("The text is no longer than the page's own description.")
    if signals.get("structuredAccessibleForFree") is False:
        flags.append("The page declares the article is not free to read.")
    ratio = signals.get("wordCountRatioToDeclared")
    if _number(ratio) and ratio < 0.6 and _number(signals.get("declaredWordCount")):
        flags.append(f"The page declares {signals['declaredWordCount']} words; we hold about {round(ratio * 100)}% of that.")
    if signals.get("responseTruncated") is True:
        flags.append("The page was larger than we read and was cut.")
    empty = signals.get("pdfEmptyPageCount")
    if _number(empty) and empty > 0 and _number(signals.get("pdfPageCount")):
        flags.append(f"{empty} of {signals['pdfPageCount']} PDF pages had no text (scanned).")
    return flags


def _card_words(card: Mapping[str, Any]) -> int | float | None:
    edited = _object(card.get("editedSignals")).get("wordCount")
    if _number(edited):
        return edited
    captured = _object(card.get("capture")).get("wordCount")
    if not _number(captured):
        captured = _object(card.get("signals")).get("wordCount")
    return captured if _number(captured) else None


def _primary_text(attachments: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    rows = [row for row in attachments if row.get("role") in EXTRACTED_TEXT_ROLES and (row.get("storagePath") or row.get("sourceUri"))]

    def newest(role: str) -> Mapping[str, Any] | None:
        found = [row for row in rows if row.get("role") == role]
        return sorted(found, key=lambda row: (str(row.get("importedAt") or ""), str(row.get("id") or "")), reverse=True)[0] if found else None

    return newest("extracted_text") or newest("extracted_text_raw")


def _recorded_characters(attachment: Mapping[str, Any]) -> int | float | None:
    length = _metadata(attachment).get("textLength")
    if _number(length) and length >= 0:
        return length
    size = attachment.get("byteSize")
    return size if _number(size) and size >= 0 else None


def _estimated_words(attachments: list[Mapping[str, Any]], card: Mapping[str, Any] | None) -> int | None:
    card_words = _card_words(card) if card else None
    if card_words is not None and card_words > 0:
        return int(card_words)
    primary = _primary_text(attachments)
    characters = _recorded_characters(primary) if primary else None
    return None if characters is None else math.floor(characters / AVERAGE_CHARACTERS_PER_WORD + 0.5)


def capture_state(attachments: Iterable[Mapping[str, Any]], teaser_line: int = DEFAULT_TEASER_WORDS) -> str:
    """The state to store for a Reference from its attachments (``captureStateOfAttachments``)."""
    rows = list(attachments)
    card = _card_of(rows)
    assessment = None
    if card:
        labels = [_object(label) for label in card.get("labels") or [] if isinstance(label, dict)]
        kinds = [label for label in labels if label.get("kind") == "capture_completeness"]
        assessment = kinds[-1].get("assessment") if kinds else None
    card_words = _card_words(card) if card else None
    card_has_text = bool(card and (card_words or 0) > 0 and (_object(card.get("capture")).get("status") == "completed" or _object(card.get("current")).get("textSortKey")))
    if card and card_has_text:
        words = card_words
        flags = completeness_flags(card.get("editedSignals") if isinstance(card.get("editedSignals"), dict) and card.get("editedSignals") else _object(card.get("signals")))
        edited = str(_object(card.get("current")).get("textSortKey") or "").startswith("curation-edit")
        thin = not edited and words is not None and words < teaser_line
        doubtful = (not edited and assessment != "complete" and bool(flags) and not thin and any(_DOUBT.search(flag) for flag in flags))
        state = "thin" if thin or doubtful else "full"
    elif _primary_text(rows):
        words = _estimated_words(rows, card)
        edited = False
        state = "thin" if words is None else "none" if words == 0 else "thin" if words < teaser_line else "full"
    elif card and card.get("status") == "running":
        return "running"
    else:
        return "none"
    if state == "none":
        return state
    if edited:
        return "full"
    if assessment == "complete":
        return "full"
    if assessment in ("incomplete", "incorrect"):
        return "thin"
    return state


def sync_capture_state(client: Any, reference: dict[str, Any], card: dict[str, Any] | None = None, *,
                       extra_attachments: list[dict[str, Any]] | None = None) -> str | None:
    """Make ``Reference.captureState`` right after captured text or the curation card changed. Returns the field written, or None when it was right.

    ``card`` is the card just built or changed (it may not be stored yet). When the card holds text the extracted-text attachments are not read at
    all; otherwise the Reference lineage's attachments are, because an older extracted text can stand in for it. A Reference with no capture and an
    empty field is already right, so nothing is written; a stale value on a Reference that now has none is cleared with null, never set to ``none``.
    """
    state = capture_state(attachments_for_state(client, reference, card, extra_attachments))
    current = normalize_capture_state(reference.get("captureState"))
    if state == current:
        return None
    value = None if state == "none" else state
    client.update_record("Reference", {"id": reference["id"], "captureState": value})
    reference["captureState"] = value
    return state


def _card_row(card: dict[str, Any]) -> dict[str, Any]:
    return {"id": "card", "role": CARD_ATTACHMENT_TYPE, "sortKey": CURATION_SORT_KEY, "metadata": card}


def attachments_for_state(client: Any, reference: dict[str, Any], card: dict[str, Any] | None = None,
                          extra_attachments: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if card is not None:
        row = _card_row(card)
        if capture_state([row]) in ("full", "thin"):
            return [row]   # the card holds text: nothing else is read
    lineage = reference.get("lineageId") or reference.get("id")
    rows = [dict(item) for item in client.list_by_index("referenceAttachmentsByReferenceLineageAndSortKey", str(lineage))] if lineage else []
    if extra_attachments:
        fresh = {str(item.get("id")) for item in extra_attachments}
        rows = [item for item in rows if str(item.get("id")) not in fresh] + [dict(item) for item in extra_attachments]
    if card is not None:
        rows = [item for item in rows if item.get("role") != CARD_ATTACHMENT_TYPE] + [_card_row(card)]
    return rows
