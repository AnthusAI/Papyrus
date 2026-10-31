"""Editors' decisions on generated ideas as training labels (PPY-5f8046, docs/idea-pipeline.md#decisions-are-labels).

A generated idea is an Item at the ``idea`` stage. What an editor does with it is a stage move recorded on the Item (``stageMoves``): forward
(reporting, assignment, copywriting, ...) accepts it, to ``spiked`` declines it, and the reason of that move is the decline reason. Nothing
is stored twice and no Message is written: the labels are read from the Items, whose ``based_on`` links name the References.

Two uses, both read-only:

* ``feedback_entries``: ``{title, verdict, note}`` entries in the shape ``ideas synthesize --feedback`` and review steering already use, so a declined
  angle is not proposed again and the model sees the reasons.
* ``export_rows``: JSON Lines rows in the priming import shape (``priming_export``), one per decided idea, for a Cyclotron over ideas (classifier
  ``idea-accept``: accepted is ``include``, declined is ``exclude``; the explanation is the editor's reason).
"""

from __future__ import annotations

import json
from typing import Any

from ..priming_export import compose_text, iso_day, machine_story_actor, row, scrubbed
from ..story_from_reference import _current_versions, reference_lineages_of_targets
from ..story_reporting import STAGE_MOVES_KEY
from .items import IDEA_STAGE, SPIKED_STAGE, generated_of

CLASSIFIER = "idea-accept"
SOURCE = "idea-pipeline"


def stage_moves(item: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = item.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    return [move for move in metadata.get(STAGE_MOVES_KEY) or [] if isinstance(move, dict)]


def decision_of(item: dict[str, Any]) -> dict[str, Any] | None:
    """``{label, reason, by, at}`` for an idea an editor has decided, or None while it is still an idea.

    The decision is the first move out of the idea stage: to ``spiked`` it is a decline (``exclude``), anywhere else an accept (``include``), even if
    the story is later held or spiked at a later stage."""
    if (item.get("stage") or IDEA_STAGE) == IDEA_STAGE:
        return None
    leaving = next((move for move in stage_moves(item) if move.get("from") == IDEA_STAGE), None) or {}
    target = leaving.get("to") or item.get("stage")
    declined = target == SPIKED_STAGE
    return {
        "label": "exclude" if declined else "include", "reason": str(leaving.get("reason") or "").strip(), "by": str(leaving.get("by") or ""),
        "at": leaving.get("at") or item.get("updatedAt") or "", "to": target,
    }


def decided_ideas(client: Any) -> list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]]:
    """(Item, its ``generated`` record, its decision) for every decided generated idea, oldest decision first."""
    found = []
    for item in _current_versions(client.list_records("Item")):
        generated = generated_of(item)
        decision = decision_of(item) if generated is not None else None
        if decision is not None:
            found.append((item, generated, decision))
    return sorted(found, key=lambda entry: (str(entry[2]["at"]), str(entry[0]["id"])))


def feedback_entries(client: Any) -> list[dict[str, Any]]:
    """Reviewer feedback from the decisions, in the shape ``ideas synthesize`` already takes."""
    return [
        {"title": item.get("title") or "", "verdict": "accept" if decision["label"] == "include" else "decline", "note": scrubbed(decision["reason"]), "source": "stage-move"}
        for item, _generated, decision in decided_ideas(client)
    ]


def export_rows(client: Any) -> list[dict[str, Any]]:
    """One priming-import row per decided idea. ``modelMade`` is true when a machine, not an editor, moved it."""
    rows = []
    for item, generated, decision in decided_ideas(client):
        url = next((str(source.get("url")) for source in (generated.get("sources") or []) if isinstance(source, dict) and source.get("url")), "")
        machine = machine_story_actor(decision["by"]) and decision["by"] != "papyrus-cli"
        provenance = {
            "source": SOURCE, "state": decision["to"], "labeledBy": "automation" if machine else "editor", "labeledAt": iso_day(decision["at"]), "modelMade": machine,
            "origin": generated.get("origin"), "monitorId": generated.get("monitorId"), "runId": generated.get("runId"),
            "referenceLineageIds": reference_lineages_of_targets(generated.get("targets")),
        }
        values = {"title": item.get("title") or "", "url": url, "summary": item.get("deck") or "", "body": item.get("bodyMarkus") or ""}
        rows.append(row(f"idea-{item.get('lineageId') or item['id']}", iso_day(item.get("versionCreatedAt")), values,
                        {CLASSIFIER: {"label": decision["label"], "explanation": "" if machine else scrubbed(decision["reason"])}}, provenance))
    return rows


__all__ = ["CLASSIFIER", "decision_of", "decided_ideas", "export_rows", "feedback_entries", "compose_text"]
