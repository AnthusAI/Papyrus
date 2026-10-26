"""What the monitor-record import has already written, so a run writes only what is new or changed (``--monitor-ledger FILE``).

The import (``monitor_import.py``) turns each record into entities, links and relations by deterministic ids, so repeating it is safe but
slow: thousands of records mean thousands of reads and checks on every run. The ledger remembers, per record, a hash of the fields the
import reads and the base models it could not place on the map. A record whose hash is unchanged, and whose unplaced base models are
still unplaced, is skipped: no read, no check, no write. The ledger is a small JSON file kept with the run state (``corpus/`` in the state
bucket); it is saved only after the import was applied, so a failed run changes nothing and the next run retries the same records.

``--monitor-full`` ignores the ledger and imports every record, the way the import always did: use it after anything changed the entities
behind the ledger's back (a restore, a hand edit, a bumped ``IMPORT_VERSION``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from .monitor_records import MonitorRecord, record_entities

LEDGER_SCHEMA = 1
#: Bump when a record would plan different entities, links or relations than before (the hash cannot see a code change).
IMPORT_VERSION = 1


def record_hash(record: MonitorRecord) -> str:
    """A hash of everything the import reads of a record: its identity, its address, the entities of its structured fields (model, maker,
    licence, task) and its base models with their relation. Likes, downloads and dates are not in it: the import does not use them, so a
    record whose counters moved is still unchanged (the snapshot reads them from the records file, not from what the import wrote)."""
    bases = [[str(base.get("modelId") or ""), str(base.get("relation") or "declared")] for base in record.details.get("baseModels") or []]
    payload = {
        "version": IMPORT_VERSION, "referenceId": record.reference_id, "lineageId": record.lineage_id, "url": record.url, "provenance": record.provenance,
        "entities": sorted([kind, name] for kind, name in record_entities(record)), "bases": sorted(bases),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]


class MonitorLedger:
    """``entries``: reference id to ``{"hash": ..., "unplacedBases": [model ids]}``."""

    def __init__(self, entries: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.entries: dict[str, dict[str, Any]] = {key: dict(value) for key, value in (entries or {}).items()}

    @classmethod
    def read(cls, path: Path | str | None) -> "MonitorLedger":
        """The ledger at ``path``; an empty one when there is no file yet. A file that is not a ledger is an error, never silently emptied."""
        if path is None or not Path(path).exists():
            return cls()
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            if raw["schema"] != LEDGER_SCHEMA:
                raise ValueError(f"schema {raw['schema']}, expected {LEDGER_SCHEMA}")
            return cls({str(key): {"hash": str(value["hash"]), "unplacedBases": [str(base) for base in value.get("unplacedBases") or []]} for key, value in raw["records"].items()})
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"{path} is not a monitor import ledger ({error}); delete it, or pass --monitor-full to import every record again.") from error

    def write(self, path: Path | str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".tmp")
        temporary.write_text(json.dumps({"schema": LEDGER_SCHEMA, "records": self.entries}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)

    def changed(self, records: Iterable[MonitorRecord], placed: Callable[[str], bool]) -> list[MonitorRecord]:
        """The records to import: new ones, ones whose hash differs, and ones with a base model that has since reached the map.
        ``placed(model_id)`` says whether a model is on the map now (it has a record in this import or an accepted entity)."""
        todo = []
        for record in records:
            entry = self.entries.get(record.reference_id)
            if entry is None or entry["hash"] != record_hash(record) or any(placed(base) for base in entry["unplacedBases"]):
                todo.append(record)
        return todo

    def after_import(self, records: Iterable[MonitorRecord], imported: Mapping[str, list[str]]) -> "MonitorLedger":
        """The ledger as it stands once ``imported`` (reference id to the base models left unplaced) was applied: entries for exactly the current
        ``records`` (a record that left the window leaves the ledger), the imported ones refreshed and the skipped ones as they were."""
        entries: dict[str, dict[str, Any]] = {}
        for record in records:
            if record.reference_id in imported:
                entries[record.reference_id] = {"hash": record_hash(record), "unplacedBases": sorted(set(imported[record.reference_id]))}
            elif record.reference_id in self.entries:
                entries[record.reference_id] = self.entries[record.reference_id]
        return MonitorLedger(entries)
