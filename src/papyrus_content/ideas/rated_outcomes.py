"""Why a highly rated Reference produced no idea in a run (docs/idea-context-packs.md, "Editor interest").

An editor who gave a Reference four or five stars asked for a story. When a run files nothing for it, the run record says so, with the reason, so the
newsroom never has to guess whether the stars were read. ``rated_without_ideas`` is a pure function over the finished run: it reads what the run already
recorded (``skipped``, ``invalid``, the ranking) and adds one row per such Reference: ``{referenceId, lineageId, title, stars, reason, ...}``.

Reasons: ``pending_not_accepted`` (a pending Reference is context, never a single-item idea), ``not_accepted`` (rejected or archived), ``not_a_candidate``
(accepted, but already has a story, an automation took it, its host is excluded, the Cyclotron judged it not relevant, or an idea already covers it),
``not_reached`` (a candidate the run stopped before), or the run's own reason for the Reference (``nothing_to_add``, ``already_rejected``,
``no_point_offered``, ``point_check_failed``, ``citation_check_failed``, ``no_source_text``, ``model_error``, ...).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..reference_stars import MIDPOINT_STARS

EXPLANATIONS = {
    "pending_not_accepted": "It is still pending, and only an accepted Reference becomes a story idea of its own. Accepting it is the next step.",
    "not_accepted": "It was rejected or archived, so it is not used as evidence.",
    "not_a_candidate": "It already has a story or an idea, an automation took it, its host is excluded, or it was judged not relevant.",
    "not_reached": "The run stopped before it got to it; it is first in line next time.",
    "nothing_to_add": "The newsroom knows nothing about it beyond the source yet: a comment, a link to another Reference or an accept reason would give the writer something to add.",
    "already_rejected": "A draft was rejected earlier and nothing new has been learned since. A new comment, link or a change of rating is something new.",
    "no_point_offered": "The writer found nothing to say that the source does not already say.",
    "point_check_failed": "The draft said nothing a reader could not get from the source.",
    "citation_check_failed": "The draft broke the citation rules.",
    "no_source_text": "The page could not be read and nothing was stored about it.",
}


def rated_without_ideas(
    run: Mapping[str, Any], ratings: Iterable[Mapping[str, Any]], *, candidate_lineages: Iterable[str], covered_lineages: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """One row per Reference rated above the midpoint that the run filed no idea for. ``ratings`` rows carry ``referenceId``, ``lineageId``, ``title``, ``stars``, ``status``."""
    drafted = {str(draft.get("referenceLineageId") or draft.get("itemLineageId") or "") for draft in run.get("drafts") or []}
    for draft in run.get("drafts") or []:
        drafted.update(str(lineage) for lineage in (draft.get("evidence") or {}).get("referenceLineageIds") or [])
    covered, candidates = set(covered_lineages), set(candidate_lineages)
    said: dict[str, str] = {}
    for key in ("invalid", "skipped"):
        for row in run.get(key) or []:
            if row.get("referenceId") and row.get("reason"):
                said.setdefault(str(row["referenceId"]), str(row["reason"]))
    rows = []
    for rating in sorted(ratings, key=lambda row: (str(row["lineageId"]), str(row["referenceId"]))):
        if rating["stars"] <= MIDPOINT_STARS or rating["lineageId"] in drafted or rating["lineageId"] in covered:
            continue
        status = str(rating.get("status") or "pending")
        if status == "pending":
            reason = "pending_not_accepted"
        elif status != "accepted":
            reason = "not_accepted"
        elif rating["referenceId"] in said:
            reason = said[rating["referenceId"]]
        elif rating["lineageId"] in candidates:
            reason = "not_reached"
        else:
            reason = "not_a_candidate"
        rows.append({
            "referenceId": rating["referenceId"], "lineageId": rating["lineageId"], "title": rating.get("title") or "", "stars": rating["stars"], "reason": reason,
            "explanation": EXPLANATIONS.get(reason, ""),
        })
    return rows
