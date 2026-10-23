from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .env import resolve_corpora_file

DEFAULT_NEWSROOM_SECTIONS_PATH = resolve_corpora_file("corpora/papyrus-newsroom-sections.yml")
SECTION_TYPES = frozenset({"canonical", "floating", "rotating"})

_section_seed_cache: dict[str, list[dict[str, Any]]] = {}


def load_newsroom_section_seeds(filepath: str | Path | None = None) -> list[dict[str, Any]]:
    resolved = str(Path(filepath or DEFAULT_NEWSROOM_SECTIONS_PATH).resolve())
    if resolved in _section_seed_cache:
        return _section_seed_cache[resolved]
    parsed = yaml.safe_load(Path(resolved).read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1 or not isinstance(parsed.get("sections"), list):
        raise ValueError(f"Invalid newsroom section seed file: {resolved}")
    sections = [_normalize_newsroom_section_seed(entry, index, resolved) for index, entry in enumerate(parsed["sections"])]
    _section_seed_cache[resolved] = sections
    return sections


def build_newsroom_section_records(sections: list[dict[str, Any]], *, now: str | None = None) -> list[dict[str, Any]]:
    timestamp = now or _utc_now()
    return [
        {
            "modelName": "NewsroomSection",
            "expected": {
                "id": section["id"],
                "title": section["title"],
                "shortTitle": section["shortTitle"],
                "type": section["type"],
                "editorialMission": section["editorialMission"],
                "editorialPolicy": section["editorialPolicy"],
                "enabled": section["enabled"],
                "enabledStatus": "enabled" if section["enabled"] else "disabled",
                "sortOrder": section["sortOrder"],
                "defaultArticleTypes": section["defaultArticleTypes"],
                "defaultPageBudget": section["defaultPageBudget"],
                "assignmentGuidance": section["assignmentGuidance"],
                "killCriteria": section["killCriteria"],
                "visualGuidance": section["visualGuidance"],
                "createdAt": section.get("createdAt") or timestamp,
                "updatedAt": timestamp,
            },
        }
        for section in sections
    ]


def _normalize_newsroom_section_seed(entry: Any, index: int, filepath: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"Newsroom section at index {index} in {filepath} must be an object.")
    section_id = str(entry.get("id") or "").strip()
    if not section_id:
        raise ValueError(f"Newsroom section at index {index} in {filepath} is missing id.")
    raw_type = str(entry.get("type") or "").strip().lower()
    section_type = "floating" if raw_type == "rotating" else raw_type
    if section_type not in SECTION_TYPES:
        raise ValueError(f"Newsroom section {section_id} in {filepath} has unsupported type '{entry.get('type')}'.")
    return {
        "id": section_id,
        "title": _required_text(entry.get("title"), f"title for section {section_id} in {filepath}"),
        "shortTitle": _required_text(entry.get("shortTitle"), f"shortTitle for section {section_id} in {filepath}"),
        "type": section_type,
        "editorialMission": _required_text(entry.get("editorialMission"), f"editorialMission for section {section_id} in {filepath}"),
        "editorialPolicy": _required_text(entry.get("editorialPolicy"), f"editorialPolicy for section {section_id} in {filepath}"),
        "enabled": entry.get("enabled") if isinstance(entry.get("enabled"), bool) else True,
        "sortOrder": _positive_integer(entry.get("sortOrder"), index + 1),
        "defaultArticleTypes": _normalize_string_list(entry.get("defaultArticleTypes")),
        "defaultPageBudget": _optional_integer(entry.get("defaultPageBudget")),
        "assignmentGuidance": _optional_text(entry.get("assignmentGuidance")),
        "killCriteria": _optional_text(entry.get("killCriteria")),
        "visualGuidance": _optional_text(entry.get("visualGuidance")),
        "createdAt": _optional_text(entry.get("createdAt")),
    }


def _required_text(value: Any, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Missing {label}.")
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry for entry in (_optional_text(item) for item in value) if entry]


def _optional_integer(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, int) else None


def _positive_integer(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
