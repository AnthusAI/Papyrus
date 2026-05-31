from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .categories_steering import semantic_state_key
from .env import PAPYRUS_ROOT
from .ids import hash_short, knowledge_corpus_id, safe_id
from .options import normalize_string, parse_options
from .relation_types import semantic_relation_type_fields_for_predicate
from .steering import require_corpus_config

DEFAULT_ANALYSIS_PROFILES_PATH = PAPYRUS_ROOT / "corpora" / "papyrus-analysis-profiles.yml"
DEFAULT_BIBLICUS_WORKDIR = Path("/Users/ryan/Projects/Biblicus")

VALID_SCOPES = frozenset(
    {
        "global-topic-model",
        "scoped-topic-model",
        "topic-classifier-train",
        "topic-projection",
        "entity-graph",
    }
)
VALID_MODES = frozenset(
    {
        "online-update",
        "classifier-retrain",
        "scoped-topic-rebuild",
        "entity-graph-rebuild",
        "generated-analysis-rebuild",
    }
)
SAFE_OVERRIDE_KEYS = frozenset(
    {
        "text_source.sample_size",
        "text_source.min_text_characters",
        "lexical_processing.enabled",
        "lexical_processing.lowercase",
        "lexical_processing.strip_punctuation",
        "lexical_processing.collapse_whitespace",
        "entity_removal.enabled",
        "entity_removal.model",
        "entity_removal.entity_types",
        "entity_removal.regex_patterns",
        "bertopic_analysis.parameters.nr_topics",
        "bertopic_analysis.parameters.min_topic_size",
        "bertopic_analysis.vectorizer.ngram_range",
        "bertopic_analysis.vectorizer.stop_words",
        "bertopic_analysis.umap_model.parameters.n_neighbors",
        "bertopic_analysis.umap_model.parameters.n_components",
        "bertopic_analysis.umap_model.parameters.min_dist",
        "bertopic_analysis.umap_model.parameters.metric",
        "bertopic_analysis.hdbscan_model.parameters.min_cluster_size",
        "bertopic_analysis.hdbscan_model.parameters.min_samples",
        "bertopic_analysis.hdbscan_model.parameters.cluster_selection_method",
        "bertopic_analysis.representation_model.model",
        "bertopic_analysis.representation_model.nr_docs",
        "bertopic_analysis.representation_model.delay_in_seconds",
        "bertopic_analysis.representation_model",
        "targetTopicRange",
        "seedManifestPath",
        "authorityCorpusKey",
        "topK",
        "reviewThreshold",
        "extractionSnapshot",
        "steeringFeedbackPath",
        "graph.extractor",
        "graph.configurationName",
        "graph.model",
        "graph.min_entity_length",
        "graph.max_entity_length",
        "graph.entity_labels",
        "graph.include_item_node",
        "graph.include_relation_edges",
        "graph.max_relation_entities_per_sentence",
        "graph.min_relation_weight",
        "graph.max_items",
        "graph.item_timeout_seconds",
        "graph.item_retry_attempts",
        "graph.heartbeat_interval_seconds",
        "graph.min_mention_count",
        "graph.min_reference_count",
    }
)

ASSIGNMENT_TYPE_POLICIES = {
    "analysis.reindex": {
        "assignmentTypeKey": "analysis.reindex",
        "handlerKey": "analysis.reindex",
        "executionMode": "queued",
        "claimPolicy": "exclusive",
        "defaultClaimTtlSeconds": 6 * 60 * 60,
        "workProductPolicy": "assignment-events-and-messages",
        "description": "Runs explicit Biblicus re-index command plans for generated analysis outputs.",
    },
}


def load_analysis_profiles(filepath: str | Path | None = None) -> dict[str, Any]:
    resolved = Path(filepath or DEFAULT_ANALYSIS_PROFILES_PATH).resolve()
    parsed = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1 or not isinstance(parsed.get("profiles"), list):
        raise ValueError(f"Invalid analysis profile file: {resolved}")
    keys: set[str] = set()
    profiles = [_normalize_profile(entry, index, resolved) for index, entry in enumerate(parsed["profiles"])]
    for profile in profiles:
        key = profile["key"]
        if key in keys:
            raise ValueError(f"Duplicate analysis profile key {key} in {resolved}.")
        keys.add(key)
    return {"schemaVersion": 1, "filepath": str(resolved), "profiles": profiles}


def analysis_profile_by_key(config: dict[str, Any], key: str) -> dict[str, Any]:
    profile = next((entry for entry in config["profiles"] if entry["key"] == key), None)
    if profile is None:
        raise ValueError(f"Unknown analysis profile {key}.")
    return profile


