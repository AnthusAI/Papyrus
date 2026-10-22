"""The knowledge snapshot a site renders from: ``_data/knowledge/index.json``, ``clusters.json`` and ``entities/<key>.json``.

``papyrus knowledge snapshot`` writes these files into the site store (or a local directory). A projector reads them
through a :class:`KnowledgeSource`: the store's ``get`` for deployed builds, a local directory for local builds. Every file
is optional; an absent file reads as ``None`` and the components that need it render nothing. A file is read at most once
per projection run (the projector calls :meth:`KnowledgeSource.reset` when a new run starts).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

SCHEMA_VERSION = 1
DATA_PREFIX = "_data/knowledge/"
INDEX_KEY = DATA_PREFIX + "index.json"
CLUSTERS_KEY = DATA_PREFIX + "clusters.json"
ENTITY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")

Reader = Callable[[str], "bytes | None"]


def entity_file_key(key: str) -> str:
    return f"{DATA_PREFIX}entities/{key}.json"


class KnowledgeSource:
    """Reads and memoises the snapshot files."""

    def __init__(self) -> None:
        self._reader: Reader | None = None
        self._directory: Path | None = None
        self._memo: dict[str, tuple[bytes | None, dict | None]] = {}

    def attach_store(self, reader: Reader) -> None:
        """Read from a site store (``writer.get``).

        A directory chosen with :meth:`use_directory` keeps winning over the store, whichever of the two calls came first
        (``ProjectionContext`` attaches the store when it is built, so callers may set the directory before or after).
        """
        self._reader = reader
        self.reset()

    def use_directory(self, directory: Path | str | None) -> None:
        """Read ``index.json``, ``clusters.json`` and ``entities/`` from this directory (a local build). It wins over an attached store in any call order."""
        self._directory = Path(directory) if directory else None
        self.reset()

    def reset(self) -> None:
        self._memo.clear()

    @property
    def configured(self) -> bool:
        return self._reader is not None or self._directory is not None

    def _bytes(self, key: str) -> bytes | None:
        if self._directory is not None:
            path = self._directory / key[len(DATA_PREFIX):]
            return path.read_bytes() if path.is_file() else None
        return self._reader(key) if self._reader is not None else None

    def _load(self, key: str) -> tuple[bytes | None, dict | None]:
        if key not in self._memo:
            raw = self._bytes(key)
            document = None
            if raw is not None:
                try:
                    document = json.loads(raw.decode("utf-8"))
                except ValueError as error:
                    raise ValueError(f"{key} is not valid JSON: {error}") from error
                if not isinstance(document, dict) or document.get("schemaVersion") != SCHEMA_VERSION:
                    raise ValueError(f"{key} must be a JSON object with schemaVersion {SCHEMA_VERSION}")
            self._memo[key] = (raw, document)
        return self._memo[key]

    def index(self) -> dict | None:
        return self._load(INDEX_KEY)[1]

    def clusters(self) -> dict | None:
        return self._load(CLUSTERS_KEY)[1]

    def entity(self, key: str) -> dict | None:
        if not ENTITY_KEY.match(key or ""):
            return None
        return self._load(entity_file_key(key))[1]

    def digest(self, entity_keys=()) -> str:
        """A digest of the files a page reads: ``index.json``, ``clusters.json`` and the named entity files."""
        parts = [self._load(INDEX_KEY)[0], self._load(CLUSTERS_KEY)[0]]
        if not entity_keys and all(part is None for part in parts):
            return ""
        parts += [self._load(entity_file_key(key))[0] if ENTITY_KEY.match(key) else None for key in sorted(set(entity_keys))]
        digest = hashlib.sha256()
        for part in parts:
            digest.update(b"-" if part is None else hashlib.sha256(part).digest())
        return digest.hexdigest()[:16]
