from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .biblicus_runner import BiblicusCommandError, BiblicusRunner
from .env import PAPYRUS_ROOT
from .ids import (
    category_lineage_id_for,
    category_set_id_for,
    hash_short,
    hash_stable,
    knowledge_corpus_id,
    reference_lineage_id_for,
    safe_id,
    semantic_node_lineage_id_for,
)
from .relation_types import semantic_relation_type_fields_for_predicate
from .papyrus_config import resolve_topics_ignore_terms, resolve_topics_lexical_config_path

DEFAULT_SEMANTIC_CONCEPTS_PATH = PAPYRUS_ROOT / "corpora" / "papyrus-semantic-concepts.yml"
DEFAULT_LEXICAL_STEERING_PATH = PAPYRUS_ROOT / resolve_topics_lexical_config_path()
GRAPH_PROPOSAL_KINDS = frozenset(
    {
        "topic-becomes-graph-entity",
        "topic-maps-to-existing-graph-entity",
        "entity-alias-edit",
        "entity-description-edit",
        "relationship-proposal",
        "merge-graph-entity",
        "deprecate-graph-entity",
    }
)
REVIEWED_PROPOSAL_STATUSES = frozenset({"accepted", "rejected", "deferred"})


def load_json_file(filepath: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(filepath).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {filepath}")
    return payload


def write_json_file(filepath: str | Path, payload: Any) -> None:
    target = Path(filepath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_steering_bundle_from_biblicus(
    *,
    corpus: str,
    classifier: str,
    topic_governance_snapshot: str | None = None,
    biblicus_workdir: str | Path | None = None,
) -> dict[str, Any]:
    if not corpus:
        raise ValueError("--corpus is required when --bundle is omitted.")
    if not classifier:
        raise ValueError("--classifier is required when --bundle is omitted.")
    from biblicus.steering import SteeringExportBundle

    arguments = ["steering", "export", "--corpus", corpus, "--classifier", classifier]
    if topic_governance_snapshot:
        arguments.extend(["--topic-governance-snapshot", topic_governance_snapshot])
    runner = BiblicusRunner.from_environment(workdir=biblicus_workdir)
    try:
        bundle = runner.run_typed(arguments, SteeringExportBundle)
    except BiblicusCommandError as error:
        raise RuntimeError(f"Biblicus steering export failed:\n{error.stderr or error.stdout}") from error
    return bundle.model_dump(mode="json")


def build_steering_import_records(bundle: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    now = options.get("importedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    corpus = bundle.get("corpus") or {}
    corpus_context = normalize_corpus_context(corpus, options.get("corpusConfig") or options.get("corpus"))
    corpus_id = options.get("corpusId") or knowledge_corpus_id(corpus_context)
    classifier_id = (bundle.get("topic_set") or {}).get("classifier_id") or options.get("classifierId") or "unknown-classifier"
    source_snapshot_id = latest_snapshot_id(bundle.get("artifacts"), "topic-governance")
    filtered_proposals, skipped_proposals = filter_ignored_proposals(
        bundle.get("proposals") or [],
        options.get("ignoredTerms"),
    )
    warning_payload = list(bundle.get("warnings") or [])
    if skipped_proposals:
        warning_payload.append(
            {
                "type": "lexical-ignore-filter",
                "message": "Skipped steering proposals that matched configured ignored terms.",
                "skippedCount": len(skipped_proposals),
                "proposalIds": [proposal.get("proposal_id") for proposal in skipped_proposals if proposal.get("proposal_id")],
            }
        )
    import_run_id = (
        f"knowledge-import-{safe_id(corpus_id)}-{safe_id(classifier_id)}-"
        f"{hash_short([bundle.get('generated_at'), len(filtered_proposals), len(bundle.get('artifacts') or [])])}"
    )
    category_set_id = options.get("categorySetId") or category_set_id_for(classifier_id, corpus_id)
    records: list[dict[str, Any]] = []

    records.append(
        record(
            "KnowledgeCorpus",
            {
                "id": corpus_id,
                "name": corpus_context["name"],
                "role": corpus_context["role"],
                "itemCount": number_or_null(corpus.get("item_count")),
                "generatedAt": date_or_null(corpus.get("generated_at") or bundle.get("generated_at")),
                "latestImportRunId": import_run_id,
                "createdAt": now,
                "updatedAt": now,
            },
        )
    )
    records.append(raw_payload_record("corpus", corpus_id, "biblicus-corpus", corpus, import_run_id, now))
    records.append(
        record(
            "KnowledgeImportRun",
            {
                "id": import_run_id,
                "corpusId": corpus_id,
                "importKind": "steering-export",
                "classifierId": classifier_id,
                "sourceSnapshotId": source_snapshot_id,
                "status": "imported",
                "generatedAt": date_or_null(bundle.get("generated_at")),
                "importedAt": now,
                "itemCount": len(bundle.get("items") or []),
                "categoryCount": len((bundle.get("topic_set") or {}).get("topics") or []),
                "proposalCount": len(filtered_proposals),
                "artifactCount": len(bundle.get("artifacts") or []),
                "referenceCount": 0,
                "relationCount": 0,
                "warningCount": len(warning_payload),
            },
        )
    )
    records.append(
        raw_payload_record("importRun", import_run_id, "warnings", {"warnings": warning_payload}, import_run_id, now)
    )
    records.extend(seeded_semantic_concept_node_records({"corpusId": corpus_id, "importRunId": import_run_id, "now": now}))

    if bundle.get("topic_set"):
        records.extend(
            category_set_records(
                bundle["topic_set"],
                {
                    "corpusId": corpus_id,
                    "importRunId": import_run_id,
                    "categorySetId": category_set_id,
                    "now": now,
                    "generatedAt": bundle.get("generated_at"),
                },
            )
        )
        records.extend(
            taxonomy_records(
                bundle,
                {
                    "corpusId": corpus_id,
                    "corpusPath": options.get("corpusPath")
                    or (options.get("corpusConfig") or {}).get("path")
                    or (options.get("corpus") or {}).get("path"),
                    "importRunId": import_run_id,
                    "now": now,
                    "categorySetId": category_set_id,
                },
            )
        )

    for artifact in bundle.get("artifacts") or []:
        records.extend(artifact_records(artifact, {"corpusId": corpus_id, "importRunId": import_run_id, "now": now}))

    for proposal in filtered_proposals:
        records.extend(
            proposal_records(
                proposal,
                {"corpusId": corpus_id, "importRunId": import_run_id, "categorySetId": category_set_id, "now": now},
            )
        )
        records.extend(
            semantic_records_from_proposal(
                proposal,
                {"corpusId": corpus_id, "importRunId": import_run_id, "categorySetId": category_set_id, "now": now},
            )
        )

    import_run = next((entry for entry in records if entry["modelName"] == "KnowledgeImportRun"), None)
    if import_run:
        import_run["expected"]["relationCount"] = sum(1 for entry in records if entry["modelName"] == "SemanticRelation")

    return {
        "corpusId": corpus_id,
        "importRunId": import_run_id,
        "categorySetId": category_set_id,
        "records": records,
    }


def build_projection_import_records(payload: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    now = options.get("importedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    items = payload.get("items") or payload.get("predictions") or []
    first_item = items[0] if items else {}
    target_corpus = normalize_corpus_context(
        {"name": corpus_name_from_uri(first_item.get("target_corpus_uri")), "corpus_uri": first_item.get("target_corpus_uri")},
        options.get("targetCorpusConfig") or options.get("targetCorpus"),
    )
    authority_corpus = normalize_corpus_context(
        {"name": corpus_name_from_uri(first_item.get("classifier_corpus_uri")), "corpus_uri": first_item.get("classifier_corpus_uri")},
        options.get("authorityCorpusConfig") or options.get("authorityCorpus"),
        {"role": "canonical"},
    )
    target_corpus_id = options.get("targetCorpusId") or knowledge_corpus_id(target_corpus)
    authority_corpus_id = options.get("authorityCorpusId") or knowledge_corpus_id(authority_corpus)
    classifier_id = payload.get("classifier_id") or first_item.get("classifier_id") or options.get("classifierId") or "unknown-classifier"
    category_set_id = options.get("categorySetId") or category_set_id_for(classifier_id, authority_corpus_id)
    import_run_id = (
        f"knowledge-import-{safe_id(target_corpus_id)}-{safe_id(classifier_id)}-projection-"
        f"{hash_short(payload.get('summary') or items)}"
    )
    relation_records = projection_relation_records(
        items,
        {
            "targetCorpusId": target_corpus_id,
            "authorityCorpusId": authority_corpus_id,
            "categorySetId": category_set_id,
            "classifierId": classifier_id,
            "importRunId": import_run_id,
            "now": now,
        },
    )
    records: list[dict[str, Any]] = [
        record(
            "KnowledgeCorpus",
            {
                "id": target_corpus_id,
                "name": target_corpus["name"],
                "role": target_corpus["role"],
                "itemCount": None,
                "generatedAt": None,
                "latestImportRunId": import_run_id,
                "createdAt": now,
                "updatedAt": now,
            },
        ),
        record(
            "KnowledgeImportRun",
            {
                "id": import_run_id,
                "corpusId": target_corpus_id,
                "importKind": "topic-projection",
                "classifierId": classifier_id,
                "sourceSnapshotId": ((first_item.get("extraction_snapshot") or {}).get("snapshot_id")),
                "status": "imported",
                "generatedAt": None,
                "importedAt": now,
                "itemCount": 0,
                "categoryCount": 0,
                "proposalCount": 0,
                "artifactCount": 0,
                "referenceCount": len(items),
                "relationCount": len(relation_records),
                "warningCount": 0,
            },
        ),
        raw_payload_record("importRun", import_run_id, "projection-summary", payload.get("summary") or {}, import_run_id, now),
        *seeded_semantic_concept_node_records({"corpusId": target_corpus_id, "importRunId": import_run_id, "now": now}),
        *relation_records,
    ]
    for item in items:
        external_item_id = required_string(item.get("item_id"), "projection item_id")
        reference_lineage_id = reference_lineage_id_for(target_corpus_id, external_item_id)
        records.append(
            raw_payload_record(
                "projection",
                reference_lineage_id,
                "biblicus-projection",
                sanitize_projection_payload(item),
                import_run_id,
                now,
            )
        )
    import_run = next((entry for entry in records if entry["modelName"] == "KnowledgeImportRun"), None)
    if import_run:
        import_run["expected"]["relationCount"] = sum(1 for entry in records if entry["modelName"] == "SemanticRelation")
    return {"importRunId": import_run_id, "categorySetId": category_set_id, "records": records}


def build_steering_config_records(config: dict[str, Any], options: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    options = options or {}
    now = options.get("importedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        record(
            "KnowledgeCorpus",
            {
                "id": knowledge_corpus_id(corpus),
                "name": corpus["name"],
                "role": corpus["role"],
                "createdAt": now,
                "updatedAt": now,
            },
        )
        for corpus in config.get("corpora") or []
    ]


def build_lexical_steering_config_records(config: dict[str, Any], options: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    options = options or {}
    now = options.get("importedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return [
        lexical_steering_rule_record(
            {
                **rule,
                "source": rule.get("source") or "papyrus-lexical-steering.yml",
                "createdBy": rule.get("createdBy") or "papyrus-config",
                "createdAt": now,
                "updatedAt": now,
                "metadata": {
                    "configPath": config.get("configPath"),
                    "keywordDisplay": config.get("keywordDisplay"),
                },
            }
        )
        for rule in config.get("ignoredTerms") or []
    ]


def build_lexical_steering_payload(rules: list[dict[str, Any]] | None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    config = options.get("config")
    generated_at = options.get("generatedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    active_rules = []
    for rule in rules or []:
        if (rule.get("ruleKind") or rule.get("rule_kind")) != "ignored_keyword":
            continue
        if (rule.get("status") or "active") != "active":
            continue
        active_rules.append(
            {
                "rule_id": rule.get("id"),
                "rule_kind": "ignored_keyword",
                "term": rule.get("term"),
                "normalized_term": rule.get("normalizedTerm") or normalize_lexical_term(rule.get("term")),
                "scope": rule.get("scope") or "publication",
                "corpus_id": rule.get("corpusId"),
                "classifier_id": rule.get("classifierId"),
                "category_set_id": rule.get("categorySetId"),
                "category_key": rule.get("categoryKey"),
                "note": rule.get("note"),
                "source": rule.get("source"),
                "created_by": rule.get("createdBy"),
                "created_at": rule.get("createdAt"),
                "updated_at": rule.get("updatedAt"),
            }
        )
    active_rules.sort(key=_compare_lexical_rules_key)
    return {
        "schema_version": 1,
        "export_kind": "papyrus-lexical-steering",
        "generated_at": generated_at,
        "keyword_display": normalize_keyword_display(config.get("keywordDisplay") if config else {}, config.get("configPath") if config else "inline"),
        "ignored_terms": active_rules,
    }


def build_accepted_category_set_payload(category_set: dict[str, Any], topics: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_topics = sorted(
        topics,
        key=lambda topic: (
            topic.get("rank") if topic.get("rank") is not None else 999999,
            str(topic.get("categoryKey") or ""),
        ),
    )
    return {
        "schema_version": 1,
        "classifier_id": required_string(category_set.get("classifierId"), "categorySet.classifierId"),
        "display_name": required_string(category_set.get("displayName"), "categorySet.displayName"),
        "description": category_set.get("description") or "",
        "topics": [
            {
                "topic_uid": required_string(topic.get("categoryKey"), "topic.categoryKey"),
                "display_name": required_string(topic.get("displayName"), "topic.displayName"),
                "description": topic.get("description") or "",
                "seed_item_ids": compact_array(topic.get("seedItemIds")),
                "holdout_item_ids": compact_array(topic.get("holdoutItemIds")),
                **({"subheading": topic["subtitle"]} if topic.get("subtitle") else {}),
                **({"aliases": compact_array(topic.get("aliases"))} if compact_array(topic.get("aliases")) else {}),
                "ranking_hints": {"pinned": bool(topic.get("isPinned")), "rank": topic.get("rank")},
            }
            for topic in sorted_topics
        ],
        "unlabeled_policy": "use_minus_one",
    }


def build_accepted_category_tree_payload(taxonomy: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_nodes = sort_taxonomy_nodes(nodes)
    generated_at = (
        taxonomy.get("generatedAt")
        or taxonomy.get("updatedAt")
        or taxonomy.get("createdAt")
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "taxonomy_id": required_string(taxonomy.get("taxonomyId") or taxonomy.get("id"), "taxonomy.taxonomyId"),
        "display_name": required_string(taxonomy.get("displayName"), "taxonomy.displayName"),
        "description": taxonomy.get("description") or "",
        "generated_at": generated_at,
        "nodes": [
            {
                "topic_uid": required_string(node.get("categoryKey"), "node.categoryKey"),
                "parent_topic_uid": node.get("parentCategoryKey"),
                "display_name": required_string(node.get("displayName"), "node.displayName"),
                "description": node.get("description") or node.get("subtitle") or "",
                "status": "archived" if node.get("status") == "archived" else "accepted",
                "seed_item_ids": compact_array(node.get("seedItemIds")),
                "holdout_item_ids": compact_array(node.get("holdoutItemIds")),
                "source": {
                    "papyrus_category_set_id": taxonomy.get("id"),
                    "papyrus_category_id": node.get("id"),
                },
            }
            for node in sorted_nodes
        ],
        "source": {
            "system": "papyrus",
            "category_set_id": taxonomy.get("categorySetId") or taxonomy.get("id"),
            "corpus_id": taxonomy.get("corpusId"),
        },
    }
    if taxonomy.get("snapshotId"):
        payload["snapshot_id"] = taxonomy["snapshotId"]
    return payload


def build_steering_feedback_payload(
    category_set: dict[str, Any],
    proposals: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options = options or {}
    generated_at = options.get("generatedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    in_scope_proposals = sorted(
        [proposal for proposal in proposals if proposal.get("categorySetId") == category_set.get("id")],
        key=lambda proposal: str(proposal.get("id") or ""),
    )
    proposal_ids = {proposal["id"] for proposal in in_scope_proposals}
    in_scope_decisions = sorted(
        [
            decision
            for decision in decisions
            if decision.get("proposalId") in proposal_ids or decision.get("categorySetId") == category_set.get("id")
        ],
        key=lambda decision: (str(decision.get("createdAt") or ""), str(decision.get("id") or "")),
    )
    latest_decision_by_proposal: dict[str, dict[str, Any]] = {}
    for decision in in_scope_decisions:
        proposal_id = decision.get("proposalId")
        if proposal_id:
            latest_decision_by_proposal[proposal_id] = decision
    reviewed_proposals = sorted(
        [
            reviewed_proposal_feedback(proposal, latest_decision_by_proposal.get(proposal["id"]))
            for proposal in in_scope_proposals
            if proposal.get("status") in {"accepted", "rejected"}
        ],
        key=_compare_feedback_key,
    )
    accepted_proposals = [
        proposal
        for proposal in reviewed_proposals
        if proposal.get("human_action") == "accept" or proposal.get("status") == "accepted"
    ]
    rejected_proposals = [
        proposal
        for proposal in reviewed_proposals
        if proposal.get("human_action") == "reject" or proposal.get("status") == "rejected"
    ]
    return {
        "schema_version": 1,
        "export_kind": "papyrus-steering-feedback",
        "generated_at": generated_at,
        "source": {
            "system": "papyrus",
            "topic_set_id": category_set.get("id"),
            "corpus_id": category_set.get("corpusId"),
            "classifier_id": category_set.get("classifierId"),
        },
        "topic_set": {
            "topic_set_id": category_set.get("id"),
            "corpus_id": category_set.get("corpusId"),
            "classifier_id": category_set.get("classifierId"),
            "display_name": category_set.get("displayName"),
            "description": category_set.get("description"),
        },
        "decisions": [decision_feedback_record(decision) for decision in in_scope_decisions],
        "accepted_proposals": accepted_proposals,
        "rejected_proposals": rejected_proposals,
        "suppressions": [suppression_from_rejected_proposal(proposal, category_set) for proposal in rejected_proposals],
    }


def merge_reviewed_proposal_state(expected: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
    if not current or current.get("status") not in REVIEWED_PROPOSAL_STATUSES:
        return expected
    return {
        **expected,
        "status": current.get("status"),
        "reviewedAt": current.get("reviewedAt"),
        "reviewedBy": current.get("reviewedBy"),
    }


@lru_cache(maxsize=4)
def load_semantic_concept_seeds(filepath: str | None = None) -> tuple[dict[str, Any], ...]:
    path = Path(filepath) if filepath else DEFAULT_SEMANTIC_CONCEPTS_PATH
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1 or not isinstance(parsed.get("concepts"), list):
        raise ValueError(f"Invalid semantic concept seed file: {path}")
    return tuple(normalize_semantic_concept_seed(concept, index, str(path)) for index, concept in enumerate(parsed["concepts"]))


@lru_cache(maxsize=4)
def load_lexical_steering_config(filepath: str | None = None) -> dict[str, Any]:
    path = Path(filepath) if filepath else DEFAULT_LEXICAL_STEERING_PATH
    parsed: dict[str, Any] = {"schemaVersion": 1}
    if path.exists():
        parsed_value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(parsed_value, dict) or parsed_value.get("schemaVersion") != 1:
            raise ValueError(f"Invalid lexical steering config file: {path}")
        parsed = parsed_value
    elif filepath:
        raise ValueError(f"Invalid lexical steering config file: {path}")
    keyword_display = normalize_keyword_display(parsed.get("keywordDisplay") or {}, str(path))
    ignored_terms = [
        normalize_lexical_rule_seed(rule, index, str(path))
        for index, rule in enumerate(parsed.get("ignoredTerms") or [])
    ]
    ignored_terms.extend(
        normalize_lexical_rule_seed({"term": term, "scope": "publication", "source": ".papyrus/config.yaml"}, index, ".papyrus/config.yaml")
        for index, term in enumerate(resolve_topics_ignore_terms())
    )
    merged_terms: list[dict[str, Any]] = []
    seen_terms: set[tuple[str, str, str, str, str, str]] = set()
    for rule in ignored_terms:
        key = (
            str(rule.get("scope") or "publication"),
            str(rule.get("normalizedTerm") or ""),
            str(rule.get("corpusId") or ""),
            str(rule.get("classifierId") or ""),
            str(rule.get("categorySetId") or ""),
            str(rule.get("categoryKey") or ""),
        )
        if key in seen_terms:
            continue
        seen_terms.add(key)
        merged_terms.append(rule)
    return {
        "schemaVersion": 1,
        "keywordDisplay": keyword_display,
        "ignoredTerms": merged_terms,
        "configPath": str(path),
    }


def normalize_lexical_term(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    text = re.sub(r"[^\w\s-]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def filter_ignored_proposals(
    proposals: list[dict[str, Any]],
    ignored_terms: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_ignored_terms = {
        normalize_lexical_term(term)
        for term in (ignored_terms or [rule.get("term") for rule in load_lexical_steering_config().get("ignoredTerms") or []])
        if normalize_lexical_term(term)
    }
    if not normalized_ignored_terms:
        return proposals, []
    filtered: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for proposal in proposals:
        if should_ignore_proposal(proposal, normalized_ignored_terms):
            skipped.append(proposal)
        else:
            filtered.append(proposal)
    return filtered, skipped


def should_ignore_proposal(proposal: dict[str, Any], normalized_ignored_terms: set[str]) -> bool:
    payload = proposal.get("payload") if isinstance(proposal.get("payload"), dict) else {}
    candidates = [
        proposal.get("display_name"),
        proposal.get("title"),
        proposal.get("category_key"),
        proposal.get("topic_uid"),
        payload.get("display_name"),
        payload.get("name"),
        payload.get("category_key"),
        payload.get("topic_uid"),
    ]
    for candidate in candidates:
        normalized = normalize_lexical_term(candidate)
        if not normalized:
            continue
        if normalized in normalized_ignored_terms:
            return True
        words = {part for part in re.split(r"[\s._:/-]+", normalized) if part}
        if words.intersection(normalized_ignored_terms):
            return True
    return False


def record(model_name: str, expected: dict[str, Any]) -> dict[str, Any]:
    if model_name == "KnowledgeImportRun":
        corpus_id = string_or_null(expected.get("corpusId"))
        import_kind = string_or_null(expected.get("importKind"))
        return {
            "modelName": model_name,
            "expected": {
                **expected,
                "corpusImportKindKey": f"{corpus_id}#{import_kind}" if corpus_id and import_kind else None,
            },
        }
    return {"modelName": model_name, "expected": expected}


def versioned_record(record_value: dict[str, Any], *, now: str, actor: str, reason: str, content: Any) -> dict[str, Any]:
    without_hash = {
        **record_value,
        "versionNumber": record_value.get("versionNumber") or 1,
        "previousVersionId": record_value.get("previousVersionId"),
        "versionState": record_value.get("versionState") or "current",
        "versionCreatedAt": record_value.get("versionCreatedAt") or now,
        "versionCreatedBy": record_value.get("versionCreatedBy") or actor,
        "changeReason": record_value.get("changeReason") or reason,
    }
    return {**without_hash, "contentHash": record_value.get("contentHash") or hash_stable(content or without_hash)}


def raw_payload_record(owner_type: str, owner_id: str, payload_kind: str, payload: Any, import_run_id: str, now: str) -> dict[str, Any]:
    return record(
        "KnowledgeRawPayload",
        {
            "id": f"raw-{safe_id(owner_type)}-{safe_id(owner_id)}-{safe_id(payload_kind)}",
            "ownerType": owner_type,
            "ownerId": owner_id,
            "payloadKind": payload_kind,
            "importRunId": import_run_id,
            "payload": json.dumps(payload or {}),
            "createdAt": now,
            "updatedAt": now,
        },
    )


def category_set_records(category_set: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    topics = category_set.get("topics") or []
    records = [
        record(
            "CategorySet",
            versioned_record(
                {
                    "id": context["categorySetId"],
                    "lineageId": context["categorySetId"],
                    "corpusId": context["corpusId"],
                    "classifierId": category_set.get("classifier_id"),
                    "displayName": category_set.get("display_name"),
                    "description": category_set.get("description"),
                    "status": "accepted",
                    "generatedAt": date_or_null(context.get("generatedAt")),
                    "categoryCount": len(topics),
                    "importRunId": context["importRunId"],
                },
                now=context["now"],
                actor="biblicus-import",
                reason="category-set-import",
                content=category_set,
            ),
        ),
        raw_payload_record("categorySet", context["categorySetId"], "biblicus-category-set", category_set, context["importRunId"], context["now"]),
    ]
    for index, topic in enumerate(topics):
        category_key = read_category_key(topic)
        category_lineage_id = category_lineage_id_for(context["categorySetId"], category_key)
        category_id = f"{category_lineage_id}-v1"
        records.append(
            record(
                "Category",
                versioned_record(
                    {
                        "id": category_id,
                        "lineageId": category_lineage_id,
                        "categorySetId": context["categorySetId"],
                        "corpusId": context["corpusId"],
                        "categoryKey": category_key,
                        "parentCategoryId": None,
                        "parentCategoryKey": None,
                        "displayName": topic.get("display_name"),
                        "shortTitle": read_short_title(topic),
                        "subtitle": topic.get("subheading") or topic.get("subtitle"),
                        "description": topic.get("description"),
                        "aliases": compact_array(topic.get("aliases")),
                        "status": "accepted",
                        "seedItemIds": compact_array(topic.get("seed_item_ids")),
                        "holdoutItemIds": compact_array(topic.get("holdout_item_ids")),
                        "rank": index + 1,
                        "depth": 0,
                        "isPinned": bool((topic.get("ranking_hints") or {}).get("pinned")),
                        "importRunId": context["importRunId"],
                        "updatedAt": context["now"],
                    },
                    now=context["now"],
                    actor="biblicus-import",
                    reason="category-import",
                    content=topic,
                ),
            )
        )
        records.append(raw_payload_record("category", category_id, "biblicus-category", topic, context["importRunId"], context["now"]))
        records.extend(
            category_keyword_records_from_source(
                topic,
                {
                    **context,
                    "categoryKey": category_key,
                    "categoryLineageId": category_lineage_id,
                    "categoryId": category_id,
                    "source": "accepted-category-set",
                    "sourceTopicId": topic.get("topic_id") or topic.get("bertopic_topic_id") or topic.get("topic_uid") or topic.get("category_key"),
                },
            )
        )
    return records


def taxonomy_records(bundle: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = load_accepted_taxonomy_manifest(bundle, context) or root_taxonomy_manifest_from_category_set(
        bundle.get("topic_set") or {}, context
    )
    manifest_nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), list) else []
    records = [
        raw_payload_record("categoryTree", context["categorySetId"], "biblicus-category-tree", manifest, context["importRunId"], context["now"])
    ]
    node_ranks = rank_taxonomy_nodes(manifest_nodes)
    for node in manifest_nodes:
        category_key = read_category_key(node)
        category_lineage_id = category_lineage_id_for(context["categorySetId"], category_key)
        category_id = f"{category_lineage_id}-v1"
        depth = taxonomy_node_depth(category_key, manifest_nodes)
        rank = node_ranks.get(category_key)
        records.append(
            record(
                "Category",
                versioned_record(
                    {
                        "id": category_id,
                        "lineageId": category_lineage_id,
                        "corpusId": context["corpusId"],
                        "categorySetId": context["categorySetId"],
                        "categoryKey": category_key,
                        "parentCategoryId": None,
                        "parentCategoryKey": read_parent_category_key(node),
                        "displayName": node.get("display_name"),
                        "shortTitle": read_short_title(node),
                        "subtitle": node.get("subheading") or node.get("subtitle"),
                        "description": node.get("description"),
                        "status": normalize_taxonomy_node_status(node.get("status")),
                        "seedItemIds": compact_array(node.get("seed_item_ids")),
                        "holdoutItemIds": compact_array(node.get("holdout_item_ids")),
                        "rank": rank,
                        "depth": depth,
                        "importRunId": context["importRunId"],
                        "updatedAt": context["now"],
                    },
                    now=context["now"],
                    actor="biblicus-import",
                    reason="category-tree-import",
                    content=node,
                ),
            )
        )
        records.append(raw_payload_record("category", category_id, "biblicus-category-tree-node", node, context["importRunId"], context["now"]))
        records.extend(
            category_keyword_records_from_source(
                node,
                {
                    **context,
                    "categoryKey": category_key,
                    "categoryLineageId": category_lineage_id,
                    "categoryId": category_id,
                    "source": "accepted-category-tree",
                    "sourceTopicId": node.get("topic_id") or node.get("bertopic_topic_id") or node.get("topic_uid") or node.get("category_key"),
                },
            )
        )
    return records


def proposal_records(proposal: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    external_proposal_id = proposal.get("proposal_id") or hash_short(proposal)
    proposal_id = f"steering-proposal-{safe_id(external_proposal_id)}"
    proposal_kind = normalize_proposal_kind(proposal.get("kind") or proposal.get("proposal_kind") or "unknown")
    proposal_payload = proposal.get("payload") if isinstance(proposal.get("payload"), dict) else {}
    evidence = proposal.get("evidence") if isinstance(proposal.get("evidence"), dict) else {}
    steering_domain = normalize_steering_domain(proposal.get("domain") or infer_steering_domain(proposal_kind))
    category_key = (
        proposal.get("category_key")
        or proposal.get("topic_uid")
        or proposal_payload.get("category_key")
        or proposal_payload.get("topic_uid")
    )
    target_category_key = (
        proposal.get("target_category_key")
        or proposal.get("target_topic_uid")
        or proposal_payload.get("target_category_key")
        or proposal_payload.get("target_topic_uid")
        or proposal_payload.get("parent_category_key")
        or proposal_payload.get("parent_topic_uid")
        or proposal_payload.get("proposed_parent_category_key")
        or proposal_payload.get("proposed_parent_topic_uid")
        or proposal_payload.get("target_ref")
    )
    graph_entity_id = (
        proposal.get("graph_entity_id")
        or proposal_payload.get("graph_entity_id")
        or proposal_payload.get("entity_id")
        or proposal_payload.get("assertion_id")
        or proposal_payload.get("source_ref")
    )
    relationship_type = (
        proposal.get("relationship_type")
        or proposal_payload.get("relationship_type")
        or proposal_payload.get("relationship_uid")
        or ("subcategory_of" if proposal_payload.get("parent_category_key") or proposal_payload.get("parent_topic_uid") else None)
    )
    display_name = proposal.get("display_name") or proposal_payload.get("display_name") or proposal_payload.get("name")
    short_title = normalize_short_title(
        proposal.get("short_title")
        or proposal.get("shortTitle")
        or proposal_payload.get("short_title")
        or proposal_payload.get("shortTitle"),
        display_name or proposal.get("title") or category_key,
    )
    subtitle = (
        proposal.get("subheading")
        or proposal.get("subtitle")
        or proposal_payload.get("subheading")
        or proposal_payload.get("subtitle")
    )
    description = proposal.get("description") or proposal_payload.get("description")
    evidence_item_ids = compact_array(
        evidence.get("item_ids")
        or evidence.get("evidence_item_ids")
        or proposal.get("evidence_item_ids")
        or proposal_payload.get("evidence_item_ids")
        or proposal_payload.get("document_ids")
    )
    suggested_seed_item_ids = ordered_unique(
        [
            *compact_array(proposal.get("suggested_seed_item_ids")),
            *evidence_item_ids,
            *compact_array(proposal_payload.get("document_ids")),
        ]
    )[:20]
    records = [
        record(
            "SteeringProposal",
            {
                "id": proposal_id,
                "categorySetId": context["categorySetId"],
                "corpusId": context["corpusId"],
                "importRunId": context["importRunId"],
                "proposalKind": proposal_kind,
                "steeringDomain": steering_domain,
                "status": proposal.get("status") or "proposed",
                "title": proposal.get("title") or display_name or category_key or proposal_kind or "Steering proposal",
                "summary": proposal.get("rationale") or proposal.get("description"),
                "categoryKey": category_key,
                "targetCategoryKey": target_category_key,
                "graphEntityId": graph_entity_id,
                "relationshipType": relationship_type,
                "displayName": display_name,
                "shortTitle": short_title,
                "subtitle": subtitle,
                "description": description,
                "evidenceItemIds": evidence_item_ids,
                "suggestedSeedItemIds": suggested_seed_item_ids,
                "suggestedHoldoutItemIds": compact_array(proposal.get("suggested_holdout_item_ids")),
                "sourceSnapshotId": proposal.get("snapshot_id") or proposal_payload.get("graph_snapshot"),
                "proposedAt": date_or_null(proposal.get("proposed_at") or proposal.get("generated_at")) or context["now"],
                "reviewedAt": None,
                "reviewedBy": None,
                "updatedAt": context["now"],
            },
        ),
        raw_payload_record("proposal", proposal_id, "biblicus-proposal", proposal, context["importRunId"], context["now"]),
    ]
    keyword_category_key = category_key or target_category_key
    if keyword_category_key:
        category_lineage_id = category_lineage_id_for(context["categorySetId"], keyword_category_key)
        records.extend(
            category_keyword_records_from_source(
                {**proposal, **proposal_payload, "keywords": proposal_payload.get("keywords") or proposal.get("keywords")},
                {
                    **context,
                    "categoryKey": keyword_category_key,
                    "categoryLineageId": category_lineage_id,
                    "categoryId": f"{category_lineage_id}-v1",
                    "source": "steering-proposal",
                    "sourceTopicId": proposal_id,
                },
            )
        )
    return records


def semantic_records_from_proposal(proposal: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    status = proposal.get("status") or "proposed"
    if status != "accepted":
        return []
    proposal_payload = proposal.get("payload") if isinstance(proposal.get("payload"), dict) else {}
    node_key = (
        proposal.get("graph_entity_id")
        or proposal_payload.get("graph_entity_id")
        or proposal_payload.get("entity_id")
        or proposal_payload.get("assertion_id")
        or proposal_payload.get("source_ref")
    )
    if not node_key:
        return []
    records: list[dict[str, Any]] = []
    node_lineage_id = semantic_node_lineage_id_for(node_key)
    node_id = f"{node_lineage_id}-v1"
    records.append(
        record(
            "SemanticNode",
            versioned_record(
                {
                    "id": node_id,
                    "lineageId": node_lineage_id,
                    "nodeKey": node_key,
                    "nodeKind": infer_semantic_node_kind(node_key, proposal.get("proposal_kind") or proposal.get("kind")),
                    "corpusId": context["corpusId"],
                    "categorySetId": context["categorySetId"],
                    "categoryLineageId": None,
                    "categoryKey": proposal_payload.get("topic_uid") or proposal_payload.get("category_key"),
                    "displayName": proposal_payload.get("display_name") or proposal.get("display_name") or proposal.get("title") or node_key,
                    "description": proposal_payload.get("description") or proposal.get("description") or proposal.get("rationale"),
                    "aliases": string_array_from(proposal_payload.get("aliases")),
                    "status": "accepted",
                    "importRunId": context["importRunId"],
                    "createdAt": context["now"],
                    "newsroomFeedKey": "semanticNodes",
                    "updatedAt": context["now"],
                },
                now=context["now"],
                actor="biblicus-import",
                reason="semantic-node-import",
                content=proposal_payload,
            ),
        )
    )
    target_ref = (
        proposal_payload.get("target_ref")
        or proposal.get("target_category_key")
        or proposal_payload.get("target_topic_uid")
    )
    relationship_type = (
        proposal.get("relationship_type")
        or proposal_payload.get("relationship_type")
        or proposal_payload.get("relationship_uid")
    )
    if target_ref and relationship_type:
        target = semantic_object_ref(target_ref, context)
        records.append(
            semantic_relation_record(
                {
                    "predicate": relationship_type,
                    "subjectKind": "semanticNode",
                    "subjectId": node_id,
                    "subjectLineageId": node_lineage_id,
                    "subjectVersionNumber": 1,
                    "objectKind": target["kind"],
                    "objectId": target["id"],
                    "objectLineageId": target["lineageId"],
                    "objectVersionNumber": target["versionNumber"],
                    "score": number_or_null(proposal.get("score")),
                    "confidence": number_or_null(proposal.get("confidence")),
                    "rank": None,
                    "classifierId": None,
                    "modelVersion": None,
                    "reviewRecommended": proposal.get("recommendation") == "recommend",
                    "sourceSnapshotId": proposal.get("snapshot_id") or proposal_payload.get("graph_snapshot"),
                    "importRunId": context["importRunId"],
                    "importedAt": context["now"],
                    "metadata": {
                        "proposalId": proposal.get("proposal_id"),
                        "sourceRef": node_key,
                        "targetRef": target_ref,
                    },
                }
            )
        )
    return records


def projection_relation_records(items: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    category_set_id = context.get("categorySetId") or category_set_id_for(context["classifierId"], context["authorityCorpusId"])
    for item in items:
        external_item_id = required_string(item.get("item_id"), "projection item_id")
        reference_lineage_id = reference_lineage_id_for(context["targetCorpusId"], external_item_id)
        reference_id = f"{reference_lineage_id}-v1"
        for candidate in projection_candidates(item):
            category_key = candidate.get("categoryKey")
            if not category_key:
                continue
            category_lineage_id = category_lineage_id_for(category_set_id, category_key)
            category_id = f"{category_lineage_id}-v1"
            records.append(
                semantic_relation_record(
                    {
                        "predicate": "classified_as",
                        "subjectKind": "reference",
                        "subjectId": reference_id,
                        "subjectLineageId": reference_lineage_id,
                        "subjectVersionNumber": 1,
                        "objectKind": "category",
                        "objectId": category_id,
                        "objectLineageId": category_lineage_id,
                        "objectVersionNumber": 1,
                        "score": number_or_null(candidate.get("score")),
                        "confidence": number_or_null(candidate.get("confidence")),
                        "rank": integer_or_null(candidate.get("rank")),
                        "classifierId": context["classifierId"],
                        "modelVersion": item.get("model_version"),
                        "reviewRecommended": bool(item.get("review_recommended") or candidate.get("reviewRecommended")),
                        "sourceSnapshotId": (item.get("extraction_snapshot") or {}).get("snapshot_id"),
                        "importRunId": context["importRunId"],
                        "importedAt": context["now"],
                        "metadata": {
                            "categoryKey": category_key,
                            "displayName": candidate.get("displayName"),
                            "bertopicTopicId": integer_or_null(candidate.get("bertopicTopicId")),
                            "authorityCorpusId": context["authorityCorpusId"],
                            "categorySetId": category_set_id,
                        },
                    }
                )
            )
    return records


def artifact_records(artifact: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    artifact_hash_input = f"{artifact.get('kind')}:{artifact.get('artifact_id')}"
    artifact_id = f"category-artifact-{safe_id(context['corpusId'])}-{hash_short(artifact_hash_input)}"
    metadata = artifact.get("metadata") if isinstance(artifact.get("metadata"), dict) else {}
    return [
        record(
            "KnowledgeArtifact",
            {
                "id": artifact_id,
                "corpusId": context["corpusId"],
                "artifactKind": artifact.get("kind"),
                "artifactId": artifact.get("artifact_id"),
                "snapshotId": artifact.get("snapshot_id"),
                "displayName": metadata.get("name") or metadata.get("configuration_id") or artifact.get("artifact_id"),
                "createdAt": date_or_null(artifact.get("created_at")),
                "importRunId": context["importRunId"],
            },
        ),
        raw_payload_record("artifact", artifact_id, "biblicus-artifact", artifact, context["importRunId"], context["now"]),
    ]


def seeded_semantic_concept_node_records(context: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for concept in load_semantic_concept_seeds():
        lineage_id = semantic_node_lineage_id_for(concept["nodeKey"])
        is_global = concept["scope"] == "global"
        records.append(
            record(
                "SemanticNode",
                versioned_record(
                    {
                        "id": f"{lineage_id}-v1",
                        "lineageId": lineage_id,
                        "nodeKey": concept["nodeKey"],
                        "nodeKind": concept["nodeKind"],
                        "corpusId": None if is_global else context["corpusId"],
                        "categorySetId": None,
                        "categoryLineageId": None,
                        "categoryKey": None,
                        "displayName": concept["displayName"],
                        "description": concept["description"],
                        "aliases": string_array_from(concept.get("aliases")),
                        "status": "accepted",
                        "importRunId": context["importRunId"],
                        "createdAt": context["now"],
                        "newsroomFeedKey": "semanticNodes",
                        "updatedAt": context["now"],
                    },
                    now=context["now"],
                    actor="biblicus-import",
                    reason=f"{concept['nodeKind']}-seed",
                    content=concept,
                ),
            )
        )
    return records


def category_keyword_records_from_source(source_value: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, entry in enumerate(keyword_entries_from(source_value)):
        keyword = required_string(entry.get("keyword"), "category keyword")
        normalized_keyword = normalize_lexical_term(keyword)
        rank = integer_or_null(entry.get("rank")) or index + 1
        category_lineage_id = context.get("categoryLineageId") or category_lineage_id_for(context["categorySetId"], context["categoryKey"])
        records.append(
            record(
                "CategoryKeyword",
                {
                    "id": (
                        f"category-keyword-{safe_id(context['categorySetId'])}-{safe_id(context['categoryKey'])}-"
                        f"{safe_id(context['source'])}-{str(rank).zfill(4)}-"
                        f"{hash_short([normalized_keyword, context.get('sourceTopicId') or ''])}"
                    ),
                    "categorySetId": context["categorySetId"],
                    "corpusId": context["corpusId"],
                    "categoryKey": context["categoryKey"],
                    "categoryLineageId": category_lineage_id,
                    "categoryId": context.get("categoryId") or f"{category_lineage_id}-v1",
                    "keyword": keyword,
                    "normalizedKeyword": normalized_keyword,
                    "weight": number_or_null(entry.get("weight")),
                    "rank": rank,
                    "source": context["source"],
                    "sourceTopicId": entry.get("sourceTopicId") or string_or_null(context.get("sourceTopicId")),
                    "importRunId": context["importRunId"],
                    "metadata": json.dumps({"original": entry.get("original"), "source": context["source"]}),
                    "createdAt": context["now"],
                    "updatedAt": context["now"],
                },
            )
        )
    return records


def lexical_steering_rule_record(rule: dict[str, Any]) -> dict[str, Any]:
    normalized_term = rule.get("normalizedTerm") or normalize_lexical_term(rule.get("term"))
    scope = rule.get("scope") or "publication"
    scope_parts = [scope, rule.get("corpusId") or "", rule.get("classifierId") or "", rule.get("categorySetId") or "", rule.get("categoryKey") or ""]
    rule_id = rule.get("id") or f"lexical-rule-{safe_id(rule.get('ruleKind') or 'ignored-keyword')}-{hash_short([*scope_parts, normalized_term])}"
    return record(
        "LexicalSteeringRule",
        {
            "id": rule_id,
            "ruleKind": rule.get("ruleKind") or "ignored_keyword",
            "term": required_string(rule.get("term"), "lexical rule term"),
            "normalizedTerm": normalized_term,
            "scope": scope,
            "status": rule.get("status") or "active",
            "corpusId": rule.get("corpusId"),
            "classifierId": rule.get("classifierId"),
            "categorySetId": rule.get("categorySetId"),
            "categoryKey": rule.get("categoryKey"),
            "note": rule.get("note"),
            "source": rule.get("source"),
            "createdBy": rule.get("createdBy"),
            "createdAt": rule.get("createdAt"),
            "updatedAt": rule.get("updatedAt") or rule.get("createdAt"),
            "metadata": json.dumps(rule.get("metadata") or {}),
        },
    )


def semantic_relation_record(input_value: dict[str, Any]) -> dict[str, Any]:
    subject_state_key = semantic_state_key(input_value["subjectKind"], input_value["subjectLineageId"])
    object_state_key = semantic_state_key(input_value["objectKind"], input_value["objectLineageId"])
    subject_version_key = semantic_version_key(input_value["subjectKind"], input_value["subjectId"])
    object_version_key = semantic_version_key(input_value["objectKind"], input_value["objectId"])
    expected = {
        "id": f"semantic-relation-{hash_short([subject_version_key, input_value['predicate'], object_version_key, input_value.get('rank') or '', input_value.get('classifierId') or '', input_value.get('modelVersion') or ''])}",
        "relationState": "current",
        "predicate": input_value["predicate"],
        **semantic_relation_type_fields_for_predicate(input_value["predicate"]),
        "subjectKind": input_value["subjectKind"],
        "subjectId": input_value["subjectId"],
        "subjectLineageId": input_value["subjectLineageId"],
        "subjectVersionNumber": input_value["subjectVersionNumber"],
        "objectKind": input_value["objectKind"],
        "objectId": input_value["objectId"],
        "objectLineageId": input_value["objectLineageId"],
        "objectVersionNumber": input_value["objectVersionNumber"],
        "subjectStateKey": subject_state_key,
        "objectStateKey": object_state_key,
        "objectSubjectStateKey": f"{object_state_key}#{input_value['subjectKind']}",
        "predicateObjectStateKey": f"{input_value['predicate']}#{object_state_key}",
        "subjectVersionKey": subject_version_key,
        "objectVersionKey": object_version_key,
        "confidence": number_or_null(input_value.get("confidence")),
        "rank": integer_or_null(input_value.get("rank")),
        "classifierId": input_value.get("classifierId"),
        "modelVersion": input_value.get("modelVersion"),
        "reviewRecommended": bool(input_value.get("reviewRecommended")),
        "sourceSnapshotId": input_value.get("sourceSnapshotId"),
        "importRunId": input_value.get("importRunId"),
        "importedAt": input_value.get("importedAt"),
        "createdAt": input_value.get("createdAt") or input_value.get("importedAt"),
        "updatedAt": input_value.get("updatedAt") or input_value.get("importedAt"),
        "newsroomFeedKey": "semanticRelations",
        "metadata": json.dumps(input_value.get("metadata") or {}),
    }
    score = number_or_null(input_value.get("score"))
    if score is not None:
        expected["score"] = score
    return record("SemanticRelation", expected)


def reviewed_proposal_feedback(proposal: dict[str, Any], decision: dict[str, Any] | None) -> dict[str, Any]:
    human_action = decision_action(decision, proposal)
    return {
        "proposal_id": proposal.get("id"),
        "proposal_kind": proposal.get("proposalKind") or "unknown",
        "steering_domain": proposal.get("steeringDomain"),
        "status": proposal.get("status"),
        "human_action": human_action,
        "decided_at": (decision or {}).get("createdAt") or proposal.get("reviewedAt") or proposal.get("updatedAt"),
        "decided_by": (decision or {}).get("actorLabel") or proposal.get("reviewedBy") or (decision or {}).get("actorSub"),
        "decision_id": (decision or {}).get("id"),
        "topic_set_id": proposal.get("categorySetId"),
        "corpus_id": proposal.get("corpusId"),
        "topic_uid": proposal.get("categoryKey"),
        "target_topic_uid": proposal.get("targetCategoryKey"),
        "graph_entity_id": proposal.get("graphEntityId"),
        "relationship_type": proposal.get("relationshipType"),
        "display_name": proposal.get("displayName") or proposal.get("title"),
        "subtitle": proposal.get("subtitle"),
        "description": proposal.get("description"),
        "summary": proposal.get("summary"),
        "evidence_item_ids": compact_array(proposal.get("evidenceItemIds")),
        "suggested_seed_item_ids": compact_array(proposal.get("suggestedSeedItemIds")),
        "suggested_holdout_item_ids": compact_array(proposal.get("suggestedHoldoutItemIds")),
        "source_snapshot_id": proposal.get("sourceSnapshotId"),
    }


def decision_feedback_record(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "decision_id": decision.get("id"),
        "proposal_id": decision.get("proposalId"),
        "topic_set_id": decision.get("categorySetId"),
        "action": decision.get("action"),
        "selected_topic_uid": decision.get("selectedCategoryKey"),
        "note": decision.get("note"),
        "actor_label": decision.get("actorLabel"),
        "actor_sub": decision.get("actorSub"),
        "created_at": decision.get("createdAt"),
    }


def suppression_from_rejected_proposal(proposal: dict[str, Any], category_set: dict[str, Any]) -> dict[str, Any]:
    return {
        "suppression_id": f"suppression-{safe_id(proposal.get('proposal_id'))}",
        "proposal_id": proposal.get("proposal_id"),
        "proposal_kind": proposal.get("proposal_kind"),
        "steering_domain": proposal.get("steering_domain"),
        "reason": proposal.get("summary") or proposal.get("description"),
        "decided_at": proposal.get("decided_at"),
        "decided_by": proposal.get("decided_by"),
        "scope": {
            "topic_set_id": category_set.get("id"),
            "corpus_id": category_set.get("corpusId") or proposal.get("corpus_id"),
            "classifier_id": category_set.get("classifierId"),
            "root_topic_uid": proposal.get("target_topic_uid"),
        },
        "match": {
            "topic_uid": proposal.get("topic_uid"),
            "display_name": proposal.get("display_name"),
            "normalized_display_name": normalize_match_text(proposal.get("display_name")),
            "relationship_type": proposal.get("relationship_type"),
            "graph_entity_id": proposal.get("graph_entity_id"),
        },
        "evidence_item_ids": compact_array(proposal.get("evidence_item_ids")),
    }


def load_accepted_taxonomy_manifest(bundle: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    artifact = latest_artifact(bundle.get("artifacts"), "taxonomy")
    if not artifact or not context.get("corpusPath"):
        return None
    for candidate in taxonomy_artifact_candidates(artifact, context["corpusPath"]):
        manifest = read_taxonomy_manifest_candidate(candidate)
        if manifest:
            return manifest
    return None


def root_taxonomy_manifest_from_category_set(category_set: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    topics = category_set.get("topics") or []
    taxonomy_identity = f"{category_set.get('classifier_id')}-accepted-taxonomy"
    return {
        "schema_version": 1,
        "taxonomy_id": taxonomy_identity,
        "display_name": f"{category_set.get('display_name') or category_set.get('classifier_id')} Taxonomy",
        "description": category_set.get("description") or "Root-only taxonomy derived from the accepted canonical topic set.",
        "generated_at": context["now"],
        "snapshot_id": f"root-only-{hash_short(category_set)}",
        "nodes": [
            {
                "category_key": read_category_key(topic),
                "parent_category_key": None,
                "display_name": topic.get("display_name"),
                "short_title": read_short_title(topic),
                "description": topic.get("description") or topic.get("subheading") or topic.get("subtitle") or "Accepted root topic.",
                "status": "accepted",
                "seed_item_ids": compact_array(topic.get("seed_item_ids")),
                "holdout_item_ids": compact_array(topic.get("holdout_item_ids")),
                "source": {"papyrus_fallback": "accepted-topic-set"},
            }
            for topic in topics
        ],
        "source": {"system": "papyrus", "fallback": "accepted-topic-set", "category_set_id": context["categorySetId"]},
    }


def taxonomy_artifact_candidates(artifact: dict[str, Any], corpus_path: str) -> list[Path]:
    artifact_paths = artifact.get("artifact_paths") if isinstance(artifact.get("artifact_paths"), dict) else {}
    metadata_paths = (artifact.get("metadata") or {}).get("artifact_paths") if isinstance(artifact.get("metadata"), dict) else {}
    paths = compact_array(
        [
            artifact.get("path"),
            artifact_paths.get("taxonomy"),
            artifact_paths.get("manifest"),
            metadata_paths.get("taxonomy") if isinstance(metadata_paths, dict) else None,
            metadata_paths.get("manifest") if isinstance(metadata_paths, dict) else None,
        ]
    )
    if artifact.get("snapshot_id"):
        paths.extend(
            [
                f"analysis/taxonomy/{artifact['snapshot_id']}/taxonomy.json",
                f"analysis/taxonomy/{artifact['snapshot_id']}/manifest.json",
            ]
        )
    candidates: list[Path] = []
    for artifact_path in paths:
        if str(artifact_path).startswith("s3://"):
            continue
        resolved = Path(artifact_path) if Path(artifact_path).is_absolute() else Path(corpus_path) / artifact_path
        candidates.append(resolved)
        if resolved.name == "manifest.json":
            candidates.append(resolved.parent / "taxonomy.json")
    return list(dict.fromkeys(candidates))


def read_taxonomy_manifest_candidate(candidate_path: Path) -> dict[str, Any] | None:
    if not candidate_path.is_file():
        return None
    payload = load_json_file(candidate_path)
    if isinstance(payload.get("nodes"), list) and payload.get("taxonomy_id"):
        return payload
    artifact_paths = payload.get("artifact_paths") if isinstance(payload.get("artifact_paths"), dict) else {}
    taxonomy_path = artifact_paths.get("taxonomy")
    if not isinstance(taxonomy_path, str) or taxonomy_path.startswith("s3://"):
        return None
    resolved = Path(taxonomy_path) if Path(taxonomy_path).is_absolute() else candidate_path.parent / taxonomy_path
    if not resolved.is_file():
        return None
    taxonomy = load_json_file(resolved)
    if isinstance(taxonomy.get("nodes"), list) and taxonomy.get("taxonomy_id"):
        return taxonomy
    return None


def normalize_semantic_concept_seed(concept: Any, index: int, filepath: str) -> dict[str, Any]:
    label = f"{filepath} concepts[{index}]"
    node_key = required_string((concept or {}).get("key") or (concept or {}).get("nodeKey"), f"{label}.key")
    node_kind = required_string((concept or {}).get("kind") or (concept or {}).get("nodeKind"), f"{label}.kind")
    display_name = required_string((concept or {}).get("name") or (concept or {}).get("displayName"), f"{label}.name")
    scope = (concept or {}).get("scope") or "global"
    if scope not in {"global", "corpus"}:
        raise ValueError(f"{label}.scope must be global or corpus.")
    return {
        "nodeKey": node_key,
        "nodeKind": node_kind,
        "scope": scope,
        "displayName": display_name,
        "description": (concept or {}).get("description"),
        "aliases": string_array_from((concept or {}).get("aliases")),
    }


def normalize_keyword_display(value: dict[str, Any], filepath: str) -> dict[str, Any]:
    return {
        "preview_count": integer_or_null(value.get("previewCount") or value.get("preview_count")) or 6,
        "default_limit": integer_or_null(value.get("defaultLimit") or value.get("default_limit")) or 30,
        "expanded_limit": integer_or_null(value.get("expandedLimit") or value.get("expanded_limit")) or 120,
        "source": filepath,
    }


def normalize_lexical_rule_seed(rule: Any, index: int, filepath: str) -> dict[str, Any]:
    label = f"{filepath} ignoredTerms[{index}]"
    term = required_string((rule or {}).get("term"), f"{label}.term")
    scope = (rule or {}).get("scope") or "publication"
    if scope not in {"publication", "corpus", "classifier", "category"}:
        raise ValueError(f"{label}.scope must be publication, corpus, classifier, or category.")
    return {
        "ruleKind": "ignored_keyword",
        "term": term,
        "normalizedTerm": normalize_lexical_term(term),
        "scope": scope,
        "status": (rule or {}).get("status") or "active",
        "corpusId": (rule or {}).get("corpusId"),
        "classifierId": (rule or {}).get("classifierId"),
        "categorySetId": (rule or {}).get("categorySetId"),
        "categoryKey": (rule or {}).get("categoryKey"),
        "note": (rule or {}).get("note"),
        "source": (rule or {}).get("source"),
        "createdBy": (rule or {}).get("createdBy"),
    }


def normalize_corpus_context(corpus: dict[str, Any], configured_corpus: dict[str, Any] | None = None, defaults: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults = defaults or {}
    configured_corpus = configured_corpus or {}
    key = configured_corpus.get("key")
    name = configured_corpus.get("name") or corpus.get("name") or key or corpus_name_from_uri(corpus.get("corpus_uri")) or "Unknown corpus"
    return {
        "key": key,
        "name": name,
        "corpus_uri": corpus.get("corpus_uri") or configured_corpus.get("s3Prefix") or configured_corpus.get("path"),
        "role": configured_corpus.get("role") or corpus.get("role") or defaults.get("role") or "source",
    }


def keyword_entries_from(value: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (
        value.get("keywords")
        or value.get("keyword_weights")
        or value.get("keywordWeights")
        or value.get("top_words")
        or value.get("topWords")
        or value.get("terms")
        or []
    )
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            keyword = string_or_null(entry)
            if keyword:
                entries.append({"keyword": keyword, "rank": index + 1, "original": entry})
            continue
        if isinstance(entry, (list, tuple)):
            keyword = string_or_null(entry[0] if entry else None)
            if keyword:
                entries.append({"keyword": keyword, "weight": number_or_null(entry[1] if len(entry) > 1 else None), "rank": index + 1, "original": entry})
            continue
        if not isinstance(entry, dict):
            continue
        keyword = string_or_null(entry.get("keyword") or entry.get("term") or entry.get("label") or entry.get("value") or entry.get("word"))
        if not keyword:
            continue
        entries.append(
            {
                "keyword": keyword,
                "weight": number_or_null(entry.get("weight") or entry.get("score") or entry.get("probability")),
                "rank": integer_or_null(entry.get("rank")) or index + 1,
                "sourceTopicId": string_or_null(entry.get("sourceTopicId") or entry.get("topic_id") or entry.get("bertopic_topic_id")),
                "original": entry,
            }
        )
    return entries


def projection_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate in item.get("topic_candidates") or []:
        candidates.append(
            {
                "rank": candidate.get("rank"),
                "categoryKey": candidate.get("category_key") or candidate.get("topic_uid"),
                "displayName": candidate.get("display_name"),
                "score": candidate.get("score"),
                "confidence": candidate.get("confidence"),
                "bertopicTopicId": candidate.get("bertopic_topic_id"),
                "reviewRecommended": candidate.get("review_recommended"),
            }
        )
    top_level_category_key = item.get("category_key") or item.get("topic_uid")
    if top_level_category_key and not any(candidate.get("categoryKey") == top_level_category_key for candidate in candidates):
        candidates.insert(
            0,
            {
                "rank": item.get("rank") or 1,
                "categoryKey": top_level_category_key,
                "displayName": item.get("display_name"),
                "score": item.get("score"),
                "confidence": item.get("confidence"),
                "bertopicTopicId": item.get("bertopic_topic_id"),
                "reviewRecommended": item.get("review_recommended"),
            },
        )
    return candidates


def semantic_object_ref(ref: str, context: dict[str, Any]) -> dict[str, Any]:
    if str(ref).startswith("topic:"):
        category_key = str(ref).replace("topic:", "", 1)
        category_set_id = context.get("categorySetId") or category_set_id_for("unknown-classifier", context["corpusId"])
        category_lineage_id = category_lineage_id_for(category_set_id, category_key)
        return {"kind": "category", "id": f"{category_lineage_id}-v1", "lineageId": category_lineage_id, "versionNumber": 1}
    node_lineage_id = semantic_node_lineage_id_for(ref)
    return {"kind": "semanticNode", "id": f"{node_lineage_id}-v1", "lineageId": node_lineage_id, "versionNumber": 1}


def rank_taxonomy_nodes(nodes: list[dict[str, Any]]) -> dict[str, int]:
    rank_by_uid: dict[str, int] = {}
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        parent = read_parent_category_key(node) or "__root__"
        children_by_parent.setdefault(parent, []).append(node)
    for children in children_by_parent.values():
        children.sort(key=lambda node: str(node.get("display_name") or read_category_key(node)))
        for index, node in enumerate(children):
            rank_by_uid[read_category_key(node)] = index + 1
    return rank_by_uid


def taxonomy_node_depth(category_key: str, nodes: list[dict[str, Any]]) -> int:
    parent_by_uid = {read_category_key(node): read_parent_category_key(node) for node in nodes}
    depth = 0
    current = parent_by_uid.get(category_key)
    seen = {category_key}
    while current:
        if current in seen:
            return depth
        seen.add(current)
        depth += 1
        current = parent_by_uid.get(current)
    return depth


def sort_taxonomy_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        nodes,
        key=lambda node: (
            node.get("depth") or 0,
            node.get("rank") if node.get("rank") is not None else 999999,
            str(node.get("categoryKey") or ""),
        ),
    )


def sanitize_projection_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in item.items() if key not in {"abstract", "body", "content"}},
        "item_id": item.get("item_id"),
        "title": item.get("title"),
        "source_uri": item.get("source_uri"),
        "classifier_id": item.get("classifier_id"),
        "model_version": item.get("model_version"),
        "classifier_corpus_uri": item.get("classifier_corpus_uri"),
        "target_corpus_uri": item.get("target_corpus_uri"),
        "extraction_snapshot": item.get("extraction_snapshot"),
        "topic_candidates": item.get("topic_candidates") if isinstance(item.get("topic_candidates"), list) else [],
    }


def normalize_proposal_kind(kind: Any) -> str:
    normalized = str(kind or "unknown")
    replacements = {
        "new-topic": "new-category",
        "rename-topic": "rename-category",
        "merge-topic": "merge-category",
        "deprecate-topic": "deprecate-category",
        "create-taxonomy-node": "create-category",
        "move-taxonomy-node": "move-category",
        "archive-taxonomy-node": "archive-category",
        "merge-taxonomy-nodes": "merge-categories",
        "split-taxonomy-node": "split-category",
        "add-topic-relationship-edge": "relationship-proposal",
    }
    if normalized in replacements:
        return replacements[normalized]
    return normalized.replace("topic", "category").replace("taxonomy-node", "category").replace("taxonomy", "category-tree")


def normalize_steering_domain(domain: Any) -> str:
    return "category" if domain == "topic" else str(domain or "category")


def infer_steering_domain(kind: str) -> str:
    if kind in GRAPH_PROPOSAL_KINDS:
        return "graph"
    kind_text = str(kind or "")
    if "graph" in kind_text or "entity" in kind_text or "relationship" in kind_text:
        return "graph"
    return "category"


def infer_semantic_node_kind(node_key: str, proposal_kind: Any) -> str:
    if str(node_key).startswith("topic:"):
        return "topic"
    if "assertion" in str(proposal_kind or ""):
        return "assertion"
    return "entity"


def latest_snapshot_id(artifacts: list[dict[str, Any]] | None, kind: str) -> str | None:
    matches = [artifact for artifact in artifacts or [] if artifact.get("kind") == kind]
    return matches[-1].get("snapshot_id") if matches else None


def latest_artifact(artifacts: list[dict[str, Any]] | None, kind: str) -> dict[str, Any] | None:
    matches = [artifact for artifact in artifacts or [] if artifact.get("kind") == kind]
    return matches[-1] if matches else None


def read_category_key(value: dict[str, Any]) -> str:
    return required_string(value.get("category_key") or value.get("topic_uid") or value.get("categoryKey"), "category key")


def read_parent_category_key(value: dict[str, Any]) -> str | None:
    return value.get("parent_category_key") or value.get("parent_topic_uid") or value.get("parentCategoryKey")


def read_short_title(value: dict[str, Any]) -> str:
    return normalize_short_title(
        value.get("short_title") or value.get("shortTitle"),
        value.get("display_name") or value.get("displayName") or value.get("name") or read_category_key(value),
    )


def normalize_short_title(value: Any, fallback: Any) -> str:
    explicit = str(value).strip() if isinstance(value, str) else ""
    if explicit:
        return normalize_short_title_words(explicit)
    return derive_short_title(fallback)


def derive_short_title(value: Any) -> str:
    words = [
        word.strip()
        for word in re.sub(r"[_/|]+", " ", str(value or "")).replace(" ", " ").split()
        if word.strip()
    ]
    if not words:
        return "Topic"
    return normalize_short_title_words(" ".join(words))


def normalize_short_title_words(value: str) -> str:
    words = [word.strip() for word in str(value or "").split() if word.strip()]
    if not words:
        return "Topic"
    return " ".join(words[:2])


def normalize_taxonomy_node_status(status: Any) -> str:
    return "archived" if status == "archived" else "accepted"


def decision_action(decision: dict[str, Any] | None, proposal: dict[str, Any]) -> str | None:
    if decision and decision.get("action") in {"accept", "reject", "edit"}:
        return decision["action"]
    if proposal.get("status") == "accepted":
        return "accept"
    if proposal.get("status") == "rejected":
        return "reject"
    return decision.get("action") if decision else None


def semantic_state_key(kind: str, lineage_id: str) -> str:
    return f"{kind}#{lineage_id}#current"


def semantic_version_key(kind: str, version_id: str) -> str:
    return f"{kind}#{version_id}"


def corpus_name_from_uri(uri: Any) -> str | None:
    if not uri:
        return None
    try:
        parsed = urlparse(str(uri))
        parts = [part for part in parsed.path.split("/") if part]
        return parts[-1] if parts else None
    except ValueError:
        return None


def required_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required.")
    return value.strip()


def compact_array(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry.strip() for entry in value if isinstance(entry, str) and entry.strip()]


def ordered_unique(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def string_array_from(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [entry.strip() for entry in value if isinstance(entry, str) and entry.strip()]


def string_or_null(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def number_or_null(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return number
    return None


def integer_or_null(value: Any) -> int | None:
    if isinstance(value, (int, float)) and float(value).is_integer():
        return int(value)
    return None


def date_or_null(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def normalize_match_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return re.sub(r"\s+", " ", value.strip().lower())
    return None


def _compare_lexical_rules_key(rule: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(rule.get("scope") or ""),
        str(rule.get("normalized_term") or rule.get("normalizedTerm") or ""),
        str(rule.get("rule_id") or rule.get("id") or ""),
    )


def _compare_feedback_key(proposal: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(proposal.get("target_topic_uid") or proposal.get("target_category_key") or ""),
        str(proposal.get("proposal_kind") or ""),
        str(proposal.get("proposal_id") or ""),
    )
