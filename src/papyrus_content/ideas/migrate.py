"""One-time conversion of open ``story_draft`` Proposals into Items at the ``idea`` stage (docs/idea-pipeline.md#ideas-are-items).

Dry run by default: ``plan`` only says what would happen. ``migrate`` with ``write=True`` files an Item for each Proposal that is converted.
A Proposal is skipped when it is not open (approved, declined and overridden ones are decided), when a story already rests on a Reference it cites
(``already_covered``), or when an older open Proposal cites exactly the same References (``duplicate``). The Proposals themselves are left as
they are. Run it by an editor (``papyrus login``): an IAM operator cannot read Proposals.
"""

from __future__ import annotations

import json
from typing import Any

from ..story_from_reference import SourceTextReader, reference_lineages_of_targets, section_of_draft_body
from ..story_reporting import stories_based_on_reference
from .items import file_idea_item, item_id_for_idea

OPEN_STATES = ("draft", "in_steering", "editor_review")


def parsed(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) and value else value


def draft_of(row: dict[str, Any]) -> dict[str, Any]:
    evidence = parsed(row.get("evidence")) or {}
    return {
        "ideaId": row["id"], "title": row.get("title") or "", "angle": row.get("summary") or "", "body": row.get("body") or "",
        "section": section_of_draft_body(str(row.get("body") or "")), "targets": parsed(row.get("targets")) or [], "origin": "migrated",
        "evidence": evidence or None, "proposedBy": "AI" if row.get("proposer") == "ai" else row.get("proposer") or "AI",
    }


def plan(client: Any, proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per story draft Proposal, oldest first: ``proposalId``, ``title``, ``action`` (``convert`` or ``skip``) and, for a skip, ``reason``."""
    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in sorted((r for r in proposals if r.get("kind") == "story_draft"), key=lambda r: (r.get("createdAt") or "", r["id"])):
        entry = {"proposalId": row["id"], "title": row.get("title") or "", "state": row.get("state"), "action": "convert"}
        lineages = tuple(sorted(reference_lineages_of_targets(row.get("targets"))))
        if row.get("state") not in OPEN_STATES:
            entry.update(action="skip", reason="decided")
        elif lineages and any(stories_based_on_reference(client, lineage) for lineage in lineages):
            entry.update(action="skip", reason="already_covered")
        elif lineages and lineages in seen:
            entry.update(action="skip", reason="duplicate")
        elif client.get_record("Item", item_id_for_idea(draft_of(row))) is not None:
            entry.update(action="skip", reason="already_covered")
        if entry["action"] == "convert" and lineages:
            seen.add(lineages)
        entries.append(entry)
    return entries


def migrate(client: Any, proposals: list[dict[str, Any]], *, write: bool, actor: str = "AI", source_text_reader: SourceTextReader | None = None, now: str | None = None) -> dict[str, Any]:
    """The plan, and with ``write`` the Items filed. A Proposal that cannot be filed (a copy-guard refusal, a body the Markus parser refuses) is
    reported as ``failed`` and the rest go on. Returns ``entries``, ``counts`` and ``written``."""
    entries = plan(client, proposals)
    by_id = {row["id"]: row for row in proposals}
    written = 0
    for entry in entries:
        if entry["action"] != "convert" or not write:
            continue
        try:
            result = file_idea_item(client, draft_of(by_id[entry["proposalId"]]), actor=actor, now=now, source_text_reader=source_text_reader,
                                    extra_generated={"migratedFromProposal": entry["proposalId"]})
        except Exception as error:  # noqa: BLE001 - one bad draft does not stop the rest
            entry.update(action="failed", reason=f"{type(error).__name__}: {error}"[:300])
            continue
        entry.update(itemLineageId=result["lineageId"], written=True)
        written += 1
    counts: dict[str, int] = {}
    for entry in entries:
        key = entry["action"] if entry["action"] != "skip" else f"skip_{entry['reason']}"
        counts[key] = counts.get(key, 0) + 1
    return {"write": write, "entries": entries, "counts": counts, "written": written}
