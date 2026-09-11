from __future__ import annotations

import re
from typing import Any

from .editorial_density import analyze_density, density_summary_as_dict
from .editorial_diagnosis_schema import (
    SCHEMA_VERSION,
    stable_finding_id,
    stable_repetition_group_id,
    validate_diagnosis,
)
from .editorial_style import LoadedStyleProfile
from .editorial_text import line_at_offset, paragraphs, sentence_spans, sentences, word_count

PROFILE_RULE_PREFIX = "Profile rule:"

_EMPTY_LEADIN_PATTERNS = (
    r"^In today's\b",
    r"^It is important to note\b",
    r"^When it comes to\b",
    r"^At the end of the day\b",
    r"^In conclusion\b",
)

# Self-closing MDX/JSX components (e.g. `<Citation data={{...}}/>`, `<BlogImage .../>`) carry
# structural prop boilerplate (field names like `container-title`, `date-parts`, `accessed`)
# that repeats verbatim across every citation in a piece. Left unmasked, the redundancy shingle
# check treats that shared JSX vocabulary as "repeated phrasing" and buries real findings under
# dozens of false positives on citation-heavy drafts. This masks such components (same character
# length, so spans into the original text stay valid) before shingling only -- sentence
# boundaries and reported excerpts still come from the original text.
_JSX_SELF_CLOSING_COMPONENT_RE = re.compile(r"<[A-Z][\w.]*(?:\s[\s\S]*?)?/>")

# Markus (the other renderer Papyrus content runs through, e.g. Pilobolus) uses colon-fenced
# directives instead of JSX: `::name{attrs}` self-closing on one line, or
# `:::name{attrs}\n...content...\n:::` block-level. Either way the attrs -- src=, alt=,
# credit=, attribution= -- repeat the same field names across every figure/pull-quote/aside
# in a piece, which is the same false-positive-redundancy trap JSX components create. Mask
# only the directive's opening line (name + attrs) and a bare `:::` closing line, not any real
# prose content sitting between them (a pull-quote's actual quoted text should still be
# checked normally).
_MARKUS_DIRECTIVE_OPEN_RE = re.compile(r"^:{2,3}[A-Za-z][\w-]*\{[^}\n]*\}[ \t]*$", re.MULTILINE)
_MARKUS_DIRECTIVE_CLOSE_RE = re.compile(r"^:::[ \t]*$", re.MULTILINE)

# A leading YAML frontmatter block (title/date/description/standfirst/...) has its own
# genre conventions -- a standfirst is deliberately terse by design -- that don't belong
# under body-prose rules like cadence or redundancy. Anth.us drafts never had frontmatter,
# so this never mattered until a differently-structured publication (Pilobolus, using
# `---\n...\n---` frontmatter) surfaced it: cadence findings were firing on the standfirst
# field itself. Mask it out (same length, so spans into the original text stay valid) before
# any check runs, for every publication, not just the one that happened to expose the gap.
_YAML_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

