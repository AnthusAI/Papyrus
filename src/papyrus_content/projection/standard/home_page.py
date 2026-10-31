"""The home-page snapshot a site renders from: ``_data/home-page/references.json`` and ``_data/home-page/threads.json``.

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

from ...home_page.snapshot import HOME_PAGE_DATA_DIRECTORY, REFERENCES_FILE, THREADS_DIRECTORY, THREADS_FILE, thread_file

REFERENCES_NAME = REFERENCES_FILE.removeprefix(HOME_PAGE_DATA_DIRECTORY + "/")
THREADS_NAME = THREADS_FILE.removeprefix(HOME_PAGE_DATA_DIRECTORY + "/")
THREAD_DIRECTORY_NAME = THREADS_DIRECTORY.removeprefix(HOME_PAGE_DATA_DIRECTORY + "/")

Reader = Callable[[str], "bytes | None"]


class HomePageSource:
    """Reads and memoises the snapshot file."""

    def __init__(self) -> None:
        self._reader: Reader | None = None
        self._directory: Path | None = None
        self._memo: dict[str, tuple[bytes | None, dict | None]] = {}

    def attach_store(self, reader: Reader) -> None:
        """Read from a site store (``writer.get``). A directory chosen with :meth:`use_directory` keeps winning, in any call order."""
        self._reader = reader
        self.reset()

    def use_directory(self, directory: Path | str | None) -> None:
        """Read the snapshot files from this directory (a local build) instead of the store."""
        self._directory = Path(directory) if directory else None
        self.reset()

    def reset(self) -> None:
        self._memo = {}

    @property
    def configured(self) -> bool:
        return self._reader is not None or self._directory is not None

    def _bytes(self, file_key: str, name: str) -> bytes | None:
        if self._directory is not None:
            path = self._directory / name
            return path.read_bytes() if path.is_file() else None
        return self._reader(file_key) if self._reader is not None else None

    def _load(self, file_key: str, name: str, list_name: str) -> tuple[bytes | None, dict | None]:
        if file_key not in self._memo:
            raw = self._bytes(file_key, name)
            document = None
            if raw is not None:
                try:
                    document = json.loads(raw.decode("utf-8"))
                except ValueError as error:
                    raise ValueError(f"{file_key} is not valid JSON: {error}") from error
                if not isinstance(document, dict) or not isinstance(document.get(list_name), list):
                    raise ValueError(f"{file_key} must be a JSON object with a {list_name} list")
            self._memo[file_key] = (raw, document)
        return self._memo[file_key]

    def references(self) -> dict | None:
        return self._load(REFERENCES_FILE, REFERENCES_NAME, "references")[1]

    def threads(self) -> dict | None:
        return self._load(THREADS_FILE, THREADS_NAME, "threads")[1]

    def digest(self) -> str:
        """A digest of the references file's bytes; empty when there is no file."""
        raw = self._load(REFERENCES_FILE, REFERENCES_NAME, "references")[0]
        return "" if raw is None else hashlib.sha256(raw).hexdigest()[:16]

    def threads_digest(self) -> str:
        """A digest of the threads file's bytes; empty when there is no file."""
        raw = self._load(THREADS_FILE, THREADS_NAME, "threads")[0]
        return "" if raw is None else hashlib.sha256(raw).hexdigest()[:16]

    def thread(self, key: str) -> dict | None:
        """The per-thread document ``_data/home-page/threads/<key>.json``; ``None`` when there is no such file."""
        return self._load(thread_file(key), f"{THREAD_DIRECTORY_NAME}/{key}.json", "messages")[1]

    def thread_digest(self, key: str) -> str:
        """A digest of one per-thread file's bytes; empty when there is no file."""
        raw = self._load(thread_file(key), f"{THREAD_DIRECTORY_NAME}/{key}.json", "messages")[0]
        return "" if raw is None else hashlib.sha256(raw).hexdigest()[:16]
