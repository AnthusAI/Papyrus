from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from papyrus_newsroom import reference_actions as newsroom_reference_actions

from .assignments import apply_assignment_action
from .env import PAPYRUS_ROOT
from .graphql_authoring import create_authoring_client
from .ids import hash_short, knowledge_corpus_id
from .model_defaults import (
    DEFAULT_REFERENCE_FILTER_MODEL,
    DEFAULT_REFERENCE_SUMMARY_MODEL,
)
from .newsroom_summary import (
    semantic_relation_count_delta,
    update_newsroom_summary_after_assignment_creates,
    update_newsroom_summary_after_extracted_text_attachments,
    update_newsroom_summary_delta,
)
from .options import (
    normalize_non_negative_integer,
    normalize_positive_integer,
    normalize_string,
    parse_boolean_option,
    parse_options,
    parse_repeated_option,
    resolve_mutation_apply,
)
from .records import apply_record_changes, build_record_changes, build_record_changes_targeted_by_id
from .reference_assignments import (
    build_reference_identifier_backfill_assignment_plan,
    build_text_extraction_assignment_records,
    doi_backfill_compatibility_flags,
    execute_reference_text_extraction_assignment,
    normalize_identifier_types,
    timestamp_for_path,
)
from .reference_discovery import run_citation_led_discovery
from .assignment_executors import execute_assignment_by_type
from .reference_attachments import build_extracted_text_attachment_plans
from .reference_citation_resolution import build_reference_citation_resolution_records
from .reference_exports import build_reference_analysis_manifest, build_reference_scope_training_export
from .reference_url_text import (
    build_reference_citation_count_records,
    run_reference_identifier_dedupe,
    run_reference_extracted_text_filtering,
    run_reference_source_find,
    run_reference_url_text_extraction,
)
from .reference_metadata_generation import run_reference_metadata_generation_from_extracted_text
from .reference_labels import (
    apply_label_relation,
    apply_unlabel_relation,
    build_accept_authoritative_label_from_prediction,
    build_classification_prediction_rows,
    build_label_rows,
    build_manual_authoritative_label_relation,
    find_current_authoritative_label,
    print_reference_label_plan,
    resolve_category_any,
    resolve_category_in_set,
    resolve_reference_any,
    resolve_reference_for_label,
)
from .reference_policy import normalize_reference_rejection_reason_code
from .source_readiness import build_extraction_index
from .steering import load_steering_config, require_corpus_config, require_steering_config

DEFAULT_GROBID_URL = "http://127.0.0.1:8070"
GROBID_CONTAINER_NAME_ENV = "BIBLICUS_GROBID_CONTAINER_NAME"
GROBID_DOCKER_IMAGE_ENV = "BIBLICUS_GROBID_DOCKER_IMAGE"
DEFAULT_GROBID_CONTAINER_NAME = "biblicus-grobid"
DEFAULT_GROBID_DOCKER_IMAGE = "lfoppiano/grobid:0.8.0"
DOCKER_CANDIDATE_PATHS = (
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
    "/Applications/Docker.app/Contents/Resources/bin/docker",
)


def references_review_curation(flags: list[str]) -> None:
    options = parse_options(flags)
    reference_id = options.get("reference") or options.get("reference-id")
    if not reference_id:
        raise ValueError("references review-curation requires --reference <id>.")
    if not options.get("action"):
        raise ValueError("references review-curation requires --action accept|reject|reopen|archive.")
    reason_code = normalize_reference_rejection_reason_code(
        options.get("reason-code") or options.get("reasonCode"),
        required=str(options.get("action")).lower() == "reject",
    )
    client, _ = create_authoring_client()
    review = newsroom_reference_actions.review_reference_curation(
        client.graphql,
        reference_id=str(reference_id),
        action=str(options["action"]),
        note=str(options.get("note") or ""),
        actor_label=str(options.get("actor") or "Papyrus content CLI"),
        reason_code=reason_code or "",
    )
    print(
        f"references\treview-curation\t{review.get('referenceId')}\t{review.get('action')}\t"
        f"{review.get('status')}\t{review.get('reasonCode') or ''}\t{review.get('messageId') or ''}"
    )


def references_list_predictions(flags: list[str]) -> None:
    options = parse_options(flags)
    limit = normalize_positive_integer(options.get("limit"), "--limit")
    status = str(options.get("status") or "current").lower()
    corpus_key = normalize_string(options.get("corpus-key"))
    category_set_id = normalize_string(options.get("category-set"))
    steering_config = load_steering_config(options.get("config")) if corpus_key else None
    corpus_id = (
        knowledge_corpus_id(require_corpus_config(steering_config, corpus_key, "--corpus-key"))
        if corpus_key and steering_config
        else None
    )
    client, _ = create_authoring_client()
    relations = client.list_records("SemanticRelation")
    references = client.list_records("Reference")
    categories = client.list_records("Category")
    predictions = build_classification_prediction_rows(
        relations=relations,
        references=references,
        categories=categories,
        corpus_id=corpus_id,
        category_set_id=category_set_id,
        status=status,
        limit=limit,
    )
    for entry in predictions:
        print(
            "\t".join(
                [
                    entry["relation"]["id"],
                    entry["relation"].get("relationState") or "-",
                    entry["reference"].get("corpusId") or "-",
                    entry["reference"].get("externalItemId") or "-",
                    entry["reference"].get("title") or "-",
                    entry["category"].get("categoryKey") or entry["category"]["id"],
                    entry["category"].get("displayName") or "-",
                    "authoritative" if entry["hasAuthoritativeLabel"] else "predicted",
                ]
            )
        )
    if not predictions:
        print("references\tlist-predictions\t0")


