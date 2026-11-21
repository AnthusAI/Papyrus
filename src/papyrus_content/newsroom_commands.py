from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .tenant_knowledge_keys import REFERENCE_FEED_KEY, REFERENCE_REVIEWED_FEED_KEY, SEMANTIC_NODE_FEED_KEY, SEMANTIC_RELATION_FEED_KEY, global_key
from .graphql_authoring import create_authoring_client
from .tenancy import tenant_id_from_options
from .procedure_deploy import SITE_REGISTRY_FILE, apply_deploy, check_drift, plan_deploy, plan_statuses
from .model_attachments import (
    MODEL_ATTACHMENT_OWNER_MODELS,
    build_json_model_payload_attachment,
    delete_attachment_storage_paths,
    list_attachment_storage_paths,
    model_attachment_id,
    upload_attachment_body,
)
from .newsroom_sections import DEFAULT_NEWSROOM_SECTIONS_PATH, build_newsroom_section_records, load_newsroom_section_seeds
from .newsroom_doctrine import (
    require_explicit_doctrine,
    build_publication_doctrine_records,
    load_publication_doctrine_seed,
)
from .newsroom_summary import (
    NEWSROOM_SUMMARY_PAYLOAD_ID,
    build_newsroom_summary_payload,
    build_newsroom_summary_payload_record,
    newsroom_summary_diff,
    print_newsroom_summary_recount,
    read_json_model_payload,
)
from .options import normalize_non_negative_integer, normalize_string, parse_options, resolve_mutation_apply
from .records import build_record_change_from_current
from .relations_commands import print_category_import_summary

def newsroom_recount_summary(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "sections recount-summary")
    client, _ = create_authoring_client()
    now = _utc_now()
    corpora = client.list_records("KnowledgeCorpus")
    import_runs = client.list_records("KnowledgeImportRun")
    category_sets = client.list_records("CategorySet")
    categories = client.list_records("Category")
    proposals = client.list_records("SteeringProposal")
    artifacts = client.list_records("KnowledgeArtifact")
    references = client.list_records("Reference")
    reference_attachments = client.list_records("ReferenceAttachment")
    semantic_nodes = client.list_records("SemanticNode")
    try:
        messages = client.list_records("Message")
    except RuntimeError as error:
        if _is_message_status_null_error(error):
            raise ValueError(
                "newsroom recount-summary failed because at least one Message has null status. "
                "Run `poetry run papyrus sections repair-message-status` (dry-run) and then "
                "`poetry run papyrus sections repair-message-status`."
            ) from error
        raise
    model_attachments = client.safe_list_records("ModelAttachment")
    semantic_relations = client.list_records("SemanticRelation")
    assignments = client.list_records("Assignment")
    assignment_events = client.list_records("AssignmentEvent")
    summary_attachment_id = model_attachment_id(
        "knowledgeRawPayload",
        NEWSROOM_SUMMARY_PAYLOAD_ID,
        "raw_payload",
        "summary-snapshot",
    )
    model_attachments_for_recount = (
        model_attachments
        if any(attachment.get("id") == summary_attachment_id for attachment in model_attachments)
        else [
            *model_attachments,
            {
                "id": summary_attachment_id,
                "ownerKind": "knowledgeRawPayload",
                "ownerId": NEWSROOM_SUMMARY_PAYLOAD_ID,
                "role": "raw_payload",
                "sortKey": "summary-snapshot",
                "mediaType": "application/json",
                "status": "active",
            },
        ]
    )
    payload = build_newsroom_summary_payload(
        corpora=corpora,
        import_runs=import_runs,
        category_sets=category_sets,
        categories=categories,
        proposals=proposals,
        artifacts=artifacts,
        references=references,
        reference_attachments=reference_attachments,
        semantic_nodes=semantic_nodes,
        messages=messages,
        model_attachments=model_attachments_for_recount,
        semantic_relations=semantic_relations,
        assignments=assignments,
        assignment_events=assignment_events,
        now=now,
        source="recount",
    )
    expected = build_newsroom_summary_payload_record(payload, now)
    summary_attachment = build_json_model_payload_attachment(
        {
            "ownerKind": "knowledgeRawPayload",
            "ownerId": expected["id"],
            "role": "raw_payload",
            "sortKey": "summary-snapshot",
            "filename": "summary-snapshot.json",
            "content": payload,
            "importRunId": expected.get("importRunId"),
            "now": now,
        }
    )
    current = client.get_record("KnowledgeRawPayload", NEWSROOM_SUMMARY_PAYLOAD_ID)
    current_payload = read_json_model_payload(
        client,
        "knowledgeRawPayload",
        NEWSROOM_SUMMARY_PAYLOAD_ID,
        "raw_payload",
        "summary-snapshot",
    )
    if current and current.get("createdAt"):
        expected["createdAt"] = current["createdAt"]
    change = build_record_change_from_current("KnowledgeRawPayload", expected, current)
    summary_diff = newsroom_summary_diff(current_payload, payload)
    if not options.get("json"):
        print_newsroom_summary_recount(current_payload, payload, change)
    if options.get("output"):
        _write_json_file(
            options["output"],
            {
                "current": current,
                "currentPayload": current_payload,
                "expected": expected,
                "attachment": summary_attachment["attachment"],
                "action": change["action"],
                "payload": payload,
            },
        )
    if not apply:
        if options.get("json"):
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "newsroom recount-summary",
                        "action": "dry-run",
                        "countsChanged": summary_diff["countsChanged"],
                        "facetSectionsChanged": summary_diff["facetSectionsChanged"],
                        "attachmentUpdated": False,
                    },
                    indent=2,
                )
            )
        else:
            print("newsroom\trecount-summary\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    client.upsert("KnowledgeRawPayload", expected)
    upload_attachment_body(client, summary_attachment["attachment"], summary_attachment["body"])
    client.upsert("ModelAttachment", summary_attachment["attachment"])
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "newsroom recount-summary",
                    "action": change["action"],
                    "countsChanged": summary_diff["countsChanged"],
                    "facetSectionsChanged": summary_diff["facetSectionsChanged"],
                    "attachmentUpdated": True,
                },
                indent=2,
            )
        )
    else:
        print(f"newsroom\trecount-summary\t{change['action']}\t{expected['id']}")


