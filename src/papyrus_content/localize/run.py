"""One translation run against a site: collect, run the stages, save, report back, hold (``papyrus.story.localize``, PPY-843a7c).

The procedure's tool (``papyrus_newsroom.tactus_tools.papyrus_localize_story``) is this function, so a run started from the cloud runner and one
started from the CLI are the same run. Every failure raises: the run fails with its reason, nothing is published, and the next start continues
from the stored stages.
"""
from __future__ import annotations

from typing import Any, Callable

from . import desired_state
from .engine import Localizer, finish
from .models import LocalizeModels, ResponsesModels, Spend
from .record import NothingToDo, collect, hold, report_back, save, stage_store_for


def procedure_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return f"papyrus-newsroom {version('papyrus-newsroom')}"
    except PackageNotFoundError:
        return "papyrus-newsroom (source checkout)"


def localize_story(client, *, story: str, language: str, ceiling_usd: float | None = None, source_version: int | None = None,
                   models: Callable[[Spend], LocalizeModels] | None = None) -> dict[str, Any]:
    """Translate the published version of ``story`` into ``language`` and save it as an unpublished version of its localization.

    The run starts only from the desired-state record (``desired_state``): with none, or with one naming a newer source than ``source_version``
    (the version the run was started for, default the published one), it stops before any model call. Its outcome is recorded on the record.

    Returns the procedure's output: ``{story, language, version, hold, reason, outcome, published, rounds, revertedBlocks, costUsd,
    sourceCharacters, findings, runKey}``."""
    spend = Spend()
    model = (models or (lambda s: ResponsesModels(s)))(spend)
    try:
        request = collect(client, story=story, language=language, judge=model.judge, procedure_version=procedure_version(), ceiling_usd=ceiling_usd)
    except NothingToDo as reason:
        return {"story": story, "language": language, "version": "", "hold": False, "reason": str(reason), "outcome": "stopped", "published": False,
                "rounds": 0, "revertedBlocks": 0, "costUsd": 0.0, "sourceCharacters": 0, "findings": {}, "runKey": ""}
    wanted = desired_state.current(client, request.source.lineage_id, request.language)
    stale = desired_state.stale_reason(wanted, {"versionNumber": source_version or request.source.version_number})
    if stale:
        return {"story": request.localization_lineage, "language": request.language, "version": "", "hold": False, "reason": stale,
                "outcome": "stopped", "published": False, "rounds": 0, "revertedBlocks": 0, "costUsd": 0.0, "sourceCharacters": 0, "findings": {},
                "runKey": request.run_key}
    stages = stage_store_for(client, request)
    try:
        outcome = Localizer(request, models=model, spend=spend, stages=stages).run()
    except Exception as error:
        desired_state.record_outcome(client, wanted, state="failed", run_key=request.run_key, reason=f"{type(error).__name__}: {error}")
        raise
    version = ""
    if outcome.get("repeated"):
        version = outcome.get("version", "")
    elif outcome["outcome"] in ("saved", "held"):
        version = save(client, request, outcome)["id"]
        report_back(client, request, outcome["provenance"]["reportBack"])
        if outcome["hold"]:
            hold(client, request, outcome["reason"])
        outcome = {**outcome, "version": version}
        finish(request, stages, outcome)
    state = "unchanged" if outcome.get("repeated") else outcome["outcome"]
    desired_state.record_outcome(client, wanted, state=state, run_key=request.run_key, reason=outcome["reason"])
    return {"story": request.localization_lineage, "language": request.language, "version": version, "hold": bool(outcome["hold"]),
            "reason": outcome["reason"], "outcome": outcome["outcome"] if not outcome.get("repeated") else "unchanged", "published": False,
            "rounds": outcome["rounds"], "revertedBlocks": outcome["revertedBlocks"], "costUsd": outcome["costUsd"],
            "sourceCharacters": outcome["provenance"]["blocks"]["sourceCharactersTranslated"] if "provenance" in outcome else 0,
            "findings": outcome["findings"], "runKey": request.run_key}
