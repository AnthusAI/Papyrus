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

from ..proposals_commands import FILE_MUTATION, LIST_QUERY, list_proposals, operator_story_drafts, receipt, using_iam

STORE_DIRECTORY_ENVIRONMENT = "PAPYRUS_IDEAS_DIR"
PUBLIC_DIRECTORY_NAMES = {"_data", "public", "static-root"}
JSON, PROPOSALS, ITEMS = "json", "proposals", "items"
STORES = (JSON, PROPOSALS, ITEMS)


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


MAXIMUM_TARGETS = 10  # what a Proposal may name (amplify/functions/proposal-actions TARGET_COUNTS)


class ProposalStore:
    """Files ideas as draft story_draft Proposals, as an editor or admin (`papyrus login`) or as an operator role of the site's own
    account (`PAPYRUS_GRAPHQL_AUTH=iam`). Only editors and admins may read Proposals in full; an operator reads the story drafts through
    ``listStoryDrafts`` (id, title, summary, targets, state, createdAt and nothing else), which is all a run needs to dedupe."""

    kind = PROPOSALS

    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def mark(record: dict[str, Any], identifier: str) -> None:
        record["proposalId"] = identifier

    def file_idea(self, idea: dict[str, Any], body: str, digest_id: str) -> str:
        variables = {
            "kind": "story_draft",
            "title": idea["title"][:200],
            "summary": idea["angle"][:300],
            "body": body,
            "evidence": json.dumps({"signals": len(idea["citedReferenceIds"]), "source": f"ideas digest {digest_id}"}),
        }
        # The cited References are the targets (``entity:reference:<lineage id>``), the same as a monitor story: that is how every later run, from
        # whichever path, sees these References are covered. A Proposal names at most ten subjects; the ones past that are not marked.
        lineages = list(dict.fromkeys(str(c.get("lineageId") or c["id"]) for c in idea.get("citations") or []))
        if lineages:
            variables["targets"] = json.dumps([{"type": "entity", "id": f"reference:{lineage}"} for lineage in lineages[:MAXIMUM_TARGETS]])
        return receipt(self.client.graphql(FILE_MUTATION, variables), "fileProposal")

    def file_story_draft(self, draft: dict[str, Any]) -> str:
        """A cited story draft (a trend story or a monitor story): the cited subjects are the targets and ``evidence`` says where it came from
        (a trend story also carries the figure spec for the editor to approve)."""
        variables = {
            "kind": "story_draft",
            "title": draft["title"][:200],
            "summary": draft["angle"][:300],
            "body": draft["body"],
            "targets": json.dumps(draft["targets"]),
            "evidence": json.dumps(draft["evidence"]),
        }
        return receipt(self.client.graphql(FILE_MUTATION, variables), "fileProposal")

    def story_drafts(self) -> list[dict[str, Any]]:
        if using_iam():
            return operator_story_drafts(self.client)
        return [row for row in list_proposals(self.client) if row.get("kind") == "story_draft"]


__all__ = ["JSON", "PROPOSALS", "ITEMS", "STORES", "JsonStore", "ProposalStore", "StoreRefused", "LIST_QUERY", "assert_private", "default_root"]