def newsroom_repair_message_status(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "sections repair-message-status")
    status_value = normalize_string(options.get("status")) or "active"
    max_scan_option = normalize_non_negative_integer(options.get("max-scan"), "--max-scan")
    max_scan = max_scan_option if max_scan_option is not None else (None if apply else 2000)
    client, _ = create_authoring_client()
    scanned = 0
    truncated = False
    candidates: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    next_token: str | None = None
    while True:
        page_token = next_token
        rows, next_token = client.list_messages_safe(limit=100, next_token=page_token)
        if max_scan is not None and scanned + len(rows) > max_scan:
            rows = rows[: max_scan - scanned]
            truncated = True
        if not rows:
            break
        scanned += len(rows)
        page_had_status_error = False
        while True:
            try:
                status_rows, _ = client.list_messages_status_page(limit=len(rows), next_token=page_token)
            except RuntimeError as error:
                status_error_index = _message_status_error_index(error) if _is_message_status_null_error(error) else None
                if status_error_index is None:
                    raise
                page_had_status_error = True
                if status_error_index >= len(rows):
                    raise ValueError(
                        f"Could not resolve Message status failure index {status_error_index}; safe page returned {len(rows)} rows."
                    ) from error
                row = rows[status_error_index]
                message_id = normalize_string(row.get("id"))
                if not message_id or message_id in candidate_ids:
                    break
                candidate_ids.add(message_id)
                candidates.append(
                    {
                        "id": message_id,
                        "messageKind": row.get("messageKind"),
                        "messageDomain": row.get("messageDomain"),
                        "createdAt": row.get("createdAt"),
                        "updatedAt": row.get("updatedAt"),
                    }
                )
                if apply:
                    now = _utc_now()
                    client.update_record(
                        "Message",
                        {
                            "id": message_id,
                            "status": status_value,
                            "updatedAt": row.get("updatedAt") or now,
                        },
                    )
                    continue
                break
            status_by_id = {entry.get("id"): normalize_string(entry.get("status")) for entry in status_rows}
            for row in rows:
                message_id = normalize_string(row.get("id"))
                if not message_id or message_id in candidate_ids:
                    continue
                if status_by_id.get(message_id):
                    continue
                candidate_ids.add(message_id)
                candidates.append(
                    {
                        "id": message_id,
                        "messageKind": row.get("messageKind"),
                        "messageDomain": row.get("messageDomain"),
                        "createdAt": row.get("createdAt"),
                        "updatedAt": row.get("updatedAt"),
                    }
                )
            break
        if not apply and page_had_status_error:
            # In dry-run, a failing status page can hide additional broken records on the same page.
            # Fall back to targeted per-record checks only for pages that already surfaced one failure.
            for row in rows:
                message_id = normalize_string(row.get("id"))
                if not message_id or message_id in candidate_ids:
                    continue
                try:
                    status_row = client.get_message_status(message_id)
                    if normalize_string((status_row or {}).get("status")):
                        continue
                except RuntimeError as error:
                    if not _is_message_status_null_error(error):
                        raise
                candidate_ids.add(message_id)
                candidates.append(
                    {
                        "id": message_id,
                        "messageKind": row.get("messageKind"),
                        "messageDomain": row.get("messageDomain"),
                        "createdAt": row.get("createdAt"),
                        "updatedAt": row.get("updatedAt"),
                    }
                )
        if apply and candidates and len(candidates) % 100 == 0:
            print(f"newsroom\trepair-message-status\tupdated\t{len(candidates)}", flush=True)
        if not options.get("json") and (scanned == len(rows) or scanned % 500 == 0):
            print(f"newsroom\trepair-message-status\tscan-progress\t{scanned}", flush=True)
        if max_scan is not None and scanned >= max_scan:
            break
        if not next_token:
            break
    candidates.sort(key=lambda entry: (str(entry.get("createdAt") or ""), str(entry["id"])))
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "newsroom repair-message-status",
                    "mode": "apply" if apply else "dry-run",
                    "status": status_value,
                    "scanned": scanned,
                    "plannedUpdates": len(candidates),
                    "updated": len(candidates) if apply else 0,
                    "truncated": truncated,
                    "maxScan": max_scan,
                    "sample": candidates[:20],
                    "next": None if apply else f"poetry run papyrus sections repair-message-status --status {status_value}",
                },
                indent=2,
            )
        )
        return
    print(f"newsroom\trepair-message-status\tmode\t{'apply' if apply else 'dry-run'}")
    print(f"newsroom\trepair-message-status\tstatus\t{status_value}")
    print(f"newsroom\trepair-message-status\tscanned\t{scanned}")
    print(f"newsroom\trepair-message-status\tmax-scan\t{max_scan if max_scan is not None else 'none'}")
    if truncated:
        print("newsroom\trepair-message-status\ttruncated\ttrue")
    print(f"newsroom\trepair-message-status\tplanned-updates\t{len(candidates)}")
    for entry in candidates[:20]:
        print(
            "newsroom\trepair-message-status\tcandidate\t"
            f"{entry['id']}\t{entry.get('messageKind') or '-'}\t{entry.get('messageDomain') or '-'}"
        )
    if len(candidates) > 20:
        print(f"newsroom\trepair-message-status\tpreview-truncated\t{len(candidates) - 20}")
    if not apply:
        print(
            "newsroom\trepair-message-status\tnext\t"
            f"poetry run papyrus sections repair-message-status --status {status_value}"
        )


