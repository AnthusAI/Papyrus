"""Plan the entities and relations of monitor records (``papyrus knowledge publish-run --monitor-records FILE``).

Everything here is a source fact, so it is deterministic and skips the extractor and the AI review:

* each record links to an entity per structured field: the model (``model--org-name``), its maker (the Hub author), its
  licence and its task (the pipeline tag). An existing entity is matched first by key, so ``licence--apache-2-0`` and
  ``task--text-to-speech`` of the site's own items are reused; a new entity is accepted by ``ai`` with the name
  ``Hugging Face Hub import``, on the strength of the Hub's own fields;
* a base model the Hub names becomes a ``built_on`` relation from the model to its base, confirmed, with the relation
  subtype (finetune, quantized, adapter, merge, declared) kept in its metadata, the Hub card as evidence and the
  provenance ``from the Hugging Face Hub``. Both ends must be entities already: a model with a record in the window, or an
  accepted entity named by that id. A base model that is neither stays in the record;
* links are ``mentions`` from the Reference (``subjectKind`` ``reference``), marked ``knowledge.record_mention``. They
  never count as an item's mention, so the extractor, the AI review and the wiki treat them as data.

A second run with the same records plans nothing new; a record whose fields changed supersedes the links it no longer has.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from ..categories_steering import semantic_relation_record
from .actors import ACTOR_AI, Actor, ReviewMarks
from .keys import entity_key
from .model import LINK_MONITOR
from .monitor_records import MonitorRecord, record_entities
from .publish_run import (
    NODE_KIND,
    STATUS_ACCEPTED,
    STATUS_GENERATED,
    STATUS_REJECTED,
    MENTIONS,
    NodeIndex,
    PublishPlan,
    _usable,
    json_object,
    new_node_row,
)

MONITOR_IMPORT_RUN = "knowledge-monitor-records"
IMPORT_ACTOR_NAME = "Hugging Face Hub import"
RECORD_KIND = "reference"
RECORD_MENTION_METADATA = "knowledge.record_mention"
RECORD_RELATION_METADATA = "knowledge.record_relation"
BUILT_ON = "built_on"


def is_record_mention(row: Mapping[str, Any]) -> bool:
    return (
        row.get("predicate") == MENTIONS
        and row.get("subjectKind") == RECORD_KIND
        and row.get("objectKind") == NODE_KIND
        and row.get("relationState", "current") == "current"
        and json_object(row.get("metadata")).get("kind") == RECORD_MENTION_METADATA
    )


def is_record_relation(row: Mapping[str, Any]) -> bool:
    return row.get("subjectKind") == NODE_KIND and json_object(row.get("metadata")).get("kind") == RECORD_RELATION_METADATA


def mention_row(record: MonitorRecord, node: Mapping[str, Any], *, now: str) -> dict:
    return semantic_relation_record(
        {
            "predicate": MENTIONS,
            "subjectKind": RECORD_KIND,
            "subjectId": record.reference_id,
            "subjectLineageId": record.lineage_id,
            "subjectVersionNumber": None,
            "objectKind": NODE_KIND,
            "objectId": node["id"],
            "objectLineageId": node["lineageId"],
            "objectVersionNumber": node.get("versionNumber") or 1,
            "rank": 1,
            "classifierId": LINK_MONITOR,
            "importRunId": MONITOR_IMPORT_RUN,
            "importedAt": now,
            "metadata": {"kind": RECORD_MENTION_METADATA, "linkSource": LINK_MONITOR, "confirmed": True, "provenance": record.provenance},
        }
    )["expected"]


def built_on_row(record: MonitorRecord, subject: Mapping[str, Any], target: Mapping[str, Any], subtype: str, actor: Actor, *, now: str) -> dict:
    return semantic_relation_record(
        {
            "predicate": BUILT_ON,
            "subjectKind": NODE_KIND,
            "subjectId": subject["id"],
            "subjectLineageId": subject["lineageId"],
            "subjectVersionNumber": subject.get("versionNumber") or 1,
            "objectKind": NODE_KIND,
            "objectId": target["id"],
            "objectLineageId": target["lineageId"],
            "objectVersionNumber": target.get("versionNumber") or 1,
            "rank": 1,
            "classifierId": LINK_MONITOR,
            "importRunId": MONITOR_IMPORT_RUN,
            "importedAt": now,
            "metadata": {
                "kind": RECORD_RELATION_METADATA, "linkSource": LINK_MONITOR, "confirmed": True, "acceptedBy": actor.to_dict(),
                "subtype": subtype, "evidence": record.url, "provenance": record.provenance,
            },
        }
    )["expected"]


def plan_monitor_records(
    records: Iterable[MonitorRecord],
    index: NodeIndex,
    existing_rows: Iterable[Mapping[str, Any]],
    plan: PublishPlan,
    *,
    corpus_id: str | None,
    now: str,
) -> None:
    """Add the nodes, links and relations of ``records`` to ``plan``. ``existing_rows`` are the current relation rows that touch
    the accepted nodes, from which the links and relations already written are known."""
    records = sorted(records, key=lambda record: record.reference_id)
    existing = {str(row.get("id")): row for row in existing_rows if is_record_mention(row) or is_record_relation(row)}
    actor = Actor(actor=ACTOR_AI, name=IMPORT_ACTOR_NAME, on=now[:10])
    reason = ReviewMarks(accepted_by=actor).encode()
    model_nodes: dict[str, dict] = {}
    desired: set[str] = set()
    per_record: list[tuple[MonitorRecord, dict]] = []
    for record in records:
        for kind, name in record_entities(record):
            if not _usable(kind, name, plan, record.reference_id):
                continue
            node = index.by_key(entity_key(kind, name)) or index.resolve(kind, name)
            if node is None:
                node = new_node_row(kind, name, STATUS_ACCEPTED, import_run_id=MONITOR_IMPORT_RUN, corpus_id=corpus_id, now=now, reason=reason)
                plan.records.append({"modelName": "SemanticNode", "expected": node})
                plan.count("recordNodesCreated")
                index.add(node)
            elif node.get("status") == STATUS_REJECTED:
                plan.count("recordLinksSkippedRejected")
                continue
            elif node.get("status") == STATUS_GENERATED:
                node["status"] = STATUS_ACCEPTED
                node["changeReason"] = reason
                plan.patches.append(
                    {"modelName": "SemanticNode", "expected": {"id": node["id"], "status": STATUS_ACCEPTED, "changeReason": reason, "updatedAt": now}}
                )
                plan.count("recordNodesAccepted")
            if kind == "model" and name == record.model_id:
                model_nodes[record.model_id] = node
            row = mention_row(record, node, now=now)
            desired.add(row["id"])
            if row["id"] in existing:
                continue
            plan.records.append({"modelName": "SemanticRelation", "expected": row, "createOnly": True})
            plan.count("recordLinks")
        per_record.append((record, model_nodes.get(record.model_id, {})))
    for record, subject in per_record:
        for base in record.details.get("baseModels") or []:
            base_id = str(base.get("modelId") or "")
            target = model_nodes.get(base_id)
            if target is None:
                resolved = index.resolve("model", base_id) if base_id else None
                target = resolved if resolved is not None and resolved.get("status") == STATUS_ACCEPTED else None
            if not subject or target is None or target["lineageId"] == subject["lineageId"]:
                plan.count("recordBaseModelsOffMap")
                continue
            row = built_on_row(record, subject, target, str(base.get("relation") or "declared"), actor, now=now)
            desired.add(row["id"])
            if row["id"] in existing:
                continue
            plan.records.append({"modelName": "SemanticRelation", "expected": row, "createOnly": True})
            plan.count("recordRelations")
    planned_subjects = {record.lineage_id for record in records}
    for row_id, row in existing.items():
        if row_id not in desired and is_record_mention(row) and row.get("subjectLineageId") in planned_subjects:
            plan.patches.append({"modelName": "SemanticRelation", "expected": {"id": row_id, "relationState": "superseded", "updatedAt": now}})
            plan.count("recordLinksSuperseded")
