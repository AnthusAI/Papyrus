from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .concept_link_predicates import MENTIONS, is_reference_concept_link
from .env import PAPYRUS_ROOT
from .graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from .ids import hash_short, hash_stable, safe_id
from .model_attachments import (
    attachment_record,
    build_json_model_payload_attachment,
    download_attachment_buffer,
    semantic_version_key,
)
from .options import parse_options, resolve_mutation_apply
from .records import apply_record_changes, build_record_changes
from .relation_types import semantic_relation_type_fields_for_predicate
from .relations_commands import print_category_import_summary

RELATION_EXPLANATION_ROLE = "ontology_relation_explanation"
CONCEPT_PROFILE_ROLE = "ontology_concept_profile"
RELATION_EXPLANATION_PROMPT_VERSION = "ontology-relation-explanation-v1"
CONCEPT_PROFILE_PROMPT_VERSION = "ontology-concept-profile-v1"
RELATION_EXPLAINER_PROCEDURE = "procedures/newsroom/ontology_relationship_explainer.tac"
CONCEPT_PROFILER_PROCEDURE = "procedures/newsroom/ontology_concept_profiler.tac"
OPERATIONAL_RELATION_TYPES = {
    "comment",
    "ingestion_rationale",
    "requests_work_on",
    "produces",
    "blocked_by",
    "planned_for_edition",
    "targets_lane",
    "targets_section",
}
RELATION_WEIGHTS = {
    "mentions": 2.0,
    "note_about": 2.0,
    "classified_as": 1.4,
    "authoritative_label": 1.6,
    "scoped_to_topic": 1.4,
    "broader_than": 1.2,
    "narrower_than": 1.2,
    "supports": 1.0,
    "contradicts": 1.0,
    "related_to": 0.35,
}
DEDUP_RELATION_KEYS = {"same_as", "alias_of"}
ASSOCIATION_CONFIDENCE_THRESHOLD = 0.86
DEDUPE_CONFIDENCE_THRESHOLD = 0.92
SUPPORTED_CONTEXT_MODELS = [
    "Reference",
    "ReferenceAttachment",
    "Message",
    "Assignment",
    "AssignmentEvent",
    "Item",
    "Category",
    "CategorySet",
    "SemanticNode",
    "SemanticRelation",
    "SteeringProposal",
    "NewsroomSection",
]
FAST_CONTEXT_MODELS = [
    "SemanticNode",
    "SemanticRelation",
]
MODEL_TO_KIND = {
    "Reference": "reference",
    "ReferenceAttachment": "referenceAttachment",
    "Message": "message",
    "Assignment": "assignment",
    "AssignmentEvent": "assignmentEvent",
    "Item": "item",
    "Category": "category",
    "CategorySet": "categorySet",
    "SemanticNode": "semanticNode",
    "SemanticRelation": "semanticRelation",
    "SteeringProposal": "steeringProposal",
    "NewsroomSection": "newsroomSection",
}
KIND_TO_MODEL = {value: key for key, value in MODEL_TO_KIND.items()}


def ontology_rank(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(
        client,
        include_attachment_payloads=True,
        model_names=_ontology_model_scope(options),
    )
    ranked = rank_concepts(state, include_operational=bool(options.get("include-operational")), include_profile_status=False)
    limit = _int_option(options, "limit", 100)
    top = [dict(row) for row in ranked[:limit]]
    if top and not options.get("skip-freshness"):
        nodes_by_id = {str(node.get("id")): node for node in current_semantic_nodes(state)}
        scoped_nodes = [nodes_by_id[str(row.get("id"))] for row in top if str(row.get("id")) in nodes_by_id]
        status_by_id = {
            str(entry["concept"].get("id")): entry.get("status", "missing")
            for entry in concept_profile_status(state, scoped_nodes)
        }
        for row in top:
            row["profileStatus"] = status_by_id.get(str(row.get("id")), row.get("profileStatus", "unknown"))
    payload = {"ok": True, "concepts": top, "totalConcepts": len(ranked)}
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"ontology-rank\tconcepts\t{len(ranked)}")
    for index, row in enumerate(payload["concepts"], start=1):
        print(
            "ontology-rank\t"
            f"{index}\t{row['score']:.8f}\t{row.get('nodeKey') or '-'}\t"
            f"{row.get('displayName') or row.get('id')}\tmentions={row.get('acceptedReferenceMentions', 0)}\t"
            f"freshness={row.get('profileStatus', 'unknown')}"
        )