def newsroom_backfill_feed_fields(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "sections backfill-feed-fields")
    from .operator_errors import require_operator_lane
    require_operator_lane("sections backfill-feed-fields", "Reference, Message, Assignment and semantic graph records", writing=apply)
    client, _ = create_authoring_client()
    models = ["Message", "Assignment", "Reference", "SemanticNode", "SemanticRelation"]
    changes: list[dict[str, Any]] = []
    for model_name in models:
        for record in client.list_records(model_name):
            patch = _newsroom_feed_patch_for(model_name, record)
            if not any(record.get(key) != patch.get(key) for key in patch):
                continue
            changes.append({"modelName": model_name, "expected": {**record, **patch}, "current": record})
    print(f"newsroom\tbackfill-feed-fields\tplanned\t{len(changes)} updates")
    for change in changes[:20]:
        expected = change["expected"]
        print(
            f"{change['modelName']}\t{change['current']['id']}\tcreatedAt={expected.get('createdAt') or ''}\t"
            f"updatedAt={expected.get('updatedAt') or ''}\tfeed={expected.get('newsroomFeedKey') or ''}"
        )
    if len(changes) > 20:
        print(f"newsroom\tbackfill-feed-fields\tpreview-truncated\t{len(changes) - 20} more")
    if not apply:
        print("newsroom\tbackfill-feed-fields\tapply\tskipped\tuse --dry-run to preview without writes")
        return
    for change in changes:
        client.upsert(change["modelName"], change["expected"])
    print(f"newsroom\tbackfill-feed-fields\tupdated\t{len(changes)}")


