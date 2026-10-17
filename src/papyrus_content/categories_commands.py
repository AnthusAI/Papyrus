from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .categories_steering import (
    build_accepted_category_set_payload,
    build_accepted_category_tree_payload,
    build_lexical_steering_config_records,
    build_lexical_steering_payload,
    build_projection_import_records,
    build_steering_config_records,
    build_steering_feedback_payload,
    build_steering_import_records,
    load_json_file,
    load_lexical_steering_config,
    load_steering_bundle_from_biblicus,
    normalize_lexical_term,
    write_json_file,
)
from .corpus_storage_paths import corpus_storage_path_prefix
from .curation_cycle import (
    build_curation_cycle_plan,
    latest_pipeline_snapshot,
    record_proposal_bundle_if_present,
    resolve_biblicus_corpus_path,
    run_biblicus,
    run_biblicus_json,
    timestamp_run_id,
    validate_cycle_corpus_paths,
)
from .env import BIBLICUS_ROOT, PAPYRUS_ROOT, storage_bucket_from_amplify_outputs
from .graphql_authoring import create_authoring_client
from .ids import hash_short, hash_stable, knowledge_corpus_id
from .options import parse_boolean_option, parse_comma_list, parse_options, resolve_mutation_apply
from .records import (
    apply_record_changes,
    build_record_changes_tolerating_optional_models,
    build_steering_config_record_changes,
    is_missing_graphql_model_error,
)
from .reference_policy import normalize_reference_curation_status
from .papyrus_config import resolve_topics_steering_config_path
from .steering import (
    load_steering_config,
    require_corpus_config,
    require_steering_config,
    resolve_classifier_for_corpus,
    resolve_projection_import_corpora,
    resolve_steering_import_corpus,
)


def categories_import_steering(flags: list[str]) -> None:
    options = parse_options(flags)
    steering_config = load_steering_config(options.get("config"))
    lexical_config = load_lexical_steering_config(options.get("lexical-config"))
    resolved = resolve_steering_import_corpus(steering_config, options)
    bundle = (
        load_json_file(options["bundle"])
        if options.get("bundle")
        else load_steering_bundle_from_biblicus(
            corpus=str(resolved["corpusPath"]),
            classifier=str(resolved["classifierId"]),
            topic_governance_snapshot=options.get("topic-governance-snapshot"),
        )
    )
    client, _ = create_authoring_client()
    plan = build_steering_import_records(
        bundle,
        {
            "classifierId": resolved["classifierId"],
            "corpusConfig": resolved["corpusConfig"],
            "corpusPath": resolved["corpusPath"],
            "ignoredTerms": [rule.get("term") for rule in lexical_config.get("ignoredTerms") or []],
        },
    )
    changes = build_record_changes_tolerating_optional_models(client, plan["records"])
    apply_record_changes(client, changes)
    print_category_import_summary("steering", plan["importRunId"], changes)


def categories_import_config(flags: list[str]) -> None:
    options = parse_options(flags)
    steering_config = require_steering_config(options.get("config"))
    client, _ = create_authoring_client()
    records = build_steering_config_records(steering_config)
    changes = build_steering_config_record_changes(client, records)
    apply_record_changes(client, changes)
    print_category_import_summary("config", "steering-config", changes)
    apply_lexical_steering_config_if_available(client, options)