def references_backfill_reviewed_feed_key(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-reviewed-feed-key")
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    changes: list[dict[str, Any]] = []
    for reference in references:
        curation_status = str(reference.get("curationStatus") or "pending").strip().lower() or "pending"
        expected_reviewed_feed_key = None if curation_status == "pending" else "references#reviewed"
        if (reference.get("reviewedFeedKey") or None) == expected_reviewed_feed_key:
            continue
        expected = {**reference, "reviewedFeedKey": expected_reviewed_feed_key}
        changes.append({"current": reference, "expected": expected})
    print(f"references\tbackfill-reviewed-feed-key\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"references\tbackfill-reviewed-feed-key\tscanned\t{len(references)}")
    print(f"references\tbackfill-reviewed-feed-key\tplanned\t{len(changes)}")
    for change in changes[:20]:
        current = change["current"]
        expected = change["expected"]
        print(
            "references\tbackfill-reviewed-feed-key\tcandidate\t"
            f"{current.get('id')}\t{current.get('curationStatus') or 'pending'}\t{expected.get('reviewedFeedKey') or '-'}"
        )
    if len(changes) > 20:
        print(f"references\tbackfill-reviewed-feed-key\tpreview-truncated\t{len(changes) - 20}")
    if not apply:
        print("references\tbackfill-reviewed-feed-key\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    for index, change in enumerate(changes, start=1):
        client.upsert("Reference", change["expected"])
        if index == len(changes) or index % 100 == 0:
            print(f"references\tbackfill-reviewed-feed-key\tprogress\t{index}/{len(changes)}")
    print(f"references\tbackfill-reviewed-feed-key\tupdated\t{len(changes)}")


def references_backfill_corpus_storage_paths(flags: list[str]) -> None:
    from .corpus_storage_paths import rewrite_corpus_storage_path
    from .env import storage_bucket_from_amplify_outputs

    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "references backfill-corpus-storage-paths")
    mirror_s3 = parse_boolean_option(options.get("mirror-s3"), False, "--mirror-s3")
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    corpus_key_by_id = {
        knowledge_corpus_id(entry): str(entry.get("key") or "")
        for entry in steering_config.get("corpora") or []
        if isinstance(entry, dict)
    }

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    if reference_ids:
        reference_id_set = reference_ids
        lineage_ids = {
            str(reference.get("lineageId") or "")
            for reference in references
            if str(reference.get("id") or "") in reference_id_set
        }
        references = [
            reference
            for reference in references
            if str(reference.get("id") or "") in reference_id_set
            or str(reference.get("lineageId") or "") in lineage_ids
        ]
        attachments = [
            attachment
            for attachment in attachments
            if str(attachment.get("referenceId") or "") in reference_id_set
            or str(attachment.get("referenceLineageId") or "") in lineage_ids
        ]

    changes: list[dict[str, Any]] = []
    s3_pairs: list[tuple[str, str]] = []

    def plan_storage_path_update(model_name: str, record: dict[str, Any], field: str) -> None:
        current_path = normalize_string(record.get(field))
        if not current_path or not current_path.startswith("corpora/"):
            return
        record_corpus_id = normalize_string(record.get("corpusId"))
        if corpus_id and record_corpus_id and record_corpus_id != corpus_id:
            return
        record_corpus_key = corpus_key or corpus_key_by_id.get(record_corpus_id or "", "")
        rewritten = rewrite_corpus_storage_path(current_path, corpus_key=record_corpus_key or None)
        if not rewritten or rewritten == current_path:
            return
        expected = {**record, field: rewritten}
        changes.append({"modelName": model_name, "current": record, "expected": expected})
        s3_pairs.append((current_path, rewritten))

    for reference in references:
        plan_storage_path_update("Reference", reference, "storagePath")
    for attachment in attachments:
        plan_storage_path_update("ReferenceAttachment", attachment, "storagePath")

    print(f"references\tbackfill-corpus-storage-paths\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"references\tbackfill-corpus-storage-paths\tcorpus\t{corpus_id or 'all'}")
    if reference_ids:
        print(f"references\tbackfill-corpus-storage-paths\treference-filter\t{len(reference_ids)}")
    print(f"references\tbackfill-corpus-storage-paths\tplanned\t{len(changes)}")
    print(f"references\tbackfill-corpus-storage-paths\tmirror-s3\t{str(mirror_s3).lower()}")
    for change in changes[:25]:
        current_path = change["current"].get("storagePath") or "-"
        expected_path = change["expected"].get("storagePath") or "-"
        print(
            "references\tbackfill-corpus-storage-paths\tcandidate\t"
            f"{change['modelName']}\t{change['current'].get('id')}\t{current_path}\t=>\t{expected_path}"
        )
    if len(changes) > 25:
        print(f"references\tbackfill-corpus-storage-paths\tpreview-truncated\t{len(changes) - 25}")
    if not apply:
        print("references\tbackfill-corpus-storage-paths\tapply\tskipped\tuse --dry-run to preview without writes")
        return

    bucket = storage_bucket_from_amplify_outputs()
    s3_client = None
    if mirror_s3 and bucket:
        try:
            import boto3  # type: ignore

            s3_client = boto3.client("s3")
        except ImportError:
            print("references\tbackfill-corpus-storage-paths\tmirror-s3\tskipped\tboto3 unavailable")
            mirror_s3 = False

    mirrored = 0
    mirror_skipped = 0
    mirror_failed = 0
    if mirror_s3 and s3_client and bucket:
        for old_key, new_key in dict.fromkeys(s3_pairs).items():
            try:
                s3_client.head_object(Bucket=bucket, Key=new_key)
                mirror_skipped += 1
                continue
            except Exception:  # noqa: BLE001
                pass
            try:
                s3_client.copy_object(
                    Bucket=bucket,
                    Key=new_key,
                    CopySource={"Bucket": bucket, "Key": old_key},
                )
                mirrored += 1
            except Exception as error:  # noqa: BLE001
                mirror_failed += 1
                print(
                    "references\tbackfill-corpus-storage-paths\tmirror-failed\t"
                    f"{old_key}\t{new_key}\t{error}"
                )
        print(f"references\tbackfill-corpus-storage-paths\tmirrored\t{mirrored}")
        print(f"references\tbackfill-corpus-storage-paths\tmirror-skipped-existing\t{mirror_skipped}")
        print(f"references\tbackfill-corpus-storage-paths\tmirror-failed\t{mirror_failed}")

    for index, change in enumerate(changes, start=1):
        client.upsert(change["modelName"], change["expected"])
        if index == len(changes) or index % 100 == 0:
            print(f"references\tbackfill-corpus-storage-paths\tprogress\t{index}/{len(changes)}")
    print(f"references\tbackfill-corpus-storage-paths\tupdated\t{len(changes)}")


def references_review_classification(flags: list[str]) -> None:
    options = parse_options(flags)
    relation_id = options.get("relation") or options.get("relation-id")
    action = str(options.get("action") or "").lower()
    if not relation_id:
        raise ValueError("references review-classification requires --relation <semantic-relation-id>.")
    if action not in {"accept", "reject"}:
        raise ValueError("references review-classification requires --action accept|reject.")
    client, _ = create_authoring_client()
    relation = client.get_record("SemanticRelation", relation_id)
    if not relation:
        raise ValueError(f"SemanticRelation {relation_id} was not found.")
    predicate = relation.get("relationTypeKey") or relation.get("predicate")
    if predicate != "classified_as":
        raise ValueError(f"SemanticRelation {relation_id} is not a classified_as prediction.")
    if relation.get("relationState") != "current":
        raise ValueError(
            f"SemanticRelation {relation_id} is {relation.get('relationState')}; only current predictions are reviewable."
        )
    if relation.get("subjectKind") != "reference" or relation.get("objectKind") != "category":
        raise ValueError(f"SemanticRelation {relation_id} must be reference -> category.")
    if action == "reject":
        client.delete_record("SemanticRelation", relation_id)
        update_newsroom_summary_delta(
            client,
            {
                "countDeltas": {"semanticRelations": -1},
                "facetDeltas": {
                    "semanticRelations": {
                        "byRelationTypeKey": {"classified_as": -1},
                        "byRelationDomain": {relation.get("relationDomain") or "unknown": -1},
                        "bySubjectKind": {relation.get("subjectKind") or "unknown": -1},
                        "byObjectKind": {relation.get("objectKind") or "unknown": -1},
                    },
                },
            },
            f"references review-classification reject {relation_id}",
        )
        print(f"references\treview-classification\t{relation_id}\treject\tdeleted_prediction")
        return
    authoritative = build_accept_authoritative_label_from_prediction(relation, note=options.get("note"))
    client.upsert("SemanticRelation", authoritative)
    update_newsroom_summary_delta(
        client,
        semantic_relation_count_delta(authoritative, 1),
        f"references review-classification accept {relation_id}",
    )
    print(f"references\treview-classification\t{relation_id}\taccept\t{authoritative['id']}")


def references_label(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("reference"):
        raise ValueError("references label requires --reference <reference-id|item-id>.")
    if not options.get("category"):
        raise ValueError("references label requires --category <category-key|lineage-id|id>.")
    if not options.get("category-set"):
        raise ValueError("references label requires --category-set <id>.")
    if not options.get("note"):
        raise ValueError("references label requires --note <text>.")
    client, _ = create_authoring_client()
    category_set = client.get_record("CategorySet", options["category-set"])
    if not category_set:
        raise ValueError(f"CategorySet {options['category-set']} was not found.")
    references = client.list_records("Reference")
    categories = client.list_records("Category")
    relations = client.list_records("SemanticRelation")
    reference = resolve_reference_for_label(references, options["reference"])
    category = resolve_category_in_set(
        [entry for entry in categories if entry.get("categorySetId") == category_set["id"]],
        options["category"],
        label="--category",
    )
    if category.get("status") in {"deprecated", "archived"}:
        raise ValueError(f"Category {category['id']} is {category['status']}; label an active draft/current category.")
    authoritative = build_manual_authoritative_label_relation(
        reference=reference,
        category=category,
        category_set=category_set,
        note=options["note"],
        actor=options.get("actor") or "Papyrus content CLI",
    )
    existing = find_current_authoritative_label(relations, authoritative)
    if existing:
        print(
            f"references\tlabel\t{reference['id']}\t{category.get('categoryKey')}\tidempotent\t{existing['id']}"
        )
        return
    apply = resolve_mutation_apply(options, "references label")
    print_reference_label_plan("label", [authoritative], apply=apply)
    if not apply:
        print("references\tlabel\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_label_relation(
        client,
        authoritative,
        reference_id=reference["id"],
        category_key=str(category.get("categoryKey") or category["id"]),
    )
    print(f"references\tlabel\t{reference['id']}\t{category.get('categoryKey')}\t{authoritative['id']}")


def references_unlabel(flags: list[str]) -> None:
    options = parse_options(flags)
    relation_id = options.get("relation") or options.get("relation-id")
    if not relation_id:
        raise ValueError("references unlabel requires --relation <authoritative-label-relation-id>.")
    client, _ = create_authoring_client()
    relation = client.get_record("SemanticRelation", relation_id)
    if not relation:
        raise ValueError(f"SemanticRelation {relation_id} was not found.")
    if (relation.get("relationTypeKey") or relation.get("predicate")) != "authoritative_label":
        raise ValueError(f"SemanticRelation {relation_id} is not an authoritative_label relation.")
    apply = resolve_mutation_apply(options, "references unlabel")
    print_reference_label_plan("unlabel", [relation], apply=apply)
    if not apply:
        print("references\tunlabel\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    apply_unlabel_relation(client, relation)
    print(f"references\tunlabel\t{relation_id}\tdeleted_authoritative_label")


def references_labels(flags: list[str]) -> None:
    options = parse_options(flags)
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    categories = client.list_records("Category")
    relations = client.list_records("SemanticRelation")
    reference = resolve_reference_any(references, options["reference"]) if options.get("reference") else None
    category = None
    if options.get("category"):
        candidates = (
            [entry for entry in categories if entry.get("categorySetId") == options.get("category-set")]
            if options.get("category-set")
            else categories
        )
        category = resolve_category_any(candidates, options["category"])
    limit = normalize_positive_integer(options.get("limit"), "--limit")
    rows = build_label_rows(
        relations=relations,
        references=references,
        categories=categories,
        reference=reference,
        category=category,
        limit=limit,
    )
    for row in rows:
        print(
            "\t".join(
                [
                    row["relation"]["id"],
                    row["relation"].get("relationTypeKey") or row["relation"].get("predicate") or "-",
                    row["reference"].get("curationStatus") or "-",
                    row["reference"].get("externalItemId") or row["reference"]["id"],
                    row["reference"].get("title") or "-",
                    row["category"].get("categoryKey") or row["category"]["id"],
                    row["category"].get("displayName") or "-",
                    row["category"].get("categorySetId") or "-",
                ]
            )
        )
    if not rows:
        print("references\tlabels\t0")


def references_discover_citation_led(flags: list[str]) -> None:
    run_citation_led_discovery(flags)


def references_curate_recent(flags: list[str]) -> None:
    options = parse_options(flags)
    references = parse_repeated_option(flags, "reference")
    apply = resolve_mutation_apply(options, "references curate-recent")
    dry_run = parse_boolean_option(options.get("dry-run"), False, "--dry-run")
    json_output = parse_boolean_option(options.get("json"), False, "--json")
    if not options.get("corpus-key"):
        raise ValueError("references curate-recent requires --corpus-key <key>.")
    curate_all = parse_boolean_option(options.get("all"), False, "--all")
    if parse_boolean_option(options.get("refresh-quality"), False, "--refresh-quality"):
        raise ValueError(
            "references curate-recent no longer supports --refresh-quality. "
            "Quality is human-only; use references review-curation / quality actions explicitly."
        )
    args = [
        "run",
        "papyrus",
        "references",
        "curate-recent",
        "--corpus-key",
        options["corpus-key"],
        "--model",
        normalize_string(options.get("model")) or DEFAULT_REFERENCE_FILTER_MODEL,
        "--summary-max-tokens",
        str(normalize_non_negative_integer(options.get("summary-max-tokens"), "--summary-max-tokens") or 500),
        "--max-count",
        str(normalize_non_negative_integer(options.get("max-count"), "--max-count") or 0),
        "--scan-limit",
        str(normalize_positive_integer(options.get("scan-limit"), "--scan-limit") or 1000),
        "--max-parallel",
        str(normalize_positive_integer(options.get("max-parallel"), "--max-parallel") or 1),
    ]
    if curate_all:
        args.append("--all")
    else:
        args.extend(
            [
                "--since-hours",
                str(normalize_non_negative_integer(options.get("since-hours"), "--since-hours") or 48),
            ]
        )
    since = normalize_string(options.get("since"))
    if since:
        args.extend(["--since", since])
    resume = normalize_string(options.get("resume"))
    if resume:
        args.extend(["--resume", resume])
    for reference_id in references:
        args.extend(["--reference", reference_id])
    if parse_boolean_option(options.get("refresh-summary"), False, "--refresh-summary"):
        args.append("--refresh-summary")
    args.append("--dry-run")
    completed = subprocess.run(["poetry", *args], cwd=PAPYRUS_ROOT, capture_output=True, text=True, check=False)
    payload = extract_last_json_object(completed.stdout or "")
    if not payload:
        raise RuntimeError(
            "papyrus references curate-recent returned invalid JSON: "
            f"{completed.stderr or completed.stdout or 'unknown error'}"
        )
    if completed.returncode != 0:
        raise RuntimeError(f"papyrus references curate-recent exited with status {completed.returncode}")
    summary = payload.get("selectionSummary") or payload.get("summary") or {}
    selected_reference_ids = [
        normalize_string(value)
        for value in (payload.get("selectedReferenceIds") or [])
        if normalize_string(value)
    ]
    if not selected_reference_ids:
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            if item.get("failed"):
                continue
            reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
            reference_id = (
                normalize_string(reference.get("id"))
                or normalize_string(item.get("referenceId"))
            )
            if reference_id:
                selected_reference_ids.append(reference_id)
    selected_reference_ids = sorted(set(selected_reference_ids))
    dispatches: list[dict[str, Any]] = []
    if apply and selected_reference_ids:
        client, _ = create_authoring_client()
        actor_label = normalize_string(options.get("actor")) or "Papyrus content CLI"
        for reference_id in selected_reference_ids:
            result = newsroom_reference_actions.start_reference_curation(
                client.graphql,
                reference_id=reference_id,
                actor_label=actor_label,
                curation_policy=None,
            )
            dispatches.append(
                {
                    "referenceId": normalize_string(result.get("referenceId")) or reference_id,
                    "assignmentId": normalize_string(result.get("assignmentId")),
                    "status": normalize_string(result.get("status")) or "queued",
                    "runId": normalize_string(result.get("runId")),
                }
            )
    output = {
        "mode": "assignment_dispatch",
        "ok": bool(payload.get("ok", True)),
        "degraded": bool(payload.get("degraded", False)),
        "runId": payload.get("runId"),
        "manifestPath": payload.get("manifestPath"),
        "selectedReferenceIds": selected_reference_ids,
        "selectedCount": len(selected_reference_ids),
        "selectionSummary": summary,
        "selectionFailures": payload.get("selectionFailures") or [],
        "warnings": payload.get("warnings") or [],
        "apply": bool(apply and not dry_run),
        "dispatches": dispatches,
        "dispatchCount": len(dispatches),
    }
    if json_output:
        print(json.dumps(output, indent=2))
        return
    print(f"references\tcurate-recent\tmode\tassignment-dispatch")
    print(f"references\tcurate-recent\trun\t{payload.get('runId', '-')}")
    print(f"references\tcurate-recent\tmanifest\t{payload.get('manifestPath', '-')}")
    print(f"references\tcurate-recent\tselected\t{len(selected_reference_ids)}")
    print(f"references\tcurate-recent\tapply\t{'yes' if output['apply'] else 'no'}")
    print(f"references\tcurate-recent\tdispatches\t{len(dispatches)}")
    for reference_id in selected_reference_ids:
        print(f"reference-curation\tselected\t{reference_id}")
    for dispatch in dispatches:
        print(
            f"reference-curation\tdispatched\t{dispatch.get('referenceId') or '-'}\t"
            f"{dispatch.get('assignmentId') or '-'}\t{dispatch.get('status') or '-'}"
        )
    for failure in output["selectionFailures"]:
        if not isinstance(failure, dict):
            continue
        print(
            f"reference-curation\tselection-failed\t{failure.get('referenceId', '-')}\t"
            f"{failure.get('failureReason', 'selection failed')}"
        )
    for warning in output["warnings"]:
        print(f"references\tcurate-recent\twarning\t{warning}")


def references_extract_text_now(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-extract-text-now")
    if not options.get("corpus-key"):
        raise ValueError("references process-extract-text-now requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, auth = create_authoring_client()
    now = _utc_now()
    actor_label = options.get("assignee-key") or options.get("assignee") or options.get("actor") or "Papyrus content CLI"
    run_id = options.get("run-id") or (
        f"reference-text-extraction-{timestamp_for_path(now)}-"
        f"{hash_short([corpus_id, options.get('stage'), options.get('configuration'), options.get('force')])}"
    )
    records = build_text_extraction_assignment_records(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        actor_label=actor_label,
        now=now,
        options=options,
        run_id=run_id,
    )
    changes = build_record_changes(client, records)
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references process-extract-text-now create {corpus_id}",
    )
    assignment_id = records[0]["expected"]["id"]
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="claim",
        assignment_id=assignment_id,
        options=options,
        actor_label=actor_label,
    )
    assignment = client.get_record("Assignment", assignment_id)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} was not found after planning.")
    execution = execute_reference_text_extraction_assignment(client, assignment, options)
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="complete",
        assignment_id=assignment_id,
        options=options,
        actor_label=actor_label,
    )
    print(f"reference-text-extraction-now\tassignment\t{assignment_id}")
    print(f"reference-text-extraction-now\trun\t{execution['runId']}")
    print(f"reference-text-extraction-now\tmanifest\t{execution['manifestPath']}")
    print(f"reference-text-extraction-now\tattachments\t{execution['importSummary'].get('importedRecords', 0)}")


def references_attach_extracted_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-attach-extracted-text")
    if not options.get("corpus-key"):
        raise ValueError("references process-attach-extracted-text requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    actor_label = options.get("actor") or "Papyrus content CLI"
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    extraction_index = build_extraction_index(corpus_config.get("path"))
    all_plans = build_extracted_text_attachment_plans(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
        extraction_index=extraction_index,
    )
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    plans = all_plans[:max_count] if max_count else all_plans
    records = [plan["record"] for plan in plans if plan.get("record")]
    changes = build_record_changes(client, records)
    print(f"references\tprocess-attach-extracted-text\tcorpus\t{corpus_id}")
    print(f"references\tprocess-attach-extracted-text\tsnapshots\t{len(extraction_index.snapshot_ids)}")
    print(f"references\tprocess-attach-extracted-text\teligible\t{len(all_plans)}")
    if max_count:
        print(f"references\tprocess-attach-extracted-text\tmax-count\t{max_count}")
    print(f"references\tprocess-attach-extracted-text\tsnapshot_attachments\t{len(plans)}")
    print(f"references\tprocess-attach-extracted-text\tplanned\t{len(records)}")
    changed = [change for change in changes if change.get("action") != "noop"]
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    print(f"references\tprocess-attach-extracted-text\tchanges\t{len(changed)}")
    for change in changed[:print_limit]:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    if len(changed) > print_limit:
        print(
            f"references\tprocess-attach-extracted-text\tomitted\t{len(changed) - print_limit}\t"
            f"pass --limit {len(changed)} to print every planned change"
        )
    apply = resolve_mutation_apply(options, "references process-attach-extracted-text")
    if not apply:
        print(
            "references\tprocess-attach-extracted-text\tapply\tskipped\tuse --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changes)
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references process-attach-extracted-text {corpus_id}",
    )
    attached = len([change for change in changes if change.get("action") == "create"])
    print(f"references\tprocess-attach-extracted-text\tattached\t{attached}")


def references_find_url_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references find-fetch-url-text")
    actor_label = options.get("actor") or "Papyrus content CLI"
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    corpus_key_by_id = {
        knowledge_corpus_id(entry): str(entry.get("key") or "")
        for entry in steering_config.get("corpora") or []
        if isinstance(entry, dict)
    }
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), False, "--force")
    apply = resolve_mutation_apply(options, "references find-fetch-url-text")
    pdf_only = parse_boolean_option(options.get("pdf-only"), False, "--pdf-only")

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    result = run_reference_source_find(
        client=client,
        references=references,
        attachments=attachments,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        apply=apply,
        bucket=normalize_string(options.get("bucket")),
        pdf_only=pdf_only,
    )

    print(f"references\tfind-fetch-url-text\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tfind-fetch-url-text\tstatus\t{curation_status}")
    print(f"references\tfind-fetch-url-text\tqueue-order\tnewest-first")
    print(f"references\tfind-fetch-url-text\tqueue-default\tmissing-only")
    print(f"references\tfind-fetch-url-text\tpdf-only\t{str(pdf_only).lower()}")
    if reference_ids:
        print(f"references\tfind-fetch-url-text\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tfind-fetch-url-text\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tfind-fetch-url-text\teligible\t{result['eligibleCount']}")
    print(f"references\tfind-fetch-url-text\tskipped-existing\t{result['skippedExistingCount']}")
    print(f"references\tfind-fetch-url-text\tskipped-missing-source\t{result.get('skippedMissingSourceCount', 0)}")
    print(f"references\tfind-fetch-url-text\tskipped-non-pdf\t{result.get('skippedNonPdfCount', 0)}")
    print(f"references\tfind-fetch-url-text\tplanned\t{result['plannedCount']}")
    print(f"references\tfind-fetch-url-text\tplanned-attachments\t{result.get('plannedAttachmentCount', 0)}")
    print(f"references\tfind-fetch-url-text\tplanned-reference-metadata\t{result.get('plannedReferenceMetadataCount', 0)}")
    print(f"references\tfind-fetch-url-text\tchanges\t{result['changeCount']}")
    print(f"references\tfind-fetch-url-text\treference-metadata-changes\t{result.get('referenceMetadataChangeCount', 0)}")
    print(f"references\tfind-fetch-url-text\tattachment-changes\t{result.get('attachmentChangeCount', 0)}")
    print(f"references\tfind-fetch-url-text\tfailures\t{len(result['failures'])}")
    print(f"references\tfind-fetch-url-text\tdoi-resolved\t{result.get('doiResolvedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-pdf-selected\t{result.get('doiPdfSelectedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-pdf-missed\t{result.get('doiPdfMissedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-search-used\t{result.get('doiSearchUsedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-search-hit\t{result.get('doiSearchHitCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-api-fallback-used\t{result.get('doiApiFallbackUsedCount', 0)}")
    print(f"references\tfind-fetch-url-text\tdoi-paywalled-or-blocked\t{result.get('doiPaywalledOrBlockedCount', 0)}")
    if max_count:
        print(f"references\tfind-fetch-url-text\tmax-count\t{max_count}")
    changed = [change for change in result["changes"] if change.get("action") != "noop"]
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for change in changed[:print_limit]:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    for failure in result["failures"][:print_limit]:
        print(
            f"reference-find\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    if not apply:
        print("references\tfind-fetch-url-text\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        result["changes"],
        actor_label=actor_label,
        reason=f"references find-fetch-url-text {corpus_id or 'all'}",
    )


def references_fetch_url_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-fetch-url-text")
    actor_label = options.get("actor") or "Papyrus content CLI"
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    corpus_key_by_id = {
        knowledge_corpus_id(entry): str(entry.get("key") or "")
        for entry in steering_config.get("corpora") or []
        if isinstance(entry, dict)
    }
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), False, "--force")
    apply = resolve_mutation_apply(options, "references process-fetch-url-text")
    bucket = normalize_string(options.get("bucket"))
    model = normalize_string(options.get("model")) or DEFAULT_REFERENCE_FILTER_MODEL
    pdf_only = parse_boolean_option(options.get("pdf-only"), False, "--pdf-only")
    grobid_url = _resolve_grobid_url(options)
    try:
        _ensure_cli_grobid_runtime(grobid_url)
    except RuntimeError as error:
        raise RuntimeError(
            "GROBID runtime preflight failed for references process-fetch-url-text. "
            f"endpoint={grobid_url} details={error}"
        ) from error

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    semantic_relations = client.list_records("SemanticRelation")
    result = run_reference_url_text_extraction(
        client=client,
        references=references,
        attachments=attachments,
        semantic_relations=semantic_relations,
        corpus_key_by_id=corpus_key_by_id,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        apply=apply,
        bucket=bucket,
        model=model,
        pdf_only=pdf_only,
        grobid_url=grobid_url,
    )
    touched_reference_ids = {
        str((item.get("reference") or {}).get("id") or "")
        for item in (result.get("items") or [])
        if isinstance(item, dict) and isinstance(item.get("reference"), dict)
    }
    touched_reference_ids.update(
        {
            str((record.get("expected") or {}).get("id") or "")
            for record in (result.get("graphRecords") or [])
            if str(record.get("modelName") or "") == "Reference" and isinstance(record.get("expected"), dict)
        }
    )
    touched_reference_ids = {reference_id for reference_id in touched_reference_ids if reference_id}
    dedupe = run_reference_identifier_dedupe(
        client=client,
        references=client.list_records("Reference"),
        attachments=attachments,
        semantic_relations=client.list_records("SemanticRelation"),
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        touched_reference_ids=touched_reference_ids or None,
        force=force,
        apply=apply,
    )

    print(f"references\tprocess-fetch-url-text\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-fetch-url-text\tstatus\t{curation_status}")
    print(f"references\tprocess-fetch-url-text\tqueue-order\tnewest-first")
    print(f"references\tprocess-fetch-url-text\tqueue-default\tprocessable-only")
    print(f"references\tprocess-fetch-url-text\tpdf-only\t{str(pdf_only).lower()}")
    print(f"references\tprocess-fetch-url-text\tgrobid-url\t{grobid_url}")
    if reference_ids:
        print(f"references\tprocess-fetch-url-text\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-fetch-url-text\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tprocess-fetch-url-text\teligible\t{result['eligibleCount']}")
    print(f"references\tprocess-fetch-url-text\tskipped-existing\t{result['skippedExistingCount']}")
    print(f"references\tprocess-fetch-url-text\tskipped-missing-source\t{result.get('skippedMissingSourceCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tskipped-needs-find\t{result.get('skippedNeedsFindCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tskipped-non-pdf\t{result.get('skippedNonPdfCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tplanned\t{result['plannedCount']}")
    print(f"references\tprocess-fetch-url-text\tplanned-attachments\t{result.get('plannedAttachmentCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tplanned-reference-metadata\t{result.get('plannedReferenceMetadataCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tauthors-parsed\t{result.get('authorsParsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tauthors-linked\t{result.get('authorsLinkedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tcitations-parsed\t{result.get('citationsParsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tcitations-upserted\t{result.get('citationsUpsertedCount', 0)}")
    print(
        f"references\tprocess-fetch-url-text\tcitations-skipped-low-confidence\t"
        f"{result.get('citationsSkippedLowConfidenceCount', 0)}"
    )
    print(
        f"references\tprocess-fetch-url-text\tcitation-relations-created\t"
        f"{result.get('citationRelationsCreatedCount', 0)}"
    )
    print(f"references\tprocess-fetch-url-text\tcitation-graph-warnings\t{len(result.get('citationGraphWarnings') or [])}")
    print(f"references\tprocess-fetch-url-text\tfiltered\t{result.get('filteredCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tfallback-raw\t{result.get('fallbackRawCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tchanges\t{result['changeCount']}")
    print(f"references\tprocess-fetch-url-text\tgraph-changes\t{result.get('graphChangeCount', 0)}")
    print(f"references\tprocess-fetch-url-text\treference-metadata-changes\t{result.get('referenceMetadataChangeCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tattachment-changes\t{result.get('attachmentChangeCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tfailures\t{len(result['failures'])}")
    print(f"references\tprocess-fetch-url-text\tfailed-grobid\t{result.get('failedGrobidCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-resolved\t{result.get('doiResolvedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-pdf-selected\t{result.get('doiPdfSelectedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-pdf-missed\t{result.get('doiPdfMissedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-search-used\t{result.get('doiSearchUsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-search-hit\t{result.get('doiSearchHitCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-api-fallback-used\t{result.get('doiApiFallbackUsedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tdoi-paywalled-or-blocked\t{result.get('doiPaywalledOrBlockedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tduplicate-groups-found\t{dedupe.get('duplicateGroupCount', 0)}")
    print(f"references\tprocess-fetch-url-text\treferences-merged\t{dedupe.get('referencesMergedCount', 0)}")
    print(f"references\tprocess-fetch-url-text\trelations-rewired\t{dedupe.get('relationsRewiredCount', 0)}")
    print(f"references\tprocess-fetch-url-text\tlosers-blocked\t{dedupe.get('losersBlockedCount', 0)}")
    if max_count:
        print(f"references\tprocess-fetch-url-text\tmax-count\t{max_count}")
    if model:
        print(f"references\tprocess-fetch-url-text\tmodel\t{model}")
    changed = [change for change in result["changes"] if change.get("action") != "noop"]
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for change in changed[:print_limit]:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    if len(changed) > print_limit:
        print(
            f"references\tprocess-fetch-url-text\tomitted\t{len(changed) - print_limit}\t"
            f"pass --limit {len(changed)} to print every planned change"
        )
    for failure in result["failures"][:print_limit]:
        print(
            f"reference-url-text\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    for fallback in (result.get("filterFallbacks") or [])[:print_limit]:
        print(
            f"reference-url-text\tfilter-fallback\t{fallback.get('referenceId') or '-'}\t"
            f"{fallback.get('sourceUri') or '-'}\t"
            f"{json.dumps(fallback.get('reason') or {}, sort_keys=True)}"
        )
    needs_find_rows = [
        item for item in (result.get("items") or [])
        if str(item.get("status") or "") == "needs_find"
    ]
    for row in needs_find_rows[:print_limit]:
        reference = row.get("reference") if isinstance(row.get("reference"), dict) else {}
        reason = row.get("error") if isinstance(row.get("error"), dict) else {"code": "needs_find", "message": "requires find"}
        print(
            f"reference-url-text\tneeds-find\t{reference.get('id') or '-'}\t"
            f"{reference.get('sourceUri') or '-'}\t{json.dumps(reason, sort_keys=True)}"
        )
    if len(result["failures"]) > print_limit:
        print(
            f"references\tprocess-fetch-url-text\tomitted-failures\t{len(result['failures']) - print_limit}\t"
            f"pass --limit {len(result['failures'])} to print every failure"
        )
    if not apply:
        print("references\tprocess-fetch-url-text\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        result["changes"],
        actor_label=actor_label,
        reason=f"references process-fetch-url-text {corpus_id or 'all'}",
    )
    created = len([change for change in result["changes"] if change.get("action") == "create"])
    print(f"references\tprocess-fetch-url-text\tattached\t{created}")


def references_fetch_pdf_url_text_queue(flags: list[str]) -> None:
    options = parse_options(flags)
    if options.get("pdf-only") is None:
        flags = [*flags, "--pdf-only", "true"]
    references_fetch_url_text(flags)


def references_find_pdf_url_text_queue(flags: list[str]) -> None:
    options = parse_options(flags)
    if options.get("pdf-only") is None:
        flags = [*flags, "--pdf-only", "true"]
    references_find_url_text(flags)


def references_recount_citation_counts(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-recount-citation-counts")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    apply = resolve_mutation_apply(options, "references process-recount-citation-counts")
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    semantic_relations = client.list_records("SemanticRelation")
    recount = build_reference_citation_count_records(
        references=references,
        semantic_relations=semantic_relations,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
    )
    changes = build_record_changes_targeted_by_id(client, recount["records"])
    changed = [change for change in changes if change.get("action") != "noop"]

    print(f"references\tprocess-recount-citation-counts\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-recount-citation-counts\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-recount-citation-counts\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-recount-citation-counts\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tprocess-recount-citation-counts\treferences\t{recount['referenceCount']}")
    print(f"references\tprocess-recount-citation-counts\tchanges\t{len(changed)}")
    for item in recount["items"][:print_limit]:
        reference = item["reference"]
        print(
            "\t".join(
                [
                    "reference-citation-count",
                    reference.get("id") or "-",
                    reference.get("externalItemId") or "-",
                    str(item.get("inboundCitationCount") or 0),
                    str(item.get("outboundCitationCount") or 0),
                ]
            )
        )
    if len(recount["items"]) > print_limit:
        print(
            f"references\tprocess-recount-citation-counts\tomitted\t{len(recount['items']) - print_limit}\t"
            f"pass --limit {len(recount['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tprocess-recount-citation-counts\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changed)


def references_process_dedupe_identifiers(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-dedupe-identifiers")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    force = parse_boolean_option(options.get("force"), False, "--force")
    apply = resolve_mutation_apply(options, "references process-dedupe-identifiers")
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    semantic_relations = client.list_records("SemanticRelation")
    dedupe = run_reference_identifier_dedupe(
        client=client,
        references=references,
        attachments=attachments,
        semantic_relations=semantic_relations,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        touched_reference_ids=None,
        force=force,
        apply=apply,
    )

    print(f"references\tprocess-dedupe-identifiers\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-dedupe-identifiers\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-dedupe-identifiers\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-dedupe-identifiers\texternal-item-filter\t{len(external_item_ids)}")
    print(f"references\tprocess-dedupe-identifiers\tduplicate-groups-found\t{dedupe.get('duplicateGroupCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\treferences-merged\t{dedupe.get('referencesMergedCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\trelations-rewired\t{dedupe.get('relationsRewiredCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\tlosers-blocked\t{dedupe.get('losersBlockedCount', 0)}")
    print(f"references\tprocess-dedupe-identifiers\tchanges\t{dedupe.get('changeCount', 0)}")
    for item in (dedupe.get("items") or [])[:print_limit]:
        print(
            "\t".join(
                [
                    "reference-dedupe",
                    str(item.get("loserId") or "-"),
                    str(item.get("loserLineageId") or "-"),
                    str(item.get("winnerId") or "-"),
                    str(item.get("winnerLineageId") or "-"),
                ]
            )
        )
    if len(dedupe.get("items") or []) > print_limit:
        print(
            f"references\tprocess-dedupe-identifiers\tomitted\t{len(dedupe['items']) - print_limit}\t"
            f"pass --limit {len(dedupe['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tprocess-dedupe-identifiers\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )


def references_process_resolve_citation_stubs(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references find-resolve-citation-stubs")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), False, "--force")
    promote_external_id = parse_boolean_option(options.get("promote-external-id"), False, "--promote-external-id")
    apply = resolve_mutation_apply(options, "references find-resolve-citation-stubs")
    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    resolved = build_reference_citation_resolution_records(
        references=references,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        promote_external_id=promote_external_id,
    )
    changes = build_record_changes_targeted_by_id(client, resolved["records"])
    changed = [change for change in changes if change.get("action") != "noop"]

    print(f"references\tfind-resolve-citation-stubs\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tfind-resolve-citation-stubs\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tfind-resolve-citation-stubs\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tfind-resolve-citation-stubs\texternal-item-filter\t{len(external_item_ids)}")
    if max_count:
        print(f"references\tfind-resolve-citation-stubs\tmax-count\t{max_count}")
    print(f"references\tfind-resolve-citation-stubs\tattempted\t{resolved['attemptedCount']}")
    print(f"references\tfind-resolve-citation-stubs\tresolved\t{resolved['resolvedCount']}")
    print(f"references\tfind-resolve-citation-stubs\tskipped-existing\t{resolved['skippedExistingCount']}")
    print(f"references\tfind-resolve-citation-stubs\tskipped-non-citation\t{resolved['skippedNonCitationCount']}")
    print(f"references\tfind-resolve-citation-stubs\tfailures\t{resolved['failureCount']}")
    print(f"references\tfind-resolve-citation-stubs\tchanges\t{len(changed)}")

    for item in resolved["items"][:print_limit]:
        best = item.get("bestCandidate") if isinstance(item.get("bestCandidate"), dict) else {}
        print(
            "\t".join(
                [
                    "reference-citation-resolve",
                    str(item.get("status") or ""),
                    str(item.get("referenceId") or "-"),
                    str(item.get("externalItemId") or "-"),
                    str(best.get("doi") or best.get("arxiv_id") or best.get("isbn") or "-"),
                    str(best.get("source_uri") or "-"),
                    str(best.get("score") or "-"),
                ]
            )
        )
    if len(resolved["items"]) > print_limit:
        print(
            f"references\tfind-resolve-citation-stubs\tomitted\t{len(resolved['items']) - print_limit}\t"
            f"pass --limit {len(resolved['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tfind-resolve-citation-stubs\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changed)


def references_filter_extracted_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-filter-text")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    force = parse_boolean_option(options.get("force"), True, "--force")
    apply = resolve_mutation_apply(options, "references process-filter-text")
    bucket = normalize_string(options.get("bucket"))
    model = normalize_string(options.get("model")) or DEFAULT_REFERENCE_FILTER_MODEL
    metadata_from_text = parse_boolean_option(options.get("metadata-from-text"), True, "--metadata-from-text")
    metadata_model = normalize_string(options.get("metadata-model")) or DEFAULT_REFERENCE_SUMMARY_MODEL

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    result = run_reference_extracted_text_filtering(
        client=client,
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        force=force,
        model=model,
        apply=apply,
        bucket=bucket,
    )

    print(f"references\tprocess-filter-text\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-filter-text\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-filter-text\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-filter-text\texternal-item-filter\t{len(external_item_ids)}")
    if max_count:
        print(f"references\tprocess-filter-text\tmax-count\t{max_count}")
    print(f"references\tprocess-filter-text\tmodel\t{model}")
    print(f"references\tprocess-filter-text\tattempted\t{result['attemptedCount']}")
    print(f"references\tprocess-filter-text\tplanned\t{result['plannedCount']}")
    print(f"references\tprocess-filter-text\tplanned-attachments\t{result['plannedAttachmentCount']}")
    print(f"references\tprocess-filter-text\tfiltered\t{result['filteredCount']}")
    print(f"references\tprocess-filter-text\tfallback-raw\t{result['fallbackRawCount']}")
    print(f"references\tprocess-filter-text\tskipped-missing-source\t{result['skippedMissingSourceCount']}")
    print(f"references\tprocess-filter-text\tchanges\t{result['changeCount']}")
    print(f"references\tprocess-filter-text\tfailures\t{len(result['failures'])}")

    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for item in (result.get("items") or [])[:print_limit]:
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
        error = item.get("error") or {}
        if not isinstance(error, dict):
            error = {"message": str(error)}
        print(
            "\t".join(
                [
                    "reference-filter-text",
                    str(item.get("status") or ""),
                    str(reference.get("id") or "-"),
                    str(reference.get("externalItemId") or "-"),
                    json.dumps(error, sort_keys=True) if error else "",
                ]
            )
        )
    if len(result.get("items") or []) > print_limit:
        print(
            f"references\tprocess-filter-text\tomitted\t{len(result['items']) - print_limit}\t"
            f"pass --limit {len(result['items'])} to print every row"
        )
    for failure in result["failures"][:print_limit]:
        print(
            f"reference-filter-text\tfailed\t{failure.get('referenceId') or '-'}\t"
            f"{failure.get('sourceUri') or '-'}\t{failure.get('error') or 'unknown error'}"
        )
    for fallback in (result.get("filterFallbacks") or [])[:print_limit]:
        print(
            f"reference-filter-text\tfallback-raw\t{fallback.get('referenceId') or '-'}\t"
            f"{fallback.get('sourceUri') or '-'}\t{json.dumps(fallback.get('reason') or {}, sort_keys=True)}"
        )
    if len(result["failures"]) > print_limit:
        print(
            f"references\tprocess-filter-text\tomitted-failures\t{len(result['failures']) - print_limit}\t"
            f"pass --limit {len(result['failures'])} to print every failure"
        )
    if not apply:
        print("references\tprocess-filter-text\tapply\tskipped\tuse --dry-run to preview without writes")
        return

    actor_label = options.get("actor") or "Papyrus content CLI"
    update_newsroom_summary_after_extracted_text_attachments(
        client,
        result["changes"],
        actor_label=actor_label,
        reason=f"references process-filter-text {corpus_id or 'all'}",
    )

    if not metadata_from_text:
        print("references\tprocess-generate-metadata\tdisabled")
        return

    processed_reference_ids = set(result.get("processedReferenceIds") or [])
    if not processed_reference_ids:
        print("references\tprocess-generate-metadata\tskipped\tno references processed by filter step")
        return
    refreshed_attachments = client.list_records("ReferenceAttachment")
    generation = run_reference_metadata_generation_from_extracted_text(
        references=references,
        attachments=refreshed_attachments,
        corpus_id=corpus_id,
        reference_ids=processed_reference_ids,
        curation_status="all",
        model=metadata_model,
        apply=True,
        bucket=bucket,
    )
    print(f"references\tprocess-generate-metadata\tmodel\t{metadata_model}")
    print(f"references\tprocess-generate-metadata\tattempted\t{generation['attemptedCount']}")
    print(f"references\tprocess-generate-metadata\tgenerated\t{generation['generatedCount']}")
    print(f"references\tprocess-generate-metadata\tskipped-missing-text\t{generation['skippedMissingTextCount']}")
    print(f"references\tprocess-generate-metadata\tgeneration-failures\t{generation['generationFailureCount']}")


def references_generate_metadata_from_text(flags: list[str]) -> None:
    options = parse_options(flags)
    _require_reference_process_runtime("references process-generate-metadata")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_key = normalize_string(options.get("corpus-key"))
    corpus_config = require_corpus_config(steering_config, corpus_key, "--corpus-key") if corpus_key else None
    corpus_id = knowledge_corpus_id(corpus_config) if corpus_config else None
    reference_ids = set(parse_repeated_option(flags, "reference"))
    if options.get("reference"):
        reference_ids.add(str(options["reference"]))
    external_item_ids = set(parse_repeated_option(flags, "external-item-id"))
    if options.get("external-item-id"):
        external_item_ids.add(str(options["external-item-id"]))
    curation_status = _normalize_reference_status_filter(options.get("status"))
    max_count = normalize_positive_integer(options.get("max-count"), "--max-count")
    apply = resolve_mutation_apply(options, "references process-generate-metadata")
    model = normalize_string(options.get("model")) or DEFAULT_REFERENCE_SUMMARY_MODEL
    bucket = normalize_string(options.get("bucket"))

    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    result = run_reference_metadata_generation_from_extracted_text(
        references=references,
        attachments=attachments,
        corpus_id=corpus_id,
        reference_ids=reference_ids or None,
        external_item_ids=external_item_ids or None,
        curation_status=curation_status,
        max_count=max_count,
        model=model,
        apply=apply,
        bucket=bucket,
    )

    print(f"references\tprocess-generate-metadata\tcorpus\t{corpus_id or 'all'}")
    print(f"references\tprocess-generate-metadata\tstatus\t{curation_status}")
    if reference_ids:
        print(f"references\tprocess-generate-metadata\treference-filter\t{len(reference_ids)}")
    if external_item_ids:
        print(f"references\tprocess-generate-metadata\texternal-item-filter\t{len(external_item_ids)}")
    if max_count:
        print(f"references\tprocess-generate-metadata\tmax-count\t{max_count}")
    print(f"references\tprocess-generate-metadata\tattempted\t{result['attemptedCount']}")
    print(f"references\tprocess-generate-metadata\tgenerated\t{result['generatedCount']}")
    print(f"references\tprocess-generate-metadata\tskipped-missing-text\t{result['skippedMissingTextCount']}")
    print(f"references\tprocess-generate-metadata\tgeneration-failures\t{result['generationFailureCount']}")

    print_limit = 25 if options.get("limit") is None else normalize_non_negative_integer(options.get("limit"), "--limit")
    print_limit = print_limit if print_limit is not None else 25
    for item in result["items"][:print_limit]:
        reference = item.get("reference") if isinstance(item.get("reference"), dict) else {}
        print(
            "\t".join(
                [
                    "reference-metadata",
                    str(item.get("status") or ""),
                    str(reference.get("id") or "-"),
                    str(reference.get("externalItemId") or "-"),
                    str(item.get("error") or ""),
                ]
            )
        )
    if len(result["items"]) > print_limit:
        print(
            f"references\tprocess-generate-metadata\tomitted\t{len(result['items']) - print_limit}\t"
            f"pass --limit {len(result['items'])} to print every row"
        )
    if not apply:
        print(
            "references\tprocess-generate-metadata\tapply\tskipped\t"
            "use --dry-run to preview without writes"
        )


def references_create_identifier_backfill_assignment(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("corpus-key"):
        raise ValueError("references create-identifier-backfill-assignment requires --corpus-key <key>.")
    actor_label = options.get("actor") or "papyrus-cli"
    now = _utc_now()
    types = normalize_identifier_types(options.get("types"))
    run_id = options.get("run-id") or (
        f"reference-identifier-backfill-{timestamp_for_path(now)}-{hash_short([options['corpus-key'], ','.join(types)])}"
    )
    client, _ = create_authoring_client()
    assignment_plan = build_reference_identifier_backfill_assignment_plan(
        options=options,
        actor_label=actor_label,
        now=now,
        run_id=run_id,
        types=types,
    )
    changes = build_record_changes_targeted_by_id(client, assignment_plan["records"])
    print(f"references\tcreate-identifier-backfill-assignment\tassignment\t{assignment_plan['assignment']['id']}")
    print(f"references\tcreate-identifier-backfill-assignment\tcorpus\t{assignment_plan['corpusId']}")
    print(f"references\tcreate-identifier-backfill-assignment\ttypes\t{','.join(types)}")
    print(f"references\tcreate-identifier-backfill-assignment\trun\t{run_id}")
    for change in changes:
        print(f"{change['action']}\t{change['modelName']}\t{change['expected']['id']}")
    apply = resolve_mutation_apply(options, "references create-identifier-backfill-assignment")
    if not apply:
        print(
            "references\tcreate-identifier-backfill-assignment\tapply\tskipped\tuse --dry-run to preview without writes"
        )
        return
    apply_record_changes(client, changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        changes,
        actor_label=actor_label,
        reason=f"references create-identifier-backfill-assignment {assignment_plan['assignment']['id']}",
    )


def references_identifier_backfill_now(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("corpus-key"):
        raise ValueError("references identifier-backfill-now requires --corpus-key <key>.")
    now = _utc_now()
    types = normalize_identifier_types(options.get("types"))
    run_now_options = {
        **options,
        "apply": True,
        "run-id": options.get("run-id") or f"reference-identifier-backfill-now-{timestamp_for_path(now)}",
        "types": ",".join(types),
    }
    actor_label = (
        run_now_options.get("assignee-key")
        or run_now_options.get("assignee")
        or run_now_options.get("actor")
        or "papyrus-cli"
    )
    client, auth = create_authoring_client()
    assignment_plan = build_reference_identifier_backfill_assignment_plan(
        options=run_now_options,
        actor_label=actor_label,
        now=now,
        run_id=run_now_options["run-id"],
        types=types,
    )
    run_now_options["__assignmentMetadata"] = assignment_plan["metadata"]
    assignment_changes = build_record_changes_targeted_by_id(client, assignment_plan["records"])
    apply_record_changes(client, assignment_changes)
    update_newsroom_summary_after_assignment_creates(
        client,
        assignment_changes,
        actor_label=actor_label,
        reason=f"references identifier-backfill-now create {assignment_plan['assignment']['id']}",
    )
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="claim",
        assignment_id=assignment_plan["assignment"]["id"],
        options=run_now_options,
        actor_label=actor_label,
    )
    execution_result = execute_assignment_by_type(
        client,
        assignment_plan["assignment"]["id"],
        run_now_options,
    )
    apply_assignment_action(
        client,
        auth_claims=auth,
        action="complete",
        assignment_id=assignment_plan["assignment"]["id"],
        options=run_now_options,
        actor_label=actor_label,
    )
    summary = execution_result.get("summary") or {}
    print(f"references-identifier-backfill-now\tassignment\t{assignment_plan['assignment']['id']}")
    print(f"references-identifier-backfill-now\trun\t{execution_result.get('runId')}")
    print(f"references-identifier-backfill-now\tmanifest\t{execution_result.get('manifestPath')}")
    print(f"references-identifier-backfill-now\tresolved\t{summary.get('resolved', 0)}")
    print(f"references-identifier-backfill-now\tunresolved\t{summary.get('unresolved', 0)}")


def references_execute_identifier_backfill(flags: list[str]) -> None:
    options = parse_options(flags)
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("references execute-identifier-backfill requires --assignment <id>.")
    client, _ = create_authoring_client()
    execute_assignment_by_type(client, assignment_id, options)


def references_create_doi_backfill_assignment(flags: list[str]) -> None:
    references_create_identifier_backfill_assignment(doi_backfill_compatibility_flags(flags))


def references_doi_backfill_now(flags: list[str]) -> None:
    references_identifier_backfill_now(doi_backfill_compatibility_flags(flags))


def references_execute_doi_backfill(flags: list[str]) -> None:
    options = parse_options(doi_backfill_compatibility_flags(flags))
    assignment_id = options.get("assignment")
    if not assignment_id:
        raise ValueError("references execute-doi-backfill requires --assignment <id>.")
    client, _ = create_authoring_client()
    execute_assignment_by_type(client, assignment_id, options)


def references_export_analysis_manifest(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("references export-analysis-manifest requires --output <accepted-manifest.json>.")
    if not options.get("corpus-key"):
        raise ValueError("references export-analysis-manifest requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    payload = build_reference_analysis_manifest(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
    )
    _write_json_file(options["output"], payload)
    print(
        f"references\texport-analysis-manifest\t{corpus_id}\t{options['output']}\t{len(payload['items'])} accepted"
    )


def references_export_scope_training(flags: list[str]) -> None:
    options = parse_options(flags)
    if not options.get("output"):
        raise ValueError("references export-scope-training requires --output <scope-training.json>.")
    if not options.get("corpus-key"):
        raise ValueError("references export-scope-training requires --corpus-key <key>.")
    steering_config = load_steering_config(options.get("config")) or require_steering_config()
    corpus_config = require_corpus_config(steering_config, options["corpus-key"], "--corpus-key")
    corpus_id = knowledge_corpus_id(corpus_config)
    client, _ = create_authoring_client()
    references = client.list_records("Reference")
    attachments = client.list_records("ReferenceAttachment")
    messages = client.list_records("Message")
    relations = client.list_records("SemanticRelation")
    payload = build_reference_scope_training_export(
        corpus_config=corpus_config,
        corpus_id=corpus_id,
        references=references,
        attachments=attachments,
        messages=messages,
        relations=relations,
    )
    _write_json_file(options["output"], payload)
    print(
        f"references\texport-scope-training\t{corpus_id}\t{options['output']}\t"
        f"{payload['counts']['positive']} positive\t{payload['counts']['negative']} negative"
    )


def _resolve_grobid_url(options: dict[str, Any]) -> str:
    return (
        normalize_string(options.get("grobid-url"))
        or str(os.environ.get("BIBLICUS_GROBID_URL") or "").strip()
        or DEFAULT_GROBID_URL
    )


def _require_reference_process_runtime(command_name: str) -> None:
    runtime_role = str(os.environ.get("PAPYRUS_RUNTIME_ROLE") or "").strip().lower()
    if runtime_role and runtime_role not in {"cli", "worker"}:
        raise RuntimeError(
            f"{command_name} requires utility worker runtime with reachable GROBID service/container. "
            f"Current PAPYRUS_RUNTIME_ROLE={runtime_role!r} is not supported."
        )
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        raise RuntimeError(
            f"{command_name} requires utility worker runtime with reachable GROBID service/container. "
            "API/Lambda runtime is not supported for process commands."
        )


def _ensure_cli_grobid_runtime(grobid_url: str) -> None:
    parsed = urlparse(grobid_url)
    host = (parsed.hostname or "").strip().lower()
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    if _grobid_is_alive(grobid_url):
        return
    if host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError(
            f"GROBID is not reachable at {grobid_url}. Auto-start is only supported for localhost endpoints. "
            "For remote endpoints, start the service and retry."
        )
    _start_or_reuse_local_grobid_container(port=port)
    _await_grobid_ready(grobid_url)


def _grobid_is_alive(grobid_url: str) -> bool:
    probe_url = f"{grobid_url.rstrip('/')}/api/isalive"
    request = Request(probe_url, method="GET")
    try:
        with urlopen(request, timeout=2.0) as response:
            status = int(getattr(response, "status", response.getcode()))
            if status < 200 or status >= 300:
                return False
            payload = response.read().decode("utf-8", errors="replace").strip().lower()
            return "true" in payload or payload == ""
    except Exception:
        return False


def _port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def _start_or_reuse_local_grobid_container(*, port: int) -> None:
    docker_command = _resolve_docker_command()
    if not docker_command:
        raise RuntimeError(
            "Docker binary was not found. Cannot auto-start local GROBID container. "
            "Install Docker Desktop/CLI or set BIBLICUS_GROBID_URL to a reachable service."
        )
    _ensure_docker_daemon_ready(docker_command)

    container_name = str(os.environ.get(GROBID_CONTAINER_NAME_ENV) or DEFAULT_GROBID_CONTAINER_NAME).strip()
    image = str(os.environ.get(GROBID_DOCKER_IMAGE_ENV) or DEFAULT_GROBID_DOCKER_IMAGE).strip()
    running = _docker_lines(
        docker_command,
        [
            "ps",
            "--filter",
            f"name=^/{container_name}$",
            "--filter",
            "status=running",
            "--format",
            "{{.ID}}",
        ]
    )
    if running:
        return

    existing = _docker_lines(
        docker_command,
        [
            "ps",
            "-a",
            "--filter",
            f"name=^/{container_name}$",
            "--format",
            "{{.ID}}",
        ]
    )
    if existing:
        completed = subprocess.run(
            [docker_command, "start", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"Failed to start existing GROBID container {container_name}: {stderr}")
        return

    completed = subprocess.run(
        [
            docker_command,
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{port}:8070",
            image,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"Failed to launch GROBID container {container_name} using {image}: {stderr}"
        )


def _await_grobid_ready(grobid_url: str) -> None:
    deadline = time.time() + 120.0
    parsed = urlparse(grobid_url)
    host = (parsed.hostname or "127.0.0.1").strip()
    port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
    while time.time() < deadline:
        if _port_is_open(host, port) and _grobid_is_alive(grobid_url):
            return
        time.sleep(1.5)
    raise RuntimeError(
        f"GROBID did not become ready at {grobid_url} after container start. "
        "Check Docker container logs and retry."
    )


def _resolve_docker_command() -> str | None:
    command = shutil.which("docker")
    if command:
        return command
    for candidate in DOCKER_CANDIDATE_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def _docker_daemon_ready(docker_command: str) -> bool:
    completed = subprocess.run(
        [docker_command, "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _ensure_docker_daemon_ready(docker_command: str) -> None:
    if _docker_daemon_ready(docker_command):
        return
    if sys.platform == "darwin" and Path("/Applications/Docker.app").exists():
        subprocess.run(
            ["open", "-a", "Docker"],
            capture_output=True,
            text=True,
            check=False,
        )
        deadline = time.time() + 90.0
        while time.time() < deadline:
            if _docker_daemon_ready(docker_command):
                return
            time.sleep(1.5)
    raise RuntimeError(
        "Docker daemon is not ready for GROBID auto-start (attempted local startup). "
        "Start Docker Desktop and retry, or set BIBLICUS_GROBID_URL to a reachable service."
    )


def _docker_lines(docker_command: str, command: list[str]) -> list[str]:
    completed = subprocess.run(
        [docker_command, *command],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]


def extract_last_json_object(text: str) -> dict[str, Any] | None:
    for line in reversed(text.strip().splitlines()):
        value = line.strip()
        if not value.startswith("{") or not value.endswith("}"):
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _write_json_file(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_reference_status_filter(value: Any) -> str:
    status = str(value or "all").strip().lower()
    allowed = {"all", "pending", "accepted", "rejected", "archived"}
    if status not in allowed:
        raise ValueError(f"--status must be one of {', '.join(sorted(allowed))}.")
    return status
