"""The public side of proposals: the data files the reader snapshot publishes and the adapter that reads vote counts.

A proposal is stored by the ``reader-actions`` function (``amplify/plugins/reader-steering/function/proposals.py`` owns the
record and its transitions). The snapshot turns the stored rows into ``_data/proposals/index.json`` and one
``_data/proposals/<id>.json`` per proposal. Every state is published, each labelled, so a site can show drafts, what is in
steering and what an editor decided. Nothing private reaches the files: not the proposer's siteSubject, not the staff
member's id. The proposer reads "AI" (or "Reader"), and a state change reads "Editor" for a decision and "Staff" otherwise.

Votes belong to the vote model. Until it publishes up, down and net per subject, :class:`VoteCounts` reads whatever the
subjects snapshot (``_data/reader/items.json``) holds for a proposal and treats missing counts as zero.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

PROPOSALS_DATA_DIRECTORY = "_data/proposals"
INDEX_FILE = f"{PROPOSALS_DATA_DIRECTORY}/index.json"
PROPOSAL_FILE = PROPOSALS_DATA_DIRECTORY + "/{id}.json"
PROPOSAL_SUBJECT_TYPE = "proposal"

DRAFT, IN_STEERING, EDITOR_REVIEW, APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR = (
    "draft",
    "in_steering",
    "editor_review",
    "approved",
    "declined",
    "overridden_by_editor",
)
STATE_LABELS = {
    DRAFT: "Draft",
    IN_STEERING: "In steering",
    EDITOR_REVIEW: "Editor review",
    APPROVED: "Approved",
    DECLINED: "Declined",
    OVERRIDDEN_BY_EDITOR: "Overridden by editor",
}
#: From the moment a proposal reaches editor review, the community result is fixed and shown beside the editor's.
FROZEN_STATES = (EDITOR_REVIEW, APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR)
DECIDED_STATES = (APPROVED, DECLINED, OVERRIDDEN_BY_EDITOR)
GROUPS = {"story_draft": "stories", "new_concept": "concepts"}
MAP_CHANGES = "map_changes"
PROPOSERS = {"ai": "AI"}
READER_PROPOSER = "Reader"


def proposal_subject_key(proposal_id: str) -> str:
    """The key votes on a proposal are stored under: ``{type: "proposal", id}`` as one string (the vote model owns the format)."""
    return f"{PROPOSAL_SUBJECT_TYPE}:{proposal_id}"


class VoteCounts:
    """Up, down, net and comment count for a proposal, read from the subjects snapshot; absent counts are zero."""

    def __init__(self, subjects: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._subjects = subjects or {}

    @classmethod
    def from_items_file(cls, payload: Mapping[str, Any] | None) -> "VoteCounts":
        """``payload`` is the content of ``_data/reader/items.json`` (its ``items`` map keyed by subject)."""
        return cls((payload or {}).get("items") or {})

    def votes(self, proposal_id: str) -> dict[str, int]:
        entry = self._subjects.get(proposal_subject_key(proposal_id)) or {}
        up, down = whole(entry.get("up")), whole(entry.get("down"))
        net = entry.get("net")
        return {"up": up, "down": down, "net": up - down if net is None else whole(net, allow_negative=True)}

    def comments(self, proposal_id: str) -> int:
        return whole((self._subjects.get(proposal_subject_key(proposal_id)) or {}).get("comments"))


def whole(value: Any, *, allow_negative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    number = int(value)
    return number if allow_negative else max(number, 0)


def parsed(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return fallback if value is None else value


def proposer_name(row: Mapping[str, Any]) -> str:
    return PROPOSERS.get(str(row.get("proposer") or ""), READER_PROPOSER)


def group_of(kind: str) -> str:
    return GROUPS.get(kind, MAP_CHANGES)


def public_history(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each state change with who made it by role, its reason and, for an override, the editor's result. No actor id."""
    entries = []
    for entry in parsed(row.get("history"), []):
        to_state = entry.get("to")
        if entry.get("from") is None:
            by = proposer_name(row)
        else:
            by = "Editor" if to_state in DECIDED_STATES else "Staff"
        item: dict[str, Any] = {"from": entry.get("from"), "to": to_state, "by": by, "reason": entry.get("reason"), "at": entry.get("at")}
        if entry.get("result"):
            item["result"] = entry["result"]
        entries.append(item)
    return entries


def decision_of(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The editor's decision: its state, result (approved or declined), public reason and time. ``None`` until one is made."""
    state = row.get("state")
    if state not in DECIDED_STATES:
        return None
    last = next((entry for entry in reversed(public_history(row)) if entry["to"] == state), None)
    if last is None:
        return None
    return {"state": state, "result": last.get("result", state), "by": "Editor", "reason": last["reason"], "at": last["at"]}


def community_result(row: Mapping[str, Any], votes: Mapping[str, int]) -> dict[str, Any] | None:
    """The votes fixed when the proposal reached editor review; live until the snapshot has fixed them; ``None`` before review."""
    if row.get("state") not in FROZEN_STATES:
        return None
    stored = parsed(row.get("communityResult"), None)
    if isinstance(stored, dict):
        return {"up": whole(stored.get("up")), "down": whole(stored.get("down")), "net": whole(stored.get("net"), allow_negative=True), "at": stored.get("at")}
    return {**votes, "at": None}


def public_proposal(row: Mapping[str, Any], counts: VoteCounts) -> dict[str, Any]:
    state = row["state"]
    votes = counts.votes(row["id"])
    entry: dict[str, Any] = {
        "id": row["id"],
        "kind": row["kind"],
        "group": group_of(row["kind"]),
        "title": row["title"],
        "summary": row.get("summary"),
        "state": state,
        "label": f"{STATE_LABELS[state]} · Proposed by {proposer_name(row)}",
        "proposedBy": proposer_name(row),
        "targets": parsed(row.get("targets"), []),
        "evidence": parsed(row.get("evidence"), None),
        "createdAt": row["createdAt"],
        "updatedAt": row.get("updatedAt") or row["createdAt"],
        "votes": votes,
        "comments": counts.comments(row["id"]),
        "communityResult": community_result(row, votes),
        "decision": decision_of(row),
    }
    return entry


def build_proposal_files(rows: Iterable[Mapping[str, Any]], counts: VoteCounts, generated_at: str) -> dict[str, dict]:
    """Site key to content: the index (newest first) and one file per proposal, which adds the body and the history."""
    rows = [row for row in rows if row.get("kind") and row.get("state") in STATE_LABELS]
    entries = [public_proposal(row, counts) for row in rows]
    by_id = {row["id"]: row for row in rows}
    entries.sort(key=lambda entry: (entry["createdAt"], entry["id"]), reverse=True)
    files: dict[str, dict] = {INDEX_FILE: {"generatedAt": generated_at, "proposals": entries}}
    for entry in entries:
        row = by_id[entry["id"]]
        files[PROPOSAL_FILE.format(id=entry["id"])] = {
            "generatedAt": generated_at,
            "proposal": {**entry, "body": row["body"], "history": public_history(row)},
        }
    return files
