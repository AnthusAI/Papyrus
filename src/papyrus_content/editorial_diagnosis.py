from __future__ import annotations

import re
from typing import Any

from .editorial_diagnosis_schema import (
    SCHEMA_VERSION,
    stable_finding_id,
    stable_repetition_group_id,
    validate_diagnosis,
)
from .editorial_style import LoadedStyleProfile

_EMPTY_LEADIN_PATTERNS = (
    r"^In today's\b",
    r"^It is important to note\b",
    r"^When it comes to\b",
    r"^At the end of the day\b",
    r"^In conclusion\b",
)

_CERTAINTY_PATTERN = re.compile(
    r"\b(everyone knows|always|never|undeniably|proven|clearly)\b",
    re.IGNORECASE,
)

_CITATION_PATTERN = re.compile(
    r"(https?://|\[[0-9]+\]|according to|\([12][0-9]{3}\)|\b20[0-9]{2}\b)",
    re.IGNORECASE,
)

_LIST_SHAPED_PATTERN = re.compile(
    r"\bFirst,\s+.+\bSecond,\s+.+\bThird,\s+",
    re.IGNORECASE,
)

_INTENSIFIER_VAGUE_PATTERN = re.compile(
    r"\b(very|significantly|dramatically|truly|really)\b.+\b(transform|revolutionize|leverage)\b",
    re.IGNORECASE,
)

_PASSIVE_PATTERN = re.compile(r"\b(is|are|was|were|been|being)\s+\w+ed\b", re.IGNORECASE)

_STAT_CLAIM_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%?\b")


def diagnose_draft(draft_text: str, *, style_profile: LoadedStyleProfile) -> dict[str, Any]:
    text = draft_text.replace("\r\n", "\n")
    profile = style_profile.profile

    generic_passages: list[dict[str, Any]] = []
    unsupported_claims: list[dict[str, Any]] = []
    voice_observations: list[dict[str, Any]] = []
    required_facts: list[dict[str, Any]] = []

    generic_passages.extend(_check_empty_leadins(text))
    generic_passages.extend(_check_list_shaped_prose(text))
    generic_passages.extend(_check_vague_claims(text, profile.lexicon_avoid))
    generic_passages.extend(_check_intensifier_vague_claims(text))

    unsupported_claims.extend(_check_unsupported_certainty(text))
    voice_observations.extend(_check_uniform_cadence(text))
    voice_observations.extend(_check_voice_mismatch(text, style_profile))

    repetition_groups = _check_redundancy(text)
    required_facts.extend(_check_required_facts(text))

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "document_intent": _extract_document_intent(text),
        "audience": profile.audience,
        "generic_passages": generic_passages,
        "unsupported_claims": unsupported_claims,
        "repetition_groups": repetition_groups,
        "voice_observations": voice_observations,
        "required_facts": required_facts,
    }
    return validate_diagnosis(result)


def normalize_finding_decision(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"skip", "rewrite", "delete", "keep", "add"}:
        raise ValueError("Finding decision must be skip, rewrite, delete, keep, or add.")
    return normalized


def record_finding_decision(
    decisions: list[dict[str, Any]],
    finding_id: str,
    decision: str,
    note: str = "",
) -> list[dict[str, Any]]:
    if not finding_id.strip():
        raise ValueError("finding_id is required.")
    normalized = normalize_finding_decision(decision)
    updated = list(decisions)
    updated.append(
        {
            "schemaVersion": SCHEMA_VERSION,
            "finding_id": finding_id.strip(),
            "decision": normalized,
            "note": note.strip(),
        }
    )
    return updated