def summarize_analysis_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "key": profile["key"],
            "title": profile["title"],
            "description": profile.get("description") or "",
            "scope": profile["scope"],
            "defaultMode": profile["defaultMode"],
            "corpusKey": profile.get("corpusKey"),
            "classifierId": profile.get("classifierId"),
            "configurationName": profile.get("configurationName"),
            "biblicus": profile.get("biblicus"),
            "defaults": profile.get("defaults"),
            "execution": profile.get("execution"),
            "allowedOverrides": profile.get("allowedOverrides"),
            "expectedOutputs": profile.get("expectedOutputs"),
        }
        for profile in config["profiles"]
    ]


def analysis_profiles(flags: list[str]) -> None:
    options = parse_options(flags)
    profiles_path = options.get("profiles") or str(DEFAULT_ANALYSIS_PROFILES_PATH)
    config = load_analysis_profiles(profiles_path)
    summaries = summarize_analysis_profiles(config)
    if options.get("json"):
        print(json.dumps({"profilesPath": config["filepath"], "profiles": summaries}, indent=2))
        return
    for profile in summaries:
        print(
            f"{profile['key']}\t{profile['scope']}\t{profile['defaultMode']}\t"
            f"{profile.get('corpusKey') or ''}\t{profile['title']}"
        )


def validate_analysis_profiles(flags: list[str]) -> None:
    options = parse_options(flags)
    profiles_path = options.get("profiles") or str(DEFAULT_ANALYSIS_PROFILES_PATH)
    config = load_analysis_profiles(profiles_path)
    print(f"analysis-profiles\tvalid\t{config['filepath']}\t{len(config['profiles'])}")


def parse_analysis_overrides(values: list[str] | str | None, profile: dict[str, Any]) -> dict[str, Any]:
    entries = values if isinstance(values, list) else ([values] if values else [])
    parsed: dict[str, Any] = {}
    for entry in entries:
        text = str(entry or "")
        equals_index = text.find("=")
        if equals_index <= 0:
            raise ValueError(f"Invalid override {text}; expected key=value.")
        key = text[:equals_index].strip()
        if key not in profile.get("allowedOverrides", []):
            raise ValueError(f"Override {key} is not allowed for profile {profile['key']}.")
        parsed[key] = _parse_override_value(text[equals_index + 1 :].strip())
    return parsed


