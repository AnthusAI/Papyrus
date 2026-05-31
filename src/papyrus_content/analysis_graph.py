from __future__ import annotations

import gzip
import json
from typing import Any

from .categories_commands import is_current_accepted_reference, with_version_fields
from .categories_steering import semantic_state_key
from .graphql_authoring import PapyrusGraphQLAuthoringClient
from .ids import hash_short, safe_id
from .model_attachments import download_attachment_buffer, model_attachment_id
from .records import build_record_change_from_current, build_record_changes_tolerating_optional_models
from .relation_types import load_semantic_relation_type_seeds, normalize_relation_type_key, semantic_relation_type_fields_for_predicate


def graph_export_summary_payload_id(import_run_id: str) -> str:
    return f"raw-importrun-{hash_short(import_run_id)}-graph-export-summary"


def compact_graph_artifact_row(row: dict[str, Any]) -> dict[str, Any]:
    attachment = row.get("attachment") or {}
    return {
        "importRunId": row.get("importRunId"),
        "corpusId": row.get("corpusId"),
        "classifierId": row.get("classifierId"),
        "artifactId": row.get("artifactId"),
        "sourceSnapshotId": row.get("sourceSnapshotId"),
        "importedAt": row.get("importedAt"),
        "status": row.get("status"),
        "attachmentId": attachment.get("id"),
        "storagePath": attachment.get("storagePath"),
        "mediaType": attachment.get("mediaType"),
        "byteSize": attachment.get("byteSize"),
        "sha256": attachment.get("sha256"),
    }


