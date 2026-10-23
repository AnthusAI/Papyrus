"""Where ideas go. Private by default: nothing here writes to a site's public data or asks a site to publish.

``JsonStore`` keeps digests, ideas and run ledgers as JSON files under a directory on this machine (default
``~/.papyrus/ideas/<publication>``), and refuses a directory that looks like a site's public output. ``ProposalStore`` files an
idea as a draft ``story_draft`` Proposal on a site that has the reader-steering proposals model; the site publishes proposals
only if it sets ``proposals.publish`` (default off).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..proposals_commands import FILE_MUTATION, LIST_QUERY, list_proposals, receipt

STORE_DIRECTORY_ENVIRONMENT = "PAPYRUS_IDEAS_DIR"
PUBLIC_DIRECTORY_NAMES = {"_data", "public", "static-root"}
JSON, PROPOSALS = "json", "proposals"
STORES = (JSON, PROPOSALS)


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


class ProposalStore:
    """Files ideas as draft story_draft Proposals. It needs an editor or admin session (`papyrus login`): the mutation is not open to IAM."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def file_idea(self, idea: dict[str, Any], body: str, digest_id: str) -> str:
        variables = {
            "kind": "story_draft",
            "title": idea["title"][:200],
            "summary": idea["angle"][:300],
            "body": body,
            "evidence": json.dumps({"signals": len(idea["citedReferenceIds"]), "source": f"ideas digest {digest_id}"}),
        }
        return receipt(self.client.graphql(FILE_MUTATION, variables), "fileProposal")

    def story_drafts(self) -> list[dict[str, Any]]:
        return [row for row in list_proposals(self.client) if row.get("kind") == "story_draft"]


__all__ = ["JSON", "PROPOSALS", "STORES", "JsonStore", "ProposalStore", "StoreRefused", "LIST_QUERY", "assert_private", "default_root"]
