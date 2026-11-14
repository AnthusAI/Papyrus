"""Where ideas go. Private by default: nothing here writes to a site's public data or asks a site to publish.

``JsonStore`` keeps digests, ideas and run ledgers as JSON files under a directory on this machine (default
``~/.papyrus/ideas/<publication>``), and refuses a directory that looks like a site's public output. Generated ideas on a site are Items at
the ``idea`` stage (``ideas/items.py``); ``legacy_story_drafts`` only *reads* the ``story_draft`` Proposals that were filed before ideas became
Items, so a site that has not run ``papyrus ideas migrate-proposals`` yet still dedupes against them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..proposals_commands import LIST_QUERY, list_proposals, operator_story_drafts, using_iam

STORE_DIRECTORY_ENVIRONMENT = "PAPYRUS_IDEAS_DIR"
PUBLIC_DIRECTORY_NAMES = {"_data", "public", "static-root"}
JSON, ITEMS = "json", "items"
STORES = (ITEMS, JSON)   # items is the default and the only store a site uses; json is for local runs and tests


class StoreRefused(ValueError):
    pass


def default_root(publication: str) -> Path:
    base = os.environ.get(STORE_DIRECTORY_ENVIRONMENT, "").strip()
    return (Path(base).expanduser() if base else Path.home() / ".papyrus" / "ideas") / publication


def assert_private(root: Path) -> Path:
    resolved = root.expanduser().resolve()
    public = sorted(set(resolved.parts) & PUBLIC_DIRECTORY_NAMES)
    if public:
        raise StoreRefused(f"{resolved} is inside a public directory ({public[0]}). Ideas are private; choose another --out directory.")
    return resolved


class JsonStore:
    def __init__(self, root: Path) -> None:
        self.root = assert_private(root)

    def _write(self, kind: str, name: str, record: dict[str, Any]) -> Path:
        directory = self.root / kind
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.json"
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def save_digest(self, digest: dict[str, Any]) -> Path:
        return self._write("digests", digest["digestId"], digest)

    def save_idea(self, idea: dict[str, Any]) -> Path:
        return self._write("ideas", idea["ideaId"], idea)

    def save_run(self, run: dict[str, Any]) -> Path:
        return self._write("runs", run["runId"], run)

    def load_digest(self, reference: str) -> dict[str, Any]:
        """A digest by id, or by path to a digest file."""
        path = Path(reference).expanduser()
        if not path.is_file():
            path = self.root / "digests" / f"{reference}.json"
        if not path.is_file():
            raise ValueError(f"No digest {reference!r} in {self.root / 'digests'}. Run `papyrus ideas digest` first.")
        digest = json.loads(path.read_text(encoding="utf-8"))
        if digest.get("kind") != "ideas-digest":
            raise ValueError(f"{path} is not an ideas digest.")
        return digest

    def batch_titles(self) -> dict[str, list[str]]:
        """Run id to the titles of the ideas that run created, for turning a batch review into per-idea feedback."""
        titles: dict[str, list[str]] = {}
        for idea in self.ideas():
            titles.setdefault(idea.get("runId"), []).append(idea["title"])
        return titles

    def ideas(self) -> list[dict[str, Any]]:
        directory = self.root / "ideas"
        if not directory.is_dir():
            return []
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]


def legacy_story_drafts(client: Any) -> list[dict[str, Any]]:
    """The ``story_draft`` Proposals filed before ideas became Items (read only). An editor reads them in full; an IAM operator reads the
    summary ``listStoryDrafts`` gives (id, title, summary, targets, state, createdAt), which is all a run needs to dedupe."""
    if using_iam():
        return operator_story_drafts(client)
    return [row for row in list_proposals(client) if row.get("kind") == "story_draft"]


__all__ = ["JSON", "ITEMS", "STORES", "JsonStore", "StoreRefused", "LIST_QUERY", "assert_private", "default_root", "legacy_story_drafts"]
