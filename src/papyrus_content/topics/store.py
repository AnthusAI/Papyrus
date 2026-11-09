"""Where a finished topic run is kept, by its saved id.

A saved id is a hash of the parameters, the engine and the exact Reference versions the run read, so asking the same question of the same
References finds the earlier answer and spends nothing (``model.cache_key``). The store holds the whole record, member lists included; the
command prints the compact form. This first store is a folder of JSON files on the machine that ran the command. Moving it behind the backend,
so that a cloud job and another machine see the same ids, is the follow-up that adds ``topics.show`` and ``topics.members``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

ENVIRONMENT_VARIABLE = "PAPYRUS_TOPICS_DIR"


class TopicStore(Protocol):
    def get(self, saved_id: str) -> dict | None: ...

    def put(self, saved_id: str, record: dict) -> None: ...


def default_directory(environ: dict | None = None) -> Path:
    environ = os.environ if environ is None else environ
    if environ.get(ENVIRONMENT_VARIABLE):
        return Path(environ[ENVIRONMENT_VARIABLE]).expanduser()
    base = Path(environ["XDG_CACHE_HOME"]).expanduser() if environ.get("XDG_CACHE_HOME") else Path.home() / ".cache"
    return base / "papyrus" / "topics"


class FileTopicStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or default_directory()

    def _path(self, saved_id: str) -> Path:
        if not saved_id.replace("-", "").isalnum():
            raise ValueError(f"{saved_id!r} is not a saved topic id.")
        return self.directory / f"{saved_id}.json"

    def get(self, saved_id: str) -> dict | None:
        path = self._path(saved_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None   # missing, or a half-written file: ask the engine again

    def put(self, saved_id: str, record: dict) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(saved_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(path)


class MemoryTopicStore:
    """For tests."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def get(self, saved_id: str) -> dict | None:
        return self.records.get(saved_id)

    def put(self, saved_id: str, record: dict) -> None:
        self.records[saved_id] = record
