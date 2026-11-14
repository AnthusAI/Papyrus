"""The weekly cluster history: ``_data/knowledge/clusters-history.json``.

One entry per ISO week, oldest first. Each lists the clusters of that week's run (stable ``uid``, ``label``, ``itemCount``) and
the lineage events that connect the run to the previous one: ``born``, ``continued``, ``merged_from`` and ``split_into``. A site
draws a cluster river and a "what changed" panel from it without reading every weekly archive entry.

The file is built incrementally. The snapshot carries the previous file's weeks forward and puts this week's entry in place of any
entry of the same week; a missing file is backfilled from the weekly archive entries (``history/<asOf>.json``) when they exist.
Everything here is pure: no clock, no storage. The file holds no reader id, email or handle; a ``uid`` is a topic-model cluster id.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from .model import Cluster
from .weeks import parse_day, week_monday, week_number

EVENT_BORN = "born"
EVENT_CONTINUED = "continued"
EVENT_MERGED_FROM = "merged_from"
EVENT_SPLIT_INTO = "split_into"
_ORDER = {EVENT_BORN: 0, EVENT_CONTINUED: 1, EVENT_MERGED_FROM: 2, EVENT_SPLIT_INTO: 3}


def identity_of(cluster: Cluster) -> dict:
    """How a cluster relates to the previous run, in the shape of an archive entry: ``{status: new}``, ``continued`` (``predecessor``),
    ``merged`` (``sources``) or ``split`` (``source``). A cluster whose event cannot be described (a merge with no source, a split with
    other than one source, an unknown event) is reported as new rather than stopping the snapshot."""
    predecessors = sorted(cluster.predecessor_uids)
    if cluster.event == "continued":
        return {"status": "continued", "predecessor": cluster.predecessor_uids[0] if cluster.predecessor_uids else cluster.uid}
    if cluster.event == "merged" and predecessors:
        return {"status": "merged", "sources": predecessors}
    if cluster.event == "split" and len(predecessors) == 1:
        return {"status": "split", "source": predecessors[0]}
    return {"status": "new"}


def events_of(rows: Iterable[dict]) -> list[dict]:
    """Lineage events of one week from rows ``{uid, identity}``. A split is one event on the source, naming every cluster it split into."""
    events: list[dict] = []
    splits: dict[str, list[str]] = {}
    for row in rows:
        identity, uid = row["identity"], row["uid"]
        status = identity.get("status")
        if status == "new":
            events.append({"event": EVENT_BORN, "uid": uid})
        elif status == "continued":
            events.append({"event": EVENT_CONTINUED, "uid": uid, "from": identity.get("predecessor", uid)})
        elif status == "merged":
            events.append({"event": EVENT_MERGED_FROM, "uid": uid, "sources": sorted(identity.get("sources", ()))})
        elif status == "split":
            splits.setdefault(identity["source"], []).append(uid)
    events.extend({"event": EVENT_SPLIT_INTO, "uid": source, "into": sorted(children)} for source, children in splits.items())
    return sorted(events, key=lambda event: (_ORDER[event["event"]], event["uid"]))


def week_entry(as_of: date | str, run_id: str | None, rows: Iterable[dict]) -> dict:
    """The entry of the ISO week of ``as_of`` (its ``asOf`` is that week's Monday) from rows ``{uid, label, itemCount, identity}``."""
    rows = sorted(rows, key=lambda row: row["uid"])
    return {
        "asOf": week_monday(week_number(parse_day(as_of))).isoformat(),
        "runId": run_id,
        "clusters": [{"uid": row["uid"], "label": row["label"], "itemCount": row["itemCount"]} for row in rows],
        "events": events_of(rows),
    }


def valid_weeks(document: Any, schema_version: int) -> list[dict] | None:
    """The weeks of a stored history file, or ``None`` when it is not a history file of this schema."""
    if not isinstance(document, dict) or document.get("schemaVersion") != schema_version:
        return None
    weeks = document.get("weeks")
    if not isinstance(weeks, list) or not all(isinstance(week, dict) and isinstance(week.get("asOf"), str) for week in weeks):
        return None
    return weeks


def history_file(schema_version: int, as_of: date, weeks: Iterable[dict], entry: dict | None) -> dict:
    """The file: ``weeks`` carried forward, with ``entry`` in place of the entry of its week, oldest first."""
    kept = {week["asOf"]: week for week in weeks}
    if entry is not None:
        kept[entry["asOf"]] = entry
    return {"schemaVersion": schema_version, "asOf": as_of.isoformat(), "weeks": [kept[day] for day in sorted(kept)]}


def weeks_from_archive(entries: Iterable[dict], *, include_unnamed: bool) -> list[dict]:
    """Weeks rebuilt from weekly archive entries. An unnamed cluster is listed (with a ``null`` label) only when ``include_unnamed``,
    the same rule ``clusters.json`` follows, and its lineage is still reported."""
    weeks = []
    for entry in entries:
        rows = [
            {"uid": cluster["uid"], "label": cluster.get("name"), "itemCount": cluster.get("itemCount", 0), "identity": cluster["identity"]}
            for cluster in entry.get("clusters", ())
            if include_unnamed or cluster.get("name")
        ]
        weeks.append(week_entry(entry["asOf"], entry.get("runId"), rows))
    return weeks
