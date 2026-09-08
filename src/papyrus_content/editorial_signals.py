from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .editorial_style import StyleProfileValidationError
from .env import PAPYRUS_ROOT

DEFAULT_EDITORIAL_SIGNALS_PATH = PAPYRUS_ROOT / "publications" / "anthus" / "editorial-signals.yml"


@dataclass(frozen=True)
class EditorialSignal:
    id: str
    established_as: str
    finding_kind: str
    implemented: bool


@dataclass(frozen=True)
class EditorialSignalsCatalog:
    publication_key: str
    signals: tuple[EditorialSignal, ...]


def load_editorial_signals_catalog(path: str | Path | None = None) -> EditorialSignalsCatalog:
    catalog_path = Path(path or DEFAULT_EDITORIAL_SIGNALS_PATH).resolve()
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise StyleProfileValidationError(f"Editorial signals catalog must be a mapping: {catalog_path}")

    if raw.get("schemaVersion") != 1:
        raise StyleProfileValidationError(f"Unsupported schemaVersion in {catalog_path}")

    publication_key = _require_non_empty_string(raw.get("publicationKey"), "publicationKey", catalog_path)
    signals_raw = raw.get("signals")
    if not isinstance(signals_raw, list) or not signals_raw:
        raise StyleProfileValidationError(f"signals must be a non-empty list in {catalog_path}")

    signals: list[EditorialSignal] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(signals_raw):
        if not isinstance(entry, dict):
            raise StyleProfileValidationError(f"signals[{index}] must be a mapping in {catalog_path}")
        signal_id = _require_non_empty_string(entry.get("id"), f"signals[{index}].id", catalog_path)
        if signal_id in seen_ids:
            raise StyleProfileValidationError(f"Duplicate signal id '{signal_id}' in {catalog_path}")
        seen_ids.add(signal_id)
        established_as = _require_non_empty_string(
            entry.get("establishedAs"), f"signals[{index}].establishedAs", catalog_path
        )
        finding_kind = _require_non_empty_string(
            entry.get("findingKind"), f"signals[{index}].findingKind", catalog_path
        )
        implemented = entry.get("implemented")
        if not isinstance(implemented, bool):
            raise StyleProfileValidationError(f"signals[{index}].implemented must be a boolean in {catalog_path}")
        signals.append(
            EditorialSignal(
                id=signal_id,
                established_as=established_as,
                finding_kind=finding_kind,
                implemented=implemented,
            )
        )

    return EditorialSignalsCatalog(publication_key=publication_key, signals=tuple(signals))


def implemented_signals(catalog: EditorialSignalsCatalog) -> list[EditorialSignal]:
    return [signal for signal in catalog.signals if signal.implemented]


def signal_by_id(catalog: EditorialSignalsCatalog, signal_id: str) -> EditorialSignal | None:
    for signal in catalog.signals:
        if signal.id == signal_id:
            return signal
    return None


def catalog_as_dict(catalog: EditorialSignalsCatalog) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "publicationKey": catalog.publication_key,
        "signals": [
            {
                "id": signal.id,
                "establishedAs": signal.established_as,
                "findingKind": signal.finding_kind,
                "implemented": signal.implemented,
            }
            for signal in catalog.signals
        ],
    }


def _require_non_empty_string(value: Any, field_name: str, catalog_path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StyleProfileValidationError(f"Missing or empty {field_name} in {catalog_path}")
    return value.strip()
