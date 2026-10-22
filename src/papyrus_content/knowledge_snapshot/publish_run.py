"""Plan what ``papyrus knowledge publish-run`` writes. Pure: rows in, records out; the command applies them.

Three sources feed the plan:

* front-matter entities of published items: accepted nodes and desk-confirmed ``mentions`` links (the desk entered them);
* extractor entities: generated nodes and unconfirmed links, created once and never changed by a later run;
* clusters: one ``topic_cluster`` proposal per cluster uid.

A name resolves to an existing node of the same kind by case and white space insensitive name or alias. A rejected
node is never revived and never linked. Everything is keyed by deterministic ids, so a second run plans nothing new.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..categories_commands import with_version_fields
from ..categories_steering import semantic_relation_record
from ..ids import safe_id
from .cluster_records import CLUSTER_KIND, cluster_proposal_id, proposal_record
from .keys import contains_email, entity_key, normalize_name, slug
from .model import LINK_EXTRACTOR, LINK_FRONT_MATTER, PublishedItem
from .run_input import ClusterRun, TypedEntity

ACTOR = "Papyrus knowledge publish-run"
FRONT_MATTER_IMPORT_RUN = "knowledge-front-matter"
MENTIONS = "mentions"
ITEM_KIND = "item"
NODE_KIND = "semanticNode"
STATUS_ACCEPTED = "accepted"
STATUS_GENERATED = "generated"
STATUS_REJECTED = "rejected"
LINK_METADATA_KIND = "knowledge.item_mention"


def json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@dataclass
class PublishPlan:
    """``records`` are full rows to create or bring up to date; ``patches`` are partial updates of existing rows."""

    records: list[dict] = field(default_factory=list)
    patches: list[dict] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def count(self, name: str, amount: int = 1) -> None:
        self.counts[name] = self.counts.get(name, 0) + amount


class NodeIndex:
    """Existing and planned node rows by kind and normalized name or alias."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self._by_name: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            if row.get("versionState", "current") == "current":
                self.add(dict(row))

    def add(self, row: dict) -> None:
        kind = slug(row.get("nodeKind") or "")
        for name in [row.get("displayName"), *(row.get("aliases") or ())]:
            normal = normalize_name(name or "")
            if normal:
                self._by_name.setdefault((kind, normal), []).append(row)

    def resolve(self, kind: str, name: str) -> dict | None:
        candidates = self._by_name.get((slug(kind), normalize_name(name)), [])
        for status in (STATUS_ACCEPTED, STATUS_GENERATED):
            matches = sorted((row for row in candidates if row.get("status") == status), key=lambda row: str(row.get("id")))
            if matches:
                return matches[0]
        return next((row for row in candidates if row.get("status") == STATUS_REJECTED), None)


def node_lineage_id(node_key: str) -> str:
    return f"semantic-node-{node_key}"


def new_node_row(kind: str, name: str, status: str, *, import_run_id: str, corpus_id: str | None, now: str, reason: str) -> dict:
    key = entity_key(kind, name)
    lineage_id = node_lineage_id(key)
    return with_version_fields(
        {
            "id": f"{lineage_id}-v1",
            "lineageId": lineage_id,
            "nodeKey": key,
            "nodeKind": slug(kind),
            "corpusId": corpus_id,
            "displayName": " ".join(name.split()),
            "aliases": [],
            "status": status,
            "importRunId": import_run_id,
            "createdAt": now,
            "newsroomFeedKey": "semanticNodes",
            "updatedAt": now,
        },
        now=now,
        actor=ACTOR,
        reason=reason,
    )


def mention_record(
    item: PublishedItem,
    node: Mapping[str, Any],
    *,
    source: str,
    confirmed: bool,
    import_run_id: str,
    now: str,
    extractor_state: str | None = None,
    run_id: str | None = None,
) -> dict:
    metadata: dict[str, Any] = {"kind": LINK_METADATA_KIND, "linkSource": source, "confirmed": confirmed}
    if extractor_state:
        metadata["extractorState"] = extractor_state
    return semantic_relation_record(
        {
            "predicate": MENTIONS,
            "subjectKind": ITEM_KIND,
            "subjectId": item.item_id,
            "subjectLineageId": item.key,
            "subjectVersionNumber": None,
            "objectKind": NODE_KIND,
            "objectId": node["id"],
            "objectLineageId": node["lineageId"],
            "objectVersionNumber": node.get("versionNumber") or 1,
            "rank": 1,
            "classifierId": source,
            "sourceSnapshotId": run_id,
            "importRunId": import_run_id,
            "importedAt": now,
            "metadata": metadata,
        }
    )


def is_item_mention(row: Mapping[str, Any]) -> bool:
    return (
        row.get("predicate") == MENTIONS
        and row.get("subjectKind") == ITEM_KIND
        and row.get("objectKind") == NODE_KIND
        and row.get("relationState", "current") == "current"
    )


def _usable(kind: str, name: str, plan: PublishPlan, where: str) -> bool:
    if not entity_key(kind, name):
        plan.warnings.append(f"{where}: an entity needs a kind and a name")
        return False
    if contains_email(name):
        plan.warnings.append(f"{where}: skipped an entity whose name holds an email address")
        return False
    return True


