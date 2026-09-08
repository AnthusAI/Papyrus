from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .env import PAPYRUS_ROOT

DEFAULT_ANTHUS_STYLE_PROFILE_PATH = PAPYRUS_ROOT / "publications" / "anthus" / "style-profile.yml"

_FORBIDDEN_KEY_PATTERN = re.compile(
    r"(detector|detectorscore|ai_detector|aidetector|perplexity_score|burstiness|ai_score|human_score)",
    re.IGNORECASE,
)

# When checks is omitted from a style profile, every diagnose check is enabled.
DEFAULT_DIAGNOSE_CHECKS: dict[str, bool] = {
    "emptyLeadin": True,
    "listShapedProse": True,
    "vagueClaim": True,
    "unsupportedCertainty": True,
    "uniformCadence": True,
    "redundancy": True,
    "voiceMismatch": True,
    "missingAttribution": True,
}


class StyleProfileValidationError(ValueError):
    """Raised when a style profile document or linked samples fail validation."""


@dataclass(frozen=True)
class StyleProfile:
    publication_key: str
    voice_name: str
    audience: str
    tone: tuple[str, ...]
    sentence_style: tuple[str, ...]
    structure: tuple[str, ...]
    lexicon_prefer: tuple[str, ...]
    lexicon_avoid: tuple[str, ...]
    evidence_rules: tuple[str, ...]
    reference_sample_refs: tuple[dict[str, str], ...]
    checks: dict[str, bool]


@dataclass(frozen=True)
class ReferenceSample:
    id: str
    title: str
    url: str
    path: Path
    body: str


@dataclass(frozen=True)
class LoadedStyleProfile:
    profile: StyleProfile
    samples: tuple[ReferenceSample, ...]


def load_style_profile(path: str | Path | None = None) -> LoadedStyleProfile:
    profile_path = Path(path or DEFAULT_ANTHUS_STYLE_PROFILE_PATH).resolve()
    raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StyleProfileValidationError(f"Style profile must be a mapping: {profile_path}")

    _assert_no_forbidden_keys(raw, profile_path)
    profile = _parse_profile(raw, profile_path)
    samples = _load_reference_samples(profile, profile_path.parent)
    return LoadedStyleProfile(profile=profile, samples=samples)


def _assert_no_forbidden_keys(value: Any, location: str | Path, key_path: str = "") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            current_path = f"{key_path}.{key_text}" if key_path else key_text
            normalized = re.sub(r"[^a-z0-9]", "", key_text.lower())
            if _FORBIDDEN_KEY_PATTERN.search(normalized):
                raise StyleProfileValidationError(
                    f"Style profile contains forbidden detector-score field '{current_path}' in {location}"
                )
            _assert_no_forbidden_keys(nested, location, current_path)
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_forbidden_keys(nested, location, f"{key_path}[{index}]")


