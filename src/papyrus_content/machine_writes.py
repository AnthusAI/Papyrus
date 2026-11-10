"""Which run wrote an Item, and undoing that run (PPY-5b5a5d).

On 2026-11-02 a knowledge run published about 1,400 wiki pages that nobody wanted, and nothing on the pages said which run made
them: cleanup had to guess by type and stage. A machine write of an Item now records the run that made it in the Item's
``metadata.machineWrite`` (``Item`` has no ``createdBy`` or ``source`` column, and the value is JSON, so no schema changes):

    {"runId": the latest run to write the Item, "createdByRunId": the run that made it (absent when a person made it),
     "writer": the step, "at": the time}

``versionCreatedBy`` is left as it was: the Idea column reads ``AI`` there to label a generated idea.

Undoing a run is one step in two directions. ``plan_undo`` selects the Items a run created; ``apply_undo`` unpublishes the live ones
and moves every one to the ``retired`` stage, recording what it was (``machineWrite.undone``). ``apply_restore`` reads that record
and puts each Item back. Nothing is deleted. A retired Item is left alone by the wiki sync and publish, so the next run does not bring it back.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .content_item_lifecycle import head_stage_fields
from .record_helpers import to_aws_json

MACHINE_WRITE_KEY = "machineWrite"
UNDONE_KEY = "undone"
RETIRED_STAGE = "retired"
UNDO_ACTOR = "papyrus-run-undo"
RUN_ID_ENVIRONMENT = "KNOWLEDGE_RUN_ID"


def _parse_json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _now() -> str:
    from .publishing import utc_now_iso  # noqa: PLC0415 - publishing imports this module

    return utc_now_iso()


def _part(value: str) -> str:
    return re.sub(r"[^a-z0-9._]+", "-", str(value or "").strip().lower()).strip("-")


def knowledge_run_id(publication: str, execution: str) -> str:
    """The id of one knowledge run (one Step Functions execution): ``knowledge-<publication>-<execution name>``."""
    return f"knowledge-{_part(publication)}-{_part(execution)}"


def run_id_from_environment(environment: Mapping[str, str]) -> str | None:
    """The run the process is part of: ``KNOWLEDGE_RUN_ID``, else built from the execution name the state machine gives every task."""
    explicit = (environment.get(RUN_ID_ENVIRONMENT) or "").strip()
    if explicit:
        return explicit
    publication, execution = (environment.get("KNOWLEDGE_PUBLICATION") or "").strip(), (environment.get("KNOWLEDGE_EXECUTION_NAME") or "").strip()
    return knowledge_run_id(publication, execution) if publication and execution else None


def machine_write(run_id: str | None, writer: str) -> dict[str, str] | None:
    """What ``ItemFields.machine_write`` carries: the run and the step. ``None`` when there is no run to record."""
    return {"runId": run_id, "writer": writer} if run_id else None


def apply_stamp(metadata: dict[str, Any], stamp: Mapping[str, str] | None, *, created: bool, now: str) -> None:
    """Record ``stamp`` in ``metadata`` (in place). The run that made the Item stays ``createdByRunId``; ``runId`` is always the latest writer."""
    if not stamp:
        return
    prior = _parse_json_object(metadata.get(MACHINE_WRITE_KEY))
    entry = {"runId": stamp["runId"], "writer": stamp.get("writer"), "at": now}
    created_by = stamp["runId"] if created else prior.get("createdByRunId")
    if created_by:
        entry["createdByRunId"] = created_by
    if prior.get(UNDONE_KEY):
        entry[UNDONE_KEY] = prior[UNDONE_KEY]
    metadata[MACHINE_WRITE_KEY] = {key: value for key, value in entry.items() if value is not None}


def machine_write_of(row: Mapping[str, Any]) -> dict[str, Any]:
    return _parse_json_object(_parse_json_object(row.get("metadata")).get(MACHINE_WRITE_KEY))


def lineage_of(row: Mapping[str, Any]) -> str:
    return str(row.get("lineageId") or row["id"])


def working_row(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """The version being worked on: the one marked current, else the latest."""
    pool = [row for row in rows if row.get("versionState") == "current"] or list(rows)
    return dict(max(pool, key=lambda row: (str(row.get("versionCreatedAt") or ""), int(row.get("versionNumber") or 0))))


@dataclass(frozen=True)
class UndoItem:
    item_id: str
    lineage_id: str
    type: str
    section: str
    slug: str
    stage: str | None
    status: str
    live_item_id: str | None
    rewritten_by: str | None  # a later run that wrote the Item again, when there is one

    @property
    def live(self) -> bool:
        return self.live_item_id is not None


@dataclass(frozen=True)
class UndoPlan:
    run_id: str
    items: tuple[UndoItem, ...] = ()
    already_retired: int = 0

    @property
    def live(self) -> list[UndoItem]:
        return [item for item in self.items if item.live]

    def summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for item in self.items:
            key = f"{item.type}:{item.section}"
            kinds[key] = kinds.get(key, 0) + 1
        return {
            "runId": self.run_id, "toRetire": len(self.items), "live": len(self.live), "alreadyRetired": self.already_retired,
            "rewrittenByLaterRuns": sum(1 for item in self.items if item.rewritten_by), "byTypeAndSection": dict(sorted(kinds.items())),
        }


def plan_undo(item_rows: Iterable[Mapping[str, Any]], run_id: str, live_source: Callable[[str], str | None]) -> UndoPlan:
    """The Items ``run_id`` created. ``live_source(lineage_id)`` is the id of the Item row a live page was made from, or ``None``."""
    lineages: dict[str, list[Mapping[str, Any]]] = {}
    for row in item_rows:
        lineages.setdefault(lineage_of(row), []).append(row)
    chosen: list[UndoItem] = []
    already = 0
    for lineage_id, rows in sorted(lineages.items()):
        working = working_row(rows)
        stamp = machine_write_of(working)
        if stamp.get("createdByRunId") != run_id:
            continue
        if working.get("stage") == RETIRED_STAGE and (stamp.get(UNDONE_KEY) or {}).get("runId") == run_id:
            already += 1
            continue
        later = stamp.get("runId") if stamp.get("runId") not in (None, run_id) else None
        chosen.append(
            UndoItem(
                item_id=working["id"], lineage_id=lineage_id, type=str(working.get("type") or ""), section=str(working.get("section") or ""),
                slug=str(working.get("slug") or ""), stage=working.get("stage"), status=str(working.get("status") or "draft"),
                live_item_id=live_source(lineage_id), rewritten_by=later,
            )
        )
    return UndoPlan(run_id, tuple(chosen), already)


def apply_undo(client: Any, plan: UndoPlan, *, by: str = UNDO_ACTOR, now: str | None = None) -> dict[str, int]:
    """Unpublish the live Items of the run, then move every one to ``retired`` and record what it was. Never deletes."""
    from .publishing import unpublish_item  # noqa: PLC0415 - publishing imports this module

    now = now or _now()
    done = {"retired": 0, "unpublished": 0}
    for item in plan.items:
        if item.live_item_id:
            unpublish_item(client, item.live_item_id, actor=by, now=now)
            done["unpublished"] += 1
        row = client.get_record("Item", item.item_id) or {}
        metadata = _parse_json_object(row.get("metadata"))
        stamp = _parse_json_object(metadata.get(MACHINE_WRITE_KEY))
        stamp[UNDONE_KEY] = {"runId": plan.run_id, "at": now, "by": by, "previous": {"stage": item.stage, "status": item.status, "wasLive": item.live}}
        metadata[MACHINE_WRITE_KEY] = stamp
        client.update_record(
            "Item",
            {"id": item.item_id, "stage": RETIRED_STAGE, **head_stage_fields({**row, "stage": RETIRED_STAGE}), "versionCreatedAt": now, "versionCreatedBy": by, "changeReason": f"undo of {plan.run_id}", "metadata": to_aws_json(metadata)},
        )
        done["retired"] += 1
    return done


@dataclass(frozen=True)
class RestorePlan:
    run_id: str
    items: tuple[tuple[str, dict[str, Any]], ...] = field(default=())  # (item id, the record of what it was)

    @property
    def was_live(self) -> int:
        return sum(1 for _id, previous in self.items if previous.get("wasLive"))


def plan_restore(item_rows: Iterable[Mapping[str, Any]], run_id: str) -> RestorePlan:
    """The Items an undo of ``run_id`` retired and that are still retired."""
    found = []
    for row in item_rows:
        undone = machine_write_of(row).get(UNDONE_KEY) or {}
        if undone.get("runId") == run_id and row.get("stage") == RETIRED_STAGE:
            found.append((row["id"], dict(undone.get("previous") or {})))
    return RestorePlan(run_id, tuple(sorted(found, key=lambda entry: entry[0])))


def _restored_stage(previous: Mapping[str, Any]) -> str:
    """The stage an Item had, except that a page that was live returns as a draft awaiting publication (the stage ``unpublish`` leaves)."""
    if previous.get("wasLive") or not previous.get("stage"):
        return "copywriting"
    return str(previous["stage"])


def apply_restore(client: Any, plan: RestorePlan, *, by: str = UNDO_ACTOR, now: str | None = None) -> int:
    """Put each Item back in the stage it had. A page that was live comes back as a draft: publishing is a separate act."""
    now = now or _now()
    for item_id, previous in plan.items:
        row = client.get_record("Item", item_id) or {}
        metadata = _parse_json_object(row.get("metadata"))
        stamp = _parse_json_object(metadata.get(MACHINE_WRITE_KEY))
        stamp.pop(UNDONE_KEY, None)
        metadata[MACHINE_WRITE_KEY] = stamp
        client.update_record(
            "Item",
            {
                "id": item_id, "stage": _restored_stage(previous), **head_stage_fields({**row, "stage": _restored_stage(previous)}), "versionCreatedAt": now, "versionCreatedBy": by,
                "changeReason": f"restored after the undo of {plan.run_id}", "metadata": to_aws_json(metadata),
            },
        )
    return len(plan.items)


def render_summary(summary: Mapping[str, Any]) -> str:
    return json.dumps(summary, indent=2, sort_keys=True)
