"""`papyrus stories backfill-published-dates`: give published Stories the dates they now mean (docs/site-hosting.md, "Published and updated dates").

Before this change every publish stamped ``publishedAt`` with the publish time of the version it published and overwrote the version's ``versionCreatedAt``,
``versionCreatedBy`` and ``changeReason`` with the publish. Now ``publishedAt`` is the first publication of the Story, carried to every later version, and
``versionPublishedAt`` / ``versionPublishedBy`` record when, and by whom, the version now served went live. This command moves the rows published before the change
to the new meaning, using only what the rows recorded:

* ``versionPublishedAt`` of the served version, on its PublishedItem and its Item row = the PublishedItem's ``publishedAt`` as it stood (the old meaning is exactly that),
  written only where the field is missing. ``versionPublishedBy`` = the served row's ``versionCreatedBy`` when its ``changeReason`` is ``publish`` (the publish put the
  publisher there); otherwise left absent.
* ``publishedAt`` = the earliest publish the Story's versions recorded: the earliest ``versionCreatedAt`` of a version whose ``changeReason`` is ``publish``, or any
  ``versionPublishedAt``; never later than the ``publishedAt`` the Story already has (an imported Story's front matter date is earlier and stays). Written on the
  PublishedItem, the served Item row and every version that is not superseded, so the next version saved from any of them carries it.
* A Story with a version whose ``changeReason`` is ``unpublish`` lost the publish time of that version when it was taken down, so its first publication cannot be
  derived; a Story with no recorded publish at all has no evidence. Both are listed ("unclear") for a person to decide and their ``publishedAt`` is not changed.

Nothing is invented. Reads: the head stage index for the ``published`` stage, then one ``itemsByLineageAndVersion`` read and one PublishedItem get per published Story.
Writes only rows that differ, each carrying its own ``updatedAt`` so no card jumps in a work queue, at most ``rate`` a second. A dry run unless ``apply``; a second
run writes nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .publishing import published_item_id_for

DEFAULT_RATE = 5.0
SWEEP_NAME = "stories-backfill-published-dates"


@dataclass
class PublishedDatesPlan:
    stories: int = 0
    already_right: int = 0
    writes: list[dict[str, Any]] = field(default_factory=list)    # {model, id, lineageId, updatedAt?, fields}
    unclear: list[dict[str, Any]] = field(default_factory=list)   # {lineageId, reason, evidence}

    def counts(self) -> dict[str, int]:
        return {"stories": self.stories, "rows to write": len(self.writes), "already right": self.already_right, "unclear": len(self.unclear)}


def _earliest(values: list[str]) -> str | None:
    return min(values) if values else None


def recorded_publishes(versions: list[dict[str, Any]]) -> list[str]:
    """Every publish time the versions recorded."""
    times = [str(row["versionCreatedAt"]) for row in versions if row.get("changeReason") == "publish" and row.get("versionCreatedAt")]
    return times + [str(row["versionPublishedAt"]) for row in versions if row.get("versionPublishedAt")]


def plan_story(published: dict[str, Any], versions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The writes for one published Story, and why its first publication is unclear (None when it is clear)."""
    lineage_id = str(published["itemLineageId"])
    served = next((row for row in versions if row["id"] == published.get("sourceItemId")), None)
    if served is None:
        return [], {"lineageId": lineage_id, "reason": "the served version is not among the Story's versions", "evidence": []}
    writes: list[dict[str, Any]] = []
    # The old meaning of publishedAt is exactly when the served version went live, so it is the source of versionPublishedAt wherever that is not yet recorded.
    version_fields: dict[str, Any] = {"versionPublishedAt": published.get("versionPublishedAt") or served.get("versionPublishedAt") or published.get("publishedAt")}
    publisher = published.get("versionPublishedBy") or served.get("versionPublishedBy") or (served.get("versionCreatedBy") if served.get("changeReason") == "publish" else None)
    if publisher:
        version_fields["versionPublishedBy"] = publisher

    unclear = None
    first = published.get("publishedAt")
    evidence = recorded_publishes(versions)
    if any(row.get("changeReason") == "unpublish" for row in versions):
        unclear = {"lineageId": lineage_id, "reason": "a version was taken down, which overwrote when it was published", "evidence": sorted(evidence)}
    elif not evidence:
        unclear = {"lineageId": lineage_id, "reason": "no version recorded a publish", "evidence": []}
    else:
        earliest = _earliest(evidence)
        first = min(earliest, published["publishedAt"]) if published.get("publishedAt") else earliest

    first_fields = {"publishedAt": first} if unclear is None else {}
    targets = [("PublishedItem", published)] + [("Item", row) for row in versions if row["id"] == served["id"] or row.get("versionState") != "superseded"]
    for model, row in targets:
        wanted = {**first_fields, **(version_fields if row is published or row["id"] == served["id"] else {})}
        changes = {name: value for name, value in wanted.items() if row.get(name) != value}
        if changes:
            writes.append({"model": model, "id": row["id"], "lineageId": lineage_id, "updatedAt": row.get("updatedAt") if model == "Item" else None, "fields": changes})
    return writes, unclear


