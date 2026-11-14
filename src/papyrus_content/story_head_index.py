"""`papyrus stories head-index`: fill in (and verify) the head stage key on rows written before it existed.

Only the head row of a story lineage carries ``headStageKey`` (docs/plans/story-head-stage-index.md), so the index
``listItemsByHeadStageAndUpdatedAt`` holds one row per story. Every writer keeps it from the deploy that adds the field on; rows written before then
have none. This command reads the old stage index once, stage by stage (the migration's one full read of story rows, counted as a named sweep),
groups the rows by lineage and picks each lineage's head with the rule the writers use: the row marked ``current``, else the one row that is not
superseded (a ``draft`` story nobody has saved since), the most recently created when a muddled lineage has several. It then

* sets the key on the head when it is missing or names the wrong stage,
* removes it from any other row that is not superseded,
* never writes a superseded row (none should carry the key; one that does is reported),
* writes only rows that differ, so a second run writes nothing and its dry run is the health check,
* passes each row's own ``updatedAt`` so no card jumps to the top of its column, and
* writes at a capped rate (default 5 a second).

A dry run unless ``--apply``. Muddled lineages (more than one row not superseded) are reported for ``papyrus stories repair-versions``; nothing
here changes a version state.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .content_item_lifecycle import CONTENT_ITEM_STAGES, HEAD_STAGE_KEY_FIELD, head_stage_key
from .tenancy import rows_for_tenant, tenant_scoped_value

#: Every stage a head row can be in: the board stages plus the one an undo of a machine write leaves (machine_writes.RETIRED_STAGE).
HEAD_INDEX_STAGES = (*CONTENT_ITEM_STAGES, "retired")
DEFAULT_RATE = 5.0
SWEEP_NAME = "stories-head-index"


@dataclass
class HeadIndexPlan:
    rows: int = 0
    stories: int = 0
    already_right: int = 0
    sets: list[dict[str, Any]] = field(default_factory=list)       # {lineageId, id, stage, key, updatedAt, previous}
    removals: list[dict[str, Any]] = field(default_factory=list)   # {lineageId, id, updatedAt, previous}
    muddled: list[dict[str, Any]] = field(default_factory=list)    # {lineageId, rows: [(id, versionState)]}
    headless: list[str] = field(default_factory=list)              # lineages whose every row is superseded
    superseded_with_key: list[str] = field(default_factory=list)   # superseded rows that carry a key: reported, never written

    def counts(self) -> dict[str, int]:
        return {
            "rows read": self.rows, "stories": self.stories, "heads to set": len(self.sets), "keys to remove": len(self.removals), "already right": self.already_right,
            "muddled": len(self.muddled), "no head": len(self.headless), "superseded with key": len(self.superseded_with_key),
        }


def head_of(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The head row of one lineage: the row marked current, else a row that is not superseded; the most recently created among several
    (story_reporting._current_of). None when every row is superseded."""
    pool = [row for row in rows if row.get("versionState") == "current"] or [row for row in rows if row.get("versionState") != "superseded"]
    if not pool:
        return None
    return max(pool, key=lambda row: (str(row.get("versionCreatedAt") or ""), int(row.get("versionNumber") or 0), str(row.get("id"))))


def plan_head_index(rows: Iterable[dict[str, Any]], *, tenant_id: str | None = None, keys_readable: bool = True) -> HeadIndexPlan:
    """What the backfill would change. ``keys_readable`` is False on a site whose data API has no head stage key yet: every head then needs it."""
    by_lineage: dict[str, list[dict[str, Any]]] = {}
    rows = list(rows)
    for row in rows:
        by_lineage.setdefault(str(row.get("lineageId") or row["id"]), []).append(row)
    plan = HeadIndexPlan(rows=len(rows), stories=len(by_lineage))

    def stored_key(row: dict[str, Any]) -> str | None:
        return (row.get(HEAD_STAGE_KEY_FIELD) or None) if keys_readable else None

    for lineage_id in sorted(by_lineage):
        versions = by_lineage[lineage_id]
        plan.superseded_with_key += [row["id"] for row in versions if row.get("versionState") == "superseded" and stored_key(row)]
        live = [row for row in versions if row.get("versionState") != "superseded"]
        if len(live) > 1:
            plan.muddled.append({"lineageId": lineage_id, "rows": [(row["id"], row.get("versionState")) for row in live]})
        head = head_of(versions)
        if head is None:
            plan.headless.append(lineage_id)
            continue
        wanted = head_stage_key(head)
        wanted_stored = tenant_scoped_value(tenant_id, wanted) if wanted else None
        changed = False
        if stored_key(head) != wanted_stored:
            plan.sets.append({"lineageId": lineage_id, "id": head["id"], "stage": head.get("stage"), "key": wanted,
                              "updatedAt": head.get("updatedAt"), "previous": stored_key(head)})
            changed = True
        for row in live:
            if row["id"] != head["id"] and stored_key(row):
                plan.removals.append({"lineageId": lineage_id, "id": row["id"], "updatedAt": row.get("updatedAt"), "previous": stored_key(row)})
                changed = True
        if not changed:
            plan.already_right += 1
    return plan