def newsroom_backfill_operational_indexes(flags: list[str]) -> None:
    options = parse_options(flags)
    started_at = datetime.now(timezone.utc)
    apply = resolve_mutation_apply(options, "sections backfill-operational-indexes")
    from .operator_errors import require_operator_lane
    require_operator_lane("sections backfill-operational-indexes", "Assignment and KnowledgeImportRun records", writing=apply)
    client, _ = create_authoring_client()
    _assert_operational_index_schema_ready(client)
    assignments = client.list_records("Assignment")
    import_runs = client.list_records("KnowledgeImportRun")
    assignment_changes: list[dict[str, Any]] = []
    for assignment in assignments:
        expected = {**assignment, **_assignment_operational_index_patch(assignment)}
        if _assignment_operational_index_changed(assignment, expected):
            assignment_changes.append({"modelName": "Assignment", "current": assignment, "expected": expected})
    import_run_changes: list[dict[str, Any]] = []
    for import_run in import_runs:
        expected = {**import_run, "corpusImportKindKey": _knowledge_import_run_corpus_kind_key(import_run)}
        if (import_run.get("corpusImportKindKey") or None) != (expected.get("corpusImportKindKey") or None):
            import_run_changes.append({"modelName": "KnowledgeImportRun", "current": import_run, "expected": expected})
    changes = sorted(
        [*assignment_changes, *import_run_changes],
        key=lambda left: (str(left["modelName"]), str(left["expected"]["id"])),
    )
    if apply:
        for index, change in enumerate(changes, start=1):
            client.upsert(change["modelName"], change["expected"])
            if index == len(changes) or index % 100 == 0:
                print(f"newsroom\tbackfill-operational-indexes\tprogress\t{index}/{len(changes)}", flush=True)
    elapsed_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
    result = {
        "ok": True,
        "command": "newsroom backfill-operational-indexes",
        "action": "apply" if apply else "dry-run",
        "indexes": [
            "Assignment.sectionStatusKey",
            "Assignment.sectionQueueStatusKey",
            "KnowledgeImportRun.corpusImportKindKey",
        ],
        "scanned": {"assignments": len(assignments), "importRuns": len(import_runs)},
        "changedByModel": {
            "Assignment": len(assignment_changes),
            "KnowledgeImportRun": len(import_run_changes),
        },
        "changedRecords": len(changes),
        "elapsedMs": elapsed_ms,
        "next": (
            "poetry run papyrus sections recount-summary"
            if apply
            else "poetry run papyrus sections backfill-operational-indexes"
        ),
    }
    if options.get("json"):
        print(json.dumps(result, indent=2))
        return
    print(f"newsroom\tbackfill-operational-indexes\taction\t{result['action']}")
    print(f"newsroom\tbackfill-operational-indexes\tchanged\t{len(changes)}")
    print(f"newsroom\tbackfill-operational-indexes\tassignments\t{len(assignment_changes)}")
    print(f"newsroom\tbackfill-operational-indexes\timport-runs\t{len(import_run_changes)}")
    for change in changes[:25]:
        expected = change["expected"]
        print(
            "\t".join(
                [
                    "operational-index",
                    change["modelName"],
                    expected["id"],
                    str(expected.get("corpusImportKindKey") or expected.get("sectionStatusKey") or ""),
                    str(expected.get("sectionQueueStatusKey") or ""),
                ]
            )
        )
    if len(changes) > 25:
        print(f"newsroom\tbackfill-operational-indexes\tpreview-truncated\t{len(changes) - 25} more")
    if not apply:
        print(f"newsroom\tbackfill-operational-indexes\tnext\t{result['next']}")