_PHRASE_CERTAINTY_PATTERN = re.compile(r"\b(everyone knows|undeniably|proven)\b", re.IGNORECASE)
_ALWAYS_NEVER_PATTERN = re.compile(r"\b(always|never)\b", re.IGNORECASE)
_HYPHENATED_ALWAYS_NEVER_PATTERN = re.compile(r"\b(always|never)-\w+", re.IGNORECASE)
_NEVER_AUXILIARY_PATTERN = re.compile(
    r"\bnever\s+(had|would|could|should|might|may|will|can)\b",
    re.IGNORECASE,
)
_CLEARLY_ASSERTIVE_PATTERN = re.compile(
    r"\bclearly\s+(shows|demonstrates|proves|will|is)\b",
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

_STAT_PERCENT_PATTERN = re.compile(r"\d+(?:\.\d+)?%")
_STAT_MULTIPLIER_PATTERN = re.compile(r"\d+\s*[×x]\b|\d+\s+times\b", re.IGNORECASE)
_STAT_COUNT_UNIT_PATTERN = re.compile(
    r"\b\d{3,}\s+(users|ms|seconds|minutes|hours|days|requests|tokens)\b",
    re.IGNORECASE,
)
_LIST_ORDINAL_LINE_PATTERN = re.compile(r"^\s*\d+\.\s")
_STICKER_NUMBER_PATTERN = re.compile(r"#\d+\b")

_REFRAIN_MAX_WORDS = 12


def _mask_yaml_frontmatter(text: str) -> str:
    match = _YAML_FRONTMATTER_RE.match(text)
    if not match:
        return text
    blanked = re.sub(r"[^\n]", " ", match.group(0))
    return blanked + text[match.end() :]


def diagnose_draft(draft_text: str, *, style_profile: LoadedStyleProfile) -> dict[str, Any]:
    text = draft_text.replace("\r\n", "\n")
    text = _mask_yaml_frontmatter(text)
    profile = style_profile.profile
    checks = profile.checks

    generic_passages: list[dict[str, Any]] = []
    unsupported_claims: list[dict[str, Any]] = []
    voice_observations: list[dict[str, Any]] = []
    required_facts: list[dict[str, Any]] = []

    if checks["emptyLeadin"]:
        generic_passages.extend(_check_empty_leadins(text))
    if checks["listShapedProse"]:
        generic_passages.extend(_check_list_shaped_prose(text))
    if checks["vagueClaim"]:
        generic_passages.extend(_check_vague_claims(text, profile.lexicon_avoid))
        generic_passages.extend(_check_intensifier_vague_claims(text))

    if checks["unsupportedCertainty"]:
        unsupported_claims.extend(_check_unsupported_certainty(text))
    if checks["uniformCadence"]:
        voice_observations.extend(_check_uniform_cadence(text))
    if checks["voiceMismatch"]:
        voice_observations.extend(_check_voice_mismatch(text, style_profile))

    repetition_groups = _check_redundancy(text) if checks["redundancy"] else []
    if checks["missingAttribution"]:
        required_facts.extend(_check_required_facts(text))

    density_summary: dict[str, Any] | None = None
    if checks["informationDensity"]:
        density_analysis = analyze_density(text, style_profile.profile.density)
        density_summary = density_summary_as_dict(density_analysis.summary)
        generic_passages.extend(density_analysis.findings)

    rules_findings = _check_profile_rules(
        text,
        style_profile,
        generic_passages=generic_passages,
        voice_observations=voice_observations,
    )
    generic_passages.extend(rules_findings["generic_passages"])
    voice_observations.extend(rules_findings["voice_observations"])

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
    if density_summary is not None:
        result["density"] = density_summary
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
    for paragraph in paragraphs(text):
        for sentence in sentences(paragraph):
            cleaned = sentence.strip()
            if cleaned:
                return cleaned
    raise ValueError("Draft must contain at least one sentence for document_intent.")


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
    for sentence, start, end in sentence_spans(text):
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
    for paragraph in paragraphs(text):
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
    for sentence, start, end in sentence_spans(text):
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


def _sentence_has_unsupported_certainty(sentence: str) -> bool:
    if _PHRASE_CERTAINTY_PATTERN.search(sentence):
        return True
    if _CLEARLY_ASSERTIVE_PATTERN.search(sentence):
        return True

    if not _ALWAYS_NEVER_PATTERN.search(sentence):
        return False

    stripped = _HYPHENATED_ALWAYS_NEVER_PATTERN.sub(" ", sentence)
    if not _ALWAYS_NEVER_PATTERN.search(stripped):
        return False

    if _NEVER_AUXILIARY_PATTERN.search(sentence):
        return False

    trimmed = sentence.strip()
    if re.match(r"^Never\s+\w", trimmed):
        return False

    return True


def _check_unsupported_certainty(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence, start, end in sentence_spans(text):
        if not _sentence_has_unsupported_certainty(sentence):
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
    spans = sentence_spans(text)
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
    prefers_active = "active voice" in style_text

    if prefers_active:
        for sentence, start, end in sentence_spans(text):
            if not _PASSIVE_PATTERN.search(sentence):
                continue
            findings.append(
                _make_finding(
                    "voice_mismatch",
                    text,
                    start,
                    end,
                    "Sentence uses passive voice where the profile prefers active voice.",
                )
            )

    for term in profile.lexicon_avoid:
        normalized = term.strip().lower()
        if not normalized or normalized == "empty intensifiers without evidence":
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


def _is_rhetorical_refrain(members: list[dict[str, Any]]) -> bool:
    excerpts = [member["excerpt"].strip() for member in members]
    normalized = {excerpt.lower() for excerpt in excerpts}
    if len(normalized) != 1:
        return False
    excerpt = excerpts[0]
    if re.match(r"^#+\s", excerpt):
        return True
    if word_count(excerpt) <= _REFRAIN_MAX_WORDS:
        return True
    return False


def _blank_match(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def _mask_jsx_components(text: str) -> str:
    """Blank out self-closing JSX component markup, preserving length and newlines so
    character offsets computed against the result stay valid against the original text."""
    text = _JSX_SELF_CLOSING_COMPONENT_RE.sub(_blank_match, text)
    text = _MARKUS_DIRECTIVE_OPEN_RE.sub(_blank_match, text)
    text = _MARKUS_DIRECTIVE_CLOSE_RE.sub(_blank_match, text)
    return text


def _check_redundancy(text: str) -> list[dict[str, Any]]:
    masked = _mask_jsx_components(text)
    shingles: dict[str, list[tuple[int, int]]] = {}
    for _masked_sentence, start, end in sentence_spans(masked):
        words = re.findall(r"[A-Za-z0-9']+", masked[start:end].lower())
        for index in range(len(words) - 3):
            shingle = " ".join(words[index : index + 4])
            shingles.setdefault(shingle, []).append((start, end))

    groups: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    for occurrences in shingles.values():
        if len(occurrences) < 2:
            continue
        unique_spans = list(dict.fromkeys(occurrences))
        if len(unique_spans) < 2:
            continue
        members = []
        for start, end in unique_spans:
            member_id = stable_finding_id("redundancy", text, start, end)
            members.append(
                {
                    "id": member_id,
                    "kind": "redundancy",
                    "excerpt": text[start:end],
                    "span": {"start": start, "end": end},
                    "rationale": "Repeated phrasing across the draft.",
                }
            )
        if _is_rhetorical_refrain(members):
            continue
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


def _sentence_has_statistical_claim(sentence: str) -> bool:
    if _STAT_PERCENT_PATTERN.search(sentence):
        return True
    if _STAT_MULTIPLIER_PATTERN.search(sentence):
        return True
    if _STAT_COUNT_UNIT_PATTERN.search(sentence):
        return True
    return False


def _sentence_excluded_from_attribution(text: str, sentence: str, start: int) -> bool:
    line = line_at_offset(text, start)
    if _LIST_ORDINAL_LINE_PATTERN.match(line):
        return True
    if _STICKER_NUMBER_PATTERN.search(sentence) and not _STAT_PERCENT_PATTERN.search(sentence):
        return True
    return False


def _normalized_lexicon_avoid(lexicon_avoid: tuple[str, ...]) -> set[str]:
    normalized: set[str] = set()
    for term in lexicon_avoid:
        cleaned = term.strip().lower()
        if cleaned and cleaned != "empty intensifiers without evidence":
            normalized.add(cleaned)
    return normalized


def _occupied_spans(findings: list[dict[str, Any]]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for finding in findings:
        span = finding.get("span")
        if not isinstance(span, dict):
            continue
        start = span.get("start")
        end = span.get("end")
        if isinstance(start, int) and isinstance(end, int):
            spans.append((start, end))
    return spans


def _spans_overlap(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied)


def _rules_term_conflicts_with_lexicon(term: str, lexicon_avoid: set[str]) -> bool:
    return term.strip().lower() in lexicon_avoid


def _profile_rule_finding(
    text: str,
    start: int,
    end: int,
    rationale: str,
    *,
    kind: str = "vague_claim",
) -> dict[str, Any]:
    return _make_finding(kind, text, start, end, f"{PROFILE_RULE_PREFIX} {rationale}")


def _check_profile_rules(
    text: str,
    style_profile: LoadedStyleProfile,
    *,
    generic_passages: list[dict[str, Any]],
    voice_observations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    rules = style_profile.profile.rules
    if not any(
        (
            rules.banned_phrases,
            rules.banned_intensifiers,
            rules.banned_patterns,
            rules.contrast_cap is not None,
        )
    ):
        return {"generic_passages": [], "voice_observations": []}

    lexicon_avoid = _normalized_lexicon_avoid(style_profile.profile.lexicon_avoid)
    occupied = _occupied_spans(generic_passages) + _occupied_spans(voice_observations)
    profile_generic: list[dict[str, Any]] = []
    profile_voice: list[dict[str, Any]] = []
    lowered_text = text.lower()

    for phrase in rules.banned_phrases:
        normalized_phrase = phrase.lower()
        if normalized_phrase in lexicon_avoid:
            continue
        search_from = 0
        while True:
            index = lowered_text.find(normalized_phrase, search_from)
            if index < 0:
                break
            start = index
            end = index + len(normalized_phrase)
            if _spans_overlap(start, end, occupied):
                search_from = end
                continue
            finding = _profile_rule_finding(
                text,
                start,
                end,
                f"banned phrase '{phrase}'",
            )
            profile_generic.append(finding)
            occupied.append((start, end))
            search_from = end

    for intensifier in rules.banned_intensifiers:
        if _rules_term_conflicts_with_lexicon(intensifier, lexicon_avoid):
            continue
        pattern = re.compile(rf"\b{re.escape(intensifier)}\b", re.IGNORECASE)
        for match in pattern.finditer(text):
            start = match.start()
            end = match.end()
            if _spans_overlap(start, end, occupied):
                continue
            profile_generic.append(
                _profile_rule_finding(
                    text,
                    start,
                    end,
                    f"banned intensifier '{intensifier}'",
                )
            )
            occupied.append((start, end))

    for pattern, message in rules.banned_patterns:
        compiled = re.compile(pattern)
        for match in compiled.finditer(text):
            start = match.start()
            end = match.end()
            if _spans_overlap(start, end, occupied):
                continue
            profile_generic.append(_profile_rule_finding(text, start, end, message))
            occupied.append((start, end))

    if rules.contrast_cap is not None:
        contrast_count = len(re.findall(r",\s*not\b", text, flags=re.IGNORECASE))
        if contrast_count > rules.contrast_cap:
            profile_voice.append(
                _profile_rule_finding(
                    text,
                    0,
                    len(text),
                    (
                        f"{contrast_count} 'X, not Y' contrast constructions "
                        f"(cap is {rules.contrast_cap})"
                    ),
                    kind="voice_mismatch",
                )
            )

    return {"generic_passages": profile_generic, "voice_observations": profile_voice}


def _check_required_facts(text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence, start, end in sentence_spans(text):
        if not _sentence_has_statistical_claim(sentence):
            continue
        if _sentence_excluded_from_attribution(text, sentence, start):
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