def read_stage_rows(client: Any, stages: Iterable[str], *, with_key: bool) -> list[dict[str, Any]]:
    """Every row of the given old stage partitions, with the fields the plan needs (and the head stage key when the site has it), the client's
    tenant only."""
    index = "itemHeadFieldsWithKeyByStage" if with_key else "itemHeadFieldsByStage"
    rows: list[dict[str, Any]] = []
    for stage in stages:
        rows += client.list_by_index(index, stage)
    return rows_for_tenant("Item", getattr(client, "tenant_id", None), rows)


def apply_head_index(client: Any, plan: HeadIndexPlan, *, rate: float = DEFAULT_RATE, sleep: Callable[[float], None] = time.sleep,
                     clock: Callable[[], float] = time.monotonic, echo: Callable[[str], None] = print) -> int:
    """Writes the plan: one update per row, carrying the row's own ``updatedAt``, no faster than ``rate`` a second. Returns the writes made."""
    interval = 1.0 / rate if rate and rate > 0 else 0.0
    writes = [("set", change) for change in plan.sets] + [("remove", change) for change in plan.removals]
    next_at = clock()
    for kind, change in writes:
        wait = next_at - clock()
        if wait > 0:
            sleep(wait)
        update: dict[str, Any] = {"id": change["id"], HEAD_STAGE_KEY_FIELD: change["key"] if kind == "set" else None}
        if change.get("updatedAt"):
            update["updatedAt"] = change["updatedAt"]   # the row's own time: a backfill is not a change of the story
        client.update_record("Item", update)
        next_at = max(next_at, clock()) + interval
        echo(_change_line(kind, change, "written"))
    return len(writes)


def _change_line(kind: str, change: dict[str, Any], state: str) -> str:
    if kind == "set":
        return "\t".join(["stories", "head-index", "set", change["lineageId"], change["id"], str(change.get("key")), state,
                          f"was {change.get('previous') or '-'}"])
    return "\t".join(["stories", "head-index", "remove", change["lineageId"], change["id"], state, f"was {change.get('previous')}"])


def run_head_index(client: Any, *, apply: bool, stages: Iterable[str] | None = None, rate: float = DEFAULT_RATE,
                   sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                   echo: Callable[[str], None] = print, warn: Callable[[str], None] | None = None) -> HeadIndexPlan:
    """Plan, print and (with ``apply``) write. Refuses to write to a site whose data API has no head stage key yet."""
    from . import request_meter

    warn = warn or (lambda line: print(line, file=sys.stderr))
    supported = bool(getattr(client, "has_head_stage_key", lambda: True)())
    chosen = tuple(stages) if stages else HEAD_INDEX_STAGES
    for stage in chosen:
        if stage not in HEAD_INDEX_STAGES:
            raise ValueError(f"Unknown stage {stage!r}. Expected one of: {', '.join(HEAD_INDEX_STAGES)}.")
    if apply and not supported:
        raise ValueError("This site's data API has no headStageKey yet: it needs the deploy that adds the head stage index "
                         "(listItemsByHeadStageAndUpdatedAt) before the backfill can write. Nothing was written.")
    with request_meter.sweep(SWEEP_NAME):   # the migration's one full read of story rows, stage by stage
        rows = read_stage_rows(client, chosen, with_key=supported)
    plan = plan_head_index(rows, tenant_id=getattr(client, "tenant_id", None), keys_readable=supported)
    if not supported:
        warn("stories\thead-index\tnote\tthis site's data API has no headStageKey yet: every head is counted as needing it. "
             "It needs the deploy that adds the head stage index first; then run with --apply.")
    for entry in plan.muddled:
        rows_text = ", ".join(f"{row_id} ({state})" for row_id, state in entry["rows"])
        echo("\t".join(["stories", "head-index", "muddled", entry["lineageId"], rows_text, "run: papyrus stories repair-versions --story " + entry["lineageId"]]))
    for lineage_id in plan.headless:
        echo("\t".join(["stories", "head-index", "no-head", lineage_id, "every row is superseded; run: papyrus stories repair-versions --story " + lineage_id]))
    for row_id in plan.superseded_with_key:
        echo("\t".join(["stories", "head-index", "superseded-with-key", row_id, "left alone (a superseded row is never written)"]))
    if apply:
        with request_meter.sweep(SWEEP_NAME):
            apply_head_index(client, plan, rate=rate, sleep=sleep, clock=clock, echo=echo)
    else:
        for change in plan.sets:
            echo(_change_line("set", change, "would write"))
        for change in plan.removals:
            echo(_change_line("remove", change, "would write"))
    summary = "\t".join(f"{name} {value}" for name, value in plan.counts().items())
    echo(f"stories\thead-index\t{'write' if apply else 'dry run'}\t{summary}")
    return plan