def findings_marked_rewrite(
    diagnosis: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    validated = validate_diagnosis(diagnosis)
    rewrite_ids = {
        entry["finding_id"]
        for entry in decisions
        if isinstance(entry, dict) and entry.get("decision") == "rewrite" and entry.get("finding_id")
    }
    if not rewrite_ids:
        return []

    findings_by_id: dict[str, dict[str, Any]] = {}
    for array_key in ("generic_passages", "unsupported_claims", "voice_observations", "required_facts"):
        for finding in validated.get(array_key, []):
            findings_by_id[finding["id"]] = finding
    for group in validated.get("repetition_groups", []):
        findings_by_id[group["id"]] = group
        for member in group.get("members", []):
            findings_by_id[member["id"]] = member

    return [findings_by_id[finding_id] for finding_id in sorted(rewrite_ids) if finding_id in findings_by_id]


def _extract_document_intent(text: str) -> str:
    for paragraph in _paragraphs(text):
        for sentence in _sentences(paragraph):
            cleaned = sentence.strip()
            if cleaned:
                return cleaned
    raise ValueError("Draft must contain at least one sentence for document_intent.")


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if part.strip()]


def _sentence_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    cursor = 0
    for paragraph in _paragraphs(text):
        paragraph_start = text.find(paragraph, cursor)
        if paragraph_start < 0:
            paragraph_start = cursor
        local_offset = 0
        for sentence in _sentences(paragraph):
            start = paragraph_start + paragraph.find(sentence, local_offset)
            end = start + len(sentence)
            spans.append((sentence, start, end))
            local_offset = paragraph.find(sentence, local_offset) + len(sentence)
        cursor = paragraph_start + len(paragraph)
    return spans


def _make_finding(kind: str, draft_text: str, start: int, end: int, rationale: str) -> dict[str, Any]:
    return {
        "id": stable_finding_id(kind, draft_text, start, end),
        "kind": kind,
        "excerpt": draft_text[start:end],
        "span": {"start": start, "end": end},
        "rationale": rationale,
    }