def categories_sandbox_steering_config(flags: list[str]) -> None:
    options = parse_options(flags)
    config_path = options.get("config") or resolve_topics_steering_config_path()
    if not options.get("output"):
        raise ValueError("categories sandbox-steering-config requires --output <sandbox-steering.yml>.")
    bucket = options.get("bucket") or storage_bucket_from_amplify_outputs(options.get("amplify-outputs") or "amplify_outputs.json")
    if not bucket:
        raise ValueError("Could not resolve sandbox storage bucket. Pass --bucket or verify amplify_outputs.json.")
    source = yaml.safe_load((PAPYRUS_ROOT / config_path).read_text(encoding="utf-8"))
    if not isinstance(source, dict) or not isinstance(source.get("corpora"), list):
        raise ValueError(f"Invalid steering config: {config_path}")
    output = {
        **source,
        "corpora": [
            {**corpus, "s3Prefix": f"s3://{bucket}/{corpus_storage_path_prefix(corpus['key'])}/"}
            for corpus in source["corpora"]
        ],
    }
    cyclotron = source.get("relevanceCyclotron")
    if isinstance(cyclotron, dict) and isinstance(cyclotron.get("store"), dict) and cyclotron["store"].get("s3Prefix"):
        # The cyclotron's store snapshot lives in the same bucket as the corpora.
        identifier = cyclotron.get("cyclotronId", "papyrus-relevance")
        output["relevanceCyclotron"] = {**cyclotron, "store": {**cyclotron["store"],
                                                               "s3Prefix": f"s3://{bucket}/cyclotrons/{identifier}/"}}
    output_path = Path(options["output"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(output, sort_keys=False), encoding="utf-8")
    print(f"categories\tsandbox-steering-config\t{options['output']}\t{bucket}")


def categories_export_category_set(flags: list[str]) -> None:
    options = parse_options(flags)
    category_set_id = options.get("category-set")
    if not category_set_id:
        raise ValueError("categories export-category-set requires --category-set.")
    if not options.get("output"):
        raise ValueError("categories export-category-set requires --output.")
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", category_set_id)
    if not category_set:
        raise ValueError(f"CategorySet {category_set_id} was not found.")
    categories = [
        category
        for category in client.list_records("Category")
        if category.get("categorySetId") == category_set_id and category.get("status") != "archived"
    ]
    write_json_file(options["output"], build_accepted_category_set_payload(category_set, categories))
    print(f"export\tcategory-set\t{category_set_id}\t{options['output']}\t{len(categories)} categories")


def categories_export_category_tree(flags: list[str]) -> None:
    options = parse_options(flags)
    category_set_id = options.get("category-set")
    if not category_set_id:
        raise ValueError("categories export-category-tree requires --category-set.")
    if not options.get("output"):
        raise ValueError("categories export-category-tree requires --output.")
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", category_set_id)
    if not category_set:
        raise ValueError(f"CategorySet {category_set_id} was not found.")
    nodes = [
        node
        for node in client.list_records("Category")
        if node.get("categorySetId") == category_set_id and node.get("status") != "archived"
    ]
    write_json_file(options["output"], build_accepted_category_tree_payload(category_set, nodes))
    print(f"export\tcategory-tree\t{category_set_id}\t{options['output']}\t{len(nodes)} categories")


def categories_export_steering_feedback(flags: list[str]) -> None:
    options = parse_options(flags)
    category_set_id = options.get("category-set")
    if not category_set_id:
        raise ValueError("categories export-steering-feedback requires --category-set.")
    if not options.get("output"):
        raise ValueError("categories export-steering-feedback requires --output.")
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", category_set_id)
    if not category_set:
        raise ValueError(f"CategorySet {category_set_id} was not found.")
    proposals = [proposal for proposal in client.list_records("SteeringProposal") if proposal.get("categorySetId") == category_set_id]
    proposal_ids = {proposal["id"] for proposal in proposals}
    decisions = [
        decision
        for decision in client.list_records("SteeringDecision")
        if decision.get("categorySetId") == category_set_id or decision.get("proposalId") in proposal_ids
    ]
    payload = build_steering_feedback_payload(category_set, proposals, decisions)
    write_json_file(options["output"], payload)
    print(
        f"export\tsteering-feedback\t{category_set_id}\t{options['output']}\t"
        f"{len(payload['accepted_proposals'])} accepted\t{len(payload['rejected_proposals'])} rejected"
    )


def categories_export_lexical_steering(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("categories export-lexical-steering requires --output.")
    client, _ = create_authoring_client()
    lexical_config = load_lexical_steering_config(options.get("lexical-config"))
    rules = client.list_records("LexicalSteeringRule")
    payload = build_lexical_steering_payload(rules, {"config": lexical_config})
    write_json_file(options["output"], payload)
    print(f"export\tlexical-steering\t{options['output']}\t{len(payload['ignored_terms'])} active ignored terms")


def categories_export_classifier_seed_manifest(flags: list[str]) -> None:
    options = parse_options(flags)
    category_set_id = options.get("category-set")
    if not category_set_id:
        raise ValueError("categories export-classifier-seed-manifest requires --category-set <id>.")
    if not options.get("corpus-key"):
        raise ValueError("categories export-classifier-seed-manifest requires --corpus-key <key>.")
    if not options.get("output"):
        raise ValueError("categories export-classifier-seed-manifest requires --output <seed-manifest.json>.")
    steering_config = load_steering_config(options.get("config"))
    if not steering_config:
        raise ValueError("Steering config is required for classifier seed manifest export.")
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", category_set_id)
    categories = client.list_records("Category")
    references = client.list_records("Reference")
    relations = client.list_records("SemanticRelation")
    if not category_set:
        raise ValueError(f"CategorySet {category_set_id} was not found.")
    if category_set.get("corpusId") and category_set["corpusId"] != corpus_id:
        raise ValueError(f"CategorySet {category_set_id} belongs to {category_set['corpusId']}, not {corpus_id}.")
    active_categories = sorted(
        [
            category
            for category in categories
            if category.get("categorySetId") == category_set.get("id")
            and category.get("status") not in {"archived", "deprecated"}
        ],
        key=compare_categories_for_draft,
    )
    category_by_lineage = {category.get("lineageId") or category.get("id"): category for category in active_categories}
    category_by_id = {category["id"]: category for category in active_categories}
    accepted_references = [
        reference
        for reference in references
        if reference.get("corpusId") == corpus_id and is_current_accepted_reference(reference)
    ]
    accepted_reference_by_lineage = {reference.get("lineageId") or reference.get("id"): reference for reference in accepted_references}
    accepted_reference_by_id = {reference["id"]: reference for reference in accepted_references}
    seed_ids_by_category_lineage: dict[str, set[str]] = {}
    for relation in relations:
        if relation.get("relationState") != "current":
            continue
        if (relation.get("relationTypeKey") or relation.get("predicate")) != "authoritative_label":
            continue
        if relation.get("subjectKind") != "reference" or relation.get("objectKind") != "category":
            continue
        category = category_by_id.get(relation.get("objectId")) or category_by_lineage.get(relation.get("objectLineageId"))
        if not category:
            continue
        reference = accepted_reference_by_id.get(relation.get("subjectId")) or accepted_reference_by_lineage.get(
            relation.get("subjectLineageId")
        )
        if not reference or not reference.get("externalItemId"):
            continue
        category_lineage = category.get("lineageId") or category.get("id")
        seed_ids_by_category_lineage.setdefault(category_lineage, set()).add(reference["externalItemId"])
    topics = []
    for category in active_categories:
        seed_item_ids = sorted(seed_ids_by_category_lineage.get(category.get("lineageId") or category.get("id"), set()))
        if not seed_item_ids:
            continue
        holdout_item_ids = sorted(
            item_id for item_id in normalize_string_list(category.get("holdoutItemIds")) if item_id not in seed_item_ids
        )
        topics.append(
            {
                "topic_uid": str(category.get("categoryKey") or category.get("id")),
                "display_name": str(category.get("displayName") or category.get("categoryKey") or category.get("id")),
                "description": str(
                    category.get("description") or category.get("subtitle") or category.get("displayName") or category.get("categoryKey") or category.get("id")
                ),
                "seed_item_ids": seed_item_ids,
                "holdout_item_ids": holdout_item_ids,
            }
        )
    if not topics:
        raise ValueError(
            f"No authoritative labels found for accepted current references in {category_set_id}; add labels before exporting a classifier seed manifest."
        )
    payload = {
        "schema_version": 1,
        "classifier_id": category_set.get("classifierId") or resolve_classifier_for_corpus(steering_config, corpus_config, None),
        "display_name": category_set.get("displayName") or category_set.get("id"),
        "description": category_set.get("description")
        or f"Papyrus classifier seed manifest for {category_set.get('displayName') or category_set.get('id')}.",
        "topics": topics,
        "unlabeled_policy": "use_minus_one",
    }
    write_json_file(options["output"], payload)
    print(
        f"export\tclassifier-seed-manifest\t{category_set['id']}\t{options['output']}\t"
        f"{len(topics)} topics\t{sum(len(topic['seed_item_ids']) for topic in topics)} labels"
    )
    if len(active_categories) > len(topics):
        print(f"export\tclassifier-seed-manifest\tunlabeled-topics\t{len(active_categories) - len(topics)}")


def categories_import_projection(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("bundle"):
        raise ValueError("categories import-projection requires --bundle.")
    payload = load_json_file(options["bundle"])
    steering_config = load_steering_config(options.get("config"))
    resolved = resolve_projection_import_corpora(steering_config, options)
    client, _ = create_authoring_client()
    category_set = resolve_accepted_category_set(
        client,
        {
            "categorySetId": options.get("category-set"),
            "corpusId": resolved.get("authorityCorpusId"),
            "classifierId": resolved.get("classifierId"),
        },
    )
    plan = build_projection_import_records(
        payload,
        {
            "authorityCorpusConfig": resolved.get("authorityCorpus"),
            "authorityCorpusId": resolved.get("authorityCorpusId"),
            "targetCorpusConfig": resolved.get("targetCorpus"),
            "targetCorpusId": resolved.get("targetCorpusId"),
            "classifierId": resolved.get("classifierId"),
            "categorySetId": category_set.get("id") if category_set else None,
        },
    )
    changes = build_record_changes_tolerating_optional_models(client, plan["records"])
    apply_record_changes(client, changes)
    print_category_import_summary("projection", plan["importRunId"], changes)


def categories_draft_create(flags: list[str]) -> None:
    options = parse_options(flags)
    source_id = options.get("from-category-set")
    if not source_id:
        raise ValueError("categories draft-create requires --from-category-set <id>.")
    if not options.get("title"):
        raise ValueError("categories draft-create requires --title <text>.")
    actor = options.get("actor") or "Papyrus content CLI"
    now = _utc_now()
    client, _ = create_authoring_client()
    category_sets = client.list_records("CategorySet")
    categories = client.list_records("Category")
    source = next((entry for entry in category_sets if entry.get("id") == source_id), None)
    if not source:
        raise ValueError(f"CategorySet {source_id} was not found.")
    if source.get("versionState") != "current" and source.get("status") != "accepted":
        raise ValueError(f"CategorySet {source_id} is {source.get('versionState')}/{source.get('status')}; create drafts from the accepted current set.")
    lineage_id = source.get("lineageId") or source.get("id")
    next_version = max([0, *[int(entry.get("versionNumber") or 0) for entry in category_sets if (entry.get("lineageId") or entry.get("id")) == lineage_id]]) + 1
    draft_id = options.get("id") or f"{slugify(lineage_id)}-draft-v{next_version}"
    if any(entry.get("id") == draft_id for entry in category_sets):
        raise ValueError(f"Draft CategorySet {draft_id} already exists.")
    source_categories = sorted(
        [category for category in categories if category.get("categorySetId") == source.get("id")],
        key=compare_categories_for_draft,
    )
    max_category_version_by_lineage: dict[str, int] = {}
    for category in categories:
        category_lineage = category.get("lineageId") or category.get("id")
        max_category_version_by_lineage[category_lineage] = max(
            max_category_version_by_lineage.get(category_lineage, 0),
            int(category.get("versionNumber") or 0),
        )
    draft_set = with_version_fields(
        {
            "id": draft_id,
            "lineageId": lineage_id,
            "versionNumber": next_version,
            "previousVersionId": source.get("id"),
            "versionState": "draft",
            "corpusId": source.get("corpusId"),
            "classifierId": source.get("classifierId"),
            "displayName": str(options["title"]).strip(),
            "description": options.get("description") or source.get("description") or "",
            "status": "draft",
            "generatedAt": now,
            "categoryCount": len(source_categories),
            "importRunId": source.get("importRunId"),
        },
        now=now,
        actor=actor,
        reason=options.get("reason") or f"Draft created from {source.get('id')}",
    )
    draft_id_by_source_id: dict[str, str] = {}
    draft_id_by_source_lineage: dict[str, str] = {}
    for category in source_categories:
        category_lineage = category.get("lineageId") or category.get("id")
        category_key = category.get("categoryKey") or category.get("id")
        cloned_id = f"{slugify(category_lineage)}-draft-v{next_version}"
        draft_id_by_source_id[category["id"]] = cloned_id
        draft_id_by_source_lineage[category_lineage] = cloned_id
    draft_categories = []
    for category in source_categories:
        category_lineage = category.get("lineageId") or category.get("id")
        category_key = category.get("categoryKey") or category.get("id")
        parent_id = draft_id_by_source_id.get(category.get("parentCategoryId") or "") if category.get("parentCategoryId") else None
        draft_categories.append(
            with_version_fields(
                {
                    "id": draft_id_by_source_lineage[category_lineage],
                    "lineageId": category_lineage,
                    "versionNumber": max_category_version_by_lineage.get(category_lineage, 0) + 1,
                    "previousVersionId": category.get("id"),
                    "versionState": "draft",
                    "categorySetId": draft_set["id"],
                    "corpusId": category.get("corpusId") or draft_set.get("corpusId"),
                    "categoryKey": category_key,
                    "parentCategoryId": parent_id,
                    "parentCategoryKey": category.get("parentCategoryKey"),
                    "displayName": category.get("displayName") or category_key,
                    "shortTitle": category.get("shortTitle"),
                    "subtitle": category.get("subtitle"),
                    "description": category.get("description") or "",
                    "aliases": normalize_string_list(category.get("aliases")),
                    "status": category.get("status") or "accepted",
                    "seedItemIds": normalize_string_list(category.get("seedItemIds")),
                    "holdoutItemIds": normalize_string_list(category.get("holdoutItemIds")),
                    "rank": category.get("rank"),
                    "depth": category.get("depth") or 0,
                    "isPinned": bool(category.get("isPinned")),
                    "importRunId": category.get("importRunId"),
                    "updatedAt": now,
                },
                now=now,
                actor=actor,
                reason=options.get("reason") or f"Draft clone from {source.get('id')}",
            )
        )
    apply = resolve_mutation_apply(options, "categories draft-create")
    print_draft_plan("draft-create", category_sets=[draft_set], categories=draft_categories, apply=apply)
    if not apply:
        print("categories\tdraft-create\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    client.upsert("CategorySet", draft_set)
    for category in draft_categories:
        client.upsert("Category", category)
    print(f"categories\tdraft-create\t{draft_set['id']}\t{len(draft_categories)} topics")


def categories_draft_add_topic(flags: list[str]) -> None:
    options = parse_options(flags)
    category_set_id = options.get("category-set")
    if not category_set_id:
        raise ValueError("categories draft-add-topic requires --category-set <draft-id>.")
    if not options.get("display-name"):
        raise ValueError("categories draft-add-topic requires --display-name <text>.")
    now = _utc_now()
    actor = options.get("actor") or "Papyrus content CLI"
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", category_set_id)
    categories = client.list_records("Category")
    require_draft_category_set(category_set, category_set_id)
    draft_categories = [category for category in categories if category.get("categorySetId") == category_set.get("id")]
    category_key = options.get("category-key") or f"category.{slugify(options['display-name'])}"
    if any(category.get("categoryKey") == category_key for category in draft_categories):
        raise ValueError(f"Category key {category_key} already exists in draft {category_set.get('id')}.")
    parent = resolve_category_in_set(draft_categories, options["parent-key"], label="--parent-key") if options.get("parent-key") else None
    siblings = [category for category in draft_categories if (category.get("parentCategoryKey") or None) == (parent.get("categoryKey") if parent else None)]
    rank = int(options["rank"]) if options.get("rank") else max([0, *[int(category.get("rank") or 0) for category in siblings]]) + 1
    lineage_id = options.get("lineage") or f"category-{slugify(category_set.get('lineageId') or category_set.get('id'))}-{slugify(category_key)}"
    category = with_version_fields(
        {
            "id": f"category-{slugify(category_set['id'])}-{slugify(category_key)}",
            "lineageId": lineage_id,
            "versionNumber": 1,
            "previousVersionId": None,
            "versionState": "draft",
            "categorySetId": category_set["id"],
            "corpusId": category_set.get("corpusId"),
            "categoryKey": category_key,
            "parentCategoryId": parent.get("id") if parent else None,
            "parentCategoryKey": parent.get("categoryKey") if parent else None,
            "displayName": str(options["display-name"]).strip(),
            "shortTitle": options.get("short-title"),
            "subtitle": options.get("subtitle"),
            "description": options.get("description") or options.get("subtitle") or str(options["display-name"]).strip(),
            "aliases": normalize_string_list(parse_comma_list(options.get("aliases")) or []),
            "status": "accepted",
            "seedItemIds": [],
            "holdoutItemIds": [],
            "rank": rank,
            "depth": (int(parent.get("depth") or 0) + 1) if parent else 0,
            "isPinned": parse_boolean_option(options.get("pinned"), False, "--pinned"),
            "importRunId": None,
            "updatedAt": now,
        },
        now=now,
        actor=actor,
        reason=options.get("reason") or "Manual draft topic added",
    )
    apply = resolve_mutation_apply(options, "categories draft-add-topic")
    print_draft_plan("draft-add-topic", categories=[category], apply=apply)
    if not apply:
        print("categories\tdraft-add-topic\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    client.upsert("Category", category)
    client.upsert(
        "CategorySet",
        {
            **category_set,
            "categoryCount": len(draft_categories) + 1,
            "changeReason": options.get("reason") or "Manual draft topic added",
            "contentHash": hash_short({**category_set, "categoryCount": len(draft_categories) + 1, "updatedAt": now}),
        },
    )
    print(f"categories\tdraft-add-topic\t{category['id']}\t{category['categoryKey']}")


def categories_draft_update_topic(flags: list[str]) -> None:
    options = parse_options(flags)
    token = options.get("category")
    if not token:
        raise ValueError("categories draft-update-topic requires --category <id|lineage|key>.")
    client, _ = create_authoring_client()
    category_sets = client.list_records("CategorySet")
    categories = client.list_records("Category")
    category = resolve_category_any(categories, token)
    category_set = next((entry for entry in category_sets if entry.get("id") == category.get("categorySetId")), None)
    require_draft_category_set(category_set, category.get("categorySetId"))
    now = _utc_now()
    updated = {
        **category,
        **({"displayName": str(options["display-name"]).strip()} if options.get("display-name") else {}),
        **({"shortTitle": str(options["short-title"]).strip()} if options.get("short-title") else {}),
        **({"subtitle": str(options["subtitle"]).strip()} if options.get("subtitle") else {}),
        **({"description": str(options["description"]).strip()} if options.get("description") else {}),
        **({"aliases": normalize_string_list(parse_comma_list(options.get("aliases")) or [])} if options.get("aliases") else {}),
        **({"rank": int(options["rank"])} if options.get("rank") else {}),
        "updatedAt": now,
        "changeReason": options.get("reason") or "Manual draft topic update",
    }
    updated["contentHash"] = hash_short(normalize_record(updated))
    apply = resolve_mutation_apply(options, "categories draft-update-topic")
    print_draft_plan("draft-update-topic", categories=[updated], apply=apply)
    if not apply:
        print("categories\tdraft-update-topic\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    client.upsert("Category", updated)
    print(f"categories\tdraft-update-topic\t{updated['id']}\t{updated['categoryKey']}")


def categories_draft_archive_topic(flags: list[str]) -> None:
    options = parse_options(flags)
    token = options.get("category")
    if not token:
        raise ValueError("categories draft-archive-topic requires --category <id|lineage|key>.")
    client, _ = create_authoring_client()
    category_sets = client.list_records("CategorySet")
    categories = client.list_records("Category")
    category = resolve_category_any(categories, token)
    category_set = next((entry for entry in category_sets if entry.get("id") == category.get("categorySetId")), None)
    require_draft_category_set(category_set, category.get("categorySetId"))
    now = _utc_now()
    archived = {
        **category,
        "status": "deprecated",
        "updatedAt": now,
        "changeReason": options.get("reason") or "Manual draft topic archived",
    }
    archived["contentHash"] = hash_short(normalize_record(archived))
    apply = resolve_mutation_apply(options, "categories draft-archive-topic")
    print_draft_plan("draft-archive-topic", categories=[archived], apply=apply)
    if not apply:
        print("categories\tdraft-archive-topic\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    client.upsert("Category", archived)
    print(f"categories\tdraft-archive-topic\t{archived['id']}\t{archived['categoryKey']}\tdeprecated")


def categories_draft_promote(flags: list[str]) -> None:
    options = parse_options(flags)
    draft_id = options.get("category-set")
    if not draft_id:
        raise ValueError("categories draft-promote requires --category-set <draft-id>.")
    now = _utc_now()
    client, _ = create_authoring_client()
    category_sets = client.list_records("CategorySet")
    categories = client.list_records("Category")
    draft = next((entry for entry in category_sets if entry.get("id") == draft_id), None)
    require_draft_category_set(draft, draft_id)
    lineage_id = draft.get("lineageId") or draft.get("id")
    previous_current = next(
        (
            entry
            for entry in category_sets
            if entry.get("id") != draft.get("id")
            and (entry.get("lineageId") or entry.get("id")) == lineage_id
            and entry.get("versionState") == "current"
        ),
        None,
    )
    draft_categories = [category for category in categories if category.get("categorySetId") == draft.get("id")]
    draft_lineages = {category.get("lineageId") or category.get("id") for category in draft_categories}
    superseded_categories = [
        {
            **category,
            "versionState": "superseded",
            "updatedAt": now,
            "changeReason": options.get("reason") or f"Superseded by {draft.get('id')}",
        }
        for category in categories
        if category.get("categorySetId") != draft.get("id")
        and (category.get("lineageId") or category.get("id")) in draft_lineages
        and category.get("versionState") == "current"
    ]
    for category in superseded_categories:
        category["contentHash"] = hash_short(normalize_record(category))
    promoted_categories = []
    for category in draft_categories:
        promoted = {
            **category,
            "versionState": "current",
            "updatedAt": now,
            "changeReason": options.get("reason") or "Draft category set promoted",
        }
        promoted["contentHash"] = hash_short(normalize_record(promoted))
        promoted_categories.append(promoted)
    updates = {
        "categorySets": [
            *(
                [
                    {
                        **previous_current,
                        "versionState": "superseded",
                        "status": "superseded",
                        "changeReason": options.get("reason") or f"Superseded by {draft.get('id')}",
                        "contentHash": hash_short(
                            {**previous_current, "versionState": "superseded", "status": "superseded", "updatedAt": now}
                        ),
                    }
                ]
                if previous_current
                else []
            ),
            {
                **draft,
                "versionState": "current",
                "status": "accepted",
                "categoryCount": len(
                    [category for category in promoted_categories if category.get("status") not in {"deprecated", "archived"}]
                ),
                "generatedAt": draft.get("generatedAt") or now,
                "changeReason": options.get("reason") or "Draft category set promoted",
                "contentHash": hash_short({**draft, "versionState": "current", "status": "accepted", "updatedAt": now}),
            },
        ],
        "categories": [*superseded_categories, *promoted_categories],
    }
    apply = resolve_mutation_apply(options, "categories draft-promote")
    print_draft_plan("draft-promote", category_sets=updates["categorySets"], categories=updates["categories"], apply=apply)
    if not apply:
        print("categories\tdraft-promote\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    for category_set in updates["categorySets"]:
        client.upsert("CategorySet", category_set)
    for category in updates["categories"]:
        client.upsert("Category", category)
    previous_current_category_count = (
        len(
            [
                category
                for category in categories
                if category.get("categorySetId") == previous_current.get("id")
                and category.get("versionState") == "current"
                and category.get("status") not in {"deprecated", "archived"}
            ]
        )
        if previous_current
        else 0
    )
    promoted_category_count = len(
        [category for category in promoted_categories if category.get("status") not in {"deprecated", "archived"}]
    )
    count_deltas: dict[str, int] = {}
    if not previous_current:
        count_deltas["categorySets"] = 1
    category_delta = promoted_category_count - previous_current_category_count
    if category_delta:
        count_deltas["categories"] = category_delta
    if count_deltas:
        client.update_newsroom_summary(
            {"source": "incremental", "countDeltas": count_deltas},
            actor_label="Papyrus content CLI",
            reason=f"categories draft-promote {draft['id']}",
        )
    print(f"categories\tdraft-promote\t{draft['id']}\tcurrent\t{len(promoted_categories)} topics")


def categories_review_proposal(flags: list[str]) -> None:
    options = parse_options(flags)
    proposal_id = options.get("proposal") or options.get("proposal-id")
    action = str(options.get("action") or "").lower()
    if not proposal_id:
        raise ValueError("categories review-proposal requires --proposal <steering-proposal-id>.")
    if action not in {"accept", "reject"}:
        raise ValueError("categories review-proposal requires --action accept|reject.")
    actor = options.get("actor") or "Papyrus content CLI"
    now = _utc_now()
    client, _ = create_authoring_client()
    proposal = client.get_record("SteeringProposal", proposal_id)
    category_sets = client.list_records("CategorySet")
    categories = client.list_records("Category")
    if not proposal:
        raise ValueError(f"SteeringProposal {proposal_id} was not found.")
    if proposal.get("status") in {"accepted", "rejected"}:
        print(f"categories\treview-proposal\t{proposal['id']}\t{proposal['status']}\tidempotent")
        return
    decision = {
        "id": f"decision-{proposal['id']}-{timestamp_for_path(now)}-{uuid.uuid4().hex[:8]}",
        "proposalId": proposal["id"],
        "categorySetId": options.get("target-category-set") or proposal.get("categorySetId"),
        "action": action,
        "actorSub": None,
        "actorLabel": actor,
        "note": options.get("note"),
        "selectedCategoryKey": proposal.get("categoryKey"),
        "createdAt": now,
    }
    updated_proposal = {
        **proposal,
        "status": "accepted" if action == "accept" else "rejected",
        "reviewedAt": now,
        "reviewedBy": actor,
        "updatedAt": now,
    }
    records = [
        {"modelName": "SteeringDecision", "expected": decision},
        {"modelName": "SteeringProposal", "expected": updated_proposal},
    ]
    category = None
    category_set_update = None
    if action == "accept":
        target_category_set_id = options.get("target-category-set") or proposal.get("categorySetId")
        if not target_category_set_id:
            raise ValueError(f"SteeringProposal {proposal['id']} has no categorySetId; pass --target-category-set.")
        category_set = next((entry for entry in category_sets if entry.get("id") == target_category_set_id), None)
        if not category_set:
            raise ValueError(f"CategorySet {target_category_set_id} was not found.")
        category_key = proposal.get("categoryKey") or derive_category_key_from_text(
            proposal.get("displayName") or proposal.get("title") or proposal.get("id")
        )
        target_categories = [entry for entry in categories if entry.get("categorySetId") == category_set.get("id")]
        if any(
            entry.get("categoryKey") == category_key and entry.get("versionState") == "current" for entry in target_categories
        ):
            raise ValueError(f"Category {category_key} already exists in {category_set['id']}; refusing duplicate proposal accept.")
        parent_category_key = proposal.get("targetCategoryKey")
        parent = (
            next(
                (
                    entry
                    for entry in target_categories
                    if entry.get("categoryKey") == parent_category_key and entry.get("versionState") == "current"
                ),
                None,
            )
            if parent_category_key
            else None
        )
        lineage_id = f"category-{slugify(category_set['id'])}-{slugify(category_key)}"
        category = with_version_fields(
            {
                "id": f"{lineage_id}-v1",
                "lineageId": lineage_id,
                "versionNumber": 1,
                "previousVersionId": None,
                "versionState": "current",
                "categorySetId": category_set["id"],
                "corpusId": proposal.get("corpusId") or category_set.get("corpusId"),
                "categoryKey": category_key,
                "parentCategoryId": parent.get("id") if parent else None,
                "parentCategoryKey": parent_category_key,
                "displayName": options.get("display-name") or proposal.get("displayName") or proposal.get("title") or category_key,
                "shortTitle": options.get("short-title")
                or proposal.get("shortTitle")
                or derive_short_title_from_text(proposal.get("displayName") or proposal.get("title") or category_key),
                "subtitle": options.get("subtitle") or proposal.get("subtitle"),
                "description": options.get("description") or proposal.get("description") or proposal.get("summary") or "",
                "aliases": [],
                "status": "accepted",
                "seedItemIds": normalize_string_list(proposal.get("suggestedSeedItemIds")),
                "holdoutItemIds": normalize_string_list(proposal.get("suggestedHoldoutItemIds")),
                "rank": len([entry for entry in target_categories if (entry.get("parentCategoryKey") or None) == parent_category_key]) + 1,
                "depth": (int(parent.get("depth") or 0) + 1) if parent else (1 if parent_category_key else 0),
                "isPinned": False,
                "importRunId": proposal.get("importRunId"),
                "updatedAt": now,
            },
            now=now,
            actor=actor,
            reason=f"proposal:{proposal['id']}",
        )
        next_count = (
            len(
                [
                    entry
                    for entry in target_categories
                    if entry.get("versionState") == "current" and entry.get("status") not in {"archived", "deprecated"}
                ]
            )
            + 1
        )
        category_set_update = {
            **category_set,
            "categoryCount": next_count,
            "changeReason": f"proposal:{proposal['id']}",
            "contentHash": hash_short({**category_set, "categoryCount": next_count, "updatedAt": now}),
        }
        records.extend(
            [
                {"modelName": "Category", "expected": category},
                {"modelName": "CategorySet", "expected": category_set_update},
            ]
        )
    apply = resolve_mutation_apply(options, "categories review-proposal")
    print(f"categories\treview-proposal\tmode\t{'apply' if apply else 'dry-run'}")
    print(
        f"categories\treview-proposal\tproposal\t{proposal['id']}\t{action}\t"
        f"{proposal.get('categoryKey') or ''}\t{proposal.get('targetCategoryKey') or ''}"
    )
    if category:
        print(
            f"categories\treview-proposal\tcategory\t{category['id']}\t{category['categoryKey']}\t"
            f"{category.get('parentCategoryKey') or ''}\tdepth={category.get('depth')}"
        )
    if not apply:
        print("categories\treview-proposal\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    for record in records:
        client.upsert(record["modelName"], record["expected"])
    count_deltas = {"openProposals": -1 if proposal.get("status") == "proposed" else 0}
    if category:
        count_deltas["categories"] = 1
    client.update_newsroom_summary(
        {"source": "incremental", "countDeltas": count_deltas},
        actor_label="Papyrus content CLI",
        reason=f"categories review-proposal {proposal['id']} {action}",
    )
    print(f"categories\treview-proposal\t{proposal['id']}\t{action}\t{category['id'] if category else ''}")
    if category:
        print(
            f"categories\treview-proposal\tnext\tpoetry run papyrus knowledge topics export-category-set "
            f"--category-set {category['categorySetId']} --output .papyrus-runs/{timestamp_for_path(now)}-{category['categorySetId']}.json"
        )
    else:
        print("categories\treview-proposal\tnext\tpoetry run papyrus sections recount-summary")


def categories_run_curation_cycle(flags: list[str]) -> None:
    options = parse_options(flags)
    steering_config = require_steering_config(options.get("config"))
    plan = build_curation_cycle_plan(
        steering_config,
        {"outputDir": options.get("output-dir"), "biblicusWorkdir": options.get("biblicus-workdir")},
    )
    Path(plan["runDir"]).mkdir(parents=True, exist_ok=True)
    client, _ = create_authoring_client()
    print(f"Curation cycle: {plan['runId']}")
    print(f"Run directory: {plan['runDir']}")
    validate_cycle_corpus_paths(plan)
    config_changes = build_steering_config_record_changes(client, build_steering_config_records(steering_config))
    apply_record_changes(client, config_changes)
    print_category_import_summary("config", "steering-config", config_changes)
    lexical_config = apply_lexical_steering_config_if_available(client, options)
    canonical_bundle = load_steering_bundle_from_biblicus(
        corpus=plan["canonical"]["corpus"]["path"],
        classifier=plan["canonical"]["classifierId"],
        biblicus_workdir=plan["biblicusWorkdir"],
    )
    write_json_file(plan["canonical"]["steeringPath"], canonical_bundle)
    steering_import_plan = build_steering_import_records(
        canonical_bundle,
        {
            "classifierId": plan["canonical"]["classifierId"],
            "corpusConfig": plan["canonical"]["corpus"],
            "corpusPath": str(resolve_biblicus_corpus_path(plan, plan["canonical"]["corpus"])),
            "ignoredTerms": [rule.get("term") for rule in lexical_config.get("ignoredTerms") or []],
        },
    )
    steering_changes = build_record_changes_tolerating_optional_models(client, steering_import_plan["records"])
    apply_record_changes(client, steering_changes)
    print_category_import_summary("steering", steering_import_plan["importRunId"], steering_changes)
    category_set = resolve_accepted_category_set(
        client,
        {
            "categorySetId": steering_import_plan["categorySetId"],
            "corpusId": plan["canonical"]["corpusId"],
            "classifierId": plan["canonical"]["classifierId"],
        },
    )
    if not category_set:
        raise ValueError(
            f"No accepted category set found for {plan['canonical']['corpusId']}/{plan['canonical']['classifierId']}."
        )
    categories = [
        category
        for category in client.list_records("Category")
        if category.get("categorySetId") == category_set.get("id") and category.get("status") != "archived"
    ]
    write_json_file(plan["canonical"]["categorySetPath"], build_accepted_category_set_payload(category_set, categories))
    write_json_file(plan["canonical"]["categoryTreePath"], build_accepted_category_tree_payload(category_set, categories))
    proposals = [proposal for proposal in client.list_records("SteeringProposal") if proposal.get("categorySetId") == category_set.get("id")]
    proposal_ids = {proposal["id"] for proposal in proposals}
    decisions = [
        decision
        for decision in client.list_records("SteeringDecision")
        if decision.get("categorySetId") == category_set.get("id") or decision.get("proposalId") in proposal_ids
    ]
    write_json_file(plan["canonical"]["steeringFeedbackPath"], build_steering_feedback_payload(category_set, proposals, decisions))
    write_lexical_steering_export_if_available(client, plan["canonical"]["lexicalSteeringPath"], lexical_config)
    canonical_extraction_snapshot = latest_pipeline_snapshot(canonical_bundle)
    if not canonical_extraction_snapshot:
        raise ValueError(f"No pipeline extraction snapshot found for {plan['canonical']['corpus']['key']}.")
    run_biblicus(
        plan,
        ["taxonomy", "record", "--corpus", plan["canonical"]["corpus"]["path"], "--input", plan["canonical"]["categoryTreePath"]],
        "taxonomy-record",
    )
    run_biblicus_json(
        plan,
        [
            "taxonomy",
            "discover",
            "--corpus",
            plan["canonical"]["corpus"]["path"],
            "--classifier",
            plan["canonical"]["classifierId"],
            "--extraction-snapshot",
            canonical_extraction_snapshot,
            "--steering-feedback",
            plan["canonical"]["steeringFeedbackPath"],
        ],
        "taxonomy-discover",
        plan["canonical"]["taxonomyDiscoveryPath"],
    )
    record_proposal_bundle_if_present(
        plan,
        plan["canonical"]["taxonomyDiscoveryPath"],
        plan["canonical"]["corpus"]["path"],
        "taxonomy-discover",
    )
    run_biblicus(
        plan,
        [
            "steering",
            "render-seed-manifest",
            "--input",
            plan["canonical"]["categorySetPath"],
            "--output",
            plan["canonical"]["seedManifestPath"],
        ],
        "render-seed-manifest",
    )
    run_biblicus(
        plan,
        [
            "topic-classifier",
            "train",
            "--corpus",
            plan["canonical"]["corpus"]["path"],
            "--manifest",
            plan["canonical"]["seedManifestPath"],
            "--configuration",
            "configurations/topic-classifier.yml",
            "--extraction-snapshot",
            canonical_extraction_snapshot,
        ],
        "topic-classifier-train",
    )
    for projection in plan.get("sourceProjections") or []:
        target_bundle = load_steering_bundle_from_biblicus(
            corpus=projection["targetCorpus"]["path"],
            classifier=(projection["targetCorpus"].get("localClassifiers") or [{}])[0].get("classifierId") or projection["classifierId"],
            biblicus_workdir=plan["biblicusWorkdir"],
        )
        write_json_file(projection["targetSteeringPath"], target_bundle)
        target_extraction_snapshot = latest_pipeline_snapshot(target_bundle)
        if not target_extraction_snapshot:
            raise ValueError(f"No pipeline extraction snapshot found for {projection['targetCorpus']['key']}.")
        run_biblicus_json(
            plan,
            [
                "topic-classifier",
                "project",
                "--classifier-corpus",
                plan["canonical"]["corpus"]["path"],
                "--target-corpus",
                projection["targetCorpus"]["path"],
                "--classifier",
                projection["classifierId"],
                "--extraction-snapshot",
                target_extraction_snapshot,
                "--all",
                "--record",
            ],
            f"project-{projection['targetCorpus']['key']}",
            projection["projectionPath"],
        )
        projection_payload = load_json_file(projection["projectionPath"])
        projection_category_set = resolve_accepted_category_set(
            client,
            {
                "categorySetId": category_set.get("id"),
                "corpusId": projection["authorityCorpusId"],
                "classifierId": projection["classifierId"],
            },
        )
        projection_import_plan = build_projection_import_records(
            projection_payload,
            {
                "authorityCorpusConfig": projection["authorityCorpus"],
                "authorityCorpusId": projection["authorityCorpusId"],
                "targetCorpusConfig": projection["targetCorpus"],
                "targetCorpusId": projection["targetCorpusId"],
                "classifierId": projection["classifierId"],
                "categorySetId": projection_category_set.get("id") if projection_category_set else None,
            },
        )
        projection_changes = build_record_changes_tolerating_optional_models(client, projection_import_plan["records"])
        apply_record_changes(client, projection_changes)
        print_category_import_summary(f"projection:{projection['targetCorpus']['key']}", projection_import_plan["importRunId"], projection_changes)
    refreshed_bundle = load_steering_bundle_from_biblicus(
        corpus=plan["canonical"]["corpus"]["path"],
        classifier=plan["canonical"]["classifierId"],
        biblicus_workdir=plan["biblicusWorkdir"],
    )
    refreshed_plan = build_steering_import_records(
        refreshed_bundle,
        {
            "classifierId": plan["canonical"]["classifierId"],
            "corpusConfig": plan["canonical"]["corpus"],
            "corpusPath": str(resolve_biblicus_corpus_path(plan, plan["canonical"]["corpus"])),
            "ignoredTerms": [rule.get("term") for rule in lexical_config.get("ignoredTerms") or []],
        },
    )
    refreshed_changes = build_record_changes_tolerating_optional_models(client, refreshed_plan["records"])
    apply_record_changes(client, refreshed_changes)
    print_category_import_summary("steering:refreshed", refreshed_plan["importRunId"], refreshed_changes)
    verification = verify_curation_cycle(client, {"plan": plan, "categorySetId": category_set.get("id")})
    write_json_file(plan["verificationPath"], verification)
    print_curation_verification(verification)
    if verification.get("failures"):
        raise RuntimeError(f"Curation cycle verification failed: {'; '.join(verification['failures'])}")


def categories_rebuild_roots(flags: list[str]) -> None:
    options = parse_options(flags)
    if not parse_boolean_option(options.get("yes"), default=False, label="--yes"):
        raise ValueError("categories rebuild-roots is mutating and requires --yes.")
    apply = resolve_mutation_apply(options, "categories rebuild-roots")
    steering_config = require_steering_config(options.get("config"))
    corpus_key = options.get("corpus-key") or steering_config["canonicalTopicSet"]["corpusKey"]
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key")
    classifier_id = resolve_classifier_for_corpus(steering_config, corpus_config, options.get("classifier"))
    root_min, root_max = parse_root_range_option(options.get("root-range"))
    lexical_config = load_lexical_steering_config(options.get("lexical-config"))
    ignored_terms = [rule.get("term") for rule in lexical_config.get("ignoredTerms") or [] if rule.get("term")]

    run_id = options.get("run-id") or f"root-rebuild-{timestamp_run_id()}-{slugify(corpus_key)}-{slugify(classifier_id)}"
    run_dir = Path(options.get("output-dir") or Path(".papyrus-runs") / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "runId": run_id,
        "runDir": str(run_dir),
        "biblicusWorkdir": str(Path(options.get("biblicus-workdir") or BIBLICUS_ROOT).resolve()),
    }
    corpus_path = str(resolve_biblicus_corpus_path(plan, corpus_config))
    if not Path(corpus_path).exists():
        raise ValueError(f"Corpus path was not found: {corpus_path}")

    client, _ = create_authoring_client()
    category_set = resolve_accepted_category_set(
        client,
        {
            "categorySetId": options.get("category-set"),
            "corpusId": knowledge_corpus_id(corpus_config),
            "classifierId": classifier_id,
        },
    )
    if not category_set:
        raise ValueError(f"No accepted category set found for corpus={corpus_key} classifier={classifier_id}.")
    categories = [
        entry
        for entry in client.list_records("Category")
        if entry.get("categorySetId") == category_set.get("id") and entry.get("status") != "archived"
    ]
    proposals = [proposal for proposal in client.list_records("SteeringProposal") if proposal.get("categorySetId") == category_set.get("id")]
    proposal_ids = {proposal["id"] for proposal in proposals if proposal.get("id")}
    decisions = [
        decision
        for decision in client.list_records("SteeringDecision")
        if decision.get("categorySetId") == category_set.get("id") or decision.get("proposalId") in proposal_ids
    ]
    write_json_file(run_dir / "accepted-category-set.json", build_accepted_category_set_payload(category_set, categories))
    write_json_file(run_dir / "accepted-category-tree.json", build_accepted_category_tree_payload(category_set, categories))
    write_json_file(run_dir / "steering-feedback.json", build_steering_feedback_payload(category_set, proposals, decisions))
    write_json_file(run_dir / "lexical-steering.json", build_lexical_steering_payload([], {"config": lexical_config}))

    steering_bundle = load_steering_bundle_from_biblicus(
        corpus=corpus_path,
        classifier=classifier_id,
        biblicus_workdir=plan["biblicusWorkdir"],
    )
    extraction_snapshot = options.get("extraction-snapshot") or latest_pipeline_snapshot(steering_bundle)
    if not extraction_snapshot:
        raise ValueError("Could not resolve extraction snapshot for root rebuild.")

    discovery_stdout = run_biblicus(
        plan,
        [
            "analyze",
            "topics",
            "--corpus",
            corpus_path,
            "--configuration",
            "configurations/topic-modeling/base.yml",
            "--configuration-name",
            f"root-rebuild:{classifier_id}",
            "--extraction-snapshot",
            extraction_snapshot,
            "--override",
            "bertopic_analysis.parameters.nr_topics=null",
            "--override",
            "bertopic_analysis.parameters.min_topic_size=2",
        ],
        "root-discovery",
    )
    root_discovery = json.loads(discovery_stdout or "{}")
    write_json_file(run_dir / "root-discovery-output.json", root_discovery)

    discovery_report = (root_discovery.get("report") or {}) if isinstance(root_discovery, dict) else {}
    topics = discovery_report.get("topics") if isinstance(discovery_report.get("topics"), list) else []
    selection = select_root_topic_candidates(
        topics=topics,
        ignored_terms=ignored_terms,
        root_min=root_min,
        root_max=root_max,
    )
    write_json_file(run_dir / "root-selection.json", selection)
    selected = selection.get("selected") or []
    if len(selected) < root_min:
        raise ValueError(
            f"Root rebuild selected {len(selected)} topics, below minimum {root_min}. "
            f"See {run_dir / 'root-selection.json'}."
        )

    draft_set, draft_categories = build_root_rebuild_draft_records(
        category_sets=client.list_records("CategorySet"),
        categories=client.list_records("Category"),
        accepted_category_set=category_set,
        selected_roots=selected,
        now=_utc_now(),
        actor=options.get("actor") or "Papyrus content CLI",
        reason=options.get("reason") or "Root taxonomy rebuild draft",
        draft_id=options.get("draft-id"),
    )
    draft_summary = {
        "runId": run_id,
        "categorySetId": draft_set.get("id"),
        "lineageId": draft_set.get("lineageId"),
        "selectedRootCount": len(selected),
        "selectedRoots": selected,
        "snapshotPaths": {
            "rootDiscovery": str(run_dir / "root-discovery-output.json"),
            "rootSelection": str(run_dir / "root-selection.json"),
            "acceptedCategorySet": str(run_dir / "accepted-category-set.json"),
            "acceptedCategoryTree": str(run_dir / "accepted-category-tree.json"),
            "steeringFeedback": str(run_dir / "steering-feedback.json"),
            "lexicalSteering": str(run_dir / "lexical-steering.json"),
        },
    }
    write_json_file(run_dir / "root-rebuild-draft-summary.json", draft_summary)
    print_draft_plan("rebuild-roots", category_sets=[draft_set], categories=draft_categories, apply=apply)
    print(f"categories\trebuild-roots\trun\t{run_id}")
    print(f"categories\trebuild-roots\troot-range\t{root_min}:{root_max}")
    print(f"categories\trebuild-roots\tselected-roots\t{len(selected)}")
    print(f"categories\trebuild-roots\tsummary\t{run_dir / 'root-rebuild-draft-summary.json'}")
    if not apply:
        print("categories\trebuild-roots\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    client.upsert("CategorySet", draft_set)
    for category in draft_categories:
        client.upsert("Category", category)
    print(f"categories\trebuild-roots\tdraft\t{draft_set['id']}\t{len(draft_categories)} roots")
    print(
        "categories\trebuild-roots\tnext\t"
        f"poetry run papyrus categories rebuild-roots-promote --category-set {draft_set['id']} --yes"
    )


def categories_rebuild_roots_promote(flags: list[str]) -> None:
    options = parse_options(flags)
    draft_id = options.get("category-set")
    if not draft_id:
        raise ValueError("categories rebuild-roots-promote requires --category-set <draft-id>.")
    if not parse_boolean_option(options.get("yes"), default=False, label="--yes"):
        raise ValueError("categories rebuild-roots-promote is mutating and requires --yes.")
    apply = resolve_mutation_apply(options, "categories rebuild-roots-promote")
    promote_flags = ["--category-set", draft_id]
    if not apply:
        promote_flags.append("--dry-run")
    if options.get("reason"):
        promote_flags.extend(["--reason", str(options.get("reason"))])
    categories_draft_promote(promote_flags)
    if not apply:
        return

    steering_config = require_steering_config(options.get("config"))
    lexical_config = load_lexical_steering_config(options.get("lexical-config"))
    ignored_terms = [rule.get("term") for rule in lexical_config.get("ignoredTerms") or [] if rule.get("term")]
    client, _ = create_authoring_client()
    promoted_set = client.get_record("CategorySet", draft_id)
    if not promoted_set:
        raise ValueError(f"Promoted CategorySet {draft_id} was not found.")
    corpus_id = promoted_set.get("corpusId")
    classifier_id = promoted_set.get("classifierId")
    corpus_config = next(
        (entry for entry in steering_config.get("corpora") or [] if knowledge_corpus_id(entry) == corpus_id),
        None,
    )
    if not corpus_config:
        raise ValueError(f"Could not resolve corpus config for promoted CategorySet {draft_id} ({corpus_id}).")

    run_id = options.get("run-id") or f"root-promote-{timestamp_run_id()}-{slugify(corpus_config.get('key') or corpus_id)}"
    run_dir = Path(options.get("output-dir") or Path(".papyrus-runs") / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "runId": run_id,
        "runDir": str(run_dir),
        "biblicusWorkdir": str(Path(options.get("biblicus-workdir") or BIBLICUS_ROOT).resolve()),
    }
    corpus_path = str(resolve_biblicus_corpus_path(plan, corpus_config))
    if not Path(corpus_path).exists():
        raise ValueError(f"Corpus path was not found: {corpus_path}")

    categories = [
        entry
        for entry in client.list_records("Category")
        if entry.get("categorySetId") == promoted_set.get("id") and entry.get("status") != "archived"
    ]
    proposals = [proposal for proposal in client.list_records("SteeringProposal") if proposal.get("categorySetId") == promoted_set.get("id")]
    proposal_ids = {proposal["id"] for proposal in proposals if proposal.get("id")}
    decisions = [
        decision
        for decision in client.list_records("SteeringDecision")
        if decision.get("categorySetId") == promoted_set.get("id") or decision.get("proposalId") in proposal_ids
    ]
    write_json_file(run_dir / "accepted-category-set.json", build_accepted_category_set_payload(promoted_set, categories))
    write_json_file(run_dir / "accepted-category-tree.json", build_accepted_category_tree_payload(promoted_set, categories))
    write_json_file(run_dir / "steering-feedback.json", build_steering_feedback_payload(promoted_set, proposals, decisions))
    write_json_file(run_dir / "lexical-steering.json", build_lexical_steering_payload([], {"config": lexical_config}))

    steering_bundle = load_steering_bundle_from_biblicus(
        corpus=corpus_path,
        classifier=classifier_id,
        biblicus_workdir=plan["biblicusWorkdir"],
    )
    extraction_snapshot = options.get("extraction-snapshot") or latest_pipeline_snapshot(steering_bundle)
    if not extraction_snapshot:
        raise ValueError("Could not resolve extraction snapshot for post-promote child discovery.")
    run_biblicus(
        plan,
        [
            "taxonomy",
            "record",
            "--corpus",
            corpus_path,
            "--input",
            str(run_dir / "accepted-category-tree.json"),
        ],
        "taxonomy-record-post-promote",
    )
    run_biblicus_json(
        plan,
        [
            "taxonomy",
            "discover",
            "--corpus",
            corpus_path,
            "--classifier",
            classifier_id,
            "--extraction-snapshot",
            extraction_snapshot,
            "--steering-feedback",
            str(run_dir / "steering-feedback.json"),
        ],
        "taxonomy-discover-post-promote",
        str(run_dir / "post-promote-child-discovery.json"),
    )
    discovery_bundle = load_json_file(run_dir / "post-promote-child-discovery.json")
    import_bundle = {
        "schema_version": 1,
        "generated_at": discovery_bundle.get("generated_at"),
        "corpus": {
            "name": corpus_config.get("name"),
            "role": corpus_config.get("role"),
            "corpus_uri": corpus_config.get("s3Prefix") or corpus_config.get("path"),
        },
        "proposals": discovery_bundle.get("proposals") or [],
        "artifacts": [],
        "warnings": discovery_bundle.get("warnings") or [],
    }
    import_plan = build_steering_import_records(
        import_bundle,
        {
            "classifierId": classifier_id,
            "corpusConfig": corpus_config,
            "corpusPath": corpus_path,
            "categorySetId": promoted_set.get("id"),
            "ignoredTerms": ignored_terms,
        },
    )
    changes = build_record_changes_tolerating_optional_models(client, import_plan["records"])
    apply_record_changes(client, changes)
    print_category_import_summary("post-promote-child-discovery", import_plan["importRunId"], changes)
    summary = {
        "runId": run_id,
        "categorySetId": promoted_set.get("id"),
        "importRunId": import_plan.get("importRunId"),
        "proposalCount": len(import_bundle.get("proposals") or []),
        "outputPath": str(run_dir / "post-promote-child-discovery.json"),
    }
    write_json_file(run_dir / "post-promote-summary.json", summary)
    print(f"categories\trebuild-roots-promote\trun\t{run_id}")
    print(f"categories\trebuild-roots-promote\tsummary\t{run_dir / 'post-promote-summary.json'}")


def categories_reset(flags: list[str]) -> None:
    options = parse_options(flags)
    if not parse_boolean_option(options.get("yes"), default=False, label="--yes"):
        raise ValueError("categories reset is destructive and requires --yes.")
    apply = resolve_mutation_apply(options, "categories reset")
    steering_config = require_steering_config(options.get("config"))
    client, _ = create_authoring_client()

    category_sets = client.list_records("CategorySet")
    if options.get("category-set"):
        selected = next((entry for entry in category_sets if entry.get("id") == options["category-set"]), None)
        if not selected:
            raise ValueError(f"CategorySet {options['category-set']} was not found.")
        selected_category_sets = [selected]
        corpus_id = selected.get("corpusId")
        classifier_id = selected.get("classifierId")
        corpus_key = options.get("corpus-key") or steering_config["canonicalTopicSet"]["corpusKey"]
    else:
        corpus_key = options.get("corpus-key") or steering_config["canonicalTopicSet"]["corpusKey"]
        corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key")
        corpus_id = knowledge_corpus_id(corpus_config)
        classifier_id = resolve_classifier_for_corpus(steering_config, corpus_config, options.get("classifier"))
        selected_category_sets = [
            entry
            for entry in category_sets
            if entry.get("corpusId") == corpus_id and entry.get("classifierId") == classifier_id
        ]
    if not selected_category_sets:
        raise ValueError("No CategorySet rows matched the reset scope.")

    category_set_ids = {entry["id"] for entry in selected_category_sets if entry.get("id")}
    categories = [entry for entry in client.list_records("Category") if entry.get("categorySetId") in category_set_ids]
    category_ids = {entry["id"] for entry in categories if entry.get("id")}
    proposals = [
        entry
        for entry in client.list_records("SteeringProposal")
        if entry.get("categorySetId") in category_set_ids
        or (
            corpus_id
            and entry.get("corpusId") == corpus_id
            and (not classifier_id or entry.get("classifierId") == classifier_id)
        )
    ]
    proposal_ids = {entry["id"] for entry in proposals if entry.get("id")}
    decisions = [
        entry
        for entry in client.list_records("SteeringDecision")
        if entry.get("categorySetId") in category_set_ids or entry.get("proposalId") in proposal_ids
    ]
    try:
        category_keywords = [entry for entry in client.list_records("CategoryKeyword") if entry.get("categorySetId") in category_set_ids]
    except (RuntimeError, KeyError, ValueError) as error:
        if not is_missing_graphql_model_error(error, "CategoryKeyword"):
            if not isinstance(error, KeyError):
                raise
        category_keywords = []
    raw_payload_targets = category_set_ids.union(category_ids).union(proposal_ids)
    knowledge_raw_payloads = [
        entry
        for entry in client.list_records("KnowledgeRawPayload")
        if entry.get("ownerId") in raw_payload_targets
        and entry.get("ownerType") in {"categorySet", "category", "proposal", "categoryTree"}
    ]
    snapshot = {
        "generatedAt": _utc_now(),
        "scope": {
            "corpusKey": corpus_key,
            "corpusId": corpus_id,
            "classifierId": classifier_id,
            "categorySetId": options.get("category-set"),
        },
        "counts": {
            "categorySets": len(selected_category_sets),
            "categories": len(categories),
            "categoryKeywords": len(category_keywords),
            "proposals": len(proposals),
            "decisions": len(decisions),
            "knowledgeRawPayloads": len(knowledge_raw_payloads),
        },
        "categorySets": selected_category_sets,
        "categories": categories,
        "categoryKeywords": category_keywords,
        "proposals": proposals,
        "decisions": decisions,
        "knowledgeRawPayloads": knowledge_raw_payloads,
    }
    suffix = f"{slugify(corpus_key or corpus_id or 'corpus')}-{slugify(classifier_id or 'classifier')}"
    output_dir = options.get("output-dir") or str(Path(".papyrus-runs") / "topic-reset" / f"{timestamp_for_path()}-{suffix}")
    snapshot_path = Path(output_dir) / "pre-reset-snapshot.json"
    write_json_file(snapshot_path, snapshot)

    print(f"categories\treset\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"categories\treset\tsnapshot\t{snapshot_path}")
    for key, value in snapshot["counts"].items():
        print(f"categories\treset\tcount\t{key}\t{value}")
    if not apply:
        print("categories\treset\tapply\tskipped\tuse --dry-run to preview without writes")
        return

    delete_groups = [
        ("SteeringDecision", decisions),
        ("SteeringProposal", proposals),
        ("CategoryKeyword", category_keywords),
        ("Category", categories),
        ("CategorySet", selected_category_sets),
        ("KnowledgeRawPayload", knowledge_raw_payloads),
    ]
    for model_name, rows in delete_groups:
        if not rows:
            continue
        try:
            for row in rows:
                if row.get("id"):
                    client.delete_record(model_name, row["id"])
        except (RuntimeError, KeyError, ValueError) as error:
            if not is_missing_graphql_model_error(error, model_name):
                if not isinstance(error, (KeyError, ValueError)):
                    raise
            print(f"categories\treset\tskip\t{model_name}\tmodel-not-deployed")
            continue
        print(f"categories\treset\tdeleted\t{model_name}\t{len(rows)}")

    print("categories\treset\tnext\tpoetry run papyrus newsroom recount-summary")


def apply_lexical_steering_config_if_available(client, options: dict[str, Any]) -> dict[str, Any]:
    lexical_config = load_lexical_steering_config(options.get("lexical-config"))
    try:
        lexical_changes = build_record_changes_tolerating_optional_models(client, build_lexical_steering_config_records(lexical_config))
        apply_record_changes(client, lexical_changes)
        print_category_import_summary("lexical-config", "papyrus-lexical-steering", lexical_changes)
    except (RuntimeError, KeyError, ValueError) as error:
        if not is_missing_graphql_model_error(error, "LexicalSteeringRule"):
            if not isinstance(error, (KeyError, ValueError)):
                raise
        print("skip\tlexical-config\tLexicalSteeringRule model is not deployed in AppSync yet.")
    return lexical_config


def write_lexical_steering_export_if_available(client, output_path: str, lexical_config: dict[str, Any]) -> None:
    try:
        lexical_rules = client.list_records("LexicalSteeringRule")
        write_json_file(output_path, build_lexical_steering_payload(lexical_rules, {"config": lexical_config}))
        print(f"export\tlexical-steering\t{output_path}\t{len(lexical_rules)} rules")
    except (RuntimeError, KeyError, ValueError) as error:
        if not is_missing_graphql_model_error(error, "LexicalSteeringRule"):
            if not isinstance(error, (KeyError, ValueError)):
                raise
        write_json_file(output_path, build_lexical_steering_payload([], {"config": lexical_config}))
        print("skip\tlexical-export\tLexicalSteeringRule model is not deployed in AppSync yet; wrote empty lexical export.")


def resolve_accepted_category_set(client, options: dict[str, Any]) -> dict[str, Any] | None:
    if options.get("categorySetId"):
        category_set = client.get_record("CategorySet", options["categorySetId"])
        if not category_set:
            raise ValueError(f"CategorySet {options['categorySetId']} was not found.")
        return category_set
    candidates = [
        category_set
        for category_set in client.list_records("CategorySet")
        if (not options.get("corpusId") or category_set.get("corpusId") == options.get("corpusId"))
        and (not options.get("classifierId") or category_set.get("classifierId") == options.get("classifierId"))
        and category_set.get("status") == "accepted"
        and (not category_set.get("versionState") or category_set.get("versionState") == "current")
    ]
    candidates.sort(key=lambda entry: str(entry.get("generatedAt") or entry.get("versionCreatedAt") or ""), reverse=True)
    return candidates[0] if candidates else None


def verify_curation_cycle(client, context: dict[str, Any]) -> dict[str, Any]:
    plan = context["plan"]
    category_set_id = context["categorySetId"]
    failures: list[str] = []
    category_set = client.get_record("CategorySet", category_set_id)
    if not category_set:
        failures.append(f"missing CategorySet {category_set_id}")
    categories = [
        category
        for category in client.list_records("Category")
        if category.get("categorySetId") == category_set_id and category.get("status") != "archived"
    ]
    if not categories:
        failures.append("no active categories found after curation cycle")
    for artifact_path in [
        plan["canonical"]["categorySetPath"],
        plan["canonical"]["categoryTreePath"],
        plan["canonical"]["steeringFeedbackPath"],
        plan["canonical"]["lexicalSteeringPath"],
    ]:
        if not Path(artifact_path).exists():
            failures.append(f"missing artifact {artifact_path}")
    return {
        "generatedAt": _utc_now(),
        "runId": plan["runId"],
        "categorySetId": category_set_id,
        "categoryCount": len(categories),
        "failures": failures,
        "ok": not failures,
    }


def print_curation_verification(verification: dict[str, Any]) -> None:
    print(f"Curation verification: {'ok' if verification.get('ok') else 'failed'}")
    print(f"Category set: {verification.get('categorySetId')}")
    print(f"Categories: {verification.get('categoryCount')}")
    for failure in verification.get("failures") or []:
        print(f"failure\t{failure}")


def print_category_import_summary(kind: str, import_run_id: str, changes: list[dict[str, Any]]) -> None:
    print(f"Import: {kind}")
    print(f"Run: {import_run_id}")
    counts: dict[str, int] = {}
    for change in changes:
        action = change.get("action") or "noop"
        counts[action] = counts.get(action, 0) + 1
    print(f"Summary: create={counts.get('create', 0)} update={counts.get('update', 0)} noop={counts.get('noop', 0)}")
    for change in changes:
        if change.get("action") == "noop":
            continue
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")


def print_draft_plan(
    label: str,
    *,
    category_sets: list[dict[str, Any]] | None = None,
    categories: list[dict[str, Any]] | None = None,
    apply: bool = False,
) -> None:
    print(f"categories\t{label}\tmode\t{'apply' if apply else 'dry-run'}")
    for category_set in category_sets or []:
        print(
            f"categories\t{label}\tcategory-set\t{category_set['id']}\t{category_set.get('versionState')}\t"
            f"{category_set.get('status')}\t{category_set.get('displayName')}"
        )
    for category in categories or []:
        print(
            f"categories\t{label}\tcategory\t{category['id']}\t{category.get('versionState')}\t"
            f"{category.get('status')}\t{category.get('categoryKey')}\t{category.get('displayName')}"
        )


def require_draft_category_set(category_set: dict[str, Any] | None, label: str) -> None:
    if not category_set:
        raise ValueError(f"CategorySet {label} was not found.")
    if category_set.get("versionState") != "draft" or category_set.get("status") != "draft":
        raise ValueError(
            f"CategorySet {category_set['id']} is {category_set.get('versionState')}/{category_set.get('status')}; "
            "this operation requires a draft CategorySet."
        )


def compare_categories_for_draft(left: dict[str, Any], right: dict[str, Any]) -> tuple[int, int, str]:
    return (
        int(left.get("depth") or 0),
        int(left.get("rank") or 999999),
        str(left.get("categoryKey") or left.get("id") or ""),
    )


def normalize_string_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    if isinstance(value, str):
        return [entry.strip() for entry in value.split(",") if entry.strip()]
    return []


def derive_category_key_from_text(value: Any) -> str:
    slug = slugify(str(value or "topic")).replace("-", "_")
    return slug or f"topic_{hash_short(value)[:8]}"


def derive_short_title_from_text(value: Any) -> str | None:
    words = [word for word in str(value or "").strip().split() if word]
    return " ".join(words[:2]) if words else None


def resolve_category_any(categories: list[dict[str, Any]], token: str) -> dict[str, Any]:
    matches = [
        category
        for category in categories
        if category.get("id") == token or category.get("lineageId") == token or category.get("categoryKey") == token
    ]
    if not matches:
        raise ValueError(f"Category {token} was not found.")
    return (
        next((category for category in matches if category.get("versionState") == "draft"), None)
        or next((category for category in matches if category.get("versionState") == "current"), None)
        or matches[0]
    )


def resolve_category_in_set(categories: list[dict[str, Any]], token: str, *, label: str = "--category") -> dict[str, Any]:
    matches = [
        category
        for category in categories
        if category.get("id") == token or category.get("lineageId") == token or category.get("categoryKey") == token
    ]
    if not matches:
        raise ValueError(f"{label} {token} did not match a category in the selected CategorySet.")
    if len(matches) > 1:
        return (
            next((category for category in matches if category.get("versionState") == "draft"), None)
            or next((category for category in matches if category.get("versionState") == "current"), None)
            or matches[0]
        )
    return matches[0]


def is_current_accepted_reference(reference: dict[str, Any]) -> bool:
    return reference.get("versionState") == "current" and normalize_reference_curation_status(
        reference.get("curationStatus"), "pending"
    ) == "accepted"


def with_version_fields(record: dict[str, Any], *, now: str, actor: str, reason: str) -> dict[str, Any]:
    versioned = {
        **record,
        "versionNumber": record.get("versionNumber") or 1,
        "previousVersionId": record.get("previousVersionId"),
        "versionState": record.get("versionState") or "current",
        "versionCreatedAt": record.get("versionCreatedAt") or now,
        "versionCreatedBy": record.get("versionCreatedBy") or actor,
        "changeReason": record.get("changeReason") or reason,
    }
    return {**versioned, "contentHash": record.get("contentHash") or hash_stable(normalize_record(versioned))}


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    ignored = {"updatedAt", "createdAt", "importedAt", "versionCreatedAt", "contentHash"}
    return {key: value for key, value in record.items() if key not in ignored}


def slugify(value: Any) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()))


def timestamp_for_path(value: str | None = None) -> str:
    return re.sub(r"(^-|-$)", "", re.sub(r"[^0-9A-Za-z]+", "-", str(value or _utc_now())))


def parse_root_range_option(value: Any) -> tuple[int, int]:
    raw = str(value or "12:20").strip()
    match = re.fullmatch(r"(\d+)\s*:\s*(\d+)", raw)
    if not match:
        raise ValueError("--root-range must be formatted as min:max (for example 12:20).")
    minimum = int(match.group(1))
    maximum = int(match.group(2))
    if minimum < 1 or maximum < 1:
        raise ValueError("--root-range values must be positive integers.")
    if minimum > maximum:
        raise ValueError("--root-range minimum must be less than or equal to maximum.")
    return minimum, maximum


def select_root_topic_candidates(
    *,
    topics: list[dict[str, Any]],
    ignored_terms: list[str],
    root_min: int,
    root_max: int,
) -> dict[str, Any]:
    normalized_ignored = {normalize_lexical_term(value) for value in ignored_terms if normalize_lexical_term(value)}
    merged: dict[str, dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for topic in topics:
        topic_id = int(topic.get("topic_id") or -1)
        if topic_id == -1:
            continue
        label = str(topic.get("label") or "").strip()
        if not label:
            continue
        normalized_label = normalize_lexical_term(label)
        keywords = [
            normalize_lexical_term(entry.get("keyword"))
            for entry in (topic.get("keywords") or [])
            if isinstance(entry, dict) and normalize_lexical_term(entry.get("keyword"))
        ]
        if normalized_label in normalized_ignored:
            skipped.append({"label": label, "reason": "ignored-label", "topicId": topic_id})
            continue
        non_ignored_keywords = [keyword for keyword in keywords if keyword not in normalized_ignored]
        if not non_ignored_keywords:
            skipped.append({"label": label, "reason": "ignored-keywords", "topicId": topic_id})
            continue
        category_key = derive_category_key_from_text(non_ignored_keywords[0] if non_ignored_keywords else label)
        entry = merged.get(category_key)
        document_ids = sorted({str(item_id) for item_id in topic.get("document_ids") or [] if str(item_id).strip()})
        if entry is None:
            merged[category_key] = {
                "topicId": topic_id,
                "displayName": title_case_label(non_ignored_keywords[0] if non_ignored_keywords else label),
                "categoryKey": category_key,
                "description": build_root_description(label, non_ignored_keywords),
                "keywords": non_ignored_keywords[:12],
                "documentIds": document_ids,
                "documentCount": int(topic.get("document_count") or len(document_ids) or 0),
                "confidence": float(((topic.get("keywords") or [{}])[0] or {}).get("score") or 0),
            }
        else:
            entry["documentIds"] = sorted({*entry.get("documentIds", []), *document_ids})
            entry["documentCount"] = max(int(entry.get("documentCount") or 0), int(topic.get("document_count") or 0), len(entry["documentIds"]))
            entry["confidence"] = max(float(entry.get("confidence") or 0), float(((topic.get("keywords") or [{}])[0] or {}).get("score") or 0))
            entry["keywords"] = list(dict.fromkeys([*entry.get("keywords", []), *non_ignored_keywords]))[:12]
    candidates = sorted(
        merged.values(),
        key=lambda entry: (
            -(int(entry.get("documentCount") or 0)),
            -(float(entry.get("confidence") or 0)),
            str(entry.get("categoryKey") or ""),
        ),
    )
    selected = candidates[:root_max]
    return {
        "requestedRange": {"min": root_min, "max": root_max},
        "candidateCount": len(candidates),
        "selectedCount": len(selected),
        "ignoredTermCount": len(normalized_ignored),
        "ignoredTerms": sorted(normalized_ignored),
        "skipped": skipped,
        "candidates": candidates,
        "selected": selected,
    }


def build_root_rebuild_draft_records(
    *,
    category_sets: list[dict[str, Any]],
    categories: list[dict[str, Any]],
    accepted_category_set: dict[str, Any],
    selected_roots: list[dict[str, Any]],
    now: str,
    actor: str,
    reason: str,
    draft_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lineage_id = accepted_category_set.get("lineageId") or accepted_category_set.get("id")
    next_version = max(
        [
            0,
            *[
                int(entry.get("versionNumber") or 0)
                for entry in category_sets
                if (entry.get("lineageId") or entry.get("id")) == lineage_id
            ],
        ]
    ) + 1
    resolved_draft_id = draft_id or f"{slugify(lineage_id)}-root-rebuild-v{next_version}"
    if any(entry.get("id") == resolved_draft_id for entry in category_sets):
        raise ValueError(f"Draft CategorySet {resolved_draft_id} already exists.")
    accepted_categories = [entry for entry in categories if entry.get("categorySetId") == accepted_category_set.get("id")]
    max_category_version_by_lineage: dict[str, int] = {}
    for category in categories:
        category_lineage = category.get("lineageId") or category.get("id")
        max_category_version_by_lineage[category_lineage] = max(
            max_category_version_by_lineage.get(category_lineage, 0),
            int(category.get("versionNumber") or 0),
        )
    lineage_by_category_key = {
        str(category.get("categoryKey") or ""): category.get("lineageId") or category.get("id")
        for category in accepted_categories
        if category.get("categoryKey")
    }
    current_by_lineage = {
        category.get("lineageId") or category.get("id"): category
        for category in accepted_categories
        if category.get("versionState") == "current"
    }
    draft_set = with_version_fields(
        {
            "id": resolved_draft_id,
            "lineageId": lineage_id,
            "versionNumber": next_version,
            "previousVersionId": accepted_category_set.get("id"),
            "versionState": "draft",
            "corpusId": accepted_category_set.get("corpusId"),
            "classifierId": accepted_category_set.get("classifierId"),
            "displayName": f"{accepted_category_set.get('displayName') or 'Category Set'} Root Rebuild Draft",
            "description": accepted_category_set.get("description") or "Draft root taxonomy rebuilt from BERTopic full-corpus discovery.",
            "status": "draft",
            "generatedAt": now,
            "categoryCount": len(selected_roots),
            "importRunId": accepted_category_set.get("importRunId"),
        },
        now=now,
        actor=actor,
        reason=reason,
    )
    draft_categories: list[dict[str, Any]] = []
    for index, root in enumerate(selected_roots):
        category_key = str(root.get("categoryKey") or derive_category_key_from_text(root.get("displayName") or f"root-{index+1}"))
        lineage = lineage_by_category_key.get(category_key) or f"category-{slugify(lineage_id)}-{slugify(category_key)}"
        previous_current = current_by_lineage.get(lineage)
        draft_categories.append(
            with_version_fields(
                {
                    "id": f"{slugify(lineage)}-root-rebuild-v{next_version}",
                    "lineageId": lineage,
                    "versionNumber": max_category_version_by_lineage.get(lineage, 0) + 1,
                    "previousVersionId": previous_current.get("id") if previous_current else None,
                    "versionState": "draft",
                    "categorySetId": draft_set["id"],
                    "corpusId": draft_set.get("corpusId"),
                    "categoryKey": category_key,
                    "parentCategoryId": None,
                    "parentCategoryKey": None,
                    "displayName": str(root.get("displayName") or title_case_label(category_key)).strip(),
                    "shortTitle": derive_short_title_from_text(root.get("displayName") or category_key),
                    "subtitle": None,
                    "description": root.get("description") or build_root_description(str(root.get("displayName") or category_key), []),
                    "aliases": [],
                    "status": "accepted",
                    "seedItemIds": sorted({str(item_id) for item_id in root.get("documentIds") or [] if str(item_id).strip()})[:250],
                    "holdoutItemIds": [],
                    "rank": index + 1,
                    "depth": 0,
                    "isPinned": False,
                    "importRunId": draft_set.get("importRunId"),
                    "updatedAt": now,
                },
                now=now,
                actor=actor,
                reason=reason,
            )
        )
    return draft_set, draft_categories


def build_root_description(label: str, keywords: list[str]) -> str:
    keyword_text = ", ".join(keywords[:5])
    if keyword_text:
        return f"Keywords: {keyword_text}."
    return f"Root topic: {label}."


def title_case_label(value: str) -> str:
    parts = [part for part in re.split(r"[\s._:/-]+", str(value or "").strip()) if part]
    if not parts:
        return "Topic"
    return " ".join(part.capitalize() for part in parts[:6])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