def plan_published_dates(client: Any) -> PublishedDatesPlan:
    """Reads the head stage index once for the ``published`` stage (one row per published Story), then each Story's versions and its PublishedItem by key."""
    from .story_head_index import read_stage_rows

    plan = PublishedDatesPlan()
    for lineage_id in sorted({str(row["lineageId"]) for row in read_stage_rows(client, ["published"], with_key=False)}):
        plan.stories += 1
        published = client.get_record("PublishedItem", published_item_id_for(lineage_id))
        versions = client.list_by_index("itemsByLineageAndVersion", lineage_id)
        if published is None:
            plan.unclear.append({"lineageId": lineage_id, "reason": "the Story is in the published stage but has no published row", "evidence": sorted(recorded_publishes(versions))})
            continue
        writes, unclear = plan_story(published, versions)
        plan.writes += writes
        if unclear:
            plan.unclear.append(unclear)
        if not writes and not unclear:
            plan.already_right += 1
    return plan


def apply_plan(client: Any, plan: PublishedDatesPlan, *, rate: float = DEFAULT_RATE, sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.monotonic, echo: Callable[[str], None] = print) -> int:
    interval = 1.0 / rate
    next_at = clock()
    for write in plan.writes:
        wait = next_at - clock()
        if wait > 0:
            sleep(wait)
        update = {"id": write["id"], **write["fields"]}
        if write.get("updatedAt"):
            update["updatedAt"] = write["updatedAt"]   # the row's own time: a backfill is not a change of the Story
        client.update_record(write["model"], update)
        next_at = max(next_at, clock()) + interval
        echo(_write_line(write, "written"))
    return len(plan.writes)


def _write_line(write: dict[str, Any], state: str) -> str:
    fields = " ".join(f"{name}={value}" for name, value in write["fields"].items())
    return "\t".join(["stories", "backfill-published-dates", "set", write["lineageId"], write["model"], write["id"], state, fields])


def run_backfill_published_dates(client: Any, *, apply: bool, rate: float = DEFAULT_RATE, sleep: Callable[[float], None] = time.sleep,
                                 clock: Callable[[], float] = time.monotonic, echo: Callable[[str], None] = print) -> PublishedDatesPlan:
    if rate <= 0 or rate > 25:
        raise ValueError("--rate must be more than 0 and at most 25 writes a second.")
    from . import request_meter

    with request_meter.sweep(SWEEP_NAME):
        plan = plan_published_dates(client)
    for entry in plan.unclear:
        echo("\t".join(["stories", "backfill-published-dates", "unclear", entry["lineageId"], entry["reason"], "recorded publishes: " + (", ".join(entry["evidence"]) or "none"),
                        "left as it is; a person decides"]))
    if apply:
        apply_plan(client, plan, rate=rate, sleep=sleep, clock=clock, echo=echo)
    else:
        for write in plan.writes:
            echo(_write_line(write, "would write"))
    echo(f"stories\tbackfill-published-dates\t{'write' if apply else 'dry run'}\t" + "\t".join(f"{name} {value}" for name, value in plan.counts().items()))
    return plan
