from __future__ import annotations

import gzip
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .analysis_graph import (
    apply_graph_generated_purge_plan,
    build_graph_export_publish_records,
    build_graph_generated_purge_plan,
    compact_graph_artifact_row,
    fetch_graph_artifact_rows_indexed,
    filter_graph_export_payload_by_entity_popularity,
    hydrate_graph_reference_map_sync,
    plan_graph_artifact_import,
    resolve_graph_entity_popularity_thresholds,
)
from .analysis_profiles import (
    DEFAULT_ANALYSIS_PROFILES_PATH,
    analysis_profile_by_key,
    build_analysis_reindex_assignment_records,
    build_analysis_reindex_plan,
    load_analysis_profiles,
    parse_analysis_overrides,
    print_analysis_reindex_plan,
)
from .corpora import maybe_sync_corpus_from_cloud_before_analysis
from .env import PAPYRUS_ROOT
from .graphql_authoring import create_authoring_client
from .ids import hash_short, knowledge_corpus_id, safe_id
from .model_attachments import attachment_record, build_model_payload_attachment, upload_attachment_body
from .options import normalize_positive_integer, normalize_string, parse_boolean_option, parse_options, resolve_mutation_apply
from .records import apply_record_changes, build_record_changes_tolerating_optional_models
from .newsroom_summary import update_newsroom_summary_after_analysis_import, update_newsroom_summary_after_assignment_creates
from .relations_commands import print_category_import_summary
from .steering import (
    require_corpus_config,
    require_steering_config,
    load_steering_config,
    resolve_biblicus_runtime_dir,
    resolve_corpus_local_path,
)


def analysis_reindex_plan(flags: list[str]) -> None:
    options = parse_options(flags)
    plan = _build_analysis_reindex_plan_from_options(options, flags)
    if options.get("output"):
        _write_json_file(options["output"], plan)
    print_analysis_reindex_plan(plan)


def analysis_entity_graph_preflight(flags: list[str]) -> None:
    options = parse_options(flags)
    profile_key = normalize_string(options.get("profile")) or "reference-entity-graph"
    plan_options = dict(options)
    plan_options["profile"] = profile_key
    plan = _build_analysis_reindex_plan_from_options(plan_options, flags)
    if not _is_entity_graph_profile(plan):
        raise ValueError(
            f"analysis entity-graph-preflight requires an entity-graph profile; {profile_key} resolved to {plan['profile']['scope']}."
        )
    started_at = datetime.now(timezone.utc)
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    snapshot_ref = normalize_string((plan.get("effectiveParameters") or {}).get("extractionSnapshot"))
    snapshot_resolved = bool(snapshot_ref and "<" not in snapshot_ref and ":" in snapshot_ref)
    if snapshot_resolved:
        checks.append({"name": "extraction_snapshot", "status": "ok", "detail": snapshot_ref})
    else:
        checks.append(
            {
                "name": "extraction_snapshot",
                "status": "error",
                "detail": snapshot_ref or "missing",
            }
        )
        blockers.append("unresolved_extraction_snapshot")
    steering_config = require_steering_config(options.get("config"))
    corpus = require_corpus_config(steering_config, plan["corpus"]["key"], "--corpus-key")
    corpus_root, biblicus_runtime = _resolve_graph_analysis_paths(
        steering_config,
        corpus,
        options,
        fallback_workdir=plan.get("biblicusWorkdir"),
    )
    try:
        _preflight_biblicus_catalog_compatibility(corpus_root)
        checks.append({"name": "catalog_compatibility", "status": "ok", "detail": str(corpus_root)})
    except Exception as error:
        checks.append({"name": "catalog_compatibility", "status": "error", "detail": str(error)})
        blockers.append("malformed_catalog")
    payload: dict[str, Any] | None = None
    if snapshot_resolved and snapshot_ref:
        snapshot_manifest = _resolve_snapshot_manifest_path(corpus_root, snapshot_ref)
        if snapshot_manifest.exists():
            checks.append({"name": "snapshot_manifest", "status": "ok", "detail": str(snapshot_manifest)})
            try:
                payload = _export_graph_snapshot_payload(
                    biblicus_runtime=biblicus_runtime,
                    corpus_root=corpus_root,
                    snapshot_ref=snapshot_ref,
                )
                _validate_graph_export_payload(payload, snapshot_ref)
                checks.append(
                    {
                        "name": "payload_schema",
                        "status": "ok",
                        "detail": f"nodes={len(payload.get('nodes') or [])} edges={len(payload.get('edges') or [])}",
                    }
                )
            except Exception as error:
                checks.append({"name": "payload_schema", "status": "error", "detail": str(error)})
                blockers.append("malformed_payload")
        else:
            checks.append({"name": "snapshot_manifest", "status": "error", "detail": str(snapshot_manifest)})
            blockers.append("missing_snapshot")
    try:
        client, _ = create_authoring_client()
        checks.append({"name": "authoring_env", "status": "ok", "detail": "graphql-auth-ok"})
    except Exception as error:
        client = None
        checks.append({"name": "authoring_env", "status": "error", "detail": str(error)})
        blockers.append("authoring_env_unavailable")
    reference_count = 0
    unresolved_references = None
    unresolved_item_ids: list[str] = []
    if client is not None:
        reference_map = hydrate_graph_reference_map_sync(client, plan["corpus"]["id"])
        reference_count = len(reference_map)
        if reference_count > 0:
            checks.append({"name": "reference_mapping", "status": "ok", "detail": f"acceptedReferences={reference_count}"})
        else:
            checks.append({"name": "reference_mapping", "status": "warning", "detail": "acceptedReferences=0"})
            blockers.append("no_accepted_references")
        if payload is not None:
            publish_preview = build_graph_export_publish_records(
                payload,
                corpus_id=plan["corpus"]["id"],
                classifier_id=plan.get("classifierId"),
                imported_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                reference_by_external_item_id=reference_map,
            )
            unresolved_references = int(publish_preview.get("unresolvedReferences") or 0)
            unresolved_item_ids = [str(value) for value in (publish_preview.get("unresolvedReferenceItemIds") or [])[:50]]
            if unresolved_references > 0:
                checks.append(
                    {
                        "name": "reference_resolution",
                        "status": "error",
                        "detail": f"unresolvedReferences={unresolved_references}",
                    }
                )
                blockers.append("unresolved_reference_item_ids")
            else:
                checks.append({"name": "reference_resolution", "status": "ok", "detail": "unresolvedReferences=0"})
    elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    result = {
        "ok": len(blockers) == 0,
        "command": "analysis entity-graph-preflight",
        "profile": profile_key,
        "corpusId": plan["corpus"]["id"],
        "snapshot": snapshot_ref,
        "checks": checks,
        "acceptedReferenceCount": reference_count,
        "unresolvedReferences": unresolved_references,
        "unresolvedReferenceItemIds": unresolved_item_ids,
        "blockers": sorted(set(blockers)),
        "elapsedMs": elapsed_ms,
        "next": (
            None
            if len(blockers) == 0
            else (
                f"poetry run papyrus analysis run-now --profile {profile_key} --override extractionSnapshot=<extractor:snapshot_id>"
                if "unresolved_extraction_snapshot" in blockers
                else "poetry run papyrus analysis graph-artifacts --json"
            )
        ),
    }
    if options.get("json"):
        print(json.dumps(result, indent=2))
        return
    print(f"analysis-preflight\tentity-graph\tok\t{result['ok']}")
    print(f"analysis-preflight\tentity-graph\tprofile\t{profile_key}")
    print(f"analysis-preflight\tentity-graph\tcorpus\t{plan['corpus']['id']}")
    print(f"analysis-preflight\tentity-graph\tsnapshot\t{snapshot_ref or '-'}")
    for check in checks:
        print(
            "analysis-preflight\tentity-graph\tcheck\t"
            f"{check['status']}\t{check['name']}\t{check.get('detail') or '-'}"
        )
    if result["blockers"]:
        print(f"analysis-preflight\tentity-graph\tblockers\t{', '.join(result['blockers'])}")
    if result["unresolvedReferenceItemIds"]:
        print(
            "analysis-preflight\tentity-graph\tunresolved-item-ids\t"
            f"{', '.join(result['unresolvedReferenceItemIds'][:20])}"
        )
    if result["next"]:
        print(f"analysis-preflight\tentity-graph\tnext\t{result['next']}")