def fetch_graph_artifact_rows_indexed(
    client: PapyrusGraphQLAuthoringClient,
    *,
    corpus_id: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    import_run_key = f"{corpus_id}#graph-export" if corpus_id else "graph-export"
    import_runs = (
        client.list_knowledge_import_runs_by_corpus_kind_and_imported_at(import_run_key)
        if corpus_id
        else client.list_knowledge_import_runs_by_kind_and_imported_at("graph-export")
    )
    rows: list[dict[str, Any]] = []
    artifact_count = 0
    payload_fetched = 0
    attachment_fetched = 0
    for run in import_runs:
        artifacts = [
            artifact
            for artifact in client.list_knowledge_artifacts_by_import_run_and_kind(run["id"])
            if artifact.get("artifactKind") in {"graph-export", "graph-snapshot"}
        ]
        artifact_count += len(artifacts)
        artifact = artifacts[0] if artifacts else None
        raw_payload_id = graph_export_summary_payload_id(run["id"])
        raw_payload = client.get_record("KnowledgeRawPayload", raw_payload_id)
        raw_payload_attachment = client.get_record(
            "ModelAttachment",
            model_attachment_id("knowledgeRawPayload", raw_payload_id, "raw_payload", "graph-export-summary"),
        )
        graph_export_attachment = client.get_record(
            "ModelAttachment",
            model_attachment_id("knowledgeRawPayload", raw_payload_id, "graph_export", "graph-export"),
        )
        payload_fetched += 1 if raw_payload else 0
        attachment_fetched += (1 if raw_payload_attachment else 0) + (1 if graph_export_attachment else 0)
        rows.append(
            {
                "importRunId": run["id"],
                "corpusId": run.get("corpusId"),
                "classifierId": run.get("classifierId"),
                "sourceSnapshotId": run.get("sourceSnapshotId"),
                "importedAt": run.get("importedAt"),
                "status": run.get("status"),
                "artifact": artifact,
                "artifactId": (artifact or {}).get("artifactId"),
                "rawPayload": raw_payload,
                "rawPayloadAttachment": raw_payload_attachment,
                "attachment": graph_export_attachment,
            }
        )
    diagnostics = {
        "importRunIndex": (
            "listKnowledgeImportRunsByCorpusKindAndImportedAt"
            if corpus_id
            else "listKnowledgeImportRunsByKindAndImportedAt"
        ),
        "importRunKey": import_run_key,
        "artifactIndex": "listKnowledgeArtifactsByImportRunAndKind",
        "importRunsFetched": len(import_runs),
        "artifactsFetched": artifact_count,
        "payloadsFetched": payload_fetched,
        "attachmentsFetched": attachment_fetched,
        "elapsedMs": None,
    }
    return rows, diagnostics


def load_graph_export_payload_from_attachment(
    client: PapyrusGraphQLAuthoringClient,
    attachment: dict[str, Any],
) -> dict[str, Any]:
    buffer = download_attachment_buffer(client, attachment)
    if not buffer:
        raise ValueError(f"Graph export attachment {attachment['id']} is empty.")
    if attachment.get("mediaType") == "application/gzip" or str(attachment.get("filename") or "").endswith(".gz"):
        payload_buffer = gzip.decompress(buffer)
    else:
        payload_buffer = buffer
    return {
        "payload": json.loads(payload_buffer.decode("utf-8")),
        "sourceByteSize": len(payload_buffer),
    }


def hydrate_graph_reference_map_sync(client: PapyrusGraphQLAuthoringClient, corpus_id: str) -> dict[str, dict[str, Any]]:
    references = client.list_records("Reference")
    return {
        reference["externalItemId"]: reference
        for reference in references
        if reference.get("corpusId") == corpus_id
        and reference.get("externalItemId")
        and is_current_accepted_reference(reference)
    }


def build_graph_export_publish_records(
    payload: dict[str, Any],
    *,
    corpus_id: str,
    classifier_id: str | None,
    imported_at: str,
    reference_by_external_item_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    identity = _graph_export_identity(payload, corpus_id)
    counts = _graph_export_publish_counts(payload, reference_by_external_item_id)
    records = [
        _record_knowledge_import_run(
            identity["importRunId"],
            corpus_id,
            classifier_id,
            identity["snapshotId"],
            imported_at,
            payload,
            relation_count=counts["mentionEdgeCount"],
        ),
        {
            "modelName": "KnowledgeArtifact",
            "expected": {
                "id": f"knowledge-artifact-{safe_id(corpus_id)}-{safe_id(identity['extractorId'])}-{safe_id(identity['snapshotId'])}",
                "corpusId": corpus_id,
                "artifactKind": "graph-export",
                "artifactId": identity["snapshotRef"],
                "snapshotId": identity["snapshotId"],
                "displayName": f"Graph export {identity['snapshotRef']}",
                "createdAt": imported_at,
                "importRunId": identity["importRunId"],
            },
        },
        {
            "modelName": "KnowledgeRawPayload",
            "expected": {
                "id": graph_export_summary_payload_id(identity["importRunId"]),
                "ownerType": "importRun",
                "ownerId": identity["importRunId"],
                "payloadKind": "graph-export-summary",
                "importRunId": identity["importRunId"],
                "payload": json.dumps(
                    {
                        "snapshot": identity["snapshotRef"],
                        "graphId": identity["graphId"],
                        "extractorId": identity["extractorId"],
                        "extractionSnapshot": identity["extractionSnapshot"],
                        "stats": payload.get("stats") or {},
                        "nodeCount": counts["nodeCount"],
                        "edgeCount": counts["edgeCount"],
                        "semanticNodeCount": counts["semanticNodeCount"],
                        "semanticRelationCount": None,
                        "skippedItemNodes": counts["skippedItemNodes"],
                        "unresolvedReferences": counts["unresolvedReferences"],
                        "unresolvedReferenceItemIds": counts["unresolvedReferenceItemIds"],
                    }
                ),
                "createdAt": imported_at,
                "updatedAt": imported_at,
            },
        },
    ]
    return {
        **identity,
        "stats": payload.get("stats") or {},
        "nodeCount": counts["nodeCount"],
        "edgeCount": counts["edgeCount"],
        "records": records,
        "semanticNodeCount": counts["semanticNodeCount"],
        "semanticRelationCount": None,
        "skippedItemNodes": counts["skippedItemNodes"],
        "unresolvedReferences": counts["unresolvedReferences"],
        "unresolvedReferenceItemIds": counts["unresolvedReferenceItemIds"],
        "mentionEdgeCount": counts["mentionEdgeCount"],
        "mentionRelationCount": None,
    }


def resolve_graph_entity_popularity_thresholds(
    options: dict[str, Any] | None,
    *,
    plan: dict[str, Any] | None = None,
) -> tuple[int | None, int | None]:
    """
  Resolve minimum mention and reference thresholds from CLI flags and profile overrides.

  :param options: Parsed CLI options.
  :type options: dict[str, object] or None
  :param plan: Optional analysis reindex plan with effectiveParameters.
  :type plan: dict[str, object] or None
  :return: Tuple of (min_mention_count, min_reference_count); unset values are None.
  :rtype: tuple[int or None, int or None]
  """
    sources: list[dict[str, Any]] = []
    if options:
        sources.append(options)
    if plan:
        sources.append(plan.get("effectiveParameters") if isinstance(plan.get("effectiveParameters"), dict) else {})
        sources.append(plan.get("defaults") if isinstance(plan.get("defaults"), dict) else {})
    min_mention_count: int | None = None
    min_reference_count: int | None = None
    for source in sources:
        if min_mention_count is None:
            min_mention_count = _positive_int_or_none(
                source.get("min-mention-count") or source.get("graph.min_mention_count")
            )
        if min_reference_count is None:
            min_reference_count = _positive_int_or_none(
                source.get("min-reference-count") or source.get("graph.min_reference_count")
            )
    return min_mention_count, min_reference_count


def filter_graph_export_payload_by_entity_popularity(
    payload: dict[str, Any],
    *,
    min_mention_count: int | None = None,
    min_reference_count: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
  Drop low-popularity entity nodes and edges before graph publish/import.

  Popularity is computed across the full export by aggregating item→entity mention edges
  per canonical entity node_id.

  :param payload: Graph export payload with nodes[] and edges[].
  :type payload: dict[str, object]
  :param min_mention_count: Minimum total mention weight required to keep an entity.
  :type min_mention_count: int or None
  :param min_reference_count: Minimum distinct corpus items (references) required to keep an entity.
  :type min_reference_count: int or None
  :return: Filtered payload and filter statistics.
  :rtype: tuple[dict[str, object], dict[str, object]]
  """
    if not min_mention_count and not min_reference_count:
        return payload, {"applied": False}
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    existing_filter = stats.get("popularityFilter") if isinstance(stats.get("popularityFilter"), dict) else {}
    existing_mention = existing_filter.get("minMentionCount")
    existing_reference = existing_filter.get("minReferenceCount")
    if (
        int(existing_filter.get("nodesAfter") or 0) > 0
        and existing_mention == min_mention_count
        and existing_reference == min_reference_count
    ):
        return payload, {**existing_filter, "applied": True, "skipped": True, "reason": "already_filtered"}
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    graph_node_by_id = {
        _clean_string(node.get("node_id")): node for node in nodes if _clean_string(node.get("node_id"))
    }
    mention_stats: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if _clean_string(edge.get("edge_type")) != "mentions":
            continue
        src = _clean_string(edge.get("src"))
        dst = _clean_string(edge.get("dst"))
        if not src or not dst:
            continue
        src_node = graph_node_by_id.get(src) or {}
        dst_node = graph_node_by_id.get(dst) or {}
        if not _edge_touches_item_endpoint(edge, src_node=src_node, dst_node=dst_node):
            continue
        item_id = _edge_source_item_id(edge, src_node=src_node, dst_node=dst_node)
        entity_id = _entity_graph_node_id_for_mention_edge(
            edge,
            src_node=src_node,
            dst_node=dst_node,
            graph_node_by_id=graph_node_by_id,
        )
        entity_node = graph_node_by_id.get(entity_id) if entity_id else {}
        if not entity_id:
            continue
        stats = mention_stats.setdefault(
            entity_id,
            {"mentionCount": 0.0, "referenceItemIds": set(), "label": _clean_string(entity_node.get("label"))},
        )
        stats["mentionCount"] += float(edge.get("weight") or 1.0)
        if item_id:
            stats["referenceItemIds"].add(item_id)

    allowed_entity_ids: set[str] = set()
    for entity_id, stats in mention_stats.items():
        mention_count = int(stats["mentionCount"])
        reference_count = len(stats["referenceItemIds"])
        if min_mention_count and mention_count < min_mention_count:
            continue
        if min_reference_count and reference_count < min_reference_count:
            continue
        allowed_entity_ids.add(entity_id)

    kept_nodes: list[dict[str, Any]] = []
    seen_entity_ids: set[str] = set()
    for node in nodes:
        node_id = _clean_string(node.get("node_id"))
        if not node_id:
            continue
        if _is_graph_item_node(node):
            continue
        if node_id not in allowed_entity_ids:
            continue
        if node_id in seen_entity_ids:
            continue
        seen_entity_ids.add(node_id)
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        stats = mention_stats.get(node_id) or {}
        kept_nodes.append(
            {
                **node,
                "properties": {
                    **properties,
                    "mention_count": int(stats.get("mentionCount") or 0),
                    "reference_count": len(stats.get("referenceItemIds") or []),
                },
            }
        )

    kept_node_ids = allowed_entity_ids
    kept_edges: list[dict[str, Any]] = []
    seen_edge_ids: set[str] = set()
    for edge in edges:
        edge_id = _clean_string(edge.get("edge_id")) or f"{_clean_string(edge.get('src'))}:{_clean_string(edge.get('dst'))}"
        if edge_id in seen_edge_ids:
            continue
        src = _clean_string(edge.get("src"))
        dst = _clean_string(edge.get("dst"))
        if not src or not dst:
            continue
        src_node = graph_node_by_id.get(src) or {}
        dst_node = graph_node_by_id.get(dst) or {}
        if _edge_touches_item_endpoint(edge, src_node=src_node, dst_node=dst_node):
            entity_id = _entity_graph_node_id_for_mention_edge(
                edge,
                src_node=src_node,
                dst_node=dst_node,
                graph_node_by_id=graph_node_by_id,
            )
            if entity_id not in kept_node_ids:
                continue
            kept_edges.append(edge)
            seen_edge_ids.add(edge_id)
            continue
        if src in kept_node_ids and dst in kept_node_ids:
            kept_edges.append(edge)
            seen_edge_ids.add(edge_id)

    filtered_payload = {**payload, "nodes": kept_nodes, "edges": kept_edges}
    if isinstance(filtered_payload.get("stats"), dict):
        filtered_payload["stats"] = {
            **filtered_payload["stats"],
            "popularityFilter": {
                "applied": True,
                "minMentionCount": min_mention_count,
                "minReferenceCount": min_reference_count,
                "entitiesBefore": len(mention_stats),
                "entitiesAfter": len(allowed_entity_ids),
                "nodesBefore": len(nodes),
                "nodesAfter": len(kept_nodes),
                "edgesBefore": len(edges),
                "edgesAfter": len(kept_edges),
            },
        }
    filter_stats = {
        "applied": True,
        "minMentionCount": min_mention_count,
        "minReferenceCount": min_reference_count,
        "entitiesBefore": len(mention_stats),
        "entitiesAfter": len(allowed_entity_ids),
        "nodesBefore": len(nodes),
        "nodesAfter": len(kept_nodes),
        "edgesBefore": len(edges),
        "edgesAfter": len(kept_edges),
    }
    return filtered_payload, filter_stats


def build_graph_export_import_records(
    payload: dict[str, Any],
    *,
    corpus_id: str,
    classifier_id: str | None,
    imported_at: str,
    reference_by_external_item_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    identity = _graph_export_identity(payload, corpus_id)
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    records: list[dict[str, Any]] = []
    materialized_node_by_graph_node_id: dict[str, dict[str, Any]] = {}
    skipped_item_nodes = 0

    for node in nodes:
        node_id = _clean_string(node.get("node_id"))
        if not node_id:
            continue
        if _is_graph_item_node(node):
            skipped_item_nodes += 1
            continue
        if node_id in materialized_node_by_graph_node_id:
            continue
        lineage_id = (
            f"semantic-node-graph-{safe_id(corpus_id)}-{safe_id(identity['extractorId'])}-"
            f"{safe_id(identity['snapshotId'])}-{hash_short(node_id)}"
        )
        properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        mention_count = _positive_int_or_none(properties.get("mention_count"))
        reference_count = _positive_int_or_none(properties.get("reference_count"))
        semantic_node = with_version_fields(
            {
                "id": f"{lineage_id}-v1",
                "lineageId": lineage_id,
                "nodeKey": f"{identity['extractorId']}:{identity['snapshotId']}:{node_id}",
                "nodeKind": _normalize_graph_node_kind(node.get("node_type")),
                "corpusId": corpus_id,
                "categorySetId": None,
                "categoryLineageId": None,
                "categoryKey": None,
                "displayName": _clean_string(node.get("label")) or node_id,
                "description": _graph_node_description(node),
                "aliases": _graph_node_aliases(node),
                "acceptedReferenceMentionCount": mention_count,
                "distinctSourceKindCount": reference_count,
                "status": "generated",
                "importRunId": identity["importRunId"],
                "createdAt": imported_at,
                "newsroomFeedKey": "semanticNodes",
                "updatedAt": imported_at,
            },
            now=imported_at,
            actor="biblicus-graph-export",
            reason=f"graph-import:{identity['snapshotRef']}",
        )
        materialized_node_by_graph_node_id[node_id] = semantic_node
        records.append({"modelName": "SemanticNode", "expected": semantic_node})

    relation_records = _build_graph_export_relation_records(
        edges=edges,
        nodes=nodes,
        materialized_node_by_graph_node_id=materialized_node_by_graph_node_id,
        corpus_id=corpus_id,
        classifier_id=classifier_id,
        import_run_id=identity["importRunId"],
        imported_at=imported_at,
        snapshot_ref=identity["snapshotRef"],
        graph_id=identity["graphId"],
        extractor_id=identity["extractorId"],
        extraction_snapshot=identity["extractionSnapshot"],
        reference_by_external_item_id=reference_by_external_item_id,
    )
    records.append(
        _record_knowledge_import_run(
            identity["importRunId"],
            corpus_id,
            classifier_id,
            identity["snapshotId"],
            imported_at,
            payload,
            relation_count=len(relation_records["records"]),
        )
    )
    records.append(
        {
            "modelName": "KnowledgeArtifact",
            "expected": {
                "id": f"knowledge-artifact-{safe_id(corpus_id)}-{safe_id(identity['extractorId'])}-{safe_id(identity['snapshotId'])}",
                "corpusId": corpus_id,
                "artifactKind": "graph-export",
                "artifactId": identity["snapshotRef"],
                "snapshotId": identity["snapshotId"],
                "displayName": f"Graph export {identity['snapshotRef']}",
                "createdAt": imported_at,
                "importRunId": identity["importRunId"],
            },
        }
    )
    records.append(
        {
            "modelName": "KnowledgeRawPayload",
            "expected": {
                "id": graph_export_summary_payload_id(identity["importRunId"]),
                "ownerType": "importRun",
                "ownerId": identity["importRunId"],
                "payloadKind": "graph-export-summary",
                "importRunId": identity["importRunId"],
                "payload": json.dumps(
                    {
                        "snapshot": identity["snapshotRef"],
                        "graphId": identity["graphId"],
                        "extractorId": identity["extractorId"],
                        "extractionSnapshot": identity["extractionSnapshot"],
                        "stats": payload.get("stats") or {},
                        "nodeCount": len(nodes),
                        "edgeCount": len(edges),
                        "semanticNodeCount": len(materialized_node_by_graph_node_id),
                        "semanticRelationCount": len(relation_records["records"]),
                        "skippedItemNodes": skipped_item_nodes,
                        "unresolvedReferences": relation_records["unresolvedReferences"],
                        "unresolvedReferenceItemIds": relation_records["unresolvedReferenceItemIds"],
                    }
                ),
                "createdAt": imported_at,
                "updatedAt": imported_at,
            },
        }
    )
    records.extend(relation_records["records"])
    return {
        **identity,
        "stats": payload.get("stats") or {},
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "records": records,
        "semanticNodeCount": len(materialized_node_by_graph_node_id),
        "semanticRelationCount": len(relation_records["records"]),
        "skippedItemNodes": skipped_item_nodes,
        "unresolvedReferences": relation_records["unresolvedReferences"],
        "unresolvedReferenceItemIds": relation_records["unresolvedReferenceItemIds"],
        "mentionEdgeCount": relation_records["mentionEdgeCount"],
        "mentionRelationCount": relation_records["mentionRelationCount"],
    }


def graph_generated_import_run_prefix(corpus_id: str) -> str:
    return f"knowledge-import-{safe_id(corpus_id)}-graph-"


def collect_graph_generated_import_run_ids(
    client: PapyrusGraphQLAuthoringClient,
    *,
    corpus_id: str,
    import_run_id: str | None = None,
) -> list[str]:
    prefix = graph_generated_import_run_prefix(corpus_id)
    rows, _ = fetch_graph_artifact_rows_indexed(client, corpus_id=corpus_id)
    run_ids = {str(row["importRunId"]) for row in rows if row.get("importRunId")}
    for run in client.list_knowledge_import_runs_by_corpus_kind_and_imported_at(f"{corpus_id}#graph-export"):
        run_id = _clean_string(run.get("id"))
        if run_id and run_id.startswith(prefix):
            run_ids.add(run_id)
    ordered = sorted(run_ids)
    if import_run_id:
        if import_run_id not in ordered:
            record = client.get_record("KnowledgeImportRun", import_run_id)
            if not record or record.get("corpusId") != corpus_id:
                raise ValueError(
                    f"Graph import run {import_run_id} was not found for corpus {corpus_id}."
                )
            ordered = [import_run_id]
        else:
            ordered = [import_run_id]
    return ordered


def build_graph_generated_purge_plan(
    client: PapyrusGraphQLAuthoringClient,
    *,
    corpus_id: str,
    import_run_id: str | None = None,
) -> dict[str, Any]:
    import_run_ids = collect_graph_generated_import_run_ids(
        client,
        corpus_id=corpus_id,
        import_run_id=import_run_id,
    )
    import_run_id_set = set(import_run_ids)
    prefix = graph_generated_import_run_prefix(corpus_id)
    print(
        f"graph-purge\tplan\tscan\tcorpus={corpus_id}\timportRuns={len(import_run_ids)}",
        flush=True,
    )
    semantic_node_ids: list[str] = []
    for node in client.list_semantic_nodes_by_corpus_and_node_key(corpus_id):
        node_id = _clean_string(node.get("id"))
        node_import_run_id = _clean_string(node.get("importRunId"))
        if not node_id or node.get("versionState") != "current":
            continue
        if not node_import_run_id or (
            node_import_run_id not in import_run_id_set
            and not (not import_run_id and node_import_run_id.startswith(prefix))
        ):
            continue
        semantic_node_ids.append(node_id)
    print(f"graph-purge\tplan\tsemantic-nodes\t{len(semantic_node_ids)}", flush=True)
    semantic_relation_ids: list[str] = []
    for index, run_id in enumerate(import_run_ids, start=1):
        print(
            f"graph-purge\tplan\tscan-relations\timportRun={run_id}\t{index}/{len(import_run_ids)}",
            flush=True,
        )
        for relation in client.list_semantic_relations_by_import_run_and_imported_at(run_id):
            relation_id = _clean_string(relation.get("id"))
            if not relation_id or relation.get("relationState") != "current":
                continue
            semantic_relation_ids.append(relation_id)
    print(f"graph-purge\tplan\tsemantic-relations\t{len(semantic_relation_ids)}", flush=True)
    return {
        "corpusId": corpus_id,
        "importRunIds": import_run_ids,
        "semanticNodeIds": sorted(set(semantic_node_ids)),
        "semanticRelationIds": sorted(set(semantic_relation_ids)),
    }


def apply_graph_generated_purge_plan(
    client: PapyrusGraphQLAuthoringClient,
    plan: dict[str, Any],
    *,
    apply: bool,
) -> dict[str, Any]:
    relation_ids = list(plan.get("semanticRelationIds") or [])
    node_ids = list(plan.get("semanticNodeIds") or [])
    deleted = {"SemanticRelation": 0, "SemanticNode": 0}
    if not apply:
        return {"deleted": deleted, "skipped": {}}
    skipped: dict[str, str] = {}
    try:
        total_relations = len(relation_ids)
        for index, relation_id in enumerate(relation_ids, start=1):
            client.delete_record("SemanticRelation", relation_id)
            deleted["SemanticRelation"] += 1
            if index == 1 or index == total_relations or index % 500 == 0:
                print(
                    f"graph-purge\tapply\trelations\t{index}/{total_relations}",
                    flush=True,
                )
        total_nodes = len(node_ids)
        for index, node_id in enumerate(node_ids, start=1):
            client.delete_record("SemanticNode", node_id)
            deleted["SemanticNode"] += 1
            if index == 1 or index == total_nodes or index % 500 == 0:
                print(
                    f"graph-purge\tapply\tnodes\t{index}/{total_nodes}",
                    flush=True,
                )
    except RuntimeError as error:
        skipped["purge"] = str(error)
    return {"deleted": deleted, "skipped": skipped}


def should_supersede_generated_graph(plan: dict[str, Any]) -> bool:
    return bool(plan.get("semanticNodeCount") or plan.get("semanticRelationCount"))


def build_generated_graph_supersession_changes(
    client: PapyrusGraphQLAuthoringClient,
    *,
    corpus_id: str,
    extractor_id: str,
    import_run_id: str,
    now: str,
) -> list[dict[str, Any]]:
    prefix = f"knowledge-import-{safe_id(corpus_id)}-graph-{safe_id(extractor_id)}-"
    graph_runs = [
        run
        for run in client.list_knowledge_import_runs_by_corpus_kind_and_imported_at(f"{corpus_id}#graph-export")
        if run.get("id") != import_run_id and str(run.get("id") or "").startswith(prefix)
    ]
    nodes = [
        node
        for run in graph_runs
        for node in client.list_semantic_nodes_by_import_run_and_node_key(run["id"])
    ]
    relations = [
        relation
        for run in graph_runs
        for relation in client.list_semantic_relations_by_import_run_and_imported_at(run["id"])
    ]
    changes: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("importRunId") == import_run_id or not str(node.get("importRunId") or "").startswith(prefix):
            continue
        if node.get("versionState") != "current":
            continue
        expected = {
            **node,
            "versionState": "superseded",
            "status": "superseded",
            "changeReason": f"superseded-by-graph-import:{import_run_id}",
            "updatedAt": now,
        }
        changes.append(build_record_change_from_current("SemanticNode", expected, node))
    for relation in relations:
        if relation.get("importRunId") == import_run_id or not str(relation.get("importRunId") or "").startswith(prefix):
            continue
        if relation.get("relationState") != "current":
            continue
        expected = {**relation, "relationState": "superseded", "updatedAt": now}
        changes.append(build_record_change_from_current("SemanticRelation", expected, relation))
    return changes


def plan_graph_artifact_import(
    client: PapyrusGraphQLAuthoringClient,
    import_run_id: str,
    *,
    resolve_existing: bool = True,
    min_mention_count: int | None = None,
    min_reference_count: int | None = None,
) -> dict[str, Any]:
    import_run = client.get_record("KnowledgeImportRun", import_run_id)
    if not import_run:
        raise ValueError(f"KnowledgeImportRun {import_run_id} was not found.")
    if import_run.get("importKind") != "graph-export":
        raise ValueError(f"KnowledgeImportRun {import_run_id} is {import_run.get('importKind')}; expected graph-export.")
    raw_payload_id = graph_export_summary_payload_id(import_run_id)
    attachment = client.get_record(
        "ModelAttachment",
        model_attachment_id("knowledgeRawPayload", raw_payload_id, "graph_export", "graph-export"),
    )
    if not attachment:
        raise ValueError(f"Graph export attachment was not found for import run {import_run_id}.")
    graph_export_artifact = load_graph_export_payload_from_attachment(client, attachment)
    payload = graph_export_artifact["payload"]
    payload, _filter_stats = filter_graph_export_payload_by_entity_popularity(
        payload,
        min_mention_count=min_mention_count,
        min_reference_count=min_reference_count,
    )
    imported_at = import_run.get("importedAt") or import_run.get("generatedAt") or _utc_now()
    reference_by_external_item_id = hydrate_graph_reference_map_sync(client, import_run["corpusId"])
    plan = build_graph_export_import_records(
        payload,
        corpus_id=import_run["corpusId"],
        classifier_id=import_run.get("classifierId"),
        imported_at=imported_at,
        reference_by_external_item_id=reference_by_external_item_id,
    )
    if plan["importRunId"] != import_run["id"]:
        raise ValueError(
            f"Graph export artifact resolves to import run {plan['importRunId']}, not requested import run {import_run['id']}."
        )
    if plan["mentionEdgeCount"] > 0 and plan["mentionRelationCount"] == 0:
        unresolved_ids = [str(value) for value in (plan.get("unresolvedReferenceItemIds") or []) if value]
        unresolved_preview = ", ".join(unresolved_ids[:20])
        unresolved_suffix = f" Unresolved item ids: {unresolved_preview}" if unresolved_preview else ""
        raise ValueError(
            "Graph import could not resolve any accepted References for "
            f"{plan['mentionEdgeCount']} reference-to-entity edge(s).{unresolved_suffix}"
        )
    now = _utc_now()
    supersession_changes = (
        build_generated_graph_supersession_changes(
            client,
            corpus_id=import_run["corpusId"],
            extractor_id=plan["extractorId"],
            import_run_id=plan["importRunId"],
            now=now,
        )
        if should_supersede_generated_graph(plan)
        else []
    )
    if resolve_existing:
        import_changes = build_record_changes_tolerating_optional_models(client, plan["records"])
    else:
        import_changes = [
            {
                "modelName": record["modelName"],
                "expected": record["expected"],
                "current": None,
                "action": "create",
            }
            for record in plan["records"]
        ]
    return {
        "importRun": import_run,
        "attachment": attachment,
        "plan": plan,
        "supersessionChanges": supersession_changes,
        "importChanges": import_changes,
        "changes": [*supersession_changes, *import_changes],
    }


def _graph_export_identity(payload: dict[str, Any], corpus_id: str) -> dict[str, Any]:
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    configuration = manifest.get("configuration") if isinstance(manifest.get("configuration"), dict) else {}
    extractor_id = _clean_string(snapshot.get("extractor_id") or configuration.get("extractor_id")) or "graph"
    snapshot_id = _clean_string(snapshot.get("snapshot_id") or manifest.get("snapshot_id"))
    if not snapshot_id:
        raise ValueError("Graph export is missing snapshot.snapshot_id.")
    snapshot_ref = f"{extractor_id}:{snapshot_id}"
    graph_id = _clean_string(manifest.get("graph_id")) or _clean_string(payload.get("graph_id")) or snapshot_ref
    extraction_snapshot = _clean_string(manifest.get("extraction_snapshot"))
    import_run_id = f"knowledge-import-{safe_id(corpus_id)}-graph-{safe_id(extractor_id)}-{hash_short(snapshot_ref)}"
    return {
        "importRunId": import_run_id,
        "extractorId": extractor_id,
        "snapshotId": snapshot_id,
        "snapshotRef": snapshot_ref,
        "graphId": graph_id,
        "extractionSnapshot": extraction_snapshot,
    }


def _graph_export_publish_counts(
    payload: dict[str, Any],
    reference_by_external_item_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    node_ids: set[str] = set()
    skipped_item_nodes = 0
    graph_node_by_id = {_clean_string(node.get("node_id")): node for node in nodes if _clean_string(node.get("node_id"))}
    for node in nodes:
        node_id = _clean_string(node.get("node_id"))
        if not node_id:
            continue
        if _is_graph_item_node(node):
            skipped_item_nodes += 1
            continue
        node_ids.add(node_id)
    unresolved_references = 0
    unresolved_reference_item_ids_limit = 500
    unresolved_reference_item_ids: list[str] = []
    unresolved_reference_item_ids_seen: set[str] = set()
    mention_edge_count = 0
    for edge in edges:
        src = _clean_string(edge.get("src"))
        dst = _clean_string(edge.get("dst"))
        if not src or not dst:
            continue
        src_node = graph_node_by_id.get(src) or {}
        dst_node = graph_node_by_id.get(dst) or {}
        if not _edge_touches_item_endpoint(edge, src_node=src_node, dst_node=dst_node):
            continue
        mention_edge_count += 1
        source_item_id = _edge_source_item_id(edge, src_node=src_node, dst_node=dst_node)
        if source_item_id and reference_by_external_item_id.get(source_item_id):
            continue
        unresolved_references += 1
        if (
            source_item_id
            and source_item_id not in unresolved_reference_item_ids_seen
            and len(unresolved_reference_item_ids) < unresolved_reference_item_ids_limit
        ):
            unresolved_reference_item_ids_seen.add(source_item_id)
            unresolved_reference_item_ids.append(source_item_id)
    return {
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "semanticNodeCount": len(node_ids),
        "skippedItemNodes": skipped_item_nodes,
        "mentionEdgeCount": mention_edge_count,
        "unresolvedReferences": unresolved_references,
        "unresolvedReferenceItemIds": unresolved_reference_item_ids,
    }


def _build_graph_export_relation_records(
    *,
    edges: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    materialized_node_by_graph_node_id: dict[str, dict[str, Any]],
    corpus_id: str,
    classifier_id: str | None,
    import_run_id: str,
    imported_at: str,
    snapshot_ref: str,
    graph_id: str,
    extractor_id: str,
    extraction_snapshot: str | None,
    reference_by_external_item_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    graph_node_by_id = {_clean_string(node.get("node_id")): node for node in nodes if _clean_string(node.get("node_id"))}
    relation_types = {entry["key"] for entry in load_semantic_relation_type_seeds()}
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    unresolved_references = 0
    unresolved_reference_item_ids_limit = 500
    unresolved_reference_item_ids: list[str] = []
    unresolved_reference_item_ids_seen: set[str] = set()
    mention_edge_count = 0
    mention_relation_count = 0

    for edge in edges:
        src = _clean_string(edge.get("src"))
        dst = _clean_string(edge.get("dst"))
        edge_id = _clean_string(edge.get("edge_id")) or hash_short(edge)
        if not src or not dst:
            continue
        src_node = graph_node_by_id.get(src) or {}
        dst_node = graph_node_by_id.get(dst) or {}
        src_semantic = materialized_node_by_graph_node_id.get(src)
        dst_semantic = materialized_node_by_graph_node_id.get(dst)
        source_item_id = _edge_source_item_id(edge, src_node=src_node, dst_node=dst_node)
        metadata = _graph_relation_metadata(
            edge=edge,
            snapshot_ref=snapshot_ref,
            graph_id=graph_id,
            extractor_id=extractor_id,
            extraction_snapshot=extraction_snapshot,
            source_item_id=source_item_id,
        )
        if _edge_touches_item_endpoint(edge, src_node=src_node, dst_node=dst_node):
            mention_edge_count += 1
            entity_node = src_semantic or dst_semantic
            if not entity_node:
                continue
            reference = reference_by_external_item_id.get(source_item_id) if source_item_id else None
            if not reference:
                unresolved_references += 1
                if (
                    source_item_id
                    and source_item_id not in unresolved_reference_item_ids_seen
                    and len(unresolved_reference_item_ids) < unresolved_reference_item_ids_limit
                ):
                    unresolved_reference_item_ids_seen.add(source_item_id)
                    unresolved_reference_item_ids.append(source_item_id)
                continue
            relation = _graph_semantic_relation_record(
                id_parts=[snapshot_ref, source_item_id, edge_id, "mentions"],
                predicate="mentions",
                subject_kind="reference",
                subject_id=reference["id"],
                subject_lineage_id=reference.get("lineageId") or reference["id"],
                subject_version_number=reference.get("versionNumber"),
                object_kind="semanticNode",
                object_id=entity_node["id"],
                object_lineage_id=entity_node["lineageId"],
                object_version_number=entity_node.get("versionNumber") or 1,
                score=_number_or_null(edge.get("weight")),
                classifier_id=classifier_id,
                source_snapshot_id=snapshot_ref,
                import_run_id=import_run_id,
                imported_at=imported_at,
                metadata=metadata,
            )
            if relation["id"] not in seen:
                records.append({"modelName": "SemanticRelation", "expected": relation})
                seen.add(relation["id"])
                mention_relation_count += 1
            continue
        if not src_semantic or not dst_semantic:
            continue
        normalized_edge_type = normalize_relation_type_key(edge.get("edge_type"))
        predicate = normalized_edge_type if normalized_edge_type in relation_types else "related_to"
        relation = _graph_semantic_relation_record(
            id_parts=[snapshot_ref, source_item_id, edge_id, predicate],
            predicate=predicate,
            subject_kind="semanticNode",
            subject_id=src_semantic["id"],
            subject_lineage_id=src_semantic["lineageId"],
            subject_version_number=src_semantic.get("versionNumber") or 1,
            object_kind="semanticNode",
            object_id=dst_semantic["id"],
            object_lineage_id=dst_semantic["lineageId"],
            object_version_number=dst_semantic.get("versionNumber") or 1,
            score=_number_or_null(edge.get("weight")),
            classifier_id=classifier_id,
            source_snapshot_id=snapshot_ref,
            import_run_id=import_run_id,
            imported_at=imported_at,
            metadata=metadata,
        )
        if relation["id"] not in seen:
            records.append({"modelName": "SemanticRelation", "expected": relation})
            seen.add(relation["id"])
    return {
        "records": records,
        "unresolvedReferences": unresolved_references,
        "unresolvedReferenceItemIds": unresolved_reference_item_ids,
        "mentionEdgeCount": mention_edge_count,
        "mentionRelationCount": mention_relation_count,
    }


def _record_knowledge_import_run(
    import_run_id: str,
    corpus_id: str,
    classifier_id: str | None,
    source_snapshot_id: str,
    imported_at: str,
    payload: dict[str, Any],
    *,
    relation_count: int,
) -> dict[str, Any]:
    stats = payload.get("stats") or {}
    item_count = int(stats.get("items_processed") or stats.get("items_total") or 0)
    return {
        "modelName": "KnowledgeImportRun",
        "expected": {
            "id": import_run_id,
            "corpusId": corpus_id,
            "importKind": "graph-export",
            "corpusImportKindKey": f"{corpus_id}#graph-export",
            "classifierId": classifier_id,
            "sourceSnapshotId": source_snapshot_id,
            "status": "imported",
            "generatedAt": imported_at,
            "importedAt": imported_at,
            "itemCount": item_count,
            "categoryCount": 0,
            "proposalCount": 0,
            "artifactCount": 1,
            "referenceCount": 0,
            "relationCount": relation_count,
            "warningCount": 0,
        },
    }


def _graph_semantic_relation_record(
    *,
    id_parts: list[Any],
    predicate: str,
    subject_kind: str,
    subject_id: str,
    subject_lineage_id: str,
    subject_version_number: Any,
    object_kind: str,
    object_id: str,
    object_lineage_id: str,
    object_version_number: Any,
    score: float | None,
    classifier_id: str | None,
    source_snapshot_id: str,
    import_run_id: str,
    imported_at: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    subject_state_key = semantic_state_key(subject_kind, subject_lineage_id)
    object_state_key = semantic_state_key(object_kind, object_lineage_id)
    subject_version_key = f"{subject_kind}#{subject_id}"
    object_version_key = f"{object_kind}#{object_id}"
    return {
        "id": f"semantic-relation-{hash_short(id_parts)}",
        "relationState": "current",
        "predicate": predicate,
        **semantic_relation_type_fields_for_predicate(predicate),
        "subjectKind": subject_kind,
        "subjectId": subject_id,
        "subjectLineageId": subject_lineage_id,
        "subjectVersionNumber": subject_version_number,
        "objectKind": object_kind,
        "objectId": object_id,
        "objectLineageId": object_lineage_id,
        "objectVersionNumber": object_version_number,
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#{subject_kind}",
        "predicateObjectStateKey": f"{predicate}#{object_state_key}",
        "subjectVersionKey": subject_version_key,
        "objectVersionKey": object_version_key,
        "score": score,
        "confidence": None,
        "rank": 1,
        "classifierId": classifier_id,
        "modelVersion": None,
        "reviewRecommended": False,
        "sourceSnapshotId": source_snapshot_id,
        "importRunId": import_run_id,
        "importedAt": imported_at,
        "createdAt": imported_at,
        "updatedAt": imported_at,
        "newsroomFeedKey": "semanticRelations",
        "metadata": json.dumps(metadata),
    }


def _graph_relation_metadata(
    *,
    edge: dict[str, Any],
    snapshot_ref: str,
    graph_id: str,
    extractor_id: str,
    extraction_snapshot: str | None,
    source_item_id: str | None,
) -> dict[str, Any]:
    properties = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    return {
        "kind": "graph.imported_relation",
        "graphSnapshot": snapshot_ref,
        "graphId": graph_id,
        "extractorId": extractor_id,
        "extractionSnapshot": extraction_snapshot,
        "sourceItemId": source_item_id,
        "edgeId": edge.get("edge_id"),
        "edgeType": edge.get("edge_type"),
        "properties": properties,
    }


def _is_graph_item_node(node: dict[str, Any]) -> bool:
    node_type = _clean_string(node.get("node_type"))
    node_id = _clean_string(node.get("node_id"))
    return (
        node_type in {"item", "reference"}
        or (node_id or "").startswith("item:")
        or (node_id or "").startswith("reference:")
    )


def _edge_touches_item_endpoint(
    edge: dict[str, Any],
    *,
    src_node: dict[str, Any],
    dst_node: dict[str, Any],
) -> bool:
    if _is_graph_item_node(src_node) or _is_graph_item_node(dst_node):
        return True
    if _clean_string(edge.get("edge_type")) == "mentions":
        return True
    src = _clean_string(edge.get("src")) or ""
    dst = _clean_string(edge.get("dst")) or ""
    return (
        src.startswith("item:")
        or src.startswith("reference:")
        or dst.startswith("item:")
        or dst.startswith("reference:")
    )


def _edge_source_item_id(
    edge: dict[str, Any],
    *,
    src_node: dict[str, Any],
    dst_node: dict[str, Any],
) -> str | None:
    direct = _clean_string(edge.get("item_id"))
    if direct:
        return direct
    from_node = _graph_item_id_from_node(src_node) or _graph_item_id_from_node(dst_node)
    if from_node:
        return from_node
    src = _clean_string(edge.get("src")) or ""
    dst = _clean_string(edge.get("dst")) or ""
    if src.startswith("item:") or src.startswith("reference:"):
        return _strip_graph_node_prefix(src, "item:") or _strip_graph_node_prefix(src, "reference:")
    if dst.startswith("item:") or dst.startswith("reference:"):
        return _strip_graph_node_prefix(dst, "item:") or _strip_graph_node_prefix(dst, "reference:")
    return None


def _entity_graph_node_id_for_mention_edge(
    edge: dict[str, Any],
    *,
    src_node: dict[str, Any],
    dst_node: dict[str, Any],
    graph_node_by_id: dict[str, dict[str, Any]],
) -> str | None:
    src = _clean_string(edge.get("src"))
    dst = _clean_string(edge.get("dst"))
    if not src or not dst:
        return None
    if _is_graph_item_node(src_node) and not _is_graph_item_node(dst_node):
        return dst
    if _is_graph_item_node(dst_node) and not _is_graph_item_node(src_node):
        return src
    if src.startswith("item:") or src.startswith("reference:"):
        return dst if dst in graph_node_by_id or not dst.startswith("item:") else dst
    if dst.startswith("item:") or dst.startswith("reference:"):
        return src if src in graph_node_by_id or not src.startswith("item:") else src
    return None


def _graph_item_id_from_node(node: dict[str, Any]) -> str | None:
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return (
        _clean_string(properties.get("item_id"))
        or _clean_string(properties.get("reference_id"))
        or _strip_graph_node_prefix(node.get("node_id"), "item:")
        or _strip_graph_node_prefix(node.get("node_id"), "reference:")
    )


def _strip_graph_node_prefix(value: Any, prefix: str) -> str | None:
    normalized = _clean_string(value)
    if normalized and normalized.startswith(prefix):
        return normalized[len(prefix) :]
    return None


def _normalize_graph_node_kind(value: Any) -> str:
    normalized = normalize_relation_type_key(str(value or ""))
    if not normalized:
        return "entity"
    if normalized in {"item", "reference"}:
        return "entity"
    return normalized


def _graph_node_description(node: dict[str, Any]) -> str | None:
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    entity_type = _clean_string(properties.get("entity_type") or properties.get("kind"))
    node_type = _clean_string(node.get("node_type"))
    parts = [part for part in [node_type, entity_type] if part]
    return ": ".join(parts) if parts else None


def _graph_node_aliases(node: dict[str, Any]) -> list[str]:
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    canonical = _clean_string(properties.get("canonical"))
    if canonical and canonical != node.get("label"):
        return [canonical]
    return []


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _positive_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _number_or_null(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
