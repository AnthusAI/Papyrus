from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .editorial_style import StyleProfileValidationError


def load_editorial_corpus_manifest(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    manifest_path = Path(path).resolve()
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StyleProfileValidationError(f"Editorial corpus manifest must be a mapping: {manifest_path}")

    manifest: dict[str, list[dict[str, Any]]] = {"mustFail": [], "mustPass": []}
    for section in ("mustFail", "mustPass"):
        entries = raw.get(section)
        if entries is None:
            continue
        if not isinstance(entries, list):
            raise StyleProfileValidationError(f"{section} must be a list in {manifest_path}")
        normalized: list[dict[str, Any]] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise StyleProfileValidationError(f"{section}[{index}] must be a mapping in {manifest_path}")
            entry_id = str(entry.get("id", "")).strip()
            rel_path = str(entry.get("path", "")).strip()
            if not entry_id or not rel_path:
                raise StyleProfileValidationError(
                    f"{section}[{index}] requires id and path in {manifest_path}"
                )
            draft_path = (manifest_path.parent / rel_path).resolve()
            if not draft_path.is_file():
                raise StyleProfileValidationError(f"Corpus draft not found: {draft_path}")
            normalized_entry = {"id": entry_id, "path": rel_path, "draftPath": str(draft_path)}
            if section == "mustFail":
                expect_terms = entry.get("expectTerms")
                if not isinstance(expect_terms, list) or not expect_terms:
                    raise StyleProfileValidationError(
                        f"{section}[{index}].expectTerms must be a non-empty list in {manifest_path}"
                    )
                normalized_entry["expectTerms"] = [str(term).strip() for term in expect_terms if str(term).strip()]
            else:
                source_sample = entry.get("sourceSample")
                if isinstance(source_sample, str) and source_sample.strip():
                    normalized_entry["sourceSample"] = source_sample.strip()
            normalized.append(normalized_entry)
        manifest[section] = normalized
    return manifest
