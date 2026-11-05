"""Retire the References the GROBID citation graph created on its own (``papyrus references retire-citation-stubs --corpus-key KEY [--dry-run]``).

Reading a paper's bibliography creates a pending Reference for every cited work (``reference_url_text.py``): ``changeReason``
``grobid-citation-graph``, ``curationStatusReason`` "auto-created from GROBID citation graph", ``curationStatusUpdatedBy``
``papyrus-reference-url-text``. Nobody chose them, and thousands of them bury the pending feed. This archives each one that is still exactly
what the citation graph made: current, pending, those markers, that actor, no star rating and no recorded vote. Anything else is counted as
skipped and left alone. A stub that has a Cyclotron prediction is still eligible: a prediction is a machine's guess, not a person's choice.

It archives and never deletes. It writes the same fields a person's archive writes (status, status key, who, when, why, the reviewed-feed
key) and clears ``feedStateKey`` so the Reference is in neither References feed. The prediction, the arrival time, the citation relations and
the Reference itself stay, so nothing is lost and a person can reopen it. It records no vote (``curationActorKind`` stays empty): a retirement
is not an editor's label, and nothing here trains the Cyclotron.

The actor ``RETIRED_BY`` marks the archive as the machine's. A monitor that later finds the same paper returns a Reference archived by that
actor, and only by that actor, to pending (``restored_fields``, used by ``monitoring_intake.py``). A rejected Reference, or one archived by a
person, is never restored. Running it again selects nothing: a retired stub is no longer pending.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .reference_feed_keys import feed_keys, feed_state_key, medium_key_patch, public_key_patch
from .reference_policy import normalize_reference_curation_status

STUB_CHANGE_REASON = "grobid-citation-graph"
STUB_STATUS_REASON = "auto-created from GROBID citation graph"
STUB_CREATED_BY = "papyrus-reference-url-text"

RETIRED_BY = "papyrus-retire-citation-stubs"
RETIRED_REASON = ("Archived by the machine: this Reference was created automatically from a paper's bibliography, was never reviewed "
                  "and has no star rating. A person can reopen it, and a monitor that finds the paper again returns it to pending.")
RESTORED_BY = "papyrus-monitoring-worker"
RESTORED_REASON = "Returned to pending: a monitor found this paper after the machine archived it as an unreviewed citation stub."
REVIEWED_FEED_KEY = "references#reviewed"   # the key a person's archive writes (amplify/functions/category-action/handler.ts)

SKIP_REASONS = ("notCurrent", "notPending", "notCitationGraph", "notSystemActor", "starred", "voted")


def _present(value: Any) -> bool:
    return value is not None and value != "" and value is not False


def skip_reason(reference: Mapping[str, Any]) -> str | None:
    """Why this Reference is not a retirable citation stub, or None when it is. The first failing rule names it."""
    if reference.get("versionState", "current") != "current":
        return "notCurrent"
    if normalize_reference_curation_status(reference.get("curationStatus")) != "pending":
        return "notPending"
    if reference.get("changeReason") != STUB_CHANGE_REASON or reference.get("curationStatusReason") != STUB_STATUS_REASON:
        return "notCitationGraph"
    if reference.get("curationStatusUpdatedBy") != STUB_CREATED_BY:
        return "notSystemActor"
    # Stars are starRating (1 to 5) with starRatedAt/By and the starFeedKey partition; any trace of one means an editor looked.
    if any(_present(reference.get(field)) for field in ("starRating", "starRatedAt", "starRatedBy", "starFeedKey")):
        return "starred"
    if _present(reference.get("curationActorKind")):
        return "voted"
    return None


def retired_fields(reference: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    """The fields that archive one stub in place. Only ``feedStateKey`` leaves the feeds; ``feedArrivalAt`` and ``predictionSortKey``
    are sort keys of those indexes and mean nothing without it."""
    archived = {**reference, "curationStatus": "archived"}
    return {"curationStatus": "archived", "curationStatusKey": f"{reference['corpusId']}#archived", "curationStatusUpdatedAt": now,
            "curationStatusUpdatedBy": RETIRED_BY, "curationStatusReason": RETIRED_REASON,
            "reviewedFeedKey": REVIEWED_FEED_KEY, "feedStateKey": feed_state_key(archived), **medium_key_patch(reference, curationStatus="archived"), **public_key_patch(reference, curationStatus="archived"),
            "updatedAt": now}


def is_machine_retired(reference: Mapping[str, Any] | None) -> bool:
    """True only for a current Reference this command archived. Rejected, or archived by anyone else, is False."""
    return bool(reference) and reference.get("versionState", "current") == "current" \
        and normalize_reference_curation_status(reference.get("curationStatus")) == "archived" \
        and reference.get("curationStatusUpdatedBy") == RETIRED_BY


def restored_fields(reference: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    """The fields that return a machine-retired Reference to pending, with the feed keys a pending Reference has. A prediction it already
    holds is kept; ``record_original_prediction`` records one when it has none."""
    pending = {**reference, "curationStatus": "pending"}
    return {"curationStatus": "pending", "curationStatusKey": f"{reference['corpusId']}#pending", "curationStatusUpdatedAt": now,
            "curationStatusUpdatedBy": RESTORED_BY, "curationStatusReason": RESTORED_REASON,
            "reviewedFeedKey": None, **feed_keys(pending), "updatedAt": now}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def retire_citation_stubs(client: Any, *, corpus_id: str, dry_run: bool = False, now: str | None = None,
                          progress: Callable[[str], None] = lambda line: None) -> dict[str, Any]:
    """Archive every retirable citation stub of one corpus. A dry run counts the same things and writes nothing."""
    stamp = now or _now()
    counts: dict[str, Any] = {"corpusId": corpus_id, "dryRun": dry_run, "scanned": 0, "eligible": 0, "withUrl": 0, "withoutUrl": 0,
                              "withInboundCitations": 0, "withPrediction": 0, **{f"skipped.{name}": 0 for name in SKIP_REASONS},
                              "skipped": 0, "written": 0}
    for reference in client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#pending"):
        if not reference:
            continue
        counts["scanned"] += 1
        reason = skip_reason(reference)
        if reason:
            counts["skipped"] += 1
            counts[f"skipped.{reason}"] += 1
            continue
        counts["eligible"] += 1
        counts["withUrl" if str(reference.get("sourceUri") or "").strip() else "withoutUrl"] += 1
        counts["withInboundCitations"] += int((reference.get("inboundCitationCount") or 0) > 0)
        counts["withPrediction"] += int(bool(reference.get("predictionDecidedAt")))
        if not dry_run:
            client.update_record("Reference", {"id": reference["id"], **retired_fields(reference, now=stamp)})
            counts["written"] += 1
            progress(f"{counts['written']} written")
    return counts
