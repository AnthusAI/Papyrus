"""Copy a monitor delivery's facts from its old provenance relation onto the Reference itself.

Before "Messages come only from people", every monitor delivery wrote an ``ingestion_rationale`` Message and a relation to
the Reference whose metadata held the ``monitorId``, the source's ``details`` and (for a rule monitor) the direct-routing
rule. A delivery now records them on the Reference (``discoveredByMonitorId``, ``discoveryDetails``, ``discoveryRule``).
This one-time backfill reads each current Reference's old relations and copies the newest facts onto the Reference.
It touches only those three fields and only a Reference that has no ``discoveredByMonitorId`` yet. Writes by default;
``--dry-run`` prints the counts and writes nothing.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

PREDICATE = "ingestion_rationale"


def _metadata(relation: Mapping[str, Any]) -> dict[str, Any]:
    value = relation.get("metadata")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _newest(relations: Iterable[Mapping[str, Any]], key: str) -> tuple[Mapping[str, Any], dict[str, Any]] | None:
    found = []
    for relation in relations:
        if relation.get("predicate") != PREDICATE or relation.get("relationState", "current") != "current":
            continue
        metadata = _metadata(relation)
        if metadata.get(key):
            found.append((str(relation.get("importedAt") or relation.get("createdAt") or ""), relation, metadata))
    if not found:
        return None
    _, relation, metadata = max(found, key=lambda entry: entry[0])
    return relation, metadata


def plan_reference_update(reference: Mapping[str, Any], relations: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The fields to write on a Reference a monitor delivered before they were recorded on it, or ``None``."""
    if reference.get("discoveredByMonitorId"):
        return None
    relations = list(relations)
    delivered = _newest(relations, "monitorId")
    if delivered is None:
        return None
    update: dict[str, Any] = {"id": reference["id"], "discoveredByMonitorId": str(delivered[1]["monitorId"]).strip()}
    detailed = _newest(relations, "details")
    if detailed is not None and isinstance(detailed[1]["details"], dict):
        update["discoveryDetails"] = json.dumps(detailed[1]["details"], sort_keys=True)
    decided = _newest(relations, "machineDecision")
    if decided is not None and isinstance(decided[1]["machineDecision"], dict) and decided[1]["machineDecision"].get("system") == "direct":
        update["discoveryRule"] = json.dumps({"system": "direct", "rule": decided[1]["machineDecision"].get("rule")}, sort_keys=True)
    return update


def run_backfill(client: Any, *, apply: bool) -> dict[str, Any]:
    from .categories_steering import semantic_state_key

    counts: Counter[str] = Counter()
    monitors: Counter[str] = Counter()
    updates: list[dict[str, Any]] = []
    for reference in client.list_records("Reference"):
        if reference.get("versionState") not in (None, "current"):
            continue
        counts["scanned"] += 1
        if reference.get("discoveredByMonitorId"):
            counts["alreadyRecorded"] += 1
            continue
        lineage = reference.get("lineageId") or reference["id"]
        update = plan_reference_update(reference, client.list_semantic_relations_by_object_state(semantic_state_key("reference", lineage)))
        if update is None:
            counts["notDelivered"] += 1
            continue
        monitors[update["discoveredByMonitorId"]] += 1
        counts["planned"] += 1
        counts["withDetails"] += int("discoveryDetails" in update)
        counts["withRule"] += int("discoveryRule" in update)
        updates.append(update)
    if apply:
        for update in updates:
            client.update_record("Reference", update)
    return {"dryRun": not apply, **counts, "written": len(updates) if apply else 0, "monitors": dict(monitors)}


def references_backfill_monitor_deliveries(flags: list[str]) -> None:
    """papyrus references backfill-monitor-deliveries [--dry-run]: copy each delivery's monitor, details and rule onto its Reference."""
    from .graphql_authoring import create_authoring_client
    from .options import parse_options, resolve_mutation_apply

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-monitor-deliveries")
    client, _ = create_authoring_client()
    result = run_backfill(client, apply=apply)
    label = "references\tbackfill-monitor-deliveries"
    print(f"{label}\tmode\t{'apply' if apply else 'dry-run'}")
    for key in ("scanned", "alreadyRecorded", "notDelivered", "planned", "withDetails", "withRule", "written"):
        print(f"{label}\t{key}\t{result.get(key, 0)}")
    for monitor, count in sorted(result["monitors"].items()):
        print(f"{label}\tmonitor\t{monitor}\t{count}")