def import_missing_records(client, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One-time import of seed records into the database: create what is absent, never touch what exists.

    The database is the source of truth once editors own it in the newsroom, so a re-run (or a deploy step)
    must not overwrite a newer edit. A doctrine record counts as present when any Item has its slug.
    """
    changes: list[dict[str, Any]] = []
    for record in records:
        expected = record["expected"]
        if record["modelName"] == "Item" and expected.get("slug"):
            present = bool(client.list_by_index("itemBySlug", expected["slug"]))
        else:
            present = client.get_record(record["modelName"], expected["id"]) is not None
        if present:
            changes.append({**record, "action": "noop"})
            continue
        client.create_record(record["modelName"], expected)
        changes.append({**record, "action": "create"})
    return changes


def newsroom_import_sections(flags: list[str]) -> None:
    options = parse_options(flags)
    config_path = options.get("config") or str(DEFAULT_NEWSROOM_SECTIONS_PATH)
    sections = load_newsroom_section_seeds(config_path)
    client, _ = create_authoring_client(tenant_id_from_options(options))
    records = build_newsroom_section_records(sections)
    changes = import_missing_records(client, records)
    print_category_import_summary("newsroom-sections", Path(config_path).name, changes)


def newsroom_import_doctrine(flags: list[str]) -> None:
    options = parse_options(flags)
    require_explicit_doctrine(options, "sections import-doctrine", flag="config")
    config_path = options["config"]
    seed = load_publication_doctrine_seed(config_path)
    records = build_publication_doctrine_records(seed["doctrine"])
    client, _ = create_authoring_client()
    changes = import_missing_records(client, records)
    print_category_import_summary("publication-doctrine", Path(config_path).name, changes)


def newsroom_seed_required_procedures(flags: list[str]) -> None:
    """`papyrus procedures seed-required [--site-registry FILE] [--root DIR] [--dry-run | --check] [--json]`

    Registers every core procedure (all kinds in the registry, from the wheel) and the site's own procedures (papyrus-site-procedures.json at --root, default the current folder, or the file --site-registry names), as
    published versions in the site's backend. The Amplify build runs it after the backend deploys. Unchanged procedures write nothing.
    --dry-run reads the backend and prints what would change; --check reads it and fails when anything differs from Git.
    """
    options = parse_options(flags)
    check = options.get("check") is True
    if check and options.get("dry-run"):
        raise ValueError("procedures seed-required takes --check or --dry-run, not both: both read only, --check also fails on a difference.")
    apply = False if check else resolve_mutation_apply(options, "procedures seed-required")
    registry_option = options.get("site-registry")
    if registry_option is True or options.get("root") is True:
        raise ValueError("--site-registry and --root each need a value.")
    root = Path(options["root"]) if options.get("root") else Path.cwd()
    # The site's own procedures are listed in papyrus-site-procedures.json at the root; a site without the file has none.
    registry_path = root / (registry_option or SITE_REGISTRY_FILE)
    if not registry_option and not registry_path.is_file():
        registry_path = None
    plans = plan_deploy(site_registry=registry_path, root=root)
    client, _ = create_authoring_client()
    if apply:
        results = apply_deploy(client, plans)
        action = "apply"
    else:
        results = check_drift(client, plans) if check else plan_statuses(client, plans)
        action = "check" if check else "dry-run"
    if options.get("json"):
        print(json.dumps({"ok": True, "command": "procedures seed-required", "action": action, "procedures": results}, indent=2))
        return
    print(f"procedures\tseed-required\taction\t{action}")
    for result in results:
        print(f"procedures\tseed-required\t{result['status']}\t{result['procedureKey']}\t{result['versionId']}\t{result['origin']}")


def newsroom_prune_attachments(flags: list[str]) -> None:
    options = parse_options(flags)
    apply = resolve_mutation_apply(options, "sections prune-attachments")
    bucket = normalize_string(options.get("bucket"))
    prefix = normalize_string(options.get("prefix")) or "newsroom/payloads/"
    client, _ = create_authoring_client()
    attachments = client.list_records("ModelAttachment")
    owner_ids_by_kind = _load_model_attachment_owner_ids(client, attachments)
    attachments_of_an_unknown_owner_kind = [
        attachment
        for attachment in attachments
        if str(attachment.get("ownerKind") or "") not in MODEL_ATTACHMENT_OWNER_MODELS
    ]
    orphan_attachment_records = [
        attachment
        for attachment in attachments
        if str(attachment.get("ownerKind") or "") in MODEL_ATTACHMENT_OWNER_MODELS
        and not _attachment_owner_exists(attachment, owner_ids_by_kind)
    ]
    orphan_attachment_ids = {attachment["id"] for attachment in orphan_attachment_records}
    valid_attachment_storage_paths = {
        attachment["storagePath"]
        for attachment in attachments
        if attachment.get("id") not in orphan_attachment_ids and attachment.get("storagePath")
    }
    attachment_storage_paths = {attachment["storagePath"] for attachment in attachments if attachment.get("storagePath")}
    storage_listing = list_attachment_storage_paths(bucket=bucket, prefix=prefix)
    orphan_storage_paths = [path for path in storage_listing["keys"] if path not in attachment_storage_paths]
    record_storage_paths_to_delete = [
        attachment["storagePath"]
        for attachment in orphan_attachment_records
        if attachment.get("storagePath") and attachment["storagePath"] not in valid_attachment_storage_paths
    ]
    deleted = {"attachmentRecords": 0, "attachmentRecordObjects": 0, "orphanStorageObjects": 0}
    if not options.get("json"):
        print(f"attachment-prune\tmode\t{'apply' if apply else 'dry-run'}")
        print(f"attachment-prune\tbucket\t{storage_listing['bucket']}")
        print(f"attachment-prune\tprefix\t{storage_listing['prefix']}")
        print(f"attachment-prune\tmodelAttachments\t{len(attachments)}")
        print(f"attachment-prune\torphanAttachmentRecords\t{len(orphan_attachment_records)}")
        print(f"attachment-prune\torphanStorageObjects\t{len(orphan_storage_paths)}")
        print(f"attachment-prune\tkeptUnknownOwnerKind\t{len(attachments_of_an_unknown_owner_kind)}")
        for attachment in attachments_of_an_unknown_owner_kind:
            print(f"attachment-prune\tkept-unknown-owner-kind\t{attachment['id']}\t{attachment.get('ownerKind')}\t{attachment.get('ownerId')}")
    if apply and record_storage_paths_to_delete:
        delete_result = delete_attachment_storage_paths(record_storage_paths_to_delete, bucket=storage_listing["bucket"])
        deleted["attachmentRecordObjects"] += delete_result.get("deleted", 0)
    for attachment in orphan_attachment_records:
        owner_model = MODEL_ATTACHMENT_OWNER_MODELS.get(attachment.get("ownerKind") or "", "unknown-owner-kind")
        if not options.get("json"):
            print(
                f"attachment-prune\torphan-record\t{attachment['id']}\t{attachment.get('ownerKind')}\t"
                f"{owner_model}\t{attachment.get('ownerId')}\t{attachment.get('storagePath')}"
            )
        if not apply:
            continue
        client.delete_record("ModelAttachment", attachment["id"])
        deleted["attachmentRecords"] += 1
    if apply and orphan_storage_paths:
        delete_result = delete_attachment_storage_paths(orphan_storage_paths, bucket=storage_listing["bucket"])
        deleted["orphanStorageObjects"] += delete_result.get("deleted", 0)
    for storage_path in orphan_storage_paths:
        if not options.get("json"):
            print(f"attachment-prune\torphan-object\t{storage_path}")
    if options.get("json"):
        print(
            json.dumps(
                {
                    "ok": True,
                    "command": "newsroom prune-attachments",
                    "mode": "apply" if apply else "dry-run",
                    "bucket": storage_listing["bucket"],
                    "prefix": storage_listing["prefix"],
                    "counts": {
                        "modelAttachments": len(attachments),
                        "orphanAttachmentRecords": len(orphan_attachment_records),
                        "orphanStorageObjects": len(orphan_storage_paths),
                        "keptUnknownOwnerKind": len(attachments_of_an_unknown_owner_kind),
                    },
                    "keptUnknownOwnerKind": [
                        {"id": attachment["id"], "ownerKind": attachment.get("ownerKind"), "ownerId": attachment.get("ownerId")}
                        for attachment in attachments_of_an_unknown_owner_kind
                    ],
                    "deleted": deleted,
                    "next": None if apply else "poetry run papyrus sections prune-attachments",
                },
                indent=2,
            )
        )
    elif not apply:
        print("attachment-prune\tnext\tpoetry run papyrus sections prune-attachments")


def _reference_feed_patch(record: dict[str, Any], created_at: str) -> dict[str, Any]:
    """The References page keys (src/papyrus_content/reference_feed_keys.py); the prediction fields are never touched here."""
    from .reference_feed_keys import feed_keys
    if not record.get("id"):
        return {}
    keys = feed_keys({**record, "createdAt": created_at})
    keys.pop("mediumFeedKey", None)   # the medium key belongs to `papyrus references backfill-medium`, which writes it with the medium
    keys.pop("contentNeededKey", None)   # and so does the content-needed key (kept right afterwards by sync_capture_state)
    keys.pop("publicFeedKey", None)   # and the public keys belong to `papyrus references backfill-public-fields`
    keys.pop("publicOrderKey", None)
    return keys


def _newsroom_feed_patch_for(model_name: str, record: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now()
    if model_name == "Message":
        return {
            "createdAt": record.get("createdAt") or record.get("updatedAt") or now,
            "updatedAt": record.get("updatedAt") or record.get("createdAt") or now,
            "newsroomFeedKey": "messages",
        }
    if model_name == "Assignment":
        return {
            "createdAt": record.get("createdAt") or record.get("updatedAt") or now,
            "updatedAt": record.get("updatedAt") or record.get("createdAt") or now,
            "newsroomFeedKey": "assignments",
        }
    if model_name == "Reference":
        created_at = record.get("createdAt") or record.get("importedAt") or record.get("versionCreatedAt") or record.get("updatedAt") or now
        curation_status = str(record.get("curationStatus") or "pending").strip().lower() or "pending"
        return {
            "createdAt": created_at,
            "updatedAt": record.get("updatedAt") or record.get("curationStatusUpdatedAt") or record.get("importedAt") or created_at,
            "newsroomFeedKey": global_key(REFERENCE_FEED_KEY),
            "reviewedFeedKey": None if curation_status == "pending" else global_key(REFERENCE_REVIEWED_FEED_KEY),
            **_reference_feed_patch(record, created_at),
        }
    if model_name == "SemanticNode":
        created_at = record.get("createdAt") or record.get("versionCreatedAt") or record.get("updatedAt") or now
        return {
            "createdAt": created_at,
            "updatedAt": record.get("updatedAt") or created_at,
            "newsroomFeedKey": global_key(SEMANTIC_NODE_FEED_KEY),
        }
    if model_name == "SemanticRelation":
        created_at = record.get("createdAt") or record.get("importedAt") or record.get("updatedAt") or now
        return {
            "createdAt": created_at,
            "updatedAt": record.get("updatedAt") or record.get("importedAt") or created_at,
            "newsroomFeedKey": global_key(SEMANTIC_RELATION_FEED_KEY),
        }
    return {}


def _assignment_operational_index_patch(assignment: dict[str, Any]) -> dict[str, Any]:
    status = normalize_string(assignment.get("status")) or "open"
    queue_key = normalize_string(assignment.get("queueKey"))
    section_key = normalize_string(assignment.get("sectionKey")) or normalize_string(assignment.get("sectionId"))
    return {
        "sectionId": assignment.get("sectionId") or section_key,
        "sectionKey": section_key,
        "sectionType": assignment.get("sectionType"),
        "sectionStatusKey": f"{section_key}#{status}" if section_key else None,
        "sectionQueueStatusKey": f"{section_key}#{queue_key}#{status}" if section_key and queue_key else None,
        "primaryFocusCategoryKey": assignment.get("primaryFocusCategoryKey"),
        "topicScopeCategoryKeys": assignment.get("topicScopeCategoryKeys") or [],
    }


def _assignment_operational_index_changed(current: dict[str, Any], expected: dict[str, Any]) -> bool:
    for key in [
        "sectionId",
        "sectionKey",
        "sectionType",
        "sectionStatusKey",
        "sectionQueueStatusKey",
        "primaryFocusCategoryKey",
    ]:
        if (current.get(key) or None) != (expected.get(key) or None):
            return True
    current_scope = [value for value in (current.get("topicScopeCategoryKeys") or []) if value]
    expected_scope = [value for value in (expected.get("topicScopeCategoryKeys") or []) if value]
    return current_scope != expected_scope


def _knowledge_import_run_corpus_kind_key(import_run: dict[str, Any]) -> str | None:
    corpus_id = normalize_string(import_run.get("corpusId"))
    import_kind = normalize_string(import_run.get("importKind"))
    return f"{corpus_id}#{import_kind}" if corpus_id and import_kind else import_run.get("corpusImportKindKey")


def _assert_operational_index_schema_ready(client) -> None:
    assignment_fields = client.graphql_type_field_names("Assignment")
    import_run_fields = client.graphql_type_field_names("KnowledgeImportRun")
    missing = [
        *[
            f"Assignment.{field}"
            for field in ["sectionStatusKey", "sectionQueueStatusKey"]
            if field not in assignment_fields
        ],
        *[
            f"KnowledgeImportRun.{field}"
            for field in ["corpusImportKindKey"]
            if field not in import_run_fields
        ],
    ]
    if missing:
        raise ValueError(
            f"Operational index fields are not deployed yet. Missing GraphQL fields: {', '.join(missing)}."
        )


def _load_model_attachment_owner_ids(client, attachments: list[dict[str, Any]]) -> dict[str, set[str]]:
    owner_kinds = sorted({attachment.get("ownerKind") for attachment in attachments if attachment.get("ownerKind")})
    result: dict[str, set[str]] = {}
    for owner_kind in owner_kinds:
        model_name = MODEL_ATTACHMENT_OWNER_MODELS.get(str(owner_kind))
        if not model_name:
            result[str(owner_kind)] = set()
            continue
        rows = client.list_records(model_name)
        result[str(owner_kind)] = {row["id"] for row in rows if row.get("id")}
    return result


def _attachment_owner_exists(attachment: dict[str, Any], owner_ids_by_kind: dict[str, set[str]]) -> bool:
    owner_kind = str(attachment.get("ownerKind") or "")
    owner_model = MODEL_ATTACHMENT_OWNER_MODELS.get(owner_kind)
    if not owner_model:
        return False
    return attachment.get("ownerId") in owner_ids_by_kind.get(owner_kind, set())


def _is_message_status_null_error(error: Exception) -> bool:
    text = str(error)
    return (
        "Message" in text
        and "status" in text
        and "Cannot return null for non-nullable type" in text
    )


def _message_status_error_index(error: Exception) -> int | None:
    text = str(error)
    match = re.search(r"/listMessages/items\[(\d+)\]/status", text)
    if not match:
        match = re.search(r"/getMessage/status", text)
    if not match:
        return None
    if "/getMessage/status" in match.group(0):
        return 0
    return int(match.group(1))


def _write_json_file(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


PLANNING_ASSIGNMENT_TYPE_KEYS = frozenset({
    "research.candidate",
    "reporting.candidate",
})
PLANNING_FORUM_THREAD_KINDS = frozenset({
    "edition_forum",
    "section_forum",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso() -> str:
    return _utc_now()
