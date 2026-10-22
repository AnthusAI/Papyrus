"""The weekly knowledge archive: one immutable entry per ISO week under ``_data/knowledge/history/``.

An entry holds the snapshot of the week, every cluster of the latest run with its identity against the previous run
(``new``, ``continued`` with its predecessor, ``merged`` with its sources, ``split`` with its source), the topic and
entity counts, the run id and the time the entry was taken. Cluster identity cannot be rebuilt later, so an entry is
never rewritten unless the operator asks for it. ``history/index.json`` lists the entries, oldest first, so a trend
feature reads one small file and then the entries it needs. Nothing here deletes a file.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from ..reader_steering.snapshot import encoded
from ..reader_steering.task import snapshot_key
from .builder import DATA_DIRECTORY, SCHEMA_VERSION
from .model import Cluster, KnowledgeData
from .weeks import iso_timestamp, parse_day, week_number

HISTORY_DIRECTORY = f"{DATA_DIRECTORY}/history"
HISTORY_INDEX_FILE = f"{HISTORY_DIRECTORY}/index.json"
IDENTITY_STATUSES = ("new", "continued", "merged", "split")

OUTCOME_CREATED = "created"
OUTCOME_KEPT = "kept"
OUTCOME_REPLACED = "replaced"


class ArchiveError(ValueError):
    """The archive step refuses: nothing was written."""


def entry_file(as_of: date | str) -> str:
    return f"{HISTORY_DIRECTORY}/{as_of}.json"


def latest_run(data: KnowledgeData) -> tuple[str, str | None, list[Cluster]]:
    """The newest cluster run and its clusters (the run with the latest date, as the clusters file picks it)."""
    runs = sorted((cluster.run_as_of or "", cluster.run_id) for cluster in data.clusters if cluster.run_id)
    if not runs:
        raise ArchiveError("No cluster run is published, so there is no cluster identity to archive. Run `papyrus knowledge publish-run` first.")
    run_id = runs[-1][1]
    clusters = [cluster for cluster in data.clusters if cluster.run_id == run_id]
    return run_id, runs[-1][0] or None, clusters


def identity_of(cluster: Cluster) -> dict:
    event = cluster.event
    predecessors = list(cluster.predecessor_uids)
    if event == "new":
        return {"status": "new"}
    if event == "continued":
        return {"status": "continued", "predecessor": predecessors[0] if predecessors else cluster.uid}
    if event == "merged" and predecessors:
        return {"status": "merged", "sources": sorted(predecessors)}
    if event == "split" and len(predecessors) == 1:
        return {"status": "split", "source": predecessors[0]}
    raise ArchiveError(
        f"Cluster {cluster.uid} has identity event {event!r} with predecessors {predecessors}; "
        "expected new, continued, merged (one or more sources) or split (one source)."
    )


def _cluster_row(cluster: Cluster) -> dict:
    named = cluster.accepted and bool(cluster.name)
    return {
        "uid": cluster.uid,
        "name": cluster.name if named else None,
        "identity": identity_of(cluster),
        "itemCount": len(cluster.member_item_keys) or cluster.member_count,
        "topTerms": list(cluster.top_terms),
    }


def build_entry(files: dict[str, dict], data: KnowledgeData, as_of: date, archived_at: str) -> dict:
    """The archive entry of the week ``as_of`` from the snapshot ``files`` (``{site key: payload}``)."""
    run_id, run_as_of, clusters = latest_run(data)
    if run_as_of and week_number(parse_day(run_as_of)) != week_number(as_of):
        raise ArchiveError(
            f"The latest cluster run (run {run_id}) is dated {run_as_of}, outside the week of {as_of}. "
            "Take the entry for that run's week with --as-of, or run this week's knowledge run first."
        )
    rows = sorted((_cluster_row(cluster) for cluster in clusters), key=lambda row: row["uid"])
    index = files[f"{DATA_DIRECTORY}/index.json"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "asOf": as_of.isoformat(),
        "runId": run_id,
        "runAsOf": run_as_of,
        "archivedAt": iso_timestamp(archived_at),
        "counts": {"entities": index["entityCount"], "topics": index["topicCount"], "clusters": len(rows)},
        "clusters": rows,
        "snapshot": {
            "index": index,
            "clusters": files[f"{DATA_DIRECTORY}/clusters.json"],
            "entities": {key[len(DATA_DIRECTORY) + len("/entities/") : -len(".json")]: payload for key, payload in sorted(files.items()) if key.startswith(f"{DATA_DIRECTORY}/entities/")},
        },
    }


def _index_row(entry: dict) -> dict:
    identity = {status: 0 for status in IDENTITY_STATUSES}
    for cluster in entry["clusters"]:
        identity[cluster["identity"]["status"]] += 1
    return {
        "asOf": entry["asOf"],
        "file": f"{entry['asOf']}.json",
        "runId": entry["runId"],
        "runAsOf": entry["runAsOf"],
        "archivedAt": entry["archivedAt"],
        "counts": entry["counts"],
        "identity": identity,
    }


def _read_json(writer: Any, key: str) -> dict | None:
    body = writer.get(key)
    if body is None:
        return None
    try:
        parsed = json.loads(body)
    except ValueError as error:
        raise ArchiveError(f"{key} is stored but is not valid JSON; fix or remove it by hand, the archive will not overwrite it.") from error
    if not isinstance(parsed, dict):
        raise ArchiveError(f"{key} is stored but is not a JSON object; the archive will not overwrite it.")
    return parsed


def _history_index(writer: Any, projector: Any, entry: dict) -> dict:
    """The index with this entry's row. Rows come from the stored index; an entry file that the index misses is read
    and added, so a lost or stale index heals itself."""
    stored = _read_json(writer, snapshot_key(projector, HISTORY_INDEX_FILE)) or {}
    rows = {row["asOf"]: row for row in stored.get("entries", []) if isinstance(row, dict) and "asOf" in row}
    prefix = snapshot_key(projector, HISTORY_DIRECTORY + "/")
    for stored_object in writer.list(prefix):
        name = stored_object.key[len(prefix) :]
        day = name[: -len(".json")] if name.endswith(".json") else ""
        if len(day) == 10 and day not in rows:
            other = _read_json(writer, stored_object.key)
            if other and other.get("clusters") is not None:
                rows[day] = _index_row(other)
    rows[entry["asOf"]] = _index_row(entry)
    return {"schemaVersion": SCHEMA_VERSION, "entries": [rows[day] for day in sorted(rows)]}


def archive_entry(context: Any, entry: dict, *, replace: bool = False) -> dict:
    """Store ``entry`` unless the week already has one. Returns ``{outcome, written, purged, existingRunId}``.

    The same run again keeps the stored entry. Another run of the same week is refused unless ``replace``; the stored
    entry then moves to the new run, and no other week is touched."""
    writer, projector = context.writer, context.projector
    key = snapshot_key(projector, entry_file(entry["asOf"]))
    existing = _read_json(writer, key)
    if existing is not None and not replace:
        if existing.get("runId") != entry["runId"]:
            raise ArchiveError(
                f"The week of {entry['asOf']} is already archived from run {existing.get('runId')}, not run {entry['runId']}. "
                "An entry is immutable; pass --replace to replace this week's entry (earlier weeks stay)."
            )
        outcome = OUTCOME_KEPT
        entry = existing
    else:
        outcome = OUTCOME_REPLACED if existing is not None else OUTCOME_CREATED
    bodies: dict[str, bytes] = {}
    if outcome != OUTCOME_KEPT:
        bodies[key] = encoded(entry)
    bodies[snapshot_key(projector, HISTORY_INDEX_FILE)] = encoded(_history_index(writer, projector, entry))
    written: list[str] = []
    for body_key in sorted(bodies, key=lambda name: name.endswith("index.json")):  # the entry first, then the index that names it
        if writer.get(body_key) != bodies[body_key]:
            writer.put(body_key, bodies[body_key])
            written.append(body_key)
    purged: list[str] = []
    purge_error = None
    if getattr(context, "invalidate", None) is not None and written:
        try:
            purged = context.invalidate(written)
        except Exception as error:  # noqa: BLE001
            purge_error = type(error).__name__
    return {
        "outcome": outcome,
        "written": written,
        "purged": purged,
        "purgeError": purge_error,
        "existingRunId": (existing or {}).get("runId"),
    }