def plan_front_matter(
    items: list[PublishedItem],
    index: NodeIndex,
    existing_mentions: Iterable[Mapping[str, Any]],
    plan: PublishPlan,
    *,
    corpus_id: str | None,
    now: str,
) -> set[tuple[str, str]]:
    desired: set[tuple[str, str]] = set()
    for item in items:
        for entity in item.entities:
            if not _usable(entity.kind, entity.name, plan, item.key):
                continue
            node = index.resolve(entity.kind, entity.name)
            if node is None:
                node = new_node_row(
                    entity.kind, entity.name, STATUS_ACCEPTED, import_run_id=FRONT_MATTER_IMPORT_RUN, corpus_id=corpus_id, now=now, reason="front-matter entity"
                )
                plan.records.append({"modelName": "SemanticNode", "expected": node})
                plan.count("nodesCreated")
                index.add(node)
            elif node.get("status") == STATUS_REJECTED:
                plan.warnings.append(f"{item.key}: {entity.name!r} is a rejected entity; no link written")
                plan.count("linksSkippedRejected")
                continue
            elif node.get("status") == STATUS_GENERATED:
                node["status"] = STATUS_ACCEPTED
                plan.patches.append({"modelName": "SemanticNode", "expected": {"id": node["id"], "status": STATUS_ACCEPTED, "updatedAt": now}})
                plan.count("nodesAccepted")
            pair = (item.key, node["lineageId"])
            if pair in desired:
                continue
            desired.add(pair)
            plan.records.append(
                {
                    "modelName": "SemanticRelation",
                    "expected": mention_record(item, node, source=LINK_FRONT_MATTER, confirmed=True, import_run_id=FRONT_MATTER_IMPORT_RUN, now=now)["expected"],
                }
            )
            plan.count("linksFrontMatter")
    planned_items = {item.key for item in items}
    for row in existing_mentions:
        metadata = json_object(row.get("metadata"))
        if (
            is_item_mention(row)
            and metadata.get("linkSource") == LINK_FRONT_MATTER
            and row.get("subjectLineageId") in planned_items
            and (row.get("subjectLineageId"), row.get("objectLineageId")) not in desired
        ):
            plan.patches.append({"modelName": "SemanticRelation", "expected": {"id": row["id"], "relationState": "superseded", "updatedAt": now}})
            plan.count("linksSuperseded")
    return desired


def plan_extractor(
    entities: list[TypedEntity],
    items: list[PublishedItem],
    index: NodeIndex,
    confirmed: set[tuple[str, str]],
    run_id: str,
    plan: PublishPlan,
    *,
    corpus_id: str | None,
    now: str,
) -> None:
    by_id = {item.item_id: item for item in items}
    import_run_id = f"typed-entities-run-{safe_id(run_id)}"
    planned: set[tuple[str, str]] = set()
    unpublished = 0
    for entity in entities:
        item = by_id.get(entity.item_id)
        if item is None:
            unpublished += 1
            continue
        if not _usable(entity.kind, entity.name, plan, entity.item_id):
            continue
        node = index.resolve(entity.kind, entity.name)
        if node is None:
            node = new_node_row(
                entity.kind, entity.name, STATUS_GENERATED, import_run_id=import_run_id, corpus_id=corpus_id, now=now, reason=f"typed-entities:{run_id}"
            )
            plan.records.append({"modelName": "SemanticNode", "expected": node, "createOnly": True})
            plan.count("nodesGenerated")
            index.add(node)
        elif node.get("status") == STATUS_REJECTED:
            plan.count("linksSkippedRejected")
            continue
        pair = (item.key, node["lineageId"])
        if pair in confirmed or pair in planned:
            continue
        planned.add(pair)
        plan.records.append(
            {
                "modelName": "SemanticRelation",
                "expected": mention_record(
                    item, node, source=LINK_EXTRACTOR, confirmed=False, import_run_id=import_run_id, now=now, extractor_state=entity.state, run_id=run_id
                )["expected"],
                "createOnly": True,
            }
        )
        plan.count("linksExtractor")
    if unpublished:
        plan.count("extractorMentionsOfUnpublishedItems", unpublished)


def plan_clusters(
    run: ClusterRun,
    existing: Mapping[str, Mapping[str, Any]],
    plan: PublishPlan,
    *,
    corpus_id: str,
    category_set_id: str | None,
    now: str,
) -> None:
    import_run_id = f"topic-cluster-run-{safe_id(run.run_id)}"
    for entry in run.clusters:
        current = existing.get(cluster_proposal_id(entry.uid))
        if current is not None and current.get("proposalKind") != CLUSTER_KIND:
            plan.warnings.append(f"{entry.uid}: id collides with a {current.get('proposalKind')} proposal; skipped")
            continue
        plan.records.append(
            {
                "modelName": "SteeringProposal",
                "expected": proposal_record(entry, run, current, corpus_id=corpus_id, category_set_id=category_set_id, import_run_id=import_run_id, now=now),
            }
        )
        plan.count("clustersContinued" if current is not None else "clustersNew")


def plan_publish_run(
    *,
    items: list[PublishedItem],
    node_rows: list[dict],
    mention_rows: list[dict],
    proposal_rows: list[dict],
    run: ClusterRun | None,
    corpus_id: str | None,
    category_set_id: str | None,
    now: str,
    include_front_matter: bool = True,
) -> PublishPlan:
    plan = PublishPlan()
    index = NodeIndex(node_rows)
    confirmed: set[tuple[str, str]] = set()
    if include_front_matter:
        confirmed = plan_front_matter(items, index, mention_rows, plan, corpus_id=corpus_id, now=now)
    if run is not None:
        plan.warnings.extend(run.warnings)
        if run.entities:
            plan_extractor(run.entities, items, index, confirmed, run.run_id, plan, corpus_id=corpus_id, now=now)
        if run.clusters:
            if not corpus_id:
                raise ValueError("Importing clusters needs --corpus-key or --corpus-id (a steering proposal belongs to a corpus).")
            plan_clusters(run, {row["id"]: row for row in proposal_rows}, plan, corpus_id=corpus_id, category_set_id=category_set_id, now=now)
    return plan