def build_analysis_reindex_plan(
    *,
    profiles_config: dict[str, Any],
    steering_config: dict[str, Any],
    profile_key: str,
    corpus_key: str | None = None,
    mode: str | None = None,
    overrides: dict[str, Any] | None = None,
    now: str | None = None,
    run_id: str | None = None,
    biblicus_workdir: str | Path | None = None,
    category_set_id: str | None = None,
    category_key: str | None = None,
) -> dict[str, Any]:
    profile = analysis_profile_by_key(profiles_config, profile_key)
    selected_mode = mode or profile["defaultMode"]
    if selected_mode not in VALID_MODES:
        raise ValueError(f"Unsupported re-index mode {selected_mode}.")
    override_values = overrides or {}
    _validate_override_object(override_values, profile)
    selected_corpus_key = corpus_key or profile.get("corpusKey")
    if not selected_corpus_key:
        raise ValueError(f"Analysis profile {profile['key']} requires a corpus key.")
    corpus = require_corpus_config(steering_config, selected_corpus_key, "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus)
    classifier_id = (
        normalize_string(override_values.get("classifierId"))
        or profile.get("classifierId")
        or _resolve_classifier_id(steering_config, corpus)
    )
    raw_effective = {**profile.get("defaults", {}), **override_values}
    generated_at = now or _utc_now()
    resolved_run_id = run_id or (
        f"analysis-reindex-{safe_id(profile['key'])}-{safe_id(selected_corpus_key)}-"
        f"{hash_short([selected_mode, raw_effective])}"
    )
    resolved_biblicus_workdir = Path(
        biblicus_workdir or os.environ.get("BIBLICUS_WORKDIR") or DEFAULT_BIBLICUS_WORKDIR
    ).resolve()
    effective = _resolve_parameter_placeholders(
        raw_effective,
        {
            "runId": resolved_run_id,
            "profileKey": profile["key"],
            "corpusKey": selected_corpus_key,
            "corpusId": corpus_id,
            "classifierId": classifier_id,
            "biblicusWorkdir": str(resolved_biblicus_workdir),
        },
    )
    steering_feedback = normalize_string(effective.get("steeringFeedbackPath"))
    if steering_feedback and not Path(steering_feedback).is_absolute():
        effective["steeringFeedbackPath"] = str(Path.cwd() / steering_feedback)
    command_plan = _build_command_plan(
        profile=profile,
        mode=selected_mode,
        corpus=corpus,
        classifier_id=classifier_id,
        effective=effective,
        steering_config=steering_config,
        biblicus_workdir=resolved_biblicus_workdir,
    )
    return {
        "schemaVersion": 1,
        "kind": "papyrus.analysis.reindex.plan",
        "runId": resolved_run_id,
        "generatedAt": generated_at,
        "profile": {
            "key": profile["key"],
            "title": profile["title"],
            "description": profile.get("description") or "",
            "scope": profile["scope"],
            "defaultMode": profile["defaultMode"],
        },
        "mode": selected_mode,
        "corpus": {
            "key": corpus["key"],
            "id": corpus_id,
            "name": corpus.get("name"),
            "path": corpus.get("path"),
            "role": corpus.get("role"),
        },
        "classifierId": classifier_id,
        "categorySetId": category_set_id,
        "categoryKey": category_key,
        "profilesPath": profiles_config["filepath"],
        "steeringConfigPath": steering_config.get("configPath"),
        "biblicusWorkdir": str(resolved_biblicus_workdir),
        "parameterOverrides": override_values,
        "effectiveParameters": effective,
        "execution": profile.get("execution") or {},
        "commandPlan": command_plan,
        "destructivePlan": _build_destructive_plan(
            mode=selected_mode,
            profile=profile,
            corpus_id=corpus_id,
            classifier_id=classifier_id,
            category_set_id=category_set_id,
            category_key=category_key,
        ),
        "expectedOutputs": profile.get("expectedOutputs") or [],
        "warnings": _build_plan_warnings(profile, effective),
    }


def build_analysis_reindex_assignment_records(
    plan: dict[str, Any],
    *,
    category_set: dict[str, Any] | None = None,
    section_target: dict[str, Any] | None = None,
    existing: dict[str, dict[str, dict[str, Any]]] | None = None,
    now: str | None = None,
    actor_label: str = "papyrus-cli",
) -> dict[str, Any]:
    existing = existing or {}
    assignment_type_key = "analysis.reindex"
    assignment_type_policy = get_assignment_type_policy(assignment_type_key)
    assignment_id = (
        f"assignment-analysis-reindex-{safe_id(plan['corpus']['key'])}-{safe_id(plan['profile']['key'])}-"
        f"{hash_short([plan['mode'], plan.get('parameterOverrides'), plan.get('categoryKey') or '', plan.get('runId') or ''])}"
    )
    queue_key = f"analysis:reindex:{safe_id(plan['corpus']['key'])}:{plan['profile']['scope']}"
    timestamp = now or plan["generatedAt"]
    metadata = {
        "kind": "analysis.reindex.requested",
        "analysisProfileKey": plan["profile"]["key"],
        "analysisProfileTitle": plan["profile"]["title"],
        "analysisScope": plan["profile"]["scope"],
        "reindexMode": plan["mode"],
        "corpusKey": plan["corpus"]["key"],
        "corpusId": plan["corpus"]["id"],
        "classifierId": plan["classifierId"],
        "categorySetId": plan.get("categorySetId"),
        "categoryKey": plan.get("categoryKey"),
        "sectionId": section_target.get("id") if section_target else None,
        "sectionKey": section_target.get("id") if section_target else None,
        "sectionTitle": section_target.get("title") if section_target else None,
        "sectionType": "floating" if section_target and section_target.get("type") == "rotating" else (section_target or {}).get("type"),
        "sectionMission": (section_target or {}).get("editorialMission"),
        "sectionPolicies": [(section_target or {}).get("editorialPolicy")] if section_target and section_target.get("editorialPolicy") else [],
        "assignmentGuidance": (section_target or {}).get("assignmentGuidance"),
        "killCriteria": (section_target or {}).get("killCriteria"),
        "visualGuidance": (section_target or {}).get("visualGuidance"),
        "primaryFocusCategoryKey": plan.get("categoryKey"),
        "topicScopeCategoryKeys": [plan["categoryKey"]] if plan.get("categoryKey") else [],
        "parameterOverrides": plan.get("parameterOverrides"),
        "effectiveParameters": plan.get("effectiveParameters"),
        "commandPlan": plan.get("commandPlan"),
        "destructivePlan": plan.get("destructivePlan"),
        "assignmentTypePolicy": assignment_type_policy,
        "expectedOutputs": plan.get("expectedOutputs"),
        "execution": plan.get("execution"),
        "planRunId": plan.get("runId"),
        "profilesPath": plan.get("profilesPath"),
        "steeringConfigPath": plan.get("steeringConfigPath"),
        "biblicusWorkdir": plan.get("biblicusWorkdir"),
    }
    assignment = {
        "id": assignment_id,
        "assignmentTypeKey": assignment_type_key,
        "queueKey": queue_key,
        "queueStatusKey": f"{queue_key}#open",
        "status": "open",
        "priority": 40,
        "title": f"Re-index {plan['profile']['title']}",
        "brief": f"Prepare {plan['mode']} for {plan['corpus']['key']} using {plan['profile']['key']}.",
        "instructions": (
            "Inspect this dry-run command plan, confirm the generated-analysis cleanup scope, "
            "then run Biblicus explicitly. Creating this assignment must not execute analysis or cleanup."
        ),
        "assigneeType": None,
        "assigneeId": None,
        "assigneeKey": None,
        "claimedAt": None,
        "claimExpiresAt": None,
        "completedAt": None,
        "canceledAt": None,
        "corpusId": plan["corpus"]["id"],
        "categorySetId": plan.get("categorySetId"),
        "classifierId": plan["classifierId"],
        **assignment_section_fields(
            section_target=section_target,
            status="open",
            queue_key=queue_key,
            primary_focus_category_key=plan.get("categoryKey"),
            topic_scope_category_keys=[plan["categoryKey"]] if plan.get("categoryKey") else [],
        ),
        "sourceSnapshotId": normalize_string((plan.get("effectiveParameters") or {}).get("extractionSnapshot")),
        "importRunId": None,
        "createdBy": actor_label,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "metadata": json.dumps(metadata),
    }
    event = {
        "id": f"assignment-event-{assignment_id}-created",
        "assignmentId": assignment_id,
        "assignmentTypeKey": assignment["assignmentTypeKey"],
        "queueKey": queue_key,
        "eventType": "created",
        "fromStatus": None,
        "toStatus": "open",
        "actorSub": None,
        "actorLabel": actor_label,
        "note": "Created re-index assignment from analysis profile.",
        "createdAt": timestamp,
        "metadata": json.dumps(
            {
                "kind": "analysis.reindex.assignment_created",
                "analysisProfileKey": plan["profile"]["key"],
                "reindexMode": plan["mode"],
                "corpusKey": plan["corpus"]["key"],
                "commandCount": len(plan.get("commandPlan") or []),
            }
        ),
    }
    records = [
        _with_action("Assignment", assignment, existing),
        _with_action("AssignmentEvent", event, existing),
    ]
    if category_set:
        records.append(
            _with_action(
                "SemanticRelation",
                _semantic_relation_record(
                    {
                        "predicate": "requests_work_on",
                        "subjectKind": "assignment",
                        "subjectId": assignment_id,
                        "subjectLineageId": assignment_id,
                        "subjectVersionNumber": None,
                        "objectKind": "categorySet",
                        "objectId": category_set["id"],
                        "objectLineageId": category_set.get("lineageId") or category_set["id"],
                        "objectVersionNumber": category_set.get("versionNumber"),
                        "rank": 1,
                        "classifierId": plan["classifierId"],
                        "importedAt": timestamp,
                        "metadata": {
                            "analysisProfileKey": plan["profile"]["key"],
                            "reindexMode": plan["mode"],
                            "corpusKey": plan["corpus"]["key"],
                        },
                    }
                ),
                existing,
            )
        )
    if section_target:
        records.append(
            _with_action(
                "SemanticRelation",
                _semantic_relation_record(
                    {
                        "predicate": "targets_section",
                        "subjectKind": "assignment",
                        "subjectId": assignment_id,
                        "subjectLineageId": assignment_id,
                        "subjectVersionNumber": None,
                        "objectKind": "newsroomSection",
                        "objectId": section_target["id"],
                        "objectLineageId": section_target["id"],
                        "objectVersionNumber": None,
                        "rank": 1,
                        "importedAt": timestamp,
                        "metadata": {
                            "analysisProfileKey": plan["profile"]["key"],
                            "reindexMode": plan["mode"],
                            "corpusKey": plan["corpus"]["key"],
                            "sectionKey": section_target["id"],
                            "sectionTitle": section_target.get("title"),
                        },
                    }
                ),
                existing,
            )
        )
    return {"assignment": assignment, "records": records, "metadata": metadata}


def get_assignment_type_policy(assignment_type_key: str) -> dict[str, Any]:
    policy = ASSIGNMENT_TYPE_POLICIES.get(assignment_type_key)
    if policy is None:
        raise ValueError(f"Unknown assignment type {assignment_type_key}.")
    return policy


def assignment_section_fields(
    *,
    section_target: dict[str, Any] | None = None,
    status: str = "open",
    queue_key: str | None = None,
    primary_focus_category_key: str | None = None,
    topic_scope_category_keys: list[str] | None = None,
) -> dict[str, Any]:
    section_key = _assignment_section_key(section_target)
    normalized_status = normalize_string(status) or "open"
    normalized_queue_key = normalize_string(queue_key)
    return {
        "sectionId": normalize_string(section_target.get("id")) if section_target else section_key,
        "sectionKey": section_key,
        "sectionType": _normalize_section_type(section_target.get("type") if section_target else None),
        "sectionStatusKey": f"{section_key}#{normalized_status}" if section_key else None,
        "sectionQueueStatusKey": (
            f"{section_key}#{normalized_queue_key}#{normalized_status}"
            if section_key and normalized_queue_key
            else None
        ),
        "primaryFocusCategoryKey": normalize_string(primary_focus_category_key),
        "topicScopeCategoryKeys": [value for value in (topic_scope_category_keys or []) if value],
    }


def print_analysis_reindex_plan(plan: dict[str, Any]) -> None:
    print(f"analysis-reindex\tprofile\t{plan['profile']['key']}\t{plan['profile']['scope']}")
    print(f"analysis-reindex\tmode\t{plan['mode']}")
    print(f"analysis-reindex\tcorpus\t{plan['corpus']['key']}\t{plan['corpus']['id']}")
    execution = plan.get("execution") or {}
    if execution.get("maxRuntimeSeconds"):
        print(f"analysis-reindex\tmax-runtime-seconds\t{execution['maxRuntimeSeconds']}")
    for key, value in (execution.get("successCriteria") or {}).items():
        if value is not None:
            print(f"analysis-reindex\tsuccess-criteria\t{key}\t{value}")
    command_plan = plan.get("commandPlan") or []
    print(f"analysis-reindex\tcommands\t{len(command_plan)}")
    for command in command_plan:
        print(f"analysis-reindex\tcommand\t{command['label']}\t{command['executable']} {' '.join(command['args'])}")
    destructive = plan.get("destructivePlan") or {}
    print(f"analysis-reindex\tdestructive-now\t{'yes' if destructive.get('mutatesGraphqlNow') else 'no'}")
    for generated_output in destructive.get("generatedOutputs") or []:
        print(f"analysis-reindex\tgenerated-output\t{generated_output['modelName']}\t{generated_output['note']}")
    for warning in plan.get("warnings") or []:
        print(f"analysis-reindex\twarning\t{warning}")


def _normalize_profile(entry: Any, index: int, filepath: Path) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"Profile at index {index} in {filepath} must be an object.")
    key = _require_string(entry, "key", filepath, index)
    scope = _require_string(entry, "scope", filepath, index)
    default_mode = _require_string(entry, "defaultMode", filepath, index)
    if scope not in VALID_SCOPES:
        raise ValueError(f"Analysis profile {key} has unsupported scope {scope}.")
    if default_mode not in VALID_MODES:
        raise ValueError(f"Analysis profile {key} has unsupported defaultMode {default_mode}.")
    allowed_overrides = _normalize_string_array(entry.get("allowedOverrides"))
    for override_key in allowed_overrides:
        if override_key not in SAFE_OVERRIDE_KEYS:
            raise ValueError(f"Analysis profile {key} allows unsafe override {override_key}.")
    biblicus = entry.get("biblicus") if isinstance(entry.get("biblicus"), dict) else {}
    return {
        "key": key,
        "title": normalize_string(entry.get("title")) or key,
        "description": normalize_string(entry.get("description")) or "",
        "scope": scope,
        "defaultMode": default_mode,
        "corpusKey": normalize_string(entry.get("corpusKey")),
        "classifierId": normalize_string(entry.get("classifierId")),
        "configurationName": normalize_string(entry.get("configurationName")) or key,
        "biblicus": {
            "extractor": normalize_string(biblicus.get("extractor")),
            "configurations": _normalize_string_array(biblicus.get("configurations")),
        },
        "defaults": entry.get("defaults") if isinstance(entry.get("defaults"), dict) else {},
        "execution": _normalize_execution_profile(entry.get("execution")),
        "allowedOverrides": allowed_overrides,
        "expectedOutputs": _normalize_string_array(entry.get("expectedOutputs")),
    }