def analysis_publish_graph_snapshot(flags: list[str]) -> None:
    options = parse_options(flags)
    corpus_key = normalize_string(options.get("corpus-key"))
    snapshot_ref = normalize_string(options.get("snapshot"))
    requested_item_ids = [value for value in _parse_repeated_option(flags, "item-id") if normalize_string(value)]
    max_items = options.get("max-items")
    max_items_value: int | None = None
    if max_items is not None and str(max_items).strip() != "":
        try:
            max_items_value = max(0, int(str(max_items)))
        except ValueError as error:
            raise ValueError("--max-items must be an integer.") from error
    if not corpus_key:
        raise ValueError("analysis publish-graph-snapshot requires --corpus-key <key>.")
    if not snapshot_ref:
        raise ValueError("analysis publish-graph-snapshot requires --snapshot <extractor_id:snapshot_id>.")
    apply = resolve_mutation_apply(options, "analysis publish-graph-snapshot")
    result = _analysis_publish_graph_snapshot_internal(
        corpus_key=corpus_key,
        snapshot_ref=snapshot_ref,
        options=options,
        apply=apply,
        item_ids=requested_item_ids,
        max_items=max_items_value,
        plan=None,
    )
    if options.get("json"):
        print(json.dumps(result, indent=2))
        return
    print(f"analysis-publish\tmode\t{result['mode']}")
    print(f"analysis-publish\timport-run\t{result['importRunId']}")
    print(f"analysis-publish\tsnapshot\t{result['snapshot']}")
    print(f"analysis-publish\tchanged-records\t{result['changedRecords']}")
    print(f"analysis-publish\tmention-edges\t{result['mentionEdges']}")
    if result.get("popularityFilter"):
        print(f"analysis-publish\tpopularity-filter\t{json.dumps(result['popularityFilter'], sort_keys=True, separators=(',', ':'))}")
    print(f"analysis-publish\tunresolved-references\t{result['unresolvedReferences']}")
    if result["unresolvedReferenceItemIds"]:
        print(
            "analysis-publish\tunresolved-reference-item-ids\t"
            f"{', '.join(str(value) for value in result['unresolvedReferenceItemIds'][:20])}"
        )
    if result["next"]:
        print(f"analysis-publish\tnext\t{result['next']}")


def analysis_create_reindex_assignment(flags: list[str]) -> None:
    options = parse_options(flags)
    plan = _build_analysis_reindex_plan_from_options(options, flags)
    client, _ = create_authoring_client()
    category_sets = client.list_records("CategorySet")
    newsroom_sections = client.safe_list_records("NewsroomSection")
    category_set = _select_analysis_category_set(category_sets, plan, options.get("category-set"))
    section_target = _resolve_newsroom_section_target(newsroom_sections, options.get("section"))
    assignment_plan = build_analysis_reindex_assignment_records(
        plan,
        category_set=category_set,
        section_target=section_target,
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
    )
    if options.get("output"):
        _write_json_file(
            options["output"],
            {"plan": plan, "assignment": assignment_plan["assignment"], "records": assignment_plan["records"]},
        )
    print_analysis_reindex_plan(plan)
    assignment_changes = build_record_changes_tolerating_optional_models(
        client,
        [{"modelName": record["modelName"], "expected": record["expected"]} for record in assignment_plan["records"]],
    )
    for change in assignment_changes:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    apply = resolve_mutation_apply(options, "analysis create-reindex-assignment")
    if not apply:
        print("analysis\tcreate-reindex-assignment\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_record_changes(client, assignment_changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        assignment_changes,
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
        reason=f"analysis create-reindex-assignment {assignment_plan['assignment']['id']}",
    )


def analysis_run_now(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("profile"):
        raise ValueError("analysis run-now requires --profile <key>.")
    plan = _build_analysis_reindex_plan_from_options(options, flags)
    if _is_entity_graph_profile(plan):
        _assert_entity_graph_run_ready(plan)
    steering_config = require_steering_config(options.get("config") or plan.get("steeringConfigPath"))
    maybe_sync_corpus_from_cloud_before_analysis(
        steering_config=steering_config,
        corpus_key=str(plan["corpus"]["key"]),
        options=options,
        log_prefix="analysis-run-now",
    )
    client, auth = create_authoring_client()
    category_sets = client.list_records("CategorySet")
    newsroom_sections = client.safe_list_records("NewsroomSection")
    category_set = _select_analysis_category_set(category_sets, plan, options.get("category-set"))
    section_target = _resolve_newsroom_section_target(newsroom_sections, options.get("section"))
    assignment_plan = build_analysis_reindex_assignment_records(
        plan,
        category_set=category_set,
        section_target=section_target,
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
    )
    from .assignments import apply_assignment_action
    from .assignment_executors import execute_assignment_by_type

    assignment_changes = build_record_changes_tolerating_optional_models(
        client,
        [{"modelName": record["modelName"], "expected": record["expected"]} for record in assignment_plan["records"]],
    )
    apply_record_changes(client, assignment_changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        assignment_changes,
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
        reason=f"analysis run-now create {assignment_plan['assignment']['id']}",
    )
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="claim",
        assignment_id=assignment_plan["assignment"]["id"],
        options=options,
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
    )
    execution_options = dict(options)
    execution_options["__commandPlan"] = plan.get("commandPlan") or []
    started_at = datetime.now(timezone.utc)
    try:
        print("analysis-run-now\tphase\texecute-assignment\tstart", flush=True)
        execution_result = execute_assignment_by_type(client, assignment_plan["assignment"]["id"], execution_options)
        print(
            "analysis-run-now\tphase\texecute-assignment\tcomplete\t"
            f"elapsedMs={int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)}",
            flush=True,
        )
        if _is_entity_graph_profile(plan):
            snapshot_ref = _entity_graph_snapshot_ref_from_execution(execution_result, plan)
            corpus_key = str(plan["corpus"]["key"])
            print(f"analysis-run-now\tphase\tpublish-graph-snapshot\tstart\tsnapshot={snapshot_ref}", flush=True)
            publish_result = _analysis_publish_graph_snapshot_internal(
                corpus_key=corpus_key,
                snapshot_ref=snapshot_ref,
                options=options,
                apply=True,
                plan=plan,
            )
            print(
                "analysis-run-now\tphase\tpublish-graph-snapshot\tcomplete\t"
                f"importRun={publish_result['importRunId']}\tchangedRecords={publish_result['changedRecords']}\t"
                f"unresolvedReferences={publish_result['unresolvedReferences']}",
                flush=True,
            )
            if int(publish_result.get("unresolvedReferences") or 0) > 0:
                unresolved_preview = ", ".join(
                    str(value) for value in (publish_result.get("unresolvedReferenceItemIds") or [])[:20]
                )
                raise ValueError(
                    "Graph publish detected unresolved reference item ids. "
                    f"count={publish_result['unresolvedReferences']}. sample={unresolved_preview or '-'}"
                )
            print(
                "analysis-run-now\tphase\timport-graph-artifact\tstart\t"
                f"importRun={publish_result['importRunId']}",
                flush=True,
            )
            import_result = _analysis_import_graph_artifact_internal(
                publish_result["importRunId"],
                options=options,
                apply=True,
                plan=plan,
            )
            print(
                "analysis-run-now\tphase\timport-graph-artifact\tcomplete\t"
                f"changedRecords={import_result['changedRecords']}\t"
                f"mentionRelations={import_result['mentionRelations']}",
                flush=True,
            )
            execution_result = {
                **execution_result,
                "graphPublish": publish_result,
                "graphImport": import_result,
            }
    except Exception as error:
        print(
            "analysis-run-now\tphase\tfailure\t"
            f"assignment={assignment_plan['assignment']['id']}\terror={error}",
            flush=True,
        )
        print(
            "analysis-run-now\tnext\t"
            f"poetry run papyrus analysis execute-assignment --assignment {assignment_plan['assignment']['id']}"
            f" --run-id {execution_options.get('run-id') or plan.get('runId') or '-'}",
            flush=True,
        )
        raise
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="complete",
        assignment_id=assignment_plan["assignment"]["id"],
        options=options,
        actor_label=normalize_string(options.get("actor")) or "papyrus-cli",
    )
    print(json.dumps(execution_result, indent=2))


