"""The home-page snapshot a site renders from: ``_data/home-page/references.json``.

``papyrus home-page snapshot`` and the ``home-page-snapshot`` projection task write the file into the site store (or a local
directory). A projector reads it through a :class:`HomePageSource`: the store's ``get`` for deployed builds, a local directory for
local builds. An absent file reads as ``None`` and the components that need it render their empty state. The file is read at most
once per projection run (the projector calls :meth:`HomePageSource.reset` when a new run starts).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from ...home_page.snapshot import HOME_PAGE_DATA_DIRECTORY, REFERENCES_FILE

REFERENCES_NAME = REFERENCES_FILE.removeprefix(HOME_PAGE_DATA_DIRECTORY + "/")

Reader = Callable[[str], "bytes | None"]


class HomePageSource:
    """Reads and memoises the snapshot file."""

    def __init__(self) -> None:
        self._reader: Reader | None = None
        self._directory: Path | None = None
        self._memo: tuple[bytes | None, dict | None] | None = None

    def attach_store(self, reader: Reader) -> None:
        """Read from a site store (``writer.get``). A directory chosen with :meth:`use_directory` keeps winning, in any call order."""
        self._reader = reader
        self.reset()

    def use_directory(self, directory: Path | str | None) -> None:
        """Read ``references.json`` from this directory (a local build) instead of the store."""
        self._directory = Path(directory) if directory else None
        self.reset()

    def reset(self) -> None:
        self._memo = None

    @property
    def configured(self) -> bool:
        return self._reader is not None or self._directory is not None

    def _bytes(self) -> bytes | None:
        if self._directory is not None:
            path = self._directory / REFERENCES_NAME
            return path.read_bytes() if path.is_file() else None
        return self._reader(REFERENCES_FILE) if self._reader is not None else None

    def _load(self) -> tuple[bytes | None, dict | None]:
        if self._memo is None:
            raw = self._bytes()
            document = None
            if raw is not None:
                try:
                    document = json.loads(raw.decode("utf-8"))
                except ValueError as error:
                    raise ValueError(f"{REFERENCES_FILE} is not valid JSON: {error}") from error
                if not isinstance(document, dict) or not isinstance(document.get("references"), list):
                    raise ValueError(f"{REFERENCES_FILE} must be a JSON object with a references list")
            self._memo = (raw, document)
        return self._memo

    def references(self) -> dict | None:
        return self._load()[1]

    def digest(self) -> str:
        """A digest of the file's bytes; empty when there is no file."""
        raw = self._load()[0]
        return "" if raw is None else hashlib.sha256(raw).hexdigest()[:16]