def _parse_profile(raw: dict[str, Any], profile_path: Path) -> StyleProfile:
    if raw.get("schemaVersion") != 1:
        raise StyleProfileValidationError(f"Unsupported schemaVersion in {profile_path}")

    publication_key = _require_non_empty_string(raw.get("publicationKey"), "publicationKey", profile_path)
    voice = raw.get("voice")
    if not isinstance(voice, dict):
        raise StyleProfileValidationError(f"Missing voice mapping in {profile_path}")
    voice_name = _require_non_empty_string(voice.get("name"), "voice.name", profile_path)
    audience = _require_non_empty_string(raw.get("audience"), "audience", profile_path)
    tone = _require_string_list(raw.get("tone"), "tone", profile_path)
    sentence_style = _require_string_list(raw.get("sentenceStyle"), "sentenceStyle", profile_path)
    structure = _require_string_list(raw.get("structure"), "structure", profile_path)

    lexicon = raw.get("lexicon")
    if not isinstance(lexicon, dict):
        raise StyleProfileValidationError(f"Missing lexicon mapping in {profile_path}")
    lexicon_prefer = _require_string_list(lexicon.get("prefer"), "lexicon.prefer", profile_path)
    lexicon_avoid = _require_string_list(lexicon.get("avoid"), "lexicon.avoid", profile_path)
    evidence_rules = _require_string_list(raw.get("evidenceRules"), "evidenceRules", profile_path)

    reference_samples = raw.get("referenceSamples")
    if not isinstance(reference_samples, list):
        raise StyleProfileValidationError(f"Missing referenceSamples list in {profile_path}")
    if not 5 <= len(reference_samples) <= 10:
        raise StyleProfileValidationError(
            f"referenceSamples must contain 5 to 10 entries in {profile_path}; found {len(reference_samples)}"
        )

    refs: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(reference_samples):
        if not isinstance(entry, dict):
            raise StyleProfileValidationError(f"referenceSamples[{index}] must be a mapping in {profile_path}")
        sample_id = _require_non_empty_string(entry.get("id"), f"referenceSamples[{index}].id", profile_path)
        if sample_id in seen_ids:
            raise StyleProfileValidationError(f"Duplicate reference sample id '{sample_id}' in {profile_path}")
        seen_ids.add(sample_id)
        title = _require_non_empty_string(entry.get("title"), f"referenceSamples[{index}].title", profile_path)
        url = _require_non_empty_string(entry.get("url"), f"referenceSamples[{index}].url", profile_path)
        rel_path = _require_non_empty_string(entry.get("path"), f"referenceSamples[{index}].path", profile_path)
        refs.append({"id": sample_id, "title": title, "url": url, "path": rel_path})

    checks = _parse_checks(raw.get("checks"), profile_path)

    return StyleProfile(
        publication_key=publication_key,
        voice_name=voice_name,
        audience=audience,
        tone=tuple(tone),
        sentence_style=tuple(sentence_style),
        structure=tuple(structure),
        lexicon_prefer=tuple(lexicon_prefer),
        lexicon_avoid=tuple(lexicon_avoid),
        evidence_rules=tuple(evidence_rules),
        reference_sample_refs=tuple(refs),
        checks=checks,
    )


def _parse_checks(value: Any, profile_path: Path) -> dict[str, bool]:
    checks = dict(DEFAULT_DIAGNOSE_CHECKS)
    if value is None:
        return checks
    if not isinstance(value, dict):
        raise StyleProfileValidationError(f"checks must be a mapping in {profile_path}")
    for key, enabled in value.items():
        if key not in DEFAULT_DIAGNOSE_CHECKS:
            raise StyleProfileValidationError(f"Unknown checks key '{key}' in {profile_path}")
        if not isinstance(enabled, bool):
            raise StyleProfileValidationError(f"checks.{key} must be a boolean in {profile_path}")
        checks[key] = enabled
    return checks


def _load_reference_samples(profile: StyleProfile, profile_root: Path) -> tuple[ReferenceSample, ...]:
    loaded: list[ReferenceSample] = []
    for ref in profile.reference_sample_refs:
        sample_path = (profile_root / ref["path"]).resolve()
        if not sample_path.is_file():
            raise StyleProfileValidationError(f"Reference sample file not found: {sample_path}")
        body = _read_sample_body(sample_path)
        loaded.append(
            ReferenceSample(
                id=ref["id"],
                title=ref["title"],
                url=ref["url"],
                path=sample_path,
                body=body,
            )
        )
    return tuple(loaded)


def _read_sample_body(sample_path: Path) -> str:
    text = sample_path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
            if body:
                return body
    body = text.strip()
    if not body:
        raise StyleProfileValidationError(f"Reference sample body is empty: {sample_path}")
    return body


def _require_non_empty_string(value: Any, field_name: str, profile_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StyleProfileValidationError(f"Missing or empty {field_name} in {profile_path}")
    return value.strip()


def _require_string_list(value: Any, field_name: str, profile_path: Path) -> list[str]:
    if not isinstance(value, list) or not value:
        raise StyleProfileValidationError(f"Missing or empty {field_name} in {profile_path}")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise StyleProfileValidationError(f"{field_name}[{index}] must be a non-empty string in {profile_path}")
        normalized.append(item.strip())
    return normalized