def _normalize_execution_profile(execution: Any) -> dict[str, Any]:
    source = execution if isinstance(execution, dict) else {}
    max_runtime = source.get("maxRuntimeSeconds")
    if max_runtime is None or max_runtime == "":
        max_runtime_seconds = None
    else:
        max_runtime_seconds = int(max_runtime)
        if max_runtime_seconds <= 0:
            raise ValueError("Analysis profile execution.maxRuntimeSeconds must be a positive integer.")
    criteria = source.get("successCriteria") if isinstance(source.get("successCriteria"), dict) else {}
    return {
        "maxRuntimeSeconds": max_runtime_seconds,
        "successCriteria": {
            "minNodes": _normalize_optional_number(criteria.get("minNodes"), "execution.successCriteria.minNodes"),
            "minEdges": _normalize_optional_number(criteria.get("minEdges"), "execution.successCriteria.minEdges"),
            "maxErrorRate": _normalize_optional_number(criteria.get("maxErrorRate"), "execution.successCriteria.maxErrorRate"),
        },
    }


def _build_command_plan(
    *,
    profile: dict[str, Any],
    mode: str,
    corpus: dict[str, Any],
    classifier_id: str,
    effective: dict[str, Any],
    steering_config: dict[str, Any],
    biblicus_workdir: Path,
) -> list[dict[str, Any]]:
    corpus_path = corpus.get("path") or f"corpora/{corpus['key']}"
    extraction_snapshot = normalize_string(effective.get("extractionSnapshot")) or "<extraction-snapshot>"
    configuration_name = normalize_string(effective.get("graph.configurationName")) or profile["configurationName"]
    configurations = profile.get("biblicus", {}).get("configurations") or []
    if profile["scope"] == "global-topic-model":
        return [
            _command(
                "topic-granularity-sweep",
                biblicus_workdir,
                [
                    "analyze",
                    "topic-granularity-sweep",
                    "--corpus",
                    corpus_path,
                    *_configuration_args(configurations),
                    *_override_args(effective, profile, exclude={"targetTopicRange", "extractionSnapshot"}),
                    "--configuration-name",
                    configuration_name,
                    "--extraction-snapshot",
                    extraction_snapshot,
                    "--target-topic-range",
                    normalize_string(effective.get("targetTopicRange")) or "10:20",
                    "--format",
                    "json",
                ],
                mode=mode,
            )
        ]
    if profile["scope"] == "topic-classifier-train":
        manifest_path = normalize_string(effective.get("seedManifestPath")) or str(
            Path(corpus_path) / "metadata" / "topic-classifiers" / classifier_id / "seed-manifest.json"
        )
        return [
            _command(
                "topic-classifier-train",
                biblicus_workdir,
                [
                    "topic-classifier",
                    "train",
                    "--corpus",
                    corpus_path,
                    "--manifest",
                    manifest_path,
                    *_configuration_args(configurations),
                    *_override_args(effective, profile, exclude={"seedManifestPath", "extractionSnapshot"}),
                    "--configuration-name",
                    configuration_name,
                    "--extraction-snapshot",
                    extraction_snapshot,
                ],
                mode=mode,
            )
        ]
    if profile["scope"] == "scoped-topic-model":
        steering_feedback_path = normalize_string(effective.get("steeringFeedbackPath"))
        args = [
            "taxonomy",
            "discover",
            "--corpus",
            corpus_path,
            "--classifier",
            classifier_id,
            "--extraction-snapshot",
            extraction_snapshot,
            "--format",
            "json",
        ]
        if steering_feedback_path:
            args.extend(["--steering-feedback", steering_feedback_path])
        return [_command("taxonomy-discover", biblicus_workdir, args, mode=mode)]
    if profile["scope"] == "topic-projection":
        authority_corpus_key = (
            normalize_string(effective.get("authorityCorpusKey"))
            or (corpus.get("canonicalProjection") or {}).get("authorityCorpusKey")
            or (steering_config.get("canonicalTopicSet") or {}).get("corpusKey")
        )
        authority_corpus = (
            require_corpus_config(steering_config, authority_corpus_key, "authorityCorpusKey")
            if authority_corpus_key
            else corpus
        )
        authority_path = authority_corpus.get("path") or f"corpora/{authority_corpus['key']}"
        return [
            _command(
                "topic-classifier-project",
                biblicus_workdir,
                [
                    "topic-classifier",
                    "project",
                    "--classifier-corpus",
                    authority_path,
                    "--target-corpus",
                    corpus_path,
                    "--classifier",
                    classifier_id,
                    "--extraction-snapshot",
                    extraction_snapshot,
                    "--all",
                    "--top-k",
                    str(effective.get("topK", 5)),
                    "--review-threshold",
                    str(effective.get("reviewThreshold", 0.35)),
                    "--format",
                    "json",
                ],
                mode=mode,
            )
        ]
    if profile["scope"] == "entity-graph":
        extractor = normalize_string(effective.get("graph.extractor")) or profile.get("biblicus", {}).get("extractor") or "ner-entities"
        return [
            _command(
                "graph-extract",
                biblicus_workdir,
                [
                    "graph",
                    "extract",
                    "--corpus",
                    corpus_path,
                    "--extractor",
                    extractor,
                    "--extraction-snapshot",
                    extraction_snapshot,
                    "--configuration-name",
                    configuration_name,
                    *_configuration_args(configurations),
                    *_graph_override_args(effective, profile),
                ],
                mode=mode,
                extras=["topic-modeling", "openai", "neo4j", "ner"],
            )
        ]
    raise ValueError(f"Unsupported analysis profile scope {profile['scope']}.")