def analysis_execute_assignment(flags: list[str]) -> None:
    options = parse_options(flags)
    assignment_id = normalize_string(options.get("assignment"))
    if not assignment_id:
        raise ValueError("analysis execute-assignment requires --assignment <id>.")
    client, _ = create_authoring_client()
    from .assignment_executors import execute_assignment_by_type

    result = execute_assignment_by_type(client, assignment_id, options)
    print(json.dumps(result, indent=2))


def analysis_purge_graph_generated(flags: list[str]) -> None:
    options = parse_options(flags)
    corpus_key = normalize_string(options.get("corpus-key"))
    import_run_id = normalize_string(options.get("import-run"))
    if not corpus_key:
        raise ValueError("analysis purge-graph-generated requires --corpus-key <key>.")
    apply = resolve_mutation_apply(options, "analysis purge-graph-generated")
    steering_config = require_steering_config(options.get("config"))
    corpus = require_corpus_config(steering_config, corpus_key, "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus)
    client, _ = create_authoring_client()
    plan = build_graph_generated_purge_plan(
        client,
        corpus_id=corpus_id,
        import_run_id=import_run_id,
    )
    result = apply_graph_generated_purge_plan(client, plan, apply=apply)
    payload = {
        "ok": True,
        "command": "analysis purge-graph-generated",
        "mode": "apply" if apply else "dry-run",
        "corpusKey": corpus_key,
        "corpusId": corpus_id,
        "importRunIds": plan["importRunIds"],
        "semanticNodes": len(plan["semanticNodeIds"]),
        "semanticRelations": len(plan["semanticRelationIds"]),
        "deleted": result["deleted"],
        "skipped": result.get("skipped") or {},
        "next": (
            None
            if apply
            else (
                f"poetry run papyrus analysis purge-graph-generated --corpus-key {corpus_key}"
                + (f" --import-run {import_run_id}" if import_run_id else "")
                + " --apply"
            )
        ),
    }
    if options.get("json"):
        print(json.dumps(payload, indent=2))
        return
    print(f"graph-purge\tmode\t{payload['mode']}")
    print(f"graph-purge\tcorpus\t{corpus_key}\t{corpus_id}")
    print(f"graph-purge\timport-runs\t{len(plan['importRunIds'])}")
    for run_id in plan["importRunIds"]:
        print(f"graph-purge\timport-run\t{run_id}")
    print(f"graph-purge\tsemantic-nodes\t{payload['semanticNodes']}")
    print(f"graph-purge\tsemantic-relations\t{payload['semanticRelations']}")
    if apply:
        print(f"graph-purge\tdeleted\tSemanticRelation\t{result['deleted']['SemanticRelation']}")
        print(f"graph-purge\tdeleted\tSemanticNode\t{result['deleted']['SemanticNode']}")
        if result.get("skipped"):
            print(f"graph-purge\tskipped\t{json.dumps(result['skipped'], sort_keys=True)}")
    elif payload["next"]:
        print(f"graph-purge\tnext\t{payload['next']}")


def analysis_graph_artifacts(flags: list[str]) -> None:
    options = parse_options(flags)
    started_at = datetime.now(timezone.utc)
    client, _ = create_authoring_client()
    corpus_id = _graph_artifact_corpus_id_from_options(options)
    rows, diagnostics = fetch_graph_artifact_rows_indexed(client, corpus_id=corpus_id)
    rows.sort(
        key=lambda left: (
            str(left.get("importedAt") or ""),
            str(left.get("importRunId") or ""),
        ),
        reverse=True,
    )
    diagnostics["elapsedMs"] = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "analysis graph-artifacts",
                    "corpusId": corpus_id,
                    "query": diagnostics,
                    "count": len(rows),
                    "artifacts": [compact_graph_artifact_row(row) for row in rows],
                },
                indent=2,
            )
        )
        return
    print(f"graph-artifacts\tcount\t{len(rows)}")
    for row in rows:
        attachment = row.get("attachment") or {}
        print(
            "\t".join(
                [
                    "graph-artifact",
                    str(row.get("importRunId") or "-"),
                    str(row.get("corpusId") or "-"),
                    str(row.get("artifactId") or row.get("sourceSnapshotId") or "-"),
                    str(row.get("importedAt") or "-"),
                    str(attachment.get("storagePath") or "-"),
                    str(attachment.get("byteSize") or "-"),
                ]
            )
        )


def analysis_import_graph_artifact(flags: list[str]) -> None:
    options = parse_options(flags)
    import_run_id = normalize_string(options.get("import-run"))
    if not import_run_id:
        raise ValueError("analysis import-graph-artifact requires --import-run <id>.")
    apply = resolve_mutation_apply(options, "analysis import-graph-artifact")
    result_payload = _analysis_import_graph_artifact_internal(import_run_id, options=options, apply=apply)
    if options.get("json"):
        include_changes = parse_boolean_option(options.get("include-changes"), False, "--include-changes")
        json_payload = dict(result_payload)
        if not include_changes:
            json_payload.pop("changes", None)
        print(json.dumps(json_payload, indent=2))
        return
    if not apply:
        print("graph-artifact-import\tmode\tdry-run")
        print(f"graph-artifact-import\timport-run\t{import_run_id}")
        print(f"graph-artifact-import\tsnapshot\t{result_payload['snapshot']}")
        print(f"graph-artifact-import\tchanged-records\t{result_payload['changedRecords']}")
        print(f"graph-artifact-import\tchunk-size\t{result_payload['chunkSize']}")
        print(f"graph-artifact-import\tmax-parallel\t{result_payload['maxParallel']}")
        print(f"graph-artifact-import\tresume\t{result_payload['resume']}")
        print(f"graph-artifact-import\tfast-apply\t{result_payload['fastApply']}")
        print(f"graph-artifact-import\tcheckpoint\t{result_payload['checkpointPath']}")
        print(f"graph-artifact-import\tmention-edges\t{result_payload['mentionEdges']}")
        print(f"graph-artifact-import\tmention-relations\t{result_payload['mentionRelations']}")
        print(f"graph-artifact-import\tunresolved-references\t{result_payload['unresolvedReferences']}")
        if result_payload.get("unresolvedReferenceItemIds"):
            print(
                "graph-artifact-import\tunresolved-reference-item-ids\t"
                f"{', '.join(str(value) for value in result_payload['unresolvedReferenceItemIds'][:20])}"
            )
        print(f"graph-artifact-import\tnext\t{result_payload['next']}")
        return
    print_category_import_summary("graph-artifact", import_run_id, result_payload["changes"])
    print(f"graph-artifact-import\timport-run\t{import_run_id}")
    print(f"graph-artifact-import\tsnapshot\t{result_payload['snapshot']}")
    print(f"graph-artifact-import\tchanged-records\t{result_payload['changedRecords']}")
    print(f"graph-artifact-import\tchunk-size\t{result_payload['chunkSize']}")
    print(f"graph-artifact-import\tmax-parallel\t{result_payload['maxParallel']}")
    print(f"graph-artifact-import\tresume\t{result_payload['resume']}")
    print(f"graph-artifact-import\tfast-apply\t{result_payload['fastApply']}")
    print(f"graph-artifact-import\tcheckpoint\t{result_payload['checkpointPath']}")
    if result_payload.get("resumedFrom") is not None:
        print(f"graph-artifact-import\tresumed-from\t{result_payload['resumedFrom']}")
    print(f"graph-artifact-import\tmention-edges\t{result_payload['mentionEdges']}")
    print(f"graph-artifact-import\tmention-relations\t{result_payload['mentionRelations']}")
    print(f"graph-artifact-import\tunresolved-references\t{result_payload['unresolvedReferences']}")


