"""A test double for the idea pipeline's filing sink (``ItemStore``'s interface: ``kind``, ``mark``, ``file_idea``, ``file_story_draft``, ``story_drafts``).

The pipeline tests check dedupe, ledgers, reviews and the run record, not where an idea lands. This double files each idea through the fake client's
``fileProposal`` mutation, so those tests can read what was filed from the fake client (``client.proposals`` / ``client.filed``). The real sink, an Item at
the ``idea`` stage, is tested in ``test_idea_items.py`` and ``features_backend/idea-items.feature``.
"""

from __future__ import annotations

import json
from typing import Any

from papyrus_content.ideas.store import ITEMS, legacy_story_drafts
from papyrus_content.proposals_commands import FILE_MUTATION, receipt

MAXIMUM_TARGETS = 10


class FakeIdeaStore:
    kind = ITEMS

    def __init__(self, client: Any) -> None:
        self.client = client

    @staticmethod
    def mark(record: dict[str, Any], identifier: str) -> None:
        record["itemLineageId"] = identifier

    def file_idea(self, idea: dict[str, Any], body: str, digest_id: str) -> str:
        variables = {
            "kind": "story_draft", "title": idea["title"][:200], "summary": idea["angle"][:300], "body": body,
            "evidence": json.dumps({"signals": len(idea["citedReferenceIds"]), "source": f"ideas digest {digest_id}"}),
        }
        lineages = list(dict.fromkeys(str(c.get("lineageId") or c["id"]) for c in idea.get("citations") or []))
        if lineages:
            variables["targets"] = json.dumps([{"type": "entity", "id": f"reference:{lineage}"} for lineage in lineages[:MAXIMUM_TARGETS]])
        return receipt(self.client.graphql(FILE_MUTATION, variables), "fileProposal")

    def file_story_draft(self, draft: dict[str, Any]) -> str:
        variables = {
            "kind": "story_draft", "title": draft["title"][:200], "summary": draft["angle"][:300], "body": draft["body"],
            "targets": json.dumps(draft["targets"]), "evidence": json.dumps(draft["evidence"]),
        }
        return receipt(self.client.graphql(FILE_MUTATION, variables), "fileProposal")

    def story_drafts(self) -> list[dict[str, Any]]:
        return legacy_story_drafts(self.client)