def _build_destructive_plan(
    *,
    mode: str,
    profile: dict[str, Any],
    corpus_id: str,
    classifier_id: str,
    category_set_id: str | None,
    category_key: str | None,
) -> dict[str, Any]:
    generated: list[dict[str, Any]] = []
    if mode in {"generated-analysis-rebuild", "classifier-retrain", "online-update"}:
        generated.append(
            {
                "modelName": "SemanticRelation",
                "relationTypes": ["classified_as"],
                "corpusId": corpus_id,
                "classifierId": classifier_id,
                "note": "Generated projection predictions can be cleared for this profile before importing a fresh projection.",
            }
        )
    if mode == "entity-graph-rebuild" or (mode == "generated-analysis-rebuild" and profile["scope"] == "entity-graph"):
        generated.append(
            {
                "modelName": "SemanticNode/SemanticRelation",
                "relationDomains": ["ontology"],
                "corpusId": corpus_id,
                "note": "Generated graph nodes and graph relations should be cleared only by recorded graph import provenance.",
            }
        )
    if mode == "scoped-topic-rebuild":
        generated.append(
            {
                "modelName": "SteeringProposal",
                "corpusId": corpus_id,
                "categorySetId": category_set_id,
                "categoryKey": category_key,
                "note": "Scoped topic discovery emits proposals; reviewed accepted/rejected decisions remain application-owned.",
            }
        )
    return {
        "mutatesGraphqlNow": False,
        "executesBiblicusNow": False,
        "mode": mode,
        "profileKey": profile["key"],
        "targetCorpusId": corpus_id,
        "generatedOutputs": generated,
        "preservedRecords": [
            "Reference",
            "ReferenceAttachment",
            "Message",
            "CategorySet",
            "Category",
            "authoritative labels",
            "review decisions",
        ],
    }