def _check_empty_leadins(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence, start, end in _sentence_spans(text):
        for pattern in _EMPTY_LEADIN_PATTERNS:
            if re.search(pattern, sentence, re.IGNORECASE):
                findings.append(
                    _make_finding(
                        "empty_leadin",
                        text,
                        start,
                        end,
                        "Sentence opens with empty boilerplate instead of a concrete stake.",
                    )
                )
                break
    return findings


def _check_list_shaped_prose(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for paragraph in _paragraphs(text):
        match = _LIST_SHAPED_PATTERN.search(paragraph)
        if not match:
            continue
        paragraph_start = text.find(paragraph)
        if paragraph_start < 0:
            continue
        start = paragraph_start
        end = paragraph_start + len(paragraph)
        findings.append(
            _make_finding(
                "list_shaped_prose",
                text,
                start,
                end,
                "Paragraph reads like an inline list without substantive development.",
            )
        )
    return findings


def _check_vague_claims(text: str, lexicon_avoid: tuple[str, ...]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    lowered_text = text.lower()
    for term in lexicon_avoid:
        normalized = term.strip().lower()
        if not normalized or normalized == "empty intensifiers without evidence":
            continue
        search_from = 0
        while True:
            index = lowered_text.find(normalized, search_from)
            if index < 0:
                break
            start = index
            end = index + len(normalized)
            findings.append(
                _make_finding(
                    "vague_claim",
                    text,
                    start,
                    end,
                    f"Passage uses avoided lexicon '{term}' without operational detail.",
                )
            )
            search_from = end
    return findings


def _check_intensifier_vague_claims(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence, start, end in _sentence_spans(text):
        if _INTENSIFIER_VAGUE_PATTERN.search(sentence):
            findings.append(
                _make_finding(
                    "vague_claim",
                    text,
                    start,
                    end,
                    "Sentence pairs empty intensifiers with vague transformation language.",
                )
            )
    return findings


def _check_unsupported_certainty(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence, start, end in _sentence_spans(text):
        if not _CERTAINTY_PATTERN.search(sentence):
            continue
        if _CITATION_PATTERN.search(sentence):
            continue
        findings.append(
            _make_finding(
                "unsupported_certainty",
                text,
                start,
                end,
                "Sentence states certainty without attributable evidence.",
            )
        )
    return findings


def _check_uniform_cadence(text: str) -> list[dict[str, Any]]:
    spans = _sentence_spans(text)
    if len(spans) < 5:
        return []

    findings: list[dict[str, Any]] = []
    run_start = 0
    while run_start < len(spans):
        anchor_len = len(spans[run_start][0].split())
        run_end = run_start + 1
        while run_end < len(spans):
            length = len(spans[run_end][0].split())
            if abs(length - anchor_len) > 3:
                break
            run_end += 1
        if run_end - run_start >= 5:
            start = spans[run_start][1]
            end = spans[run_end - 1][2]
            findings.append(
                _make_finding(
                    "uniform_cadence",
                    text,
                    start,
                    end,
                    "Five or more consecutive sentences share nearly identical length.",
                )
            )
            run_start = run_end
            continue
        run_start += 1
    return findings


def _check_voice_mismatch(text: str, style_profile: LoadedStyleProfile) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    profile = style_profile.profile
    style_text = " ".join(profile.sentence_style).lower()
    prefers_contractions = "contraction" in style_text
    prefers_active = "active voice" in style_text

    if prefers_contractions or prefers_active:
        passive_without_contraction = 0
        block_start = None
        block_end = None
        for sentence, start, end in _sentence_spans(text):
            has_contraction = bool(re.search(r"\b\w+'\w+", sentence))
            is_passive = bool(_PASSIVE_PATTERN.search(sentence))
            mismatch = (prefers_active and is_passive) or (prefers_contractions and not has_contraction)
            if mismatch:
                if block_start is None:
                    block_start = start
                block_end = end
                passive_without_contraction += 1
            elif passive_without_contraction >= 3 and block_start is not None and block_end is not None:
                findings.append(
                    _make_finding(
                        "voice_mismatch",
                        text,
                        block_start,
                        block_end,
                        "Draft voice diverges from profile sentence style guidance.",
                    )
                )
                passive_without_contraction = 0
                block_start = None
                block_end = None
            else:
                passive_without_contraction = 0
                block_start = None
                block_end = None
        if passive_without_contraction >= 3 and block_start is not None and block_end is not None:
            findings.append(
                _make_finding(
                    "voice_mismatch",
                    text,
                    block_start,
                    block_end,
                    "Draft voice diverges from profile sentence style guidance.",
                )
            )

    for term in profile.lexicon_avoid:
        normalized = term.strip().lower()
        if not normalized:
            continue
        index = text.lower().find(normalized)
        if index < 0:
            continue
        finding = _make_finding(
            "voice_mismatch",
            text,
            index,
            index + len(normalized),
            f"Passage conflicts with profile avoid lexicon '{term}'.",
        )
        if finding["id"] not in {entry["id"] for entry in findings}:
            findings.append(finding)
    return findings


def _check_redundancy(text: str) -> list[dict[str, Any]]:
    shingles: dict[str, list[tuple[int, int, str]]] = {}
    for sentence, start, end in _sentence_spans(text):
        words = re.findall(r"[A-Za-z0-9']+", sentence.lower())
        for index in range(len(words) - 3):
            shingle = " ".join(words[index : index + 4])
            shingles.setdefault(shingle, []).append((start, end, sentence))

    groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    for occurrences in shingles.values():
        if len(occurrences) < 2:
            continue
        unique_spans = list(dict.fromkeys(occurrences))
        if len(unique_spans) < 2:
            continue
        members = []
        for start, end, sentence in unique_spans:
            member_id = stable_finding_id("redundancy", text, start, end)
            members.append(
                {
                    "id": member_id,
                    "kind": "redundancy",
                    "excerpt": sentence,
                    "span": {"start": start, "end": end},
                    "rationale": "Repeated phrasing across the draft.",
                }
            )
        group_id = stable_repetition_group_id([member["id"] for member in members])
        if group_id in seen_group_ids:
            continue
        seen_group_ids.add(group_id)
        groups.append(
            {
                "id": group_id,
                "kind": "redundancy",
                "members": members,
                "rationale": "Multiple passages repeat the same four-word phrase.",
            }
        )
    return groups


def _check_required_facts(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence, start, end in _sentence_spans(text):
        if not _STAT_CLAIM_PATTERN.search(sentence):
            continue
        if _CITATION_PATTERN.search(sentence):
            continue
        findings.append(
            _make_finding(
                "missing_attribution",
                text,
                start,
                end,
                "Numeric or statistical claim lacks attributable evidence.",
            )
        )
    return findings