def _analysis_import_graph_artifact_internal(
    import_run_id: str,
    *,
    options: dict[str, Any] | None = None,
    apply: bool = False,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    client, _ = create_authoring_client()
    fast_apply = parse_boolean_option(options.get("fast-apply"), apply, "--fast-apply")
    try:
        min_mention_count, min_reference_count = resolve_graph_entity_popularity_thresholds(options, plan=plan)
        result = plan_graph_artifact_import(
            client,
            import_run_id,
            resolve_existing=not fast_apply,
            min_mention_count=min_mention_count,
            min_reference_count=min_reference_count,
        )
    except ValueError as error:
        message = str(error)
        if "was not found" in message and "KnowledgeImportRun" in message:
            raise ValueError(
                f"Graph import failed: missing import run {import_run_id}. "
                "Run analysis publish-graph-snapshot first."
            ) from error
        if "Graph export attachment was not found" in message:
            raise ValueError(
                f"Graph import failed: missing graph-export attachment for {import_run_id}. "
                "Re-run analysis publish-graph-snapshot for the same snapshot."
            ) from error
        raise
    changed_records = sum(1 for change in result["changes"] if change.get("action") != "noop")
    unresolved_count = int(result["plan"].get("unresolvedReferences") or 0)
    unresolved_ids = (result["plan"].get("unresolvedReferenceItemIds") or [])[:50]
    chunk_size = normalize_positive_integer(options.get("chunk-size"), "--chunk-size") or 200
    max_parallel = min(normalize_positive_integer(options.get("max-parallel"), "--max-parallel") or 1, 16)
    resume = parse_boolean_option(options.get("resume"), True, "--resume")
    checkpoint_path = _graph_import_checkpoint_path(import_run_id, options)
    change_digest = _graph_import_change_digest(result["changes"])
    resumed_from = None
    checkpoint_state = _load_graph_import_checkpoint(checkpoint_path) if resume else None
    if checkpoint_state:
        if checkpoint_state.get("importRunId") != import_run_id:
            raise ValueError(
                f"Graph import checkpoint mismatch at {checkpoint_path}: importRunId differs."
            )
        if checkpoint_state.get("changeDigest") != change_digest:
            raise ValueError(
                "Graph import checkpoint no longer matches the planned change set. "
                f"Delete {checkpoint_path} or run with --resume false."
            )
        resumed_from = int(checkpoint_state.get("nextIndex") or 0)
    start_index = resumed_from if (apply and resume and resumed_from is not None) else 0
    if start_index < 0:
        start_index = 0
    if start_index > len(result["changes"]):
        raise ValueError(
            f"Graph import checkpoint nextIndex {start_index} exceeds planned change count {len(result['changes'])}: {checkpoint_path}"
        )
    payload = {
        "ok": True,
        "command": "analysis import-graph-artifact",
        "mode": "apply" if apply else "dry-run",
        "importRunId": import_run_id,
        "snapshot": result["plan"]["snapshotRef"],
        "storagePath": result["attachment"].get("storagePath"),
        "plannedRecords": len(result["plan"]["records"]),
        "changedRecords": changed_records,
        "semanticNodes": result["plan"]["semanticNodeCount"],
        "semanticRelations": result["plan"]["semanticRelationCount"],
        "mentionEdges": result["plan"]["mentionEdgeCount"],
        "mentionRelations": result["plan"]["mentionRelationCount"],
        "unresolvedReferences": unresolved_count,
        "unresolvedReferenceItemIds": unresolved_ids,
        "chunkSize": chunk_size,
        "maxParallel": max_parallel,
        "resume": resume,
        "fastApply": fast_apply,
        "checkpointPath": str(checkpoint_path),
        "resumedFrom": start_index if start_index > 0 else None,
        "next": f"poetry run papyrus analysis import-graph-artifact --import-run {import_run_id}",
    }
    action_counts, model_counts = _summarize_change_counts(result["changes"])
    payload["actionCounts"] = action_counts
    payload["modelCounts"] = model_counts
    if unresolved_count > 0 and apply:
        unresolved_preview = ", ".join(str(value) for value in unresolved_ids[:20])
        raise ValueError(
            "Graph import blocked because unresolved reference item ids are present. "
            f"count={unresolved_count}. sample={unresolved_preview or '-'}"
        )
    if apply:
        started_at = datetime.now(timezone.utc)
        total_changes = len(result["changes"])
        print(
            "graph-artifact-import\tphase\tplan\tready\t"
            f"importRun={import_run_id}\tplanned={total_changes}\tprocessed={start_index}"
            f"\tremaining={max(total_changes - start_index, 0)}"
            f"\tactionCounts={json.dumps(action_counts, sort_keys=True, separators=(',', ':'))}"
            f"\tmodelCounts={json.dumps(model_counts, sort_keys=True, separators=(',', ':'))}",
            flush=True,
        )
        if total_changes == 0:
            checkpoint_path.unlink(missing_ok=True)
        next_index = start_index
        if start_index > 0:
            print(
                "graph-artifact-import\tphase\tresume\tstart\t"
                f"importRun={import_run_id}\tnextIndex={start_index}\tcheckpoint={checkpoint_path}",
                flush=True,
            )
        while next_index < total_changes:
            chunk_end = min(next_index + chunk_size, total_changes)
            chunk = result["changes"][next_index:chunk_end]
            _, chunk_model_counts = _summarize_change_counts(chunk)
            elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            print(
                "graph-artifact-import\tphase\tapply-chunk\tstart\t"
                f"importRun={import_run_id}\tstartIndex={next_index}\tendIndex={chunk_end}\ttotal={total_changes}"
                f"\tremaining={max(total_changes - next_index, 0)}\telapsedMs={elapsed_ms}"
                f"\tchunkModelCounts={json.dumps(chunk_model_counts, sort_keys=True, separators=(',', ':'))}",
                flush=True,
            )
            apply_record_changes(
                client,
                chunk,
                max_parallel=max_parallel,
                client_factory=(lambda: create_authoring_client()[0]) if max_parallel > 1 else None,
            )
            next_index = chunk_end
            _write_graph_import_checkpoint(
                checkpoint_path,
                {
                    "schemaVersion": 1,
                    "importRunId": import_run_id,
                    "changeDigest": change_digest,
                    "nextIndex": next_index,
                    "totalChanges": total_changes,
                    "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
            )
            elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            print(
                "graph-artifact-import\tphase\tapply-chunk\tcomplete\t"
                f"importRun={import_run_id}\tprocessed={next_index}\ttotal={total_changes}"
                f"\tremaining={max(total_changes - next_index, 0)}\telapsedMs={elapsed_ms}\tcheckpoint={checkpoint_path}",
                flush=True,
            )
        checkpoint_path.unlink(missing_ok=True)
        update_newsroom_summary_after_analysis_import(
            client,
            result["changes"],
            actor_label="papyrus-cli",
            reason=f"analysis reimport graph artifact {result['plan']['importRunId']}",
        )
        if not parse_boolean_option(options.get("skip-recount-summary"), False, "--skip-recount-summary"):
            print("graph-artifact-import\tphase\trecount-summary\tstart", flush=True)
            from .newsroom_commands import apply_newsroom_summary_recount

            apply_newsroom_summary_recount(client, reason=f"analysis import graph artifact {import_run_id}")
            print("graph-artifact-import\tphase\trecount-summary\tcomplete", flush=True)
    payload["changes"] = result["changes"]
    return payload


def analysis_doctor_entity_graph(flags: list[str]) -> None:
    options = parse_options(flags)
    started_at = datetime.now(timezone.utc)
    client, _ = create_authoring_client()
    corpus_id = _graph_artifact_corpus_id_from_options(options)
    references = [
        row
        for row in client.list_records("Reference")
        if (not corpus_id or row.get("corpusId") == corpus_id)
        and row.get("versionState") == "current"
        and row.get("curationStatus") == "accepted"
    ]
    rows, diagnostics = fetch_graph_artifact_rows_indexed(client, corpus_id=corpus_id)
    graph_import_run_ids = {str(row.get("importRunId")) for row in rows if row.get("importRunId")}
    semantic_nodes_by_id: dict[str, dict[str, Any]] = {}
    graph_semantic_relations_by_id: dict[str, dict[str, Any]] = {}
    for run_id in sorted(graph_import_run_ids):
        for row in client.list_semantic_nodes_by_import_run_and_node_key(run_id):
            if row.get("versionState") != "current":
                continue
            if corpus_id and row.get("corpusId") != corpus_id:
                continue
            node_id = normalize_string(row.get("id"))
            if node_id:
                semantic_nodes_by_id[node_id] = row
        for row in client.list_semantic_relations_by_import_run_and_imported_at(run_id):
            if row.get("relationState") != "current":
                continue
            relation_id = normalize_string(row.get("id"))
            if relation_id:
                graph_semantic_relations_by_id[relation_id] = row
    semantic_nodes = list(semantic_nodes_by_id.values())
    graph_semantic_relations = list(graph_semantic_relations_by_id.values())
    mention_relations = [row for row in graph_semantic_relations if row.get("predicate") == "mentions"]
    unresolved_references = 0
    unresolved_reference_item_ids: list[str] = []
    timed_out_items = 0
    processed_items = 0
    timeout_heavy_runs = 0
    for row in rows:
        payload_record = row.get("rawPayload") or {}
        payload_blob = payload_record.get("payload")
        if not payload_blob:
            continue
        try:
            parsed = json.loads(payload_blob)
        except json.JSONDecodeError:
            continue
        unresolved_references += int(parsed.get("unresolvedReferences") or 0)
        stats = parsed.get("stats") if isinstance(parsed.get("stats"), dict) else {}
        row_timed_out = int(stats.get("items_timed_out") or 0)
        row_processed = int(stats.get("items_processed") or stats.get("items_total") or 0)
        timed_out_items += row_timed_out
        processed_items += row_processed
        if row_processed > 0 and row_timed_out > 0 and (row_timed_out / row_processed) >= 0.2:
            timeout_heavy_runs += 1
        for value in parsed.get("unresolvedReferenceItemIds") or []:
            normalized = normalize_string(value)
            if normalized and normalized not in unresolved_reference_item_ids:
                unresolved_reference_item_ids.append(normalized)
    semantic_node_kind_counts: dict[str, int] = {}
    for row in semantic_nodes:
        key = normalize_string(row.get("nodeKind")) or "unknown"
        semantic_node_kind_counts[key] = semantic_node_kind_counts.get(key, 0) + 1
    mention_edges = 0
    latest_row = None
    if rows:
        rows.sort(
            key=lambda left: (
                str(left.get("importedAt") or ""),
                str(left.get("importRunId") or ""),
            ),
            reverse=True,
        )
        latest_row = rows[0]
        latest_payload_record = (latest_row.get("rawPayload") or {}).get("payload")
        if isinstance(latest_payload_record, str):
            try:
                latest_payload = json.loads(latest_payload_record)
                mention_edges = int(latest_payload.get("stats", {}).get("mentions_found") or latest_payload.get("edgeCount") or 0)
            except json.JSONDecodeError:
                mention_edges = 0
    blockers: list[str] = []
    warnings: list[str] = []
    if not rows:
        blockers.append("no_graph_artifact")
    if rows and not semantic_nodes:
        blockers.append("graph_artifact_without_semantic_nodes")
    if unresolved_references > 0:
        blockers.append("unresolved_reference_item_ids")
    if rows and not mention_relations:
        blockers.append("no_mentions_relations")
    if timeout_heavy_runs > 0:
        warnings.append("timeout_heavy_runs")
    elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    diagnostics["semanticNodeIndex"] = "listSemanticNodesByImportRunAndNodeKey"
    diagnostics["semanticRelationIndex"] = "listSemanticRelationsByImportRunAndImportedAt"
    diagnostics["elapsedMs"] = elapsed_ms
    result = {
        "ok": len(blockers) == 0,
        "command": "analysis doctor-entity-graph",
        "corpusId": corpus_id,
        "counts": {
            "acceptedReferences": len(references),
            "graphArtifacts": len(rows),
            "semanticNodes": len(semantic_nodes),
            "semanticNodesByKind": semantic_node_kind_counts,
            "graphSemanticRelations": len(graph_semantic_relations),
            "mentionsRelations": len(mention_relations),
            "unresolvedReferences": unresolved_references,
            "mentionsEdgesEstimate": mention_edges,
            "processedItems": processed_items,
            "timedOutItems": timed_out_items,
            "timeoutHeavyRuns": timeout_heavy_runs,
        },
        "latest": {
            "importRunId": (latest_row or {}).get("importRunId"),
            "artifactId": (latest_row or {}).get("artifactId"),
            "snapshotId": (latest_row or {}).get("sourceSnapshotId"),
            "importedAt": (latest_row or {}).get("importedAt"),
        },
        "blockers": blockers,
        "warnings": warnings,
        "unresolvedReferenceItemIds": unresolved_reference_item_ids[:100],
        "query": diagnostics,
        "next": (
            "poetry run papyrus analysis run-now --profile reference-entity-graph "
            if not rows
            else (
                "poetry run papyrus analysis import-graph-artifact --import-run <id>"
                if rows and not graph_semantic_relations
                else None
            )
        ),
    }
    if options.get("json"):
        print(json.dumps(result, indent=2))
        return
    print(f"analysis-doctor\tentity-graph\tok\t{result['ok']}")
    print(f"analysis-doctor\tentity-graph\tcorpus\t{corpus_id or '-'}")
    print(f"analysis-doctor\tentity-graph\taccepted-references\t{result['counts']['acceptedReferences']}")
    print(f"analysis-doctor\tentity-graph\tgraph-artifacts\t{result['counts']['graphArtifacts']}")
    print(f"analysis-doctor\tentity-graph\tsemantic-nodes\t{result['counts']['semanticNodes']}")
    print(f"analysis-doctor\tentity-graph\tmentions-relations\t{result['counts']['mentionsRelations']}")
    print(f"analysis-doctor\tentity-graph\tunresolved-references\t{result['counts']['unresolvedReferences']}")
    print(f"analysis-doctor\tentity-graph\ttimed-out-items\t{result['counts']['timedOutItems']}")
    if blockers:
        print(f"analysis-doctor\tentity-graph\tblockers\t{', '.join(blockers)}")
    if warnings:
        print(f"analysis-doctor\tentity-graph\twarnings\t{', '.join(warnings)}")
    if unresolved_reference_item_ids:
        print(
            "analysis-doctor\tentity-graph\tunresolved-item-ids\t"
            f"{', '.join(unresolved_reference_item_ids[:20])}"
        )
    if result["next"]:
        print(f"analysis-doctor\tentity-graph\tnext\t{result['next']}")


def _analysis_publish_graph_snapshot_internal(
    *,
    corpus_key: str,
    snapshot_ref: str,
    options: dict[str, Any] | None = None,
    apply: bool = False,
    item_ids: list[str] | None = None,
    max_items: int | None = None,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    started_at = datetime.now(timezone.utc)
    steering_config = require_steering_config(options.get("config"))
    corpus = require_corpus_config(steering_config, corpus_key, "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus)
    corpus_root, biblicus_runtime = _resolve_graph_analysis_paths(steering_config, corpus, options)
    snapshot_manifest = _resolve_snapshot_manifest_path(corpus_root, snapshot_ref)
    if not snapshot_manifest.exists():
        raise ValueError(
            f"Missing graph snapshot manifest for {snapshot_ref}: {snapshot_manifest}. "
            "Run graph extract before publish."
        )
    print("analysis-publish\tphase\tpreflight\tstart", flush=True)
    _preflight_biblicus_catalog_compatibility(corpus_root)
    print("analysis-publish\tphase\tpreflight\tcomplete", flush=True)
    print("analysis-publish\tphase\texport\tstart", flush=True)
    payload = _export_graph_snapshot_payload(
        biblicus_runtime=biblicus_runtime,
        corpus_root=corpus_root,
        snapshot_ref=snapshot_ref,
    )
    print("analysis-publish\tphase\texport\tcomplete", flush=True)
    _validate_graph_export_payload(payload, snapshot_ref)
    payload = _apply_graph_export_item_scope(payload, item_ids=item_ids or [], max_items=max_items)
    min_mention_count, min_reference_count = resolve_graph_entity_popularity_thresholds(options, plan=plan)
    payload, popularity_filter = filter_graph_export_payload_by_entity_popularity(
        payload,
        min_mention_count=min_mention_count,
        min_reference_count=min_reference_count,
    )
    client, _ = create_authoring_client()
    imported_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    reference_by_external_item_id = hydrate_graph_reference_map_sync(client, corpus_id)
    publish_plan = build_graph_export_publish_records(
        payload,
        corpus_id=corpus_id,
        classifier_id=None,
        imported_at=imported_at,
        reference_by_external_item_id=reference_by_external_item_id,
    )
    raw_payload_record = next(
        (record for record in publish_plan["records"] if record["modelName"] == "KnowledgeRawPayload"),
        None,
    )
    if not raw_payload_record:
        raise ValueError("Graph publish plan did not produce a KnowledgeRawPayload record.")
    raw_payload_id = raw_payload_record["expected"]["id"]
    graph_attachment = attachment_record(
        build_model_payload_attachment(
            {
                "ownerKind": "knowledgeRawPayload",
                "ownerId": raw_payload_id,
                "ownerLineageId": raw_payload_id,
                "role": "graph_export",
                "sortKey": "graph-export",
                "filename": "graph-export.json.gz",
                "mediaType": "application/gzip",
                "content": gzip.compress((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")),
                "importRunId": publish_plan["importRunId"],
                "now": imported_at,
                "status": "active",
            }
        )
    )
    records = [*publish_plan["records"], graph_attachment]
    changes = build_record_changes_tolerating_optional_models(client, records)
    changed_records = sum(1 for change in changes if change.get("action") != "noop")
    if apply:
        print("analysis-publish\tphase\trecords-apply\tstart", flush=True)
        apply_record_changes(client, changes)
        uploaded = upload_attachment_body(client, graph_attachment["expected"], graph_attachment["attachmentBody"])
        merged_attachment = (
            {**graph_attachment["expected"], **uploaded}
            if isinstance(uploaded, dict)
            else graph_attachment["expected"]
        )
        client.upsert("ModelAttachment", merged_attachment)
        print("analysis-publish\tphase\trecords-apply\tcomplete", flush=True)
    return {
        "ok": True,
        "command": "analysis publish-graph-snapshot",
        "mode": "apply" if apply else "dry-run",
        "corpusKey": corpus_key,
        "corpusId": corpus_id,
        "snapshot": publish_plan["snapshotRef"],
        "importRunId": publish_plan["importRunId"],
        "graphId": publish_plan["graphId"],
        "nodeCount": publish_plan["nodeCount"],
        "edgeCount": publish_plan["edgeCount"],
        "semanticNodeCount": publish_plan["semanticNodeCount"],
        "mentionEdges": publish_plan["mentionEdgeCount"],
        "popularityFilter": popularity_filter if popularity_filter.get("applied") else None,
        "unresolvedReferences": publish_plan["unresolvedReferences"],
        "unresolvedReferenceItemIds": (publish_plan.get("unresolvedReferenceItemIds") or [])[:50],
        "plannedRecords": len(records),
        "changedRecords": changed_records,
        "elapsedMs": int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
        "next": (
            None
            if apply
            else f"poetry run papyrus analysis publish-graph-snapshot --corpus-key {corpus_key} --snapshot {snapshot_ref}"
        ),
    }


def _apply_graph_export_item_scope(
    payload: dict[str, Any],
    *,
    item_ids: list[str],
    max_items: int | None,
) -> dict[str, Any]:
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    edges = payload.get("edges") if isinstance(payload.get("edges"), list) else []
    if not edges:
        return payload
    graph_node_by_id = {_clean_string(node.get("node_id")): node for node in nodes if _clean_string(node.get("node_id"))}
    mention_edges = [edge for edge in edges if _edge_touches_item_node(edge, graph_node_by_id)]
    available_item_ids = sorted(
        {
            item_id
            for edge in mention_edges
            for item_id in [_edge_source_item_id(edge, graph_node_by_id)]
            if item_id
        }
    )
    selected_items = {normalized for normalized in (_clean_string(value) for value in item_ids) if normalized}
    if selected_items:
        selected_items = selected_items.intersection(set(available_item_ids))
    elif max_items is not None and max_items >= 0:
        selected_items = set(available_item_ids[:max_items])
    if not selected_items:
        return payload
    selected_edge_ids: set[str] = set()
    selected_edges: list[dict[str, Any]] = []
    selected_node_ids: set[str] = set()
    for edge in mention_edges:
        edge_item_id = _edge_source_item_id(edge, graph_node_by_id)
        if edge_item_id not in selected_items:
            continue
        edge_id = _clean_string(edge.get("edge_id")) or f"{_clean_string(edge.get('src'))}:{_clean_string(edge.get('dst'))}"
        if edge_id not in selected_edge_ids:
            selected_edges.append(edge)
            selected_edge_ids.add(edge_id)
        src = _clean_string(edge.get("src"))
        dst = _clean_string(edge.get("dst"))
        if src:
            selected_node_ids.add(src)
        if dst:
            selected_node_ids.add(dst)
    for edge in edges:
        src = _clean_string(edge.get("src"))
        dst = _clean_string(edge.get("dst"))
        if not src or not dst:
            continue
        if src not in selected_node_ids or dst not in selected_node_ids:
            continue
        if _edge_touches_item_node(edge, graph_node_by_id):
            continue
        edge_id = _clean_string(edge.get("edge_id")) or f"{src}:{dst}"
        if edge_id in selected_edge_ids:
            continue
        selected_edges.append(edge)
        selected_edge_ids.add(edge_id)
    scoped_nodes = [node for node in nodes if _clean_string(node.get("node_id")) in selected_node_ids]
    scoped_payload = {**payload, "nodes": scoped_nodes, "edges": selected_edges}
    if isinstance(scoped_payload.get("stats"), dict):
        scoped_payload["stats"] = {
            **scoped_payload["stats"],
            "scoped_item_ids": sorted(selected_items),
            "scoped_node_count": len(scoped_nodes),
            "scoped_edge_count": len(selected_edges),
        }
    return scoped_payload


def _edge_touches_item_node(edge: dict[str, Any], graph_node_by_id: dict[str, dict[str, Any]]) -> bool:
    src_node = graph_node_by_id.get(_clean_string(edge.get("src"))) or {}
    dst_node = graph_node_by_id.get(_clean_string(edge.get("dst"))) or {}
    return _is_item_node(src_node) or _is_item_node(dst_node)


def _edge_source_item_id(edge: dict[str, Any], graph_node_by_id: dict[str, dict[str, Any]]) -> str | None:
    src_node = graph_node_by_id.get(_clean_string(edge.get("src"))) or {}
    dst_node = graph_node_by_id.get(_clean_string(edge.get("dst"))) or {}
    direct = _clean_string(edge.get("item_id"))
    if direct:
        return direct
    return _item_id_from_node(src_node) or _item_id_from_node(dst_node)


def _is_item_node(node: dict[str, Any]) -> bool:
    node_type = _clean_string(node.get("node_type"))
    node_id = _clean_string(node.get("node_id")) or ""
    return node_type in {"item", "reference"} or node_id.startswith("item:") or node_id.startswith("reference:")


def _item_id_from_node(node: dict[str, Any]) -> str | None:
    properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return (
        _clean_string(properties.get("item_id"))
        or _clean_string(properties.get("reference_id"))
        or _strip_prefix(_clean_string(node.get("node_id")), "item:")
        or _strip_prefix(_clean_string(node.get("node_id")), "reference:")
    )


def _strip_prefix(value: str | None, prefix: str) -> str | None:
    if value and value.startswith(prefix):
        return value[len(prefix) :]
    return None


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_entity_graph_profile(plan: dict[str, Any]) -> bool:
    profile = plan.get("profile") if isinstance(plan.get("profile"), dict) else {}
    return normalize_string(profile.get("scope")) == "entity-graph"


def _assert_entity_graph_run_ready(plan: dict[str, Any]) -> None:
    effective = plan.get("effectiveParameters") if isinstance(plan.get("effectiveParameters"), dict) else {}
    snapshot = normalize_string(effective.get("extractionSnapshot"))
    if not snapshot or "<" in snapshot or ":" not in snapshot:
        raise ValueError(
            "analysis run-now requires a resolved extraction snapshot for entity-graph runs. "
            "Provide --override extractionSnapshot=<extractor_id:snapshot_id>."
        )


def _entity_graph_snapshot_ref_from_execution(execution_result: dict[str, Any], plan: dict[str, Any]) -> str:
    command_results = execution_result.get("commandResults") if isinstance(execution_result.get("commandResults"), list) else []
    graph_extract = next((entry for entry in command_results if entry.get("label") == "graph-extract"), None)
    if not graph_extract:
        raise ValueError("analysis run-now did not produce graph-extract command output.")
    stdout_log_path = normalize_string(graph_extract.get("stdoutLogPath"))
    if not stdout_log_path:
        raise ValueError("analysis run-now graph-extract output did not include stdoutLogPath.")
    parsed = _extract_last_json_from_file(Path(stdout_log_path))
    snapshot_id = normalize_string(parsed.get("snapshot_id"))
    if not snapshot_id:
        raise ValueError("analysis run-now graph-extract output did not include snapshot_id.")
    extractor = _extractor_from_graph_extract_command(graph_extract, plan)
    return f"{extractor}:{snapshot_id}"


def _extractor_from_graph_extract_command(command_result: dict[str, Any], plan: dict[str, Any]) -> str:
    argv = [str(part) for part in command_result.get("argv") or []]
    for index, part in enumerate(argv):
        if part == "--extractor" and index + 1 < len(argv):
            return str(argv[index + 1])
    command_plan = plan.get("commandPlan") if isinstance(plan.get("commandPlan"), list) else []
    graph_extract = next((entry for entry in command_plan if entry.get("label") == "graph-extract"), None)
    args = [str(part) for part in (graph_extract or {}).get("args") or []]
    for index, part in enumerate(args):
        if part == "--extractor" and index + 1 < len(args):
            return str(args[index + 1])
    return "graph"


def _extract_last_json_from_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"Missing graph extract stdout log: {path}")
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        candidate = line.strip()
        if not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    decoder = json.JSONDecoder()
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in reversed(starts):
        chunk = text[start:].strip()
        try:
            parsed, offset = decoder.raw_decode(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        if chunk[offset:].strip():
            continue
        return parsed
    raise ValueError(f"Could not parse JSON payload from graph extract stdout log: {path}")


def _resolve_graph_analysis_paths(
    steering_config: dict[str, Any],
    corpus: dict[str, Any],
    options: dict[str, Any],
    *,
    fallback_workdir: str | Path | None = None,
) -> tuple[Path, Path]:
    corpus_root = resolve_corpus_local_path(
        corpus,
        steering_config,
        fallback_workdir=fallback_workdir or options.get("biblicus-workdir") or options.get("biblicusWorkdir"),
    )
    biblicus_runtime = resolve_biblicus_runtime_dir(options)
    return corpus_root, biblicus_runtime


def _resolve_snapshot_manifest_path(corpus_root: Path, snapshot_ref: str) -> Path:
    extractor, snapshot_id = _parse_snapshot_ref(snapshot_ref)
    return (corpus_root / "graph" / extractor / snapshot_id / "manifest.json").resolve()


def _parse_snapshot_ref(snapshot_ref: str) -> tuple[str, str]:
    normalized = normalize_string(snapshot_ref)
    if not normalized or ":" not in normalized:
        raise ValueError("Graph snapshot reference must be in extractor_id:snapshot_id form.")
    extractor, snapshot_id = normalized.split(":", 1)
    if not extractor or not snapshot_id:
        raise ValueError("Graph snapshot reference must be in extractor_id:snapshot_id form.")
    return extractor, snapshot_id


def _preflight_biblicus_catalog_compatibility(corpus_root: Path) -> None:
    catalog_path = (corpus_root / "metadata" / "catalog.json").resolve()
    if not catalog_path.exists():
        raise ValueError(f"Missing Biblicus corpus catalog: {catalog_path}")
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Malformed Biblicus corpus catalog JSON: {catalog_path}: {error}") from error
    items = catalog.get("items")
    if not isinstance(items, dict):
        raise ValueError(f"Biblicus catalog items must be an object map: {catalog_path}")
    allowed_item_keys = {
        "id",
        "relpath",
        "sha256",
        "bytes",
        "media_type",
        "title",
        "tags",
        "metadata",
        "dates",
        "created_at",
        "source_uri",
    }
    extras: list[tuple[str, list[str]]] = []
    for item_id, item in items.items():
        if not isinstance(item, dict):
            continue
        unexpected = sorted(key for key in item.keys() if key not in allowed_item_keys)
        if unexpected:
            extras.append((str(item_id), unexpected))
        if len(extras) >= 5:
            break
    if extras:
        preview = "; ".join(f"{item_id}: {','.join(keys)}" for item_id, keys in extras)
        raise ValueError(
            "Biblicus catalog contains unsupported top-level item fields for graph extraction. "
            f"sample={preview}"
        )


def _export_graph_snapshot_payload(
    *,
    biblicus_runtime: Path,
    corpus_root: Path,
    snapshot_ref: str,
) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(prefix="papyrus-graph-export-", suffix=".json", delete=False) as temp_file:
        output_path = Path(temp_file.name)
    try:
        result = subprocess.run(
            [
                "uv",
                "run",
                "biblicus",
                "graph",
                "export",
                "--corpus",
                str(corpus_root),
                "--snapshot",
                snapshot_ref,
                "--output",
                str(output_path),
            ],
            cwd=biblicus_runtime,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            error_text = stderr or stdout or f"exit code {result.returncode}"
            if "No such file" in error_text or "not found" in error_text.lower():
                raise ValueError(
                    f"Graph snapshot {snapshot_ref} is missing in Biblicus corpus {corpus_root}. "
                    f"Details: {error_text}"
                )
            raise RuntimeError(f"Failed to export graph snapshot {snapshot_ref}: {error_text}")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    finally:
        output_path.unlink(missing_ok=True)
    return payload


def _validate_graph_export_payload(payload: dict[str, Any], snapshot_ref: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"Graph export payload for {snapshot_ref} is not a JSON object.")
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError(
            f"Graph export payload for {snapshot_ref} is missing required nodes[] or edges[] arrays."
        )
    snapshot = payload.get("snapshot")
    snapshot_id = normalize_string((snapshot or {}).get("snapshot_id")) if isinstance(snapshot, dict) else None
    if not snapshot_id:
        raise ValueError(f"Graph export payload for {snapshot_ref} is missing snapshot.snapshot_id.")


def _build_analysis_reindex_plan_from_options(options: dict[str, Any], flags: list[str]) -> dict[str, Any]:
    if not options.get("profile"):
        raise ValueError("analysis reindex-plan requires --profile <key>.")
    steering_config = require_steering_config(options.get("config"))
    profiles_config = load_analysis_profiles(options.get("profiles") or str(DEFAULT_ANALYSIS_PROFILES_PATH))
    profile = analysis_profile_by_key(profiles_config, options["profile"])
    overrides = parse_analysis_overrides(
        _parse_repeated_option(flags, "override"),
        profile,
    )
    if profile.get("scope") == "entity-graph" and not options.get("full-corpus") and "graph.max_items" not in overrides:
        overrides = {**overrides, "graph.max_items": 50}
    return build_analysis_reindex_plan(
        profiles_config=profiles_config,
        steering_config=steering_config,
        profile_key=options["profile"],
        corpus_key=options.get("corpus-key"),
        mode=options.get("mode"),
        overrides=overrides,
        run_id=options.get("run-id"),
        biblicus_workdir=options.get("biblicus-workdir"),
        category_set_id=options.get("category-set"),
        category_key=options.get("category-key"),
    )


def _select_analysis_category_set(
    category_sets: list[dict[str, Any]],
    plan: dict[str, Any],
    explicit_category_set_id: str | None,
) -> dict[str, Any] | None:
    if explicit_category_set_id:
        category_set = next((entry for entry in category_sets if entry.get("id") == explicit_category_set_id), None)
        if category_set is None:
            raise ValueError(f"CategorySet {explicit_category_set_id} was not found.")
        return category_set
    accepted = [
        entry
        for entry in category_sets
        if entry.get("status") == "accepted"
        and (not entry.get("versionState") or entry.get("versionState") == "current")
        and entry.get("corpusId") == plan["corpus"]["id"]
        and (not plan.get("classifierId") or entry.get("classifierId") == plan["classifierId"])
    ]
    accepted.sort(
        key=lambda left: (
            str(left.get("generatedAt") or ""),
            str(left.get("displayName") or ""),
        ),
        reverse=True,
    )
    return accepted[0] if accepted else None


def _resolve_newsroom_section_target(
    newsroom_sections: list[dict[str, Any]],
    section_key: str | None,
) -> dict[str, Any] | None:
    normalized = normalize_string(section_key)
    if not normalized:
        return None
    section = next(
        (
            entry
            for entry in newsroom_sections
            if entry.get("id") == normalized
            or entry.get("sectionKey") == normalized
            or safe_id(entry.get("title") or "") == normalized
        ),
        None,
    )
    if section is None:
        raise ValueError(f"Unknown NewsroomSection '{normalized}'.")
    if section.get("enabled") is False or section.get("enabledStatus") == "disabled":
        raise ValueError(f"NewsroomSection '{normalized}' is disabled.")
    return {
        "id": section["id"],
        "title": section.get("title"),
        "type": "floating" if section.get("type") == "rotating" else section.get("type"),
        "editorialMission": section.get("editorialMission"),
        "editorialPolicy": section.get("editorialPolicy"),
        "assignmentGuidance": section.get("assignmentGuidance"),
        "killCriteria": section.get("killCriteria"),
        "visualGuidance": section.get("visualGuidance"),
    }


def _graph_artifact_corpus_id_from_options(options: dict[str, Any]) -> str | None:
    if not options.get("corpus-key"):
        return None
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    return knowledge_corpus_id(corpus_config)


def _parse_repeated_option(flags: list[str], key: str) -> list[str]:
    values: list[str] = []
    index = 0
    while index < len(flags):
        if flags[index] == f"--{key}" and index + 1 < len(flags):
            values.append(flags[index + 1])
            index += 2
        else:
            index += 1
    return values


def _graph_import_checkpoint_path(import_run_id: str, options: dict[str, Any]) -> Path:
    override = normalize_string(options.get("checkpoint"))
    if override:
        return Path(override).expanduser().resolve()
    return (PAPYRUS_ROOT / ".papyrus-runs" / "graph-import" / f"{safe_id(import_run_id)}.checkpoint.json").resolve()


def _graph_import_change_digest(changes: list[dict[str, Any]]) -> str:
    rows = [
        {
            "action": change.get("action"),
            "modelName": change.get("modelName"),
            "id": (change.get("expected") or {}).get("id"),
        }
        for change in changes
    ]
    return hash_short(json.dumps(rows, sort_keys=True))


def _load_graph_import_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Graph import checkpoint is malformed JSON: {path}: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"Graph import checkpoint must be a JSON object: {path}")
    return parsed


def _write_graph_import_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_json_file(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _summarize_change_counts(changes: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    action_counts: dict[str, int] = {}
    model_counts: dict[str, int] = {}
    for change in changes:
        action = str(change.get("action") or "noop")
        model_name = str(change.get("modelName") or "unknown")
        action_counts[action] = action_counts.get(action, 0) + 1
        if action != "noop":
            model_counts[model_name] = model_counts.get(model_name, 0) + 1
    return action_counts, model_counts