def _build_plan_warnings(profile: dict[str, Any], effective: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    snapshot = normalize_string(effective.get("extractionSnapshot"))
    if not snapshot or "<" in snapshot:
        warnings.append("Extraction snapshot is a placeholder and must be resolved before execution.")
    if profile["scope"] == "scoped-topic-model" and not normalize_string(effective.get("steeringFeedbackPath")):
        warnings.append("No steering feedback path is configured; Biblicus may re-emit previously rejected topic proposals.")
    warnings.append(
        "analysis run-now and execute-assignment sync corpora/<key>/ from S3 when the local catalog is missing or stale; "
        "pass --skip-sync-from-cloud to skip or --sync-from-cloud to force a pull."
    )
    return warnings


def _resolve_parameter_placeholders(value: Any, context: dict[str, str]) -> Any:
    if isinstance(value, str):
        return (
            value.replace("<run-id>", context["runId"])
            .replace("<profile-key>", context["profileKey"])
            .replace("<corpus-key>", context["corpusKey"])
            .replace("<corpus-id>", context["corpusId"])
            .replace("<classifier-id>", context["classifierId"])
            .replace("<biblicus-workdir>", context["biblicusWorkdir"])
        )
    if isinstance(value, list):
        return [_resolve_parameter_placeholders(entry, context) for entry in value]
    if isinstance(value, dict):
        return {key: _resolve_parameter_placeholders(entry, context) for key, entry in value.items()}
    return value


def _validate_override_object(overrides: dict[str, Any], profile: dict[str, Any]) -> None:
    for key in overrides:
        if key not in profile.get("allowedOverrides", []):
            raise ValueError(f"Override {key} is not allowed for profile {profile['key']}.")


def _configuration_args(configurations: list[str]) -> list[str]:
    args: list[str] = []
    for configuration in configurations:
        args.extend(["--configuration", configuration])
    return args


def _override_args(
    effective: dict[str, Any],
    profile: dict[str, Any],
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    exclude = exclude or set()
    args: list[str] = []
    for key, value in effective.items():
        if key not in profile.get("allowedOverrides", []):
            continue
        if key in exclude or str(key).startswith("graph."):
            continue
        args.extend(["--override", f"{key}={_format_override_value(value)}"])
    return args


def _graph_override_args(effective: dict[str, Any], profile: dict[str, Any]) -> list[str]:
    graph_key_map = {
        "graph.model": "model",
        "graph.min_entity_length": "min_entity_length",
        "graph.max_entity_length": "max_entity_length",
        "graph.entity_labels": "entity_labels",
        "graph.include_item_node": "include_item_node",
        "graph.include_relation_edges": "include_relation_edges",
        "graph.max_relation_entities_per_sentence": "max_relation_entities_per_sentence",
        "graph.min_relation_weight": "min_relation_weight",
    }
    args: list[str] = []
    for key, mapped in graph_key_map.items():
        if key in profile.get("allowedOverrides", []) and key in effective:
            args.extend(["--override", f"{mapped}={_format_override_value(effective[key])}"])
    if "graph.item_timeout_seconds" in profile.get("allowedOverrides", []) and effective.get("graph.item_timeout_seconds") is not None:
        args.extend(["--item-timeout-seconds", str(effective["graph.item_timeout_seconds"])])
    if "graph.item_retry_attempts" in profile.get("allowedOverrides", []) and effective.get("graph.item_retry_attempts") is not None:
        args.extend(["--item-retry-attempts", str(effective["graph.item_retry_attempts"])])
    if "graph.heartbeat_interval_seconds" in profile.get("allowedOverrides", []) and effective.get("graph.heartbeat_interval_seconds") is not None:
        args.extend(["--heartbeat-interval-seconds", str(effective["graph.heartbeat_interval_seconds"])])
    if "graph.max_items" in profile.get("allowedOverrides", []) and effective.get("graph.max_items") is not None:
        args.extend(["--max-items", str(effective["graph.max_items"])])
    return args


def _command(
    label: str,
    cwd: Path,
    args: list[str],
    *,
    mode: str,
    extras: list[str] | None = None,
) -> dict[str, Any]:
    extra_values = extras or ["topic-modeling", "openai"]
    uv_args: list[str] = ["run"]
    for extra in extra_values:
        uv_args.extend(["--extra", extra])
    uv_args.extend(["biblicus", *args])
    return {
        "label": label,
        "cwd": str(cwd),
        "executable": "uv",
        "args": uv_args,
        "metadata": {"mode": mode},
    }


def _resolve_classifier_id(steering_config: dict[str, Any], corpus: dict[str, Any]) -> str:
    local_classifiers = corpus.get("localClassifiers") or []
    if local_classifiers and local_classifiers[0].get("classifierId"):
        return str(local_classifiers[0]["classifierId"])
    canonical_projection = corpus.get("canonicalProjection") or {}
    if canonical_projection.get("classifierId"):
        return str(canonical_projection["classifierId"])
    canonical_topic_set = steering_config.get("canonicalTopicSet") or {}
    if canonical_topic_set.get("corpusKey") == corpus.get("key") and canonical_topic_set.get("classifierId"):
        return str(canonical_topic_set["classifierId"])
    return f"{safe_id(corpus.get('key') or corpus.get('name') or 'corpus')}-classifier"


def _semantic_relation_record(input_value: dict[str, Any]) -> dict[str, Any]:
    subject_state_key = semantic_state_key(input_value["subjectKind"], input_value["subjectLineageId"])
    object_state_key = semantic_state_key(input_value["objectKind"], input_value["objectLineageId"])
    subject_version_key = _semantic_version_key(input_value["subjectKind"], input_value["subjectId"])
    object_version_key = _semantic_version_key(input_value["objectKind"], input_value["objectId"])
    return {
        "id": f"semantic-relation-{hash_short([subject_version_key, input_value['predicate'], object_version_key, input_value.get('rank'), input_value.get('classifierId')])}",
        "relationState": "current",
        "predicate": input_value["predicate"],
        **semantic_relation_type_fields_for_predicate(input_value["predicate"]),
        "subjectKind": input_value["subjectKind"],
        "subjectId": input_value["subjectId"],
        "subjectLineageId": input_value["subjectLineageId"],
        "subjectVersionNumber": input_value.get("subjectVersionNumber"),
        "objectKind": input_value["objectKind"],
        "objectId": input_value["objectId"],
        "objectLineageId": input_value["objectLineageId"],
        "objectVersionNumber": input_value.get("objectVersionNumber"),
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#{input_value['subjectKind']}",
        "predicateObjectStateKey": f"{input_value['predicate']}#{object_state_key}",
        "subjectVersionKey": subject_version_key,
        "objectVersionKey": object_version_key,
        "score": float(input_value["score"]) if isinstance(input_value.get("score"), (int, float)) else 1,
        "confidence": None,
        "rank": input_value.get("rank"),
        "classifierId": input_value.get("classifierId"),
        "modelVersion": None,
        "reviewRecommended": False,
        "sourceSnapshotId": None,
        "importRunId": None,
        "importedAt": input_value.get("importedAt"),
        "createdAt": input_value.get("createdAt") or input_value.get("importedAt"),
        "updatedAt": input_value.get("updatedAt") or input_value.get("importedAt"),
        "newsroomFeedKey": "semanticRelations",
        "metadata": json.dumps(input_value.get("metadata") or {}),
    }


def _with_action(
    model_name: str,
    expected: dict[str, Any],
    existing: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    current = (existing.get(model_name) or {}).get(expected["id"])
    if current and model_name in {"Assignment", "AssignmentEvent", "SemanticRelation"}:
        return {"modelName": model_name, "expected": current, "current": current, "action": "noop"}
    return {
        "modelName": model_name,
        "expected": expected,
        "current": current,
        "action": "update" if current else "create",
    }


def _assignment_section_key(section_target: dict[str, Any] | None) -> str | None:
    if not section_target:
        return None
    return normalize_string(section_target.get("id")) or normalize_string(section_target.get("sectionKey"))


def _normalize_section_type(value: Any) -> str | None:
    normalized = normalize_string(value)
    if normalized and normalized.lower() == "rotating":
        return "floating"
    return normalized.lower() if normalized else None


def _parse_override_value(value: str) -> Any:
    if value == "true":
        return True
    if value == "false":
        return False
    if value == "null":
        return None
    if value.replace(".", "", 1).replace("-", "", 1).isdigit():
        return float(value) if "." in value else int(value)
    if (value.startswith("[") and value.endswith("]")) or (value.startswith("{") and value.endswith("}")):
        return json.loads(value)
    return value


def _format_override_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


def _normalize_string_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry for entry in (normalize_string(item) for item in value) if entry]


def _normalize_optional_number(value: Any, label: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Analysis profile {label} must be numeric.") from error


def _require_string(entry: dict[str, Any], field: str, filepath: Path, index: int) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Profile at index {index} in {filepath} requires {field}.")
    return value.strip()


def _semantic_version_key(kind: str, version_id: str) -> str:
    return f"{kind}#{version_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
