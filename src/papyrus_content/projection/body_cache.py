"""The source text of every published Story, kept beside the pages so that one publish does not read every Story again.

A few pages need the body of every published Story, not only its listing fields: ``llms-full.txt`` holds the full text of the site,
and every item page is rendered again when something all of them read changes (the follow-up). Reading those bodies from AppSync
costs two requests a Story (the Item, then its PublishedItem), one after another, so a publish grew with the site: about 200
requests and a minute of waiting on Machines on Machines with 100 Stories (PPY-ee02b8 family, "no O(N) per change").

The body of a published version never changes, so it is read once, when that version is first projected (or by the whole-site
render, which reads every row anyway), and kept in one compressed object in the site store, ``_papyrus/bodies.json.gz``, keyed by
item id and a fingerprint of the published version (version number, the source content hash and the front matter). A later
projection uses the kept text when the fingerprint in the listing data (``PublishedItemSummary``, which every projection reads
anyway) matches; any mismatch, or an entry that is missing, is read from AppSync as before and kept for next time. The object is
written under the projection lease, at the end of a projection that changed it, so two projections never race on it.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
from collections.abc import Iterable
from typing import Any

from .writers import STATE_PREFIX

LOGGER = logging.getLogger("papyrus.projection")
BODY_CACHE_KEY = STATE_PREFIX + "bodies.json.gz"
FORMAT = 1


def _metadata_of(row: dict) -> dict:
    value = row.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value) if value.strip() else {}
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def version_fingerprint(row: dict) -> str | None:
    """What identifies the source text of a published row: its version number, the source item's content hash and its front matter.

    None when the row does not say (no content hash): such a body is never kept and always read."""
    metadata = _metadata_of(row)
    content_hash = metadata.get("sourceContentHash")
    if not content_hash:
        return None
    front_matter = metadata.get("frontMatterYaml") or ""
    digest = hashlib.sha256(front_matter.encode("utf-8")).hexdigest()[:16]
    return f"{row.get('versionNumber')}:{content_hash}:{digest}"


class BodyCache:
    """``{item id: (fingerprint, source text)}`` in one object of the site store, read on first use and written by :meth:`flush`."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._entries: dict[str, dict[str, str]] | None = None
        self._dirty = False
        self.hits = 0
        self.misses = 0

    def _load(self) -> dict[str, dict[str, str]]:
        if self._entries is None:
            entries: dict[str, dict[str, str]] = {}
            try:
                body = self._store.get(BODY_CACHE_KEY)
                if body:
                    document = json.loads(gzip.decompress(body).decode("utf-8"))
                    if isinstance(document, dict) and document.get("format") == FORMAT and isinstance(document.get("items"), dict):
                        entries = {key: value for key, value in document["items"].items() if isinstance(value, dict)}
            except Exception as error:  # noqa: BLE001 - a damaged cache is only a slower projection: read everything again
                LOGGER.warning("ignoring the body cache %s: %s: %s", BODY_CACHE_KEY, type(error).__name__, error)
            self._entries = entries
        return self._entries

    def get(self, item_id: str, fingerprint: str | None) -> str | None:
        if fingerprint is None:
            self.misses += 1
            return None
        entry = self._load().get(item_id)
        if entry is not None and entry.get("fingerprint") == fingerprint and isinstance(entry.get("source"), str):
            self.hits += 1
            return entry["source"]
        self.misses += 1
        return None

    def put(self, item_id: str, fingerprint: str | None, source_text: str) -> None:
        if fingerprint is None:
            return
        entries = self._load()
        current = entries.get(item_id)
        if current is not None and current.get("fingerprint") == fingerprint and current.get("source") == source_text:
            return
        entries[item_id] = {"fingerprint": fingerprint, "source": source_text}
        self._dirty = True

    def retain(self, item_ids: Iterable[str]) -> None:
        """Forget the bodies of items that are no longer published, so the object stays the size of the site."""
        keep = set(item_ids)
        entries = self._load()
        gone = [key for key in entries if key not in keep]
        for key in gone:
            del entries[key]
        if gone:
            self._dirty = True

    def flush(self) -> bool:
        """Write the object if anything changed since it was read. Returns whether it wrote."""
        if not self._dirty or self._entries is None:
            return False
        document = {"format": FORMAT, "items": self._entries}
        self._store.put(BODY_CACHE_KEY, gzip.compress(json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8"), mtime=0))
        self._dirty = False
        return True
