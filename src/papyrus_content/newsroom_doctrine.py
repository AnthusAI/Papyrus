from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .env import PAPYRUS_ROOT

DEFAULT_PUBLICATION_DOCTRINE_PATH = PAPYRUS_ROOT / "corpora" / "papyrus-publication-doctrine.yml"
DOCTRINE_KINDS = frozenset({"mission", "policy"})
DOCTRINE_DEFINITION_BY_KIND = {
    "mission": {
        "slug": "editorial-doctrine-mission",
        "id": "item-editorial-doctrine-mission-v1",
        "lineageId": "item-editorial-doctrine-mission",
        "title": "Editorial Mission",
    },
    "policy": {
        "slug": "editorial-doctrine-policy",
        "id": "item-editorial-doctrine-policy-v1",
        "lineageId": "item-editorial-doctrine-policy",
        "title": "Editorial Policy",
    },
}

_publication_doctrine_seed_cache: dict[str, dict[str, Any]] = {}


def load_publication_doctrine_seed(filepath: str | Path | None = None) -> dict[str, Any]:
    resolved = str(Path(filepath or DEFAULT_PUBLICATION_DOCTRINE_PATH).resolve())
    if resolved in _publication_doctrine_seed_cache:
        return _publication_doctrine_seed_cache[resolved]
    parsed = yaml.safe_load(Path(resolved).read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1:
        raise ValueError(f"Invalid publication doctrine seed file: {resolved}")
    doctrine_entries = parsed.get("doctrine")
    if not isinstance(doctrine_entries, list):
        raise ValueError(f"Invalid doctrine list in {resolved}")
    by_kind: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(doctrine_entries):
        normalized = _normalize_doctrine_seed_entry(entry, index, resolved)
        by_kind[normalized["kind"]] = normalized
    missing = [kind for kind in sorted(DOCTRINE_KINDS) if kind not in by_kind]
    if missing:
        raise ValueError(f"Missing doctrine entries for {', '.join(missing)} in {resolved}")
    payload = {"doctrine": [by_kind["mission"], by_kind["policy"]]}
    _publication_doctrine_seed_cache[resolved] = payload
    return payload


def require_explicit_doctrine(options: dict[str, Any], command: str, *, flag: str = "doctrine") -> None:
    """Refuse to write for a publication without naming its doctrine file.

    The default file is the doctrine of this repository's first publication
    (Threat Intelligence). Falling back to it for another site silently seeds
    that site's store with the wrong mission, so a writing run must say which
    file it means.
    """
    if isinstance(options.get(flag), str) and options[flag].strip():
        return
    raise ValueError(
        f"{command} writes to a publication's store, so it needs --{flag} <path> naming that publication's "
        f"doctrine file. It will not fall back to the default ({_display_path(DEFAULT_PUBLICATION_DOCTRINE_PATH)}), "
        "which is the Threat Intelligence doctrine and would seed this site with the wrong mission. "
        f"Re-run with --{flag} <path>."
    )


def describe_doctrine_choice(filepath: str | Path | None = None) -> dict[str, Any]:
    """Which doctrine file a run uses, whether it is the default, and its first mission line."""
    resolved = Path(filepath or DEFAULT_PUBLICATION_DOCTRINE_PATH).resolve()
    mission = next(entry for entry in load_publication_doctrine_seed(resolved)["doctrine"] if entry["kind"] == "mission")
    return {"path": str(resolved), "isDefault": filepath is None or resolved == DEFAULT_PUBLICATION_DOCTRINE_PATH.resolve(),
            "firstMissionLine": mission["body"][0]}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PAPYRUS_ROOT))
    except ValueError:
        return str(path)


def build_publication_doctrine_records(
    doctrine_entries: list[dict[str, Any]],
    *,
    now: str | None = None,
    actor: str = "papyrus-cli",
) -> list[dict[str, Any]]:
    timestamp = now or _utc_now()
    records: list[dict[str, Any]] = []
    for entry in doctrine_entries:
        details = DOCTRINE_DEFINITION_BY_KIND[entry["kind"]]
        records.append(
            {
                "modelName": "Item",
                "expected": {
                    "id": details["id"],
                    "lineageId": details["lineageId"],
                    "versionNumber": 1,
                    "versionState": "current",
                    "versionCreatedAt": timestamp,
                    "versionCreatedBy": actor,
                    "type": "doctrine",
                    "status": "private",
                    "typeStatus": "doctrine#private",
                    "slug": details["slug"],
                    "title": details["title"],
                    "body": entry["body"],
                    "updatedAt": timestamp,
                },
            }
        )
    return records


def _normalize_doctrine_seed_entry(entry: Any, index: int, filepath: str) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"Doctrine entry at index {index} in {filepath} must be an object.")
    kind = str(entry.get("kind") or "").strip().lower()
    if kind not in DOCTRINE_KINDS:
        raise ValueError(f"Doctrine entry at index {index} in {filepath} has unsupported kind '{entry.get('kind')}'.")
    body_value = entry.get("body")
    if isinstance(body_value, str):
        body = [line.strip() for line in body_value.split("\n\n") if line.strip()]
    elif isinstance(body_value, list):
        body = [str(line).strip() for line in body_value if str(line or "").strip()]
    else:
        body = []
    if not body:
        raise ValueError(f"Doctrine entry '{kind}' in {filepath} requires non-empty body.")
    return {"kind": kind, "body": body}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
