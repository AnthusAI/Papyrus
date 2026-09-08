from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from .editorial_diagnosis import findings_marked_rewrite
from .editorial_diagnosis_schema import validate_diagnosis
from .editorial_llm import call_structured_responses_api
from .editorial_options_schema import (
    SCHEMA_VERSION,
    stable_option_id,
    validate_decisions,
    validate_options,
)
from .editorial_style import LoadedStyleProfile
from .env import PAPYRUS_ROOT
from .model_defaults import DEFAULT_EDITORIAL_REWRITE_MODEL

DEFAULT_EDITORIAL_REWRITE_SKILL_PATH = (
    PAPYRUS_ROOT / "publications" / "anthus" / "editorial-rewrite-skill.yml"
)

EVASION_TERMS = (
    "lol",
    "tbh",
    "ngl",
    "gonna",
    "wanna",
    "kinda",
    "sorta",
    "as an ai",
    "in my experience",
    "i remember",
    "i once",
)

_LLM_OPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["options"],
    "properties": {
        "options": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "replacement",
                    "reason",
                    "factVerificationRequired",
                    "unresolvedQuestions",
                ],
                "properties": {
                    "replacement": {"type": "string"},
                    "reason": {"type": "string"},
                    "factVerificationRequired": {"type": "boolean"},
                    "unresolvedQuestions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class EditorialRewriteSkill:
    role: str
    constraints: tuple[str, ...]
    min_options_per_finding: int
    max_options_per_finding: int


OptionsResolver = Callable[..., list[dict[str, Any]]]


def load_rewrite_skill(path: str | Path | None = None) -> EditorialRewriteSkill:
    skill_path = Path(path or DEFAULT_EDITORIAL_REWRITE_SKILL_PATH).resolve()
    raw = yaml.safe_load(skill_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Editorial rewrite skill must be a mapping: {skill_path}")
    role = str(raw.get("role") or "Senior copy editor").strip()
    constraints_raw = raw.get("constraints") or []
    if not isinstance(constraints_raw, list) or not constraints_raw:
        raise ValueError(f"Editorial rewrite skill constraints are required: {skill_path}")
    constraints = tuple(str(item).strip() for item in constraints_raw if str(item).strip())
    output = raw.get("output") or {}
    if not isinstance(output, dict):
        output = {}
    min_options = int(output.get("minOptionsPerFinding") or 2)
    max_options = int(output.get("maxOptionsPerFinding") or 3)
    if min_options < 1 or max_options < min_options:
        raise ValueError("Editorial rewrite skill output option counts are invalid.")
    return EditorialRewriteSkill(
        role=role,
        constraints=constraints,
        min_options_per_finding=min_options,
        max_options_per_finding=max_options,
    )


def generate_rewrite_options(
    draft_text: str,
    *,
    style_profile: LoadedStyleProfile,
    diagnosis: dict[str, Any],
    decisions: list[dict[str, Any]],
    model: str = DEFAULT_EDITORIAL_REWRITE_MODEL,
    skill_path: str | Path | None = None,
    llm_resolver: OptionsResolver | None = None,
) -> dict[str, Any]:
    validated_diagnosis = validate_diagnosis(diagnosis)
    validated_decisions = validate_decisions(decisions)
    rewrite_findings = findings_marked_rewrite(validated_diagnosis, validated_decisions)
    skill = load_rewrite_skill(skill_path)
    resolver = llm_resolver or _generate_options_with_llm

    findings_payload: list[dict[str, Any]] = []
    for finding in rewrite_findings:
        raw_options = resolver(
            draft_text=draft_text,
            finding=finding,
            style_profile=style_profile,
            skill=skill,
            model=model,
        )
        options = _normalize_options_for_finding(finding, raw_options)
        options = _ensure_empty_leadin_deletion_option(finding, options)
        findings_payload.append({"findingId": finding["id"], "options": options})

    return validate_options({"schemaVersion": SCHEMA_VERSION, "findings": findings_payload})


def _generate_options_with_llm(
    *,
    draft_text: str,
    finding: dict[str, Any],
    style_profile: LoadedStyleProfile,
    skill: EditorialRewriteSkill,
    model: str,
) -> list[dict[str, Any]]:
    span = finding["span"]
    excerpt = finding["excerpt"]
    prompt = _build_rewrite_prompt(
        draft_text=draft_text,
        finding=finding,
        style_profile=style_profile,
        skill=skill,
    )
    system_prompt = (
        f"You are a {skill.role} for a technical publication. "
        "Return strict JSON only. Offer constrained patch replacements for the flagged span."
    )
    result = call_structured_responses_api(
        model=model,
        system_prompt=system_prompt,
        user_prompt=prompt,
        schema_name="editorial_rewrite_options",
        schema=_LLM_OPTION_SCHEMA,
    )
    options = result.get("options") or []
    normalized: list[dict[str, Any]] = []
    for entry in options:
        if not isinstance(entry, dict):
            continue
        replacement = str(entry.get("replacement") or "")
        reason = str(entry.get("reason") or "").strip()
        if not reason:
            continue
        normalized.append(
            {
                "id": stable_option_id(finding["id"], replacement, reason),
                "patch": {
                    "span": {"start": span["start"], "end": span["end"]},
                    "replacement": replacement,
                },
                "reason": reason,
                "factVerificationRequired": bool(entry.get("factVerificationRequired")),
                "unresolvedQuestions": [
                    str(question)
                    for question in (entry.get("unresolvedQuestions") or [])
                    if str(question).strip()
                ],
            }
        )
    return normalized


def _build_rewrite_prompt(
    *,
    draft_text: str,
    finding: dict[str, Any],
    style_profile: LoadedStyleProfile,
    skill: EditorialRewriteSkill,
) -> str:
    profile = style_profile.profile
    span = finding["span"]
    lines = [
        "Generate patch options for one editorial finding.",
        "",
        "Skill constraints:",
        *[f"- {constraint}" for constraint in skill.constraints],
        "",
        "Style profile:",
        f"- Audience: {profile.audience}",
        f"- Tone: {'; '.join(profile.tone)}",
        f"- Sentence style: {'; '.join(profile.sentence_style)}",
        f"- Prefer lexicon: {', '.join(profile.lexicon_prefer)}",
        f"- Avoid lexicon: {', '.join(profile.lexicon_avoid)}",
        f"- Evidence rules: {'; '.join(profile.evidence_rules)}",
        "",
        f"Finding kind: {finding['kind']}",
        f"Finding rationale: {finding['rationale']}",
        f"Flagged excerpt: {finding['excerpt']}",
        f"Span coordinates: start={span['start']}, end={span['end']}",
        "",
        "Draft text:",
        draft_text,
        "",
        (
            f"Return {skill.min_options_per_finding} to {skill.max_options_per_finding} options. "
            "Each option must replace only the flagged span. "
            "Do not return a whole-document rewrite."
        ),
    ]
    if finding["kind"] == "empty_leadin":
        lines.extend(
            [
                "",
                "At least one option must delete the empty lead-in by using an empty replacement string.",
            ]
        )
    return "\n".join(lines)


def _normalize_options_for_finding(
    finding: dict[str, Any],
    options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    span = finding["span"]
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in options:
        if not isinstance(entry, dict):
            continue
        replacement = str(entry.get("patch", {}).get("replacement", entry.get("replacement", "")))
        reason = str(entry.get("reason") or "").strip()
        if not reason:
            continue
        option_id = str(entry.get("id") or stable_option_id(finding["id"], replacement, reason))
        if option_id in seen_ids:
            continue
        seen_ids.add(option_id)
        normalized.append(
            {
                "id": option_id,
                "patch": {
                    "span": {"start": span["start"], "end": span["end"]},
                    "replacement": replacement,
                },
                "reason": reason,
                "factVerificationRequired": bool(entry.get("factVerificationRequired")),
                "unresolvedQuestions": [
                    str(question)
                    for question in (entry.get("unresolvedQuestions") or [])
                    if str(question).strip()
                ],
            }
        )
    if len(normalized) < 2:
        raise ValueError(f"Finding {finding['id']} requires at least two rewrite options.")
    return normalized[:3]


def _ensure_empty_leadin_deletion_option(
    finding: dict[str, Any],
    options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if finding.get("kind") != "empty_leadin":
        return options
    has_deletion = any(not option["patch"]["replacement"].strip() for option in options)
    if has_deletion:
        return options
    deletion = {
        "id": stable_option_id(finding["id"], "", "Delete the empty lead-in."),
        "patch": {
            "span": {"start": finding["span"]["start"], "end": finding["span"]["end"]},
            "replacement": "",
        },
        "reason": "Delete the empty lead-in and let the next sentence carry the opening.",
        "factVerificationRequired": False,
        "unresolvedQuestions": [],
    }
    return [deletion, *options[:2]]


def options_contain_evasion_tactics(options_payload: dict[str, Any]) -> bool:
    for finding_entry in options_payload.get("findings", []):
        for option in finding_entry.get("options", []):
            replacement = str(option.get("patch", {}).get("replacement", "")).lower()
            reason = str(option.get("reason", "")).lower()
            combined = f"{replacement} {reason}"
            if any(term in combined for term in EVASION_TERMS):
                return True
    return False