def ontology_recompute_authority(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(
        client,
        include_attachment_payloads=False,
        model_names=_ontology_model_scope(options),
    )
    ranked = rank_concepts(
        state,
        include_operational=bool(options.get("include-operational")),
        include_profile_status=False,
    )
    scoped = scoped_ranked_concepts(state, ranked, options)
    apply = resolve_mutation_apply(options, "knowledge ontology recompute-authority")
    records = build_concept_authority_records(state, scoped)
    result = apply_or_report(client, "ontology-recompute-authority", records, apply=apply)
    limit = _int_option(options, "limit", 25)
    top = scoped[:limit] if limit else scoped
    payload = {
        "ok": True,
        "mode": "apply" if apply else "dry-run",
        "plannedRecords": len(records),
        "changedRecords": result["changedRecords"],
        "totalConcepts": len(scoped),
        "concepts": top,
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"ontology-recompute-authority\tmode\t{payload['mode']}")
    print(f"ontology-recompute-authority\ttotal-concepts\t{payload['totalConcepts']}")
    print(f"ontology-recompute-authority\tplanned-records\t{payload['plannedRecords']}")
    print(f"ontology-recompute-authority\tchanged-records\t{payload['changedRecords']}")
    for row in top:
        print(
            "ontology-recompute-authority\t"
            f"rank={row.get('authorityRank')}\t"
            f"score={float(row.get('score') or 0.0):.8f}\t"
            f"{row.get('nodeKey') or row.get('id')}\t"
            f"mentions={row.get('acceptedReferenceMentions', 0)}\t"
            f"relations={row.get('relationCount', 0)}"
        )


def ontology_status(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(
        client,
        include_attachment_payloads=True,
        model_names=_ontology_model_scope(options),
    )
    ranked = (
        rank_concepts(state, include_operational=bool(options.get("include-operational")), include_profile_status=False)
        if options.get("ranked")
        else []
    )
    limit = _int_option(options, "limit", 100)
    relation_scope = select_relation_scope(state, ranked, options, limit=limit)
    concept_scope = select_concept_scope(state, ranked, options, limit=limit)
    relation_status = relation_explanation_status(state, relation_scope)
    concept_status = concept_profile_status(state, concept_scope)
    payload = ontology_status_payload(relation_status, concept_status, ranked=ranked[:limit])
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print_status_summary(payload)


def ontology_preflight(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    checks = run_preflight_checks(client)
    payload = {"ok": all(check["ok"] for check in checks), "checks": checks}
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    for check in checks:
        print(f"ontology-preflight\t{check['status']}\t{check['name']}\t{check.get('detail') or '-'}")
    if not payload["ok"]:
        raise RuntimeError("Ontology enrichment preflight failed.")


def ontology_explain(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(client, include_attachment_payloads=True)
    ranked = rank_concepts(state, include_operational=bool(options.get("include-operational"))) if options.get("ranked") else []
    limit = _int_option(options, "limit", 50)
    relations = select_relation_scope(state, ranked, options, limit=limit)
    statuses = relation_explanation_status(state, relations)
    targets = [entry for entry in statuses if entry["status"] in {"missing", "stale"} or options.get("force")]
    if limit:
        targets = targets[:limit]
    use_llm = not bool(options.get("no-llm"))
    apply = resolve_mutation_apply(options, "knowledge ontology explain")
    records: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for index, status in enumerate(targets, start=1):
        relation = status["relation"]
        context = build_relation_context(state, relation, input_fingerprint=status["inputFingerprint"])
        relation_id = str(relation.get("id") or "")
        try:
            output = run_relationship_explainer(context, use_llm=use_llm, dry_run=not apply)
        except Exception as error:
            _emit_ontology_llm_failure(
                command="ontology-explain",
                target_kind="relation",
                target_id=relation_id,
                error=error,
                next_commands=[
                    f"poetry run papyrus knowledge ontology explain --relation-id {relation_id} --no-llm",
                    f"poetry run papyrus knowledge ontology explain --relation-id {relation_id}",
                ],
            )
            raise
        outputs.append({"relationId": relation["id"], "output": output, "inputFingerprint": status["inputFingerprint"]})
        records.extend(build_relation_explanation_records(relation, context, output, now=_utc_now()))
        _ontology_progress(
            "ontology-explain",
            "progress",
            f"{index}/{len(targets)}",
            f"{relation_id}\tconfidence={output.get('confidence')}\tllm={'yes' if use_llm else 'no'}",
        )
    result = apply_or_report(client, "ontology-relation-explanations", records, apply=apply)
    payload = {
        "ok": True,
        "mode": "apply" if apply else "dry-run",
        "selectedRelations": len(relations),
        "targetRelations": len(targets),
        "recordChanges": result["changedRecords"],
        "outputs": outputs,
        "changes": result.get("changes", []),
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"ontology-explain\tmode\t{payload['mode']}")
    print(f"ontology-explain\tselected-relations\t{payload['selectedRelations']}")
    print(f"ontology-explain\ttarget-relations\t{payload['targetRelations']}")
    print(f"ontology-explain\tchanged-records\t{payload['recordChanges']}")


def ontology_profile(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(client, include_attachment_payloads=True)
    ranked = rank_concepts(state, include_operational=bool(options.get("include-operational"))) if options.get("ranked") else []
    limit = _int_option(options, "limit", 50)
    concepts = select_concept_scope(state, ranked, options, limit=limit)
    statuses = concept_profile_status(state, concepts)
    targets = [entry for entry in statuses if entry["status"] in {"missing", "stale"} or options.get("force")]
    if not options.get("force"):
        targets = [entry for entry in targets if entry.get("missingRelationExplanations", 0) == 0]
    if limit:
        targets = targets[:limit]
    use_llm = not bool(options.get("no-llm"))
    apply = resolve_mutation_apply(options, "knowledge ontology profile")
    records: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    for index, status in enumerate(targets, start=1):
        concept = status["concept"]
        context = build_concept_context(state, concept, input_fingerprint=status["inputFingerprint"])
        concept_id = str(concept.get("id") or "")
        try:
            output = run_concept_profiler(context, use_llm=use_llm, dry_run=not apply)
        except Exception as error:
            _emit_ontology_llm_failure(
                command="ontology-profile",
                target_kind="concept",
                target_id=concept_id,
                error=error,
                next_commands=[
                    f"poetry run papyrus knowledge ontology profile --concept-id {concept_id} --no-llm",
                    f"poetry run papyrus knowledge ontology profile --concept-id {concept_id}",
                ],
            )
            raise
        outputs.append({"conceptId": concept["id"], "output": output, "inputFingerprint": status["inputFingerprint"]})
        records.extend(build_concept_profile_records(concept, context, output, now=_utc_now()))
        _ontology_progress(
            "ontology-profile",
            "progress",
            f"{index}/{len(targets)}",
            f"{concept_id}\tconfidence={output.get('confidence')}\tllm={'yes' if use_llm else 'no'}",
        )
    result = apply_or_report(client, "ontology-concept-profiles", records, apply=apply)
    payload = {
        "ok": True,
        "mode": "apply" if apply else "dry-run",
        "selectedConcepts": len(concepts),
        "targetConcepts": len(targets),
        "recordChanges": result["changedRecords"],
        "outputs": outputs,
        "changes": result.get("changes", []),
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"ontology-profile\tmode\t{payload['mode']}")
    print(f"ontology-profile\tselected-concepts\t{payload['selectedConcepts']}")
    print(f"ontology-profile\ttarget-concepts\t{payload['targetConcepts']}")
    print(f"ontology-profile\tchanged-records\t{payload['recordChanges']}")


def ontology_associate(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(client, include_attachment_payloads=True)
    ranked = rank_concepts(state, include_operational=bool(options.get("include-operational"))) if options.get("ranked") else []
    concepts = select_concept_scope(state, ranked, options, limit=_int_option(options, "limit", 50))
    records = build_association_relation_records(state, concepts, threshold=_float_option(options, "threshold", ASSOCIATION_CONFIDENCE_THRESHOLD))
    apply = resolve_mutation_apply(options, "knowledge ontology associate")
    result = apply_or_report(client, "ontology-associations", records, apply=apply)
    payload = {"ok": True, "plannedRelations": len(records), **result}
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"ontology-associate\tplanned-relations\t{len(records)}")
    print(f"ontology-associate\tchanged-records\t{result['changedRecords']}")


def ontology_dedupe(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(client, include_attachment_payloads=True)
    ranked = rank_concepts(state, include_operational=bool(options.get("include-operational"))) if options.get("ranked") else []
    concepts = select_concept_scope(state, ranked, options, limit=_int_option(options, "limit", 50))
    records = build_dedupe_relation_records(state, concepts, threshold=_float_option(options, "threshold", DEDUPE_CONFIDENCE_THRESHOLD))
    apply = resolve_mutation_apply(options, "knowledge ontology dedupe")
    result = apply_or_report(client, "ontology-dedupe", records, apply=apply)
    payload = {"ok": True, "plannedRelations": len(records), **result}
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"ontology-dedupe\tplanned-relations\t{len(records)}")
    print(f"ontology-dedupe\tchanged-records\t{result['changedRecords']}")


def ontology_doctor(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    state = load_ontology_state(
        client,
        include_attachment_payloads=True,
        model_names=_ontology_model_scope(options),
    )
    ranked = rank_concepts(state, include_profile_status=False)
    relation_status = relation_explanation_status(state, current_relations(state))
    concept_status = concept_profile_status(state, current_semantic_nodes(state))
    payload = ontology_status_payload(relation_status, concept_status, ranked=ranked[: _int_option(options, "limit", 20)])
    payload["nextRecommendedCommand"] = next_recommended_command(payload)
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print_status_summary(payload)
    print(f"ontology-doctor\tnext\t{payload['nextRecommendedCommand']}")


def load_ontology_state(
    client: PapyrusGraphQLAuthoringClient,
    *,
    include_attachment_payloads: bool = False,
    model_names: list[str] | None = None,
) -> dict[str, Any]:
    models: dict[str, list[dict[str, Any]]] = {}
    requested_models = [*model_names] if model_names else [*SUPPORTED_CONTEXT_MODELS]
    requested_models.extend(["ModelAttachment", "SemanticRelationType"])
    for model_name in requested_models:
        _ontology_progress("ontology-state", "model-load", "start", model_name)
        models[model_name] = client.safe_list_records(model_name)
        _ontology_progress("ontology-state", "model-load", "done", f"{model_name}\trows={len(models[model_name])}")
    state = build_state_indexes(models)
    state["corpusText"] = resolve_corpus_text_provider()
    state["attachmentPayloadClient"] = client
    if include_attachment_payloads:
        _ontology_progress("ontology-state", "attachment-payloads", "start", f"attachments={len(state['attachments'])}")
        state["attachmentPayloads"] = load_attachment_payloads(client, state["attachments"])
        _ontology_progress("ontology-state", "attachment-payloads", "done", f"loaded={len(state['attachmentPayloads'])}")
    else:
        state["attachmentPayloads"] = {}
    _ontology_progress("ontology-state", "ready", "ok")
    return state


def build_state_indexes(models: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    by_model_id = {
        model_name: {str(row.get("id")): row for row in rows if row.get("id")}
        for model_name, rows in models.items()
    }
    attachments = models.get("ModelAttachment", [])
    attachments_by_owner_role: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for attachment in attachments:
        key = (str(attachment.get("ownerKind") or ""), str(attachment.get("ownerId") or ""), str(attachment.get("role") or ""))
        attachments_by_owner_role[key].append(attachment)
    for values in attachments_by_owner_role.values():
        values.sort(key=lambda item: str(item.get("sortKey") or ""))
    relation_types = {
        str(row.get("key") or ""): row
        for row in models.get("SemanticRelationType", [])
        if row.get("key")
    }
    return {
        "models": models,
        "byModelId": by_model_id,
        "attachments": attachments,
        "attachmentsByOwnerRole": attachments_by_owner_role,
        "attachmentPayloads": {},
        "relationTypes": relation_types,
    }


def load_attachment_payloads(client: PapyrusGraphQLAuthoringClient, attachments: list[dict[str, Any]]) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    relevant = [
        attachment for attachment in attachments
        if attachment.get("role") in {RELATION_EXPLANATION_ROLE, CONCEPT_PROFILE_ROLE}
        and attachment.get("status") not in {"deleted", "aborted"}
    ]
    total = len(relevant)
    for index, attachment in enumerate(relevant, start=1):
        payload = parse_attachment_payload(client, attachment)
        if isinstance(payload, dict):
            payloads[str(attachment["id"])] = payload
        if index == 1 or index % 25 == 0 or index == total:
            _ontology_progress("ontology-state", "attachment-payloads", "progress", f"{index}/{total}\tloaded={len(payloads)}")
    return payloads


def current_semantic_nodes(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        node for node in state["models"].get("SemanticNode", [])
        if node.get("versionState") == "current" and node.get("status") not in {"deleted", "archived", "rejected"}
    ]


def current_relations(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        relation for relation in state["models"].get("SemanticRelation", [])
        if relation.get("relationState") in {None, "", "current"}
    ]


def rank_concepts(
    state: dict[str, Any],
    *,
    include_operational: bool = False,
    include_profile_status: bool = True,
) -> list[dict[str, Any]]:
    nodes = current_semantic_nodes(state)
    node_lineages = {str(node.get("lineageId") or node.get("id")) for node in nodes}
    graph_nodes: set[str] = {f"semanticNode#{lineage}" for lineage in node_lineages if lineage}
    weighted_edges: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    mentions_by_node: dict[str, set[str]] = defaultdict(set)
    source_kinds_by_node: dict[str, set[str]] = defaultdict(set)
    relation_count_by_node: dict[str, int] = defaultdict(int)
    for relation in current_relations(state):
        relation_key = relation_type_key(relation)
        if not include_operational and relation_key in OPERATIONAL_RELATION_TYPES:
            continue
        subject_kind = str(relation.get("subjectKind") or "")
        object_kind = str(relation.get("objectKind") or "")
        subject_lineage = str(relation.get("subjectLineageId") or relation.get("subjectId") or "")
        object_lineage = str(relation.get("objectLineageId") or relation.get("objectId") or "")
        if not subject_kind or not object_kind or not subject_lineage or not object_lineage:
            continue
        subject_ref = f"{subject_kind}#{subject_lineage}"
        object_ref = f"{object_kind}#{object_lineage}"
        graph_nodes.add(subject_ref)
        graph_nodes.add(object_ref)
        weight = relation_weight(relation_key)
        if is_reference_concept_link(relation_key, subject_kind, object_kind):
            weight = max(weight, RELATION_WEIGHTS[MENTIONS])
        weighted_edges[subject_ref][object_ref] += weight
        if relation_key in {"related_to", "same_as"}:
            weighted_edges[object_ref][subject_ref] += weight
        if object_kind == "semanticNode" and object_lineage in node_lineages:
            relation_count_by_node[object_lineage] += 1
            source_kinds_by_node[object_lineage].add(subject_kind)
            if is_reference_concept_link(relation_key, subject_kind, object_kind):
                mentions_by_node[object_lineage].add(subject_lineage)
        if subject_kind == "semanticNode" and subject_lineage in node_lineages:
            relation_count_by_node[subject_lineage] += 1
            source_kinds_by_node[subject_lineage].add(object_kind)
    pagerank = compute_pagerank(graph_nodes, weighted_edges)
    profile_status_by_id: dict[str, str] = {}
    if include_profile_status:
        profile_status_by_id = {
            str(entry["concept"].get("id")): str(entry.get("status") or "missing")
            for entry in concept_profile_status(state, nodes)
        }
    ranked: list[dict[str, Any]] = []
    for node in nodes:
        lineage_id = str(node.get("lineageId") or node.get("id") or "")
        ref = f"semanticNode#{lineage_id}"
        accepted_mentions = len(mentions_by_node.get(lineage_id, set()))
        distinct_source_kinds = len(source_kinds_by_node.get(lineage_id, set()))
        relation_count = relation_count_by_node.get(lineage_id, 0)
        if include_profile_status:
            freshness_boost = {"missing": 0.12, "stale": 0.08, "fresh": 0.0}.get(
                profile_status_by_id.get(str(node.get("id"))),
                0.05,
            )
        else:
            freshness_boost = 0.05
        score = pagerank.get(ref, 0.0) + accepted_mentions * 0.003 + distinct_source_kinds * 0.01 + relation_count * 0.0005 + freshness_boost
        ranked.append(
            {
                "id": node.get("id"),
                "lineageId": lineage_id,
                "nodeKey": node.get("nodeKey"),
                "nodeKind": node.get("nodeKind"),
                "displayName": node.get("displayName"),
                "score": score,
                "pageRank": pagerank.get(ref, 0.0),
                "acceptedReferenceMentions": accepted_mentions,
                "distinctSourceKinds": distinct_source_kinds,
                "relationCount": relation_count,
                "profileStatus": profile_status_by_id.get(str(node.get("id")), "missing"),
            }
        )
    return sorted(ranked, key=lambda row: (-float(row["score"]), str(row.get("nodeKey") or row.get("id") or "")))


def scoped_ranked_concepts(
    state: dict[str, Any],
    ranked: list[dict[str, Any]],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    global_ranked = [dict(row, authorityRank=index) for index, row in enumerate(ranked, start=1)]
    by_id = {str(row.get("id")): row for row in global_ranked if row.get("id")}
    by_lineage = {str(row.get("lineageId")): row for row in global_ranked if row.get("lineageId")}
    by_node_key = {str(row.get("nodeKey")): row for row in global_ranked if row.get("nodeKey")}
    node_by_lineage = {
        str(node.get("lineageId") or node.get("id") or ""): node
        for node in current_semantic_nodes(state)
        if node.get("lineageId") or node.get("id")
    }
    scoped: list[dict[str, Any]] = []
    requested_ids = _list_option(options, "concept-id") or _list_option(options, "concept")
    requested_lineages = _list_option(options, "lineage-id")
    requested_keys = _list_option(options, "node-key")
    requested_corpora = set(_list_option(options, "corpus-id"))
    if requested_ids or requested_lineages or requested_keys:
        for value in [*requested_ids, *requested_lineages, *requested_keys]:
            row = by_id.get(value) or by_lineage.get(value) or by_node_key.get(value)
            if row and row not in scoped:
                scoped.append(row)
    elif requested_corpora:
        for row in global_ranked:
            lineage_id = str(row.get("lineageId") or "")
            node = node_by_lineage.get(lineage_id)
            if node and str(node.get("corpusId") or "") in requested_corpora:
                scoped.append(row)
    else:
        scoped = list(global_ranked)
    return sorted(scoped, key=lambda row: int(row.get("authorityRank") or 0))


def build_concept_authority_records(state: dict[str, Any], ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes_by_id = {str(node.get("id")): node for node in current_semantic_nodes(state) if node.get("id")}
    records: list[dict[str, Any]] = []
    for row in ranked:
        node_id = str(row.get("id") or "")
        node = nodes_by_id.get(node_id)
        if not node:
            continue
        expected = dict(node)
        expected["authorityScore"] = float(row.get("score") or 0.0)
        expected["authorityRank"] = int(row.get("authorityRank") or 0)
        expected["acceptedReferenceMentionCount"] = int(row.get("acceptedReferenceMentions") or 0)
        expected["distinctSourceKindCount"] = int(row.get("distinctSourceKinds") or 0)
        expected["relationCount"] = int(row.get("relationCount") or 0)
        records.append({"modelName": "SemanticNode", "expected": expected})
    return records


def compute_pagerank(nodes: set[str], edges: dict[str, dict[str, float]], *, damping: float = 0.85, iterations: int = 32) -> dict[str, float]:
    if not nodes:
        return {}
    node_list = sorted(nodes)
    n = len(node_list)
    ranks = {node: 1.0 / n for node in node_list}
    base = (1.0 - damping) / n
    for _ in range(iterations):
        next_ranks = {node: base for node in node_list}
        dangling_total = 0.0
        for node in node_list:
            outgoing = edges.get(node) or {}
            total_weight = sum(max(0.0, weight) for weight in outgoing.values())
            if total_weight <= 0:
                dangling_total += ranks[node]
                continue
            for target, weight in outgoing.items():
                if target in next_ranks and weight > 0:
                    next_ranks[target] += damping * ranks[node] * (weight / total_weight)
        dangling_share = damping * dangling_total / n
        ranks = {node: value + dangling_share for node, value in next_ranks.items()}
    return ranks


def relation_weight(relation_key: str) -> float:
    if relation_key in RELATION_WEIGHTS:
        return RELATION_WEIGHTS[relation_key]
    if relation_key.endswith("_identifier_is") or relation_key == "digital_object_identifier_is":
        return 0.8
    return 0.75


def select_relation_scope(state: dict[str, Any], ranked: list[dict[str, Any]], options: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    relations_by_id = {str(relation.get("id")): relation for relation in current_relations(state)}
    explicit_ids = _list_option(options, "relation-id") or _list_option(options, "relation")
    if explicit_ids:
        return [relations_by_id[value] for value in explicit_ids if value in relations_by_id]
    concept_ids = set(_list_option(options, "concept-id") or _list_option(options, "concept"))
    if ranked:
        ranked_lineages = {str(row.get("lineageId")) for row in ranked[:limit] if row.get("lineageId")}
        concept_ids |= {str(row.get("id")) for row in ranked[:limit] if row.get("id")}
    else:
        ranked_lineages = set()
    selected: list[dict[str, Any]] = []
    for relation in current_relations(state):
        touches_explicit = (
            relation.get("subjectId") in concept_ids
            or relation.get("objectId") in concept_ids
            or relation.get("subjectLineageId") in ranked_lineages
            or relation.get("objectLineageId") in ranked_lineages
        )
        if concept_ids or ranked_lineages:
            if not touches_explicit:
                continue
        if not options.get("include-operational") and relation_type_key(relation) in OPERATIONAL_RELATION_TYPES:
            continue
        selected.append(relation)
    selected.sort(key=lambda relation: relation_priority_sort_key(relation, ranked))
    return selected[:limit] if limit else selected


def relation_priority_sort_key(relation: dict[str, Any], ranked: list[dict[str, Any]]) -> tuple[float, str]:
    scores = {str(row.get("lineageId")): float(row.get("score") or 0) for row in ranked}
    score = max(scores.get(str(relation.get("subjectLineageId")), 0.0), scores.get(str(relation.get("objectLineageId")), 0.0))
    return (-score, str(relation.get("id") or ""))


def select_concept_scope(state: dict[str, Any], ranked: list[dict[str, Any]], options: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    nodes_by_id = {str(node.get("id")): node for node in current_semantic_nodes(state)}
    ids = _list_option(options, "concept-id") or _list_option(options, "concept")
    if ids:
        return [nodes_by_id[value] for value in ids if value in nodes_by_id]
    if ranked:
        return [nodes_by_id[row["id"]] for row in ranked[:limit] if row.get("id") in nodes_by_id]
    nodes = sorted(current_semantic_nodes(state), key=lambda node: str(node.get("nodeKey") or node.get("id") or ""))
    return nodes[:limit] if limit else nodes


def relation_explanation_status(state: dict[str, Any], relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for relation in relations:
        fingerprint = relation_explanation_fingerprint(state, relation)
        attachment, payload = current_enrichment_attachment(state, "semanticRelation", str(relation.get("id") or ""), RELATION_EXPLANATION_ROLE)
        status = freshness_status(attachment, payload, fingerprint)
        entries.append({"relation": relation, "status": status, "inputFingerprint": fingerprint, "attachment": attachment, "payload": payload})
    return entries


def concept_profile_status(state: dict[str, Any], concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for concept in concepts:
        touching = touching_relations(state, concept)
        missing_explanations = 0
        explanation_inputs = []
        for relation in touching:
            _, explanation_payload = current_enrichment_attachment(
                state,
                "semanticRelation",
                str(relation.get("id") or ""),
                RELATION_EXPLANATION_ROLE,
            )
            if not explanation_payload:
                missing_explanations += 1
            else:
                explanation_inputs.append(
                    {
                        "relationId": relation.get("id"),
                        "attachmentSha256": explanation_payload.get("attachmentSha256"),
                        "inputFingerprint": explanation_payload.get("inputFingerprint"),
                    }
                )
        fingerprint = concept_profile_fingerprint(state, concept, explanation_inputs)
        attachment, payload = current_enrichment_attachment(state, "semanticNode", str(concept.get("id") or ""), CONCEPT_PROFILE_ROLE)
        status = freshness_status(attachment, payload, fingerprint)
        if missing_explanations and status == "fresh":
            status = "stale"
        entries.append(
            {
                "concept": concept,
                "status": status,
                "inputFingerprint": fingerprint,
                "attachment": attachment,
                "payload": payload,
                "touchingRelationCount": len(touching),
                "missingRelationExplanations": missing_explanations,
            }
        )
    return entries


def current_enrichment_attachment(state: dict[str, Any], owner_kind: str, owner_id: str, role: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidates = [
        attachment for attachment in state["attachmentsByOwnerRole"].get((owner_kind, owner_id, role), [])
        if attachment.get("status") not in {"deleted", "aborted"}
    ]
    current = [attachment for attachment in candidates if attachment.get("sortKey") == "current"] or candidates
    if not current:
        return None, None
    attachment = sorted(current, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)[0]
    payload = attachment_payload_for_attachment(state, attachment)
    if isinstance(payload, dict):
        payload = {**payload, "attachmentSha256": attachment.get("sha256")}
    return attachment, payload if isinstance(payload, dict) else None


def attachment_payload_for_attachment(state: dict[str, Any], attachment: dict[str, Any]) -> dict[str, Any] | None:
    attachment_id = str(attachment.get("id") or "")
    if not attachment_id:
        return None
    payload_cache = state.setdefault("attachmentPayloads", {})
    cached = payload_cache.get(attachment_id)
    if isinstance(cached, dict):
        return cached
    if cached is False:
        return None
    client = state.get("attachmentPayloadClient")
    if not isinstance(client, PapyrusGraphQLAuthoringClient):
        return None
    payload = parse_attachment_payload(client, attachment)
    if isinstance(payload, dict):
        payload_cache[attachment_id] = payload
        return payload
    payload_cache[attachment_id] = False
    return None


def parse_attachment_payload(
    client: PapyrusGraphQLAuthoringClient,
    attachment: dict[str, Any],
) -> dict[str, Any] | None:
    try:
        buffer = download_attachment_buffer(client, attachment)
    except Exception:
        return None
    text = (buffer or b"").decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"raw": text}
    return payload if isinstance(payload, dict) else None


def freshness_status(attachment: dict[str, Any] | None, payload: dict[str, Any] | None, input_fingerprint: str) -> str:
    if not attachment:
        return "missing"
    if not payload or payload.get("inputFingerprint") != input_fingerprint:
        return "stale"
    return "fresh"


def relation_explanation_fingerprint(state: dict[str, Any], relation: dict[str, Any]) -> str:
    return hash_stable(
        {
            "schemaVersion": 1,
            "kind": "ontology_relation_explanation_input",
            "promptVersion": RELATION_EXPLANATION_PROMPT_VERSION,
            "relation": relation_fingerprint_fields(relation),
            "subject": object_fingerprint(state, str(relation.get("subjectKind") or ""), str(relation.get("subjectId") or ""), str(relation.get("subjectLineageId") or "")),
            "object": object_fingerprint(state, str(relation.get("objectKind") or ""), str(relation.get("objectId") or ""), str(relation.get("objectLineageId") or "")),
            "contextAttachments": context_attachment_fingerprints(state, relation),
            "contextMessages": context_message_fingerprints(state, relation),
        }
    )


def concept_profile_fingerprint(state: dict[str, Any], concept: dict[str, Any], explanation_inputs: list[dict[str, Any]]) -> str:
    return hash_stable(
        {
            "schemaVersion": 1,
            "kind": "ontology_concept_profile_input",
            "promptVersion": CONCEPT_PROFILE_PROMPT_VERSION,
            "concept": object_fingerprint(state, "semanticNode", str(concept.get("id") or ""), str(concept.get("lineageId") or concept.get("id") or "")),
            "relationExplanations": sorted(explanation_inputs, key=lambda entry: str(entry.get("relationId") or "")),
        }
    )


def relation_fingerprint_fields(relation: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id", "relationState", "predicate", "relationTypeKey", "relationDomain", "subjectKind", "subjectId", "subjectLineageId",
        "subjectVersionNumber", "objectKind", "objectId", "objectLineageId", "objectVersionNumber", "score", "confidence",
        "classifierId", "modelVersion", "sourceSnapshotId", "importRunId", "updatedAt", "metadata",
    ]
    return {key: relation.get(key) for key in keys}


def object_fingerprint(state: dict[str, Any], kind: str, object_id: str, lineage_id: str) -> dict[str, Any]:
    model_name = KIND_TO_MODEL.get(kind)
    record = (state.get("byModelId", {}).get(model_name, {}) or {}).get(object_id) if model_name else None
    if not record and model_name in {"Reference", "SemanticNode", "Category", "Item", "CategorySet"}:
        for candidate in state.get("models", {}).get(model_name, []):
            if str(candidate.get("lineageId") or "") == lineage_id:
                record = candidate
                break
    if not record:
        return {"kind": kind, "id": object_id, "lineageId": lineage_id, "missing": True}
    keys = [
        "id", "lineageId", "versionNumber", "versionState", "contentHash", "updatedAt", "createdAt", "title", "displayName",
        "summary", "description", "nodeKey", "nodeKind", "messageKind", "messageDomain", "status", "curationStatus",
        "assignmentTypeKey", "eventType", "sourceSnapshotId", "importRunId",
    ]
    return {key: record.get(key) for key in keys if key in record}


def context_attachment_fingerprints(state: dict[str, Any], relation: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [(relation.get("subjectKind"), relation.get("subjectId")), (relation.get("objectKind"), relation.get("objectId"))]
    values: list[dict[str, Any]] = []
    for kind, object_id in refs:
        if not kind or not object_id:
            continue
        for attachment in state["attachments"]:
            if attachment.get("ownerKind") == kind and attachment.get("ownerId") == object_id and attachment.get("status") not in {"deleted", "aborted"}:
                values.append(
                    {
                        "id": attachment.get("id"),
                        "role": attachment.get("role"),
                        "sortKey": attachment.get("sortKey"),
                        "sha256": attachment.get("sha256"),
                        "updatedAt": attachment.get("updatedAt"),
                    }
                )
    return sorted(values, key=lambda item: str(item.get("id") or ""))


def context_message_fingerprints(state: dict[str, Any], relation: dict[str, Any]) -> list[dict[str, Any]]:
    target_lineages = {str(relation.get("subjectLineageId") or ""), str(relation.get("objectLineageId") or "")}
    message_ids: set[str] = set()
    for candidate in current_relations(state):
        key = relation_type_key(candidate)
        if key not in {"comment", "note_about", "produces"}:
            continue
        if str(candidate.get("objectLineageId") or "") in target_lineages and candidate.get("subjectKind") == "message":
            message_ids.add(str(candidate.get("subjectId") or ""))
        if str(candidate.get("subjectLineageId") or "") in target_lineages and candidate.get("objectKind") == "message":
            message_ids.add(str(candidate.get("objectId") or ""))
    messages_by_id = state.get("byModelId", {}).get("Message", {})
    values = []
    for message_id in sorted(message_ids):
        message = messages_by_id.get(message_id)
        if not message:
            continue
        values.append(
            {
                "id": message.get("id"),
                "messageKind": message.get("messageKind"),
                "messageDomain": message.get("messageDomain"),
                "summary": message.get("summary"),
                "status": message.get("status"),
                "updatedAt": message.get("updatedAt"),
            }
        )
    return values


def touching_relations(state: dict[str, Any], concept: dict[str, Any]) -> list[dict[str, Any]]:
    lineage_id = str(concept.get("lineageId") or concept.get("id") or "")
    return [
        relation for relation in current_relations(state)
        if (relation.get("subjectKind") == "semanticNode" and str(relation.get("subjectLineageId") or "") == lineage_id)
        or (relation.get("objectKind") == "semanticNode" and str(relation.get("objectLineageId") or "") == lineage_id)
    ]


def relation_explanation_payloads_by_relation_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for attachment in state.get("attachments", []):
        if attachment.get("ownerKind") != "semanticRelation" or attachment.get("role") != RELATION_EXPLANATION_ROLE:
            continue
        payload = attachment_payload_for_attachment(state, attachment)
        if isinstance(payload, dict):
            results[str(attachment.get("ownerId") or "")] = {**payload, "attachmentSha256": attachment.get("sha256")}
    return results


def build_relation_context(state: dict[str, Any], relation: dict[str, Any], *, input_fingerprint: str) -> dict[str, Any]:
    subject = resolve_context_object(state, str(relation.get("subjectKind") or ""), str(relation.get("subjectId") or ""), str(relation.get("subjectLineageId") or ""))
    obj = resolve_context_object(state, str(relation.get("objectKind") or ""), str(relation.get("objectId") or ""), str(relation.get("objectLineageId") or ""))
    return {
        "schemaVersion": 1,
        "procedureKey": "ontology.relationship-explainer",
        "promptVersion": RELATION_EXPLANATION_PROMPT_VERSION,
        "inputFingerprint": input_fingerprint,
        "relation": relation,
        "subject": subject,
        "object": obj,
        "neighborRelations": neighbor_relations_for_relation(state, relation)[:24],
        "contextMessages": context_message_fingerprints(state, relation),
    }


def build_concept_context(state: dict[str, Any], concept: dict[str, Any], *, input_fingerprint: str) -> dict[str, Any]:
    explanations = []
    explanation_by_relation_id = relation_explanation_payloads_by_relation_id(state)
    for relation in touching_relations(state, concept):
        payload = explanation_by_relation_id.get(str(relation.get("id") or ""))
        if payload:
            explanations.append({"relation": relation, "explanation": payload})
    return {
        "schemaVersion": 1,
        "procedureKey": "ontology.concept-profiler",
        "promptVersion": CONCEPT_PROFILE_PROMPT_VERSION,
        "inputFingerprint": input_fingerprint,
        "concept": concept,
        "relationExplanations": explanations,
    }


def resolve_context_object(state: dict[str, Any], kind: str, object_id: str, lineage_id: str) -> dict[str, Any]:
    model_name = KIND_TO_MODEL.get(kind)
    record = (state.get("byModelId", {}).get(model_name, {}) or {}).get(object_id) if model_name else None
    if not record and model_name:
        for candidate in state.get("models", {}).get(model_name, []):
            if str(candidate.get("lineageId") or "") == lineage_id:
                record = candidate
                break
    attachments = [
        attachment for attachment in state.get("attachments", [])
        if attachment.get("ownerKind") == kind and attachment.get("ownerId") == object_id and attachment.get("status") not in {"deleted", "aborted"}
    ]
    context = {"kind": kind, "id": object_id, "lineageId": lineage_id, "record": record or {}, "attachments": attachments}
    if kind == "reference":
        reference_attachments = [
            attachment for attachment in state.get("models", {}).get("ReferenceAttachment", [])
            if attachment.get("referenceId") == object_id or attachment.get("referenceLineageId") == lineage_id
        ]
        context["referenceAttachments"] = reference_attachments
        context["sourceText"] = first_readable_reference_text(state, reference_attachments)
    elif kind == "message":
        context["bodyText"] = first_readable_model_attachment_text(state, attachments, role="message_body")
        context["metadataText"] = first_readable_model_attachment_text(state, attachments, role="metadata")
    return context


def first_readable_reference_text(state: dict[str, Any], attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = sorted(
        [
            attachment for attachment in attachments
            if attachment.get("role") in {"extracted_text", "metadata", "source"} and attachment.get("storagePath")
        ],
        key=lambda item: {"extracted_text": 0, "metadata": 1, "source": 2}.get(str(item.get("role")), 9),
    )
    for attachment in preferred:
        text = read_bounded_text(state, str(attachment.get("storagePath") or ""))
        if text:
            return {
                "attachmentId": attachment.get("id"),
                "role": attachment.get("role"),
                "storagePath": attachment.get("storagePath"),
                "text": text,
                "truncated": len(text) >= 4000,
            }
    return None


def first_readable_model_attachment_text(state: dict[str, Any], attachments: list[dict[str, Any]], *, role: str) -> dict[str, Any] | None:
    for attachment in sorted(attachments, key=lambda item: str(item.get("sortKey") or "")):
        if attachment.get("role") != role or not attachment.get("storagePath"):
            continue
        text = read_bounded_text(state, str(attachment.get("storagePath") or ""))
        if text:
            return {
                "attachmentId": attachment.get("id"),
                "role": attachment.get("role"),
                "storagePath": attachment.get("storagePath"),
                "text": text,
                "truncated": len(text) >= 4000,
            }
    return None


def read_bounded_text(state: dict[str, Any], storage_path: str, *, limit: int = 4000) -> str:
    provider = state.get("corpusText")
    if not provider or not storage_path:
        return ""
    try:
        text = provider.read_text(storage_path)
    except Exception:
        return ""
    if not text:
        return ""
    return str(text)[:limit]


def resolve_corpus_text_provider() -> Any:
    try:
        from papyrus_knowledge_query.services import build_environment_services

        return build_environment_services().corpus_text
    except Exception:
        return None


def neighbor_relations_for_relation(state: dict[str, Any], relation: dict[str, Any]) -> list[dict[str, Any]]:
    lineages = {str(relation.get("subjectLineageId") or ""), str(relation.get("objectLineageId") or "")}
    rows = [
        candidate for candidate in current_relations(state)
        if candidate.get("id") != relation.get("id")
        and (str(candidate.get("subjectLineageId") or "") in lineages or str(candidate.get("objectLineageId") or "") in lineages)
    ]
    return sorted(rows, key=lambda row: str(row.get("id") or ""))


def run_relationship_explainer(context: dict[str, Any], *, use_llm: bool, dry_run: bool) -> dict[str, Any]:
    relation_id = str((context.get("relation") or {}).get("id") or "")
    if use_llm and not dry_run:
        return run_tactus_json_procedure(
            PAPYRUS_ROOT / RELATION_EXPLAINER_PROCEDURE,
            {"context_json": context},
            markers=("relation_explanation", "meaning", "confidence"),
            target_kind="relation",
            target_id=relation_id,
        ).get("relation_explanation") or {}
    return deterministic_relation_explanation(context)


def run_concept_profiler(context: dict[str, Any], *, use_llm: bool, dry_run: bool) -> dict[str, Any]:
    concept_id = str((context.get("concept") or {}).get("id") or "")
    if use_llm and not dry_run:
        return run_tactus_json_procedure(
            PAPYRUS_ROOT / CONCEPT_PROFILER_PROCEDURE,
            {"context_json": context},
            markers=("concept_profile", "meaning", "confidence"),
            target_kind="concept",
            target_id=concept_id,
        ).get("concept_profile") or {}
    return deterministic_concept_profile(context)


def run_tactus_json_procedure(
    path: Path,
    params: dict[str, Any],
    *,
    markers: tuple[str, ...],
    target_kind: str,
    target_id: str,
) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Missing Tactus procedure: {path}\ttarget={target_kind}:{target_id}")
    command = ["tactus", "run", str(path), "--no-sandbox", "--real-all"]
    for key, value in params.items():
        encoded = urllib.parse.quote(json.dumps(value), safe="")
        command.extend(["--param", f"{key}=@urljson:{encoded}"])
    command.extend(["--log-format", "raw"])
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(part for part in [str(PAPYRUS_ROOT.parent / "Tactus"), str(PAPYRUS_ROOT / "src"), env.get("PYTHONPATH", "")] if part)
    completed = subprocess.run(command, cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False, env=env)
    if completed.returncode != 0:
        stderr_excerpt = _log_excerpt(completed.stderr)
        stdout_excerpt = _log_excerpt(completed.stdout)
        raise RuntimeError(
            "Tactus ontology procedure failed "
            f"target={target_kind}:{target_id} path={path} exit={completed.returncode} "
            f"stderr={stderr_excerpt!r} stdout={stdout_excerpt!r}"
        )
    from .cloud_procedures import extract_research_run_payload

    payload = extract_research_run_payload(completed.stdout, markers=markers)
    if not isinstance(payload, dict):
        stderr_excerpt = _log_excerpt(completed.stderr)
        stdout_excerpt = _log_excerpt(completed.stdout)
        raise RuntimeError(
            "Tactus ontology procedure completed without a JSON payload "
            f"target={target_kind}:{target_id} path={path} "
            f"stderr={stderr_excerpt!r} stdout={stdout_excerpt!r}"
        )
    return payload


def deterministic_relation_explanation(context: dict[str, Any]) -> dict[str, Any]:
    relation = context.get("relation") or {}
    subject_title = object_title(context.get("subject", {}).get("record") or {}) or relation.get("subjectId")
    object_title_text = object_title(context.get("object", {}).get("record") or {}) or relation.get("objectId")
    predicate = relation_type_key(relation)
    return {
        "meaning": f"{subject_title} {predicate.replace('_', ' ')} {object_title_text}.",
        "evidence": [],
        "ambiguity": [],
        "confidence": 0.72,
        "candidateAssociations": [],
        "model": "deterministic-dry-run",
    }


def deterministic_concept_profile(context: dict[str, Any]) -> dict[str, Any]:
    concept = context.get("concept") or {}
    explanations = context.get("relationExplanations") or []
    label = object_title(concept) or concept.get("nodeKey") or concept.get("id")
    return {
        "meaning": f"{label} is represented by {len(explanations)} contextual ontology relationship explanation(s).",
        "contextualVariants": [],
        "aliases": concept.get("aliases") or [],
        "disambiguators": [],
        "exemplarSources": [entry.get("relation", {}).get("id") for entry in explanations[:5] if entry.get("relation")],
        "likelyDuplicates": [],
        "recommendedRelations": [],
        "confidence": 0.72,
        "model": "deterministic-dry-run",
    }


def build_relation_explanation_records(relation: dict[str, Any], context: dict[str, Any], output: dict[str, Any], *, now: str) -> list[dict[str, Any]]:
    relation_id = str(relation.get("id") or "")
    payload = {
        "schemaVersion": 1,
        "artifactKind": RELATION_EXPLANATION_ROLE,
        "procedureKey": "ontology.relationship-explainer",
        "promptVersion": RELATION_EXPLANATION_PROMPT_VERSION,
        "inputFingerprint": context["inputFingerprint"],
        "relationId": relation_id,
        "relationTypeKey": relation_type_key(relation),
        "generatedAt": now,
        "output": output,
    }
    attachment = attachment_record(
        build_json_model_payload_attachment(
            {
                "ownerKind": "semanticRelation",
                "ownerId": relation_id,
                "ownerLineageId": relation_id,
                "role": RELATION_EXPLANATION_ROLE,
                "sortKey": "current",
                "filename": "ontology-relation-explanation.json",
                "content": payload,
                "importRunId": relation.get("importRunId"),
                "now": now,
            }
        )
    )
    return [attachment]


def build_concept_profile_records(concept: dict[str, Any], context: dict[str, Any], output: dict[str, Any], *, now: str) -> list[dict[str, Any]]:
    concept_id = str(concept.get("id") or "")
    concept_lineage = str(concept.get("lineageId") or concept_id)
    payload = {
        "schemaVersion": 1,
        "artifactKind": CONCEPT_PROFILE_ROLE,
        "procedureKey": "ontology.concept-profiler",
        "promptVersion": CONCEPT_PROFILE_PROMPT_VERSION,
        "inputFingerprint": context["inputFingerprint"],
        "conceptId": concept_id,
        "conceptLineageId": concept_lineage,
        "generatedAt": now,
        "output": output,
    }
    attachment = attachment_record(
        build_json_model_payload_attachment(
            {
                "ownerKind": "semanticNode",
                "ownerId": concept_id,
                "ownerLineageId": concept_lineage,
                "ownerVersionNumber": concept.get("versionNumber"),
                "ownerVersionKey": semantic_version_key("semanticNode", concept_id),
                "role": CONCEPT_PROFILE_ROLE,
                "sortKey": "current",
                "filename": "ontology-concept-profile.json",
                "content": payload,
                "importRunId": concept.get("importRunId"),
                "now": now,
            }
        )
    )
    return [attachment]


def build_association_relation_records(state: dict[str, Any], concepts: list[dict[str, Any]], *, threshold: float) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    concept_ids = {str(concept.get("id") or "") for concept in concepts}
    now = _utc_now()
    existing_keys = existing_relation_keys(state)
    for concept in concepts:
        _, payload = current_enrichment_attachment(state, "semanticNode", str(concept.get("id") or ""), CONCEPT_PROFILE_ROLE)
        output = payload.get("output") if isinstance(payload, dict) else None
        if not isinstance(output, dict):
            continue
        for recommendation in output.get("recommendedRelations") or []:
            if not isinstance(recommendation, dict):
                continue
            confidence = _number_or_none(recommendation.get("confidence")) or 0.0
            if confidence < threshold:
                continue
            predicate = normalize_predicate(str(recommendation.get("predicate") or recommendation.get("relationTypeKey") or "related_to"), state)
            target_id = str(recommendation.get("targetConceptId") or recommendation.get("objectId") or "")
            target = state.get("byModelId", {}).get("SemanticNode", {}).get(target_id)
            if not target:
                continue
            relation_key = relation_identity_key("semanticNode", concept, predicate, "semanticNode", target)
            if relation_key in existing_keys:
                continue
            records.append(
                semantic_relation_record(
                    predicate=predicate,
                    subject_kind="semanticNode",
                    subject_id=str(concept["id"]),
                    subject_lineage_id=str(concept.get("lineageId") or concept["id"]),
                    subject_version_number=concept.get("versionNumber"),
                    object_kind="semanticNode",
                    object_id=str(target["id"]),
                    object_lineage_id=str(target.get("lineageId") or target["id"]),
                    object_version_number=target.get("versionNumber"),
                    confidence=confidence,
                    score=confidence,
                    classifier_id="ontology.association-miner",
                    model_version=str(output.get("model") or ""),
                    source_snapshot_id=None,
                    import_run_id=concept.get("importRunId"),
                    imported_at=now,
                    metadata={"sourceConceptProfileId": concept.get("id"), "recommendation": recommendation},
                )
            )
    return records


def build_dedupe_relation_records(state: dict[str, Any], concepts: list[dict[str, Any]], *, threshold: float) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    now = _utc_now()
    existing_keys = existing_relation_keys(state)
    for concept in concepts:
        _, payload = current_enrichment_attachment(state, "semanticNode", str(concept.get("id") or ""), CONCEPT_PROFILE_ROLE)
        output = payload.get("output") if isinstance(payload, dict) else None
        if not isinstance(output, dict):
            continue
        for duplicate in output.get("likelyDuplicates") or []:
            if not isinstance(duplicate, dict):
                continue
            confidence = _number_or_none(duplicate.get("confidence")) or 0.0
            if confidence < threshold:
                continue
            predicate = str(duplicate.get("predicate") or duplicate.get("relationTypeKey") or "same_as")
            if predicate not in DEDUP_RELATION_KEYS:
                predicate = "same_as"
            target_id = str(duplicate.get("conceptId") or duplicate.get("targetConceptId") or duplicate.get("objectId") or "")
            target = state.get("byModelId", {}).get("SemanticNode", {}).get(target_id)
            if not target or target.get("id") == concept.get("id"):
                continue
            relation_key = relation_identity_key("semanticNode", concept, predicate, "semanticNode", target)
            inverse_key = relation_identity_key("semanticNode", target, predicate, "semanticNode", concept)
            if relation_key in existing_keys or inverse_key in existing_keys:
                continue
            records.append(
                semantic_relation_record(
                    predicate=predicate,
                    subject_kind="semanticNode",
                    subject_id=str(concept["id"]),
                    subject_lineage_id=str(concept.get("lineageId") or concept["id"]),
                    subject_version_number=concept.get("versionNumber"),
                    object_kind="semanticNode",
                    object_id=str(target["id"]),
                    object_lineage_id=str(target.get("lineageId") or target["id"]),
                    object_version_number=target.get("versionNumber"),
                    confidence=confidence,
                    score=confidence,
                    classifier_id="ontology.dedupe",
                    model_version=str(output.get("model") or ""),
                    source_snapshot_id=None,
                    import_run_id=concept.get("importRunId"),
                    imported_at=now,
                    metadata={"sourceConceptProfileId": concept.get("id"), "duplicate": duplicate},
                )
            )
    return records


def semantic_relation_record(
    *,
    predicate: str,
    subject_kind: str,
    subject_id: str,
    subject_lineage_id: str,
    subject_version_number: Any,
    object_kind: str,
    object_id: str,
    object_lineage_id: str,
    object_version_number: Any,
    confidence: float | None,
    score: float | None,
    classifier_id: str,
    model_version: str,
    source_snapshot_id: str | None,
    import_run_id: str | None,
    imported_at: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    subject_state_key = semantic_state_key(subject_kind, subject_lineage_id)
    object_state_key = semantic_state_key(object_kind, object_lineage_id)
    subject_version_key = semantic_version_key(subject_kind, subject_id)
    object_version_key = semantic_version_key(object_kind, object_id)
    expected = {
        "id": "semantic-relation-" + hash_short([subject_version_key, predicate, object_version_key, classifier_id, model_version, metadata]),
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
        "confidence": confidence,
        "rank": 1,
        "classifierId": classifier_id,
        "modelVersion": model_version or None,
        "reviewRecommended": False,
        "sourceSnapshotId": source_snapshot_id,
        "importRunId": import_run_id,
        "importedAt": imported_at,
        "createdAt": imported_at,
        "updatedAt": imported_at,
        "newsroomFeedKey": "semanticRelations",
        "metadata": json.dumps(metadata, sort_keys=True),
    }
    return {"modelName": "SemanticRelation", "expected": expected}


def existing_relation_keys(state: dict[str, Any]) -> set[tuple[str, str, str, str, str]]:
    keys = set()
    for relation in current_relations(state):
        keys.add(
            (
                str(relation.get("subjectKind") or ""),
                str(relation.get("subjectLineageId") or ""),
                relation_type_key(relation),
                str(relation.get("objectKind") or ""),
                str(relation.get("objectLineageId") or ""),
            )
        )
    return keys


def relation_identity_key(subject_kind: str, subject: dict[str, Any], predicate: str, object_kind: str, obj: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        subject_kind,
        str(subject.get("lineageId") or subject.get("id") or ""),
        predicate,
        object_kind,
        str(obj.get("lineageId") or obj.get("id") or ""),
    )


def normalize_predicate(value: str, state: dict[str, Any]) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "related_to"
    return normalized if normalized in state.get("relationTypes", {}) else "related_to"


def apply_or_report(client: PapyrusGraphQLAuthoringClient, label: str, records: list[dict[str, Any]], *, apply: bool) -> dict[str, Any]:
    changes = build_record_changes(client, records) if records else []
    changed = sum(1 for change in changes if change.get("action") != "noop")
    if apply and changes:
        apply_record_changes(client, changes)
    return {"changedRecords": changed, "changes": changes}


def ontology_status_payload(relation_status: list[dict[str, Any]], concept_status: list[dict[str, Any]], *, ranked: list[dict[str, Any]]) -> dict[str, Any]:
    relation_counts = status_counts(relation_status)
    concept_counts = status_counts(concept_status)
    return {
        "ok": True,
        "rankedConcepts": len(ranked),
        "conceptProfiles": concept_counts,
        "relationExplanations": relation_counts,
        "conceptStatus": compact_concept_status(concept_status),
        "relationStatus": compact_relation_status(relation_status),
        "ranked": ranked,
    }


def status_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"fresh": 0, "stale": 0, "missing": 0}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    counts["total"] = len(entries)
    return counts


def compact_concept_status(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": entry["concept"].get("id"),
            "lineageId": entry["concept"].get("lineageId"),
            "nodeKey": entry["concept"].get("nodeKey"),
            "displayName": entry["concept"].get("displayName"),
            "status": entry["status"],
            "inputFingerprint": entry["inputFingerprint"],
            "touchingRelationCount": entry.get("touchingRelationCount"),
            "missingRelationExplanations": entry.get("missingRelationExplanations"),
        }
        for entry in entries
    ]


def compact_relation_status(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": entry["relation"].get("id"),
            "predicate": relation_type_key(entry["relation"]),
            "subjectKind": entry["relation"].get("subjectKind"),
            "objectKind": entry["relation"].get("objectKind"),
            "status": entry["status"],
            "inputFingerprint": entry["inputFingerprint"],
        }
        for entry in entries
    ]


def print_status_summary(payload: dict[str, Any]) -> None:
    c = payload["conceptProfiles"]
    r = payload["relationExplanations"]
    print(f"ontology-status\tconcepts\ttotal={c['total']}\tfresh={c['fresh']}\tstale={c['stale']}\tmissing={c['missing']}")
    print(f"ontology-status\trelations\ttotal={r['total']}\tfresh={r['fresh']}\tstale={r['stale']}\tmissing={r['missing']}")


def next_recommended_command(payload: dict[str, Any]) -> str:
    relations = payload.get("relationExplanations") or {}
    concepts = payload.get("conceptProfiles") or {}
    if relations.get("missing") or relations.get("stale"):
        return "poetry run papyrus knowledge ontology explain --ranked --limit 50"
    if concepts.get("missing") or concepts.get("stale"):
        return "poetry run papyrus knowledge ontology profile --ranked --limit 50"
    return "poetry run papyrus knowledge vector-index --action sync --include-ontology-vectors --force"


def run_preflight_checks(client: PapyrusGraphQLAuthoringClient) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    relation_types = {row.get("key") for row in client.safe_list_records("SemanticRelationType")}
    required_types = {"explains_relation", "same_as", "alias_of", "mentions", "note_about"}
    missing_types = sorted(required_types - relation_types)
    checks.append(check_result("relation-types", not missing_types, f"missing={','.join(missing_types)}" if missing_types else "ok"))
    for owner_kind in ("semanticNode", "semanticRelation"):
        checks.append(check_result(f"attachment-owner-{owner_kind}", owner_kind in {"semanticNode", "semanticRelation"}, "configured locally"))
    for path in (PAPYRUS_ROOT / RELATION_EXPLAINER_PROCEDURE, PAPYRUS_ROOT / CONCEPT_PROFILER_PROCEDURE):
        checks.append(check_result(f"procedure-{path.name}", path.exists(), str(path)))
    checks.append(check_result("graphql-authoring", True, "authoring client initialized"))
    checks.append(check_result("openai-api-key", bool(os.environ.get("OPENAI_API_KEY")), "OPENAI_API_KEY present" if os.environ.get("OPENAI_API_KEY") else "OPENAI_API_KEY missing; --no-llm dry runs still work"))
    return checks


def check_result(name: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "status": "ok" if ok else "fail", "detail": detail}


def relation_type_key(relation: dict[str, Any]) -> str:
    return str(relation.get("relationTypeKey") or relation.get("predicate") or "related_to")


def semantic_state_key(kind: str, lineage_id: str, state: str = "current") -> str:
    return f"{kind}#{lineage_id}#{state}"


def object_title(record: dict[str, Any]) -> str:
    for key in ("displayName", "title", "headline", "summary", "nodeKey", "categoryKey", "id"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _ontology_progress(command: str, stage: str, status: str, detail: str | None = None) -> None:
    if detail:
        print(f"{command}\t{stage}\t{status}\t{detail}", file=sys.stderr, flush=True)
    else:
        print(f"{command}\t{stage}\t{status}", file=sys.stderr, flush=True)


def _emit_ontology_llm_failure(
    *,
    command: str,
    target_kind: str,
    target_id: str,
    error: Exception,
    next_commands: list[str],
) -> None:
    _ontology_progress(command, "ontology-error", "failed", f"{target_kind}={target_id}\terror={error}")
    for index, next_command in enumerate(next_commands, start=1):
        _ontology_progress(command, "ontology-next", str(index), next_command)


def _log_excerpt(text: str | None, *, max_lines: int = 8, max_chars: int = 600) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    lines = raw.splitlines()
    tail = "\n".join(lines[-max_lines:])
    return tail[-max_chars:]


def _ontology_model_scope(options: dict[str, Any]) -> list[str] | None:
    if options.get("deep-context"):
        return None
    return FAST_CONTEXT_MODELS


def _number_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        numeric = float(value)
        if math.isnan(numeric) or math.isinf(numeric):
            return None
        return numeric
    except (TypeError, ValueError):
        return None


def _int_option(options: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(options.get(key) if options.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def _float_option(options: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(options.get(key) if options.get(key) is not None else default)
    except (TypeError, ValueError):
        return default


def _list_option(options: dict[str, Any], key: str) -> list[str]:
    value = options.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
