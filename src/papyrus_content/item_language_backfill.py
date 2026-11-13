"""`papyrus stories languages`: write the language and the language group on every Item row written before the fields existed (PPY-843a7c).

Every Item version carries ``language`` and ``languageGroupId`` (``item_language``). Writers set them from the deploy that adds the fields on; this
command writes them on the rows written before, once, so that no reader ever meets a row without a language (the plan's rule: no "missing means
primary" default at read time). Every row written before the fields existed is a primary-language row, so each gets the site's primary language and
its own lineage as its group.

* It reads the rows through the version-state index, state by state: every Item row has a version state, so the partitions together hold every row
  of the table without a table scan (the migration's one full read, counted as a named sweep). The client's tenant only.
* It writes only rows that lack a field, carrying each row's own ``updatedAt`` (a backfill is not a change of the Story), so a second run writes
  nothing and its dry run is the health check.
* It never changes a language a row already has.
* It does the same for the published rows (``PublishedItem``), which carry a copy of their version's language and group for the projection
  (docs/multilingual-serving.md). They are read with the one list of published summaries every projection reads; a published row's group is its
  lineage, because every row written before the fields is a primary-language Story.

Writes by default; ``--dry-run`` prints what it would write and writes nothing.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .item_language import LANGUAGE_FIELD, LANGUAGE_GROUP_FIELD
from .story_head_index import DEFAULT_RATE
from .tenancy import rows_for_tenant

#: Every version state an Item row can be in: a Story's (story_reporting), and a guideline document's row while its files are stored (guidelines/store.py).
VERSION_STATES = ("current", "draft", "superseded", "pending")
SWEEP_NAME = "stories-languages"


@dataclass
class LanguagePlan:
    rows: int = 0
    already_right: int = 0
    writes: list[dict[str, Any]] = field(default_factory=list)   # {id, lineageId, language?, languageGroupId?, updatedAt}
    published: "LanguagePlan | None" = None   # the plan for the published rows, beside the Item rows' plan

    def counts(self) -> dict[str, int]:
        return {"rows read": self.rows, "rows to write": len(self.writes), "already right": self.already_right}


def plan_languages(rows: Iterable[dict[str, Any]], primary: str) -> LanguagePlan:
    """The writes that give every row a language and a group. A row keeps what it has; only missing fields are written."""
    rows = list(rows)
    plan = LanguagePlan(rows=len(rows))
    for row in sorted(rows, key=lambda r: (str(r.get("lineageId") or r["id"]), int(r.get("versionNumber") or 0), str(r["id"]))):
        change: dict[str, Any] = {}
        if not row.get(LANGUAGE_FIELD):
            change[LANGUAGE_FIELD] = primary
        if not row.get(LANGUAGE_GROUP_FIELD):
            change[LANGUAGE_GROUP_FIELD] = str(row.get("lineageId") or row["id"])
        if not change:
            plan.already_right += 1
            continue
        plan.writes.append({"id": row["id"], "lineageId": str(row.get("lineageId") or row["id"]), **change, "updatedAt": row.get("updatedAt")})
    return plan


def plan_published_languages(rows: Iterable[dict[str, Any]], primary: str) -> LanguagePlan:
    """The writes that give every published row a language and a group: the primary language and the row's own lineage, only where missing."""
    rows = list(rows)
    plan = LanguagePlan(rows=len(rows))
    for row in sorted(rows, key=lambda r: str(r["id"])):
        change: dict[str, Any] = {}
        if not row.get(LANGUAGE_FIELD):
            change[LANGUAGE_FIELD] = primary
        if not row.get(LANGUAGE_GROUP_FIELD):
            change[LANGUAGE_GROUP_FIELD] = str(row.get("itemLineageId") or row["id"])
        if not change:
            plan.already_right += 1
            continue
        plan.writes.append({"id": row["id"], "lineageId": str(row.get("itemLineageId") or row["id"]), **change})
    return plan


def read_rows(client: Any, states: Iterable[str] = VERSION_STATES) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        rows += client.list_by_index("itemLanguageFieldsByVersionState", state)
    return rows_for_tenant("Item", getattr(client, "tenant_id", None), rows)


def _line(change: dict[str, Any], state: str, model: str = "Item") -> str:
    fields = " ".join(f"{name}={change[name]}" for name in (LANGUAGE_FIELD, LANGUAGE_GROUP_FIELD) if name in change)
    return "\t".join(["stories", "languages", model, change["lineageId"], change["id"], fields, state])


def run_languages(client: Any, *, primary: str, dry_run: bool = False, rate: float = DEFAULT_RATE, sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], float] = time.monotonic, echo: Callable[[str], None] = print) -> LanguagePlan:
    """Plan, print and (unless ``dry_run``) write, no faster than ``rate`` writes a second."""
    from . import request_meter

    with request_meter.sweep(SWEEP_NAME):   # the migration's one full read of Item rows, version state by version state, and of the published summaries
        plan = plan_languages(read_rows(client), primary)
        published = plan_published_languages(client.list_published_item_summaries(), primary)
    if dry_run:
        for model, found in (("Item", plan), ("PublishedItem", published)):
            for change in found.writes:
                echo(_line(change, "would write", model))
    else:
        interval = 1.0 / rate if rate and rate > 0 else 0.0
        next_at = clock()
        with request_meter.sweep(SWEEP_NAME):
            for model, found in (("Item", plan), ("PublishedItem", published)):
                for change in found.writes:
                    wait = next_at - clock()
                    if wait > 0:
                        sleep(wait)
                    update = {key: value for key, value in change.items() if key != "lineageId" and value is not None}
                    client.update_record(model, update)
                    next_at = max(next_at, clock()) + interval
                    echo(_line(change, "written", model))
    for model, found in (("Item", plan), ("PublishedItem", published)):
        summary = "\t".join(f"{name} {value}" for name, value in found.counts().items())
        echo(f"stories\tlanguages\t{model}\t{'dry run' if dry_run else 'write'}\t{summary}")
    plan.published = published
    return plan
