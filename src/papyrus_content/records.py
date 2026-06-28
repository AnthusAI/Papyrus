from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from .graphql_authoring import PapyrusGraphQLAuthoringClient, strip_unsupported_payload_fields
from .ids import hash_short
from .model_attachments import expand_private_payload_records, upload_attachment_body


APPEND_ONLY_EXISTING_NOOP_MODELS = frozenset(
    {"Assignment", "AssignmentEvent", "Message", "SteeringDecision"}
)

OPTIONAL_SCHEMA_MODELS = frozenset({"CategoryKeyword", "LexicalSteeringRule", "ModelAttachment"})


def is_missing_graphql_model_error(error: Exception, model_name: str) -> bool:
    message = str(error)
    list_field = f"list{model_name}s"
    get_field = f"get{model_name}"
    return "FieldUndefined" in message and (list_field in message or get_field in message or model_name in message)


def build_record_changes_tolerating_optional_models(
    client: PapyrusGraphQLAuthoringClient,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    pending = list(records)
    skipped_models: set[str] = set()
    while True:
        try:
            filtered = [record for record in pending if record["modelName"] not in skipped_models]
            return build_record_changes(client, filtered)
        except (RuntimeError, KeyError, ValueError) as error:
            if isinstance(error, KeyError):
                missing_model = str(error).strip("'\"")
                if missing_model in OPTIONAL_SCHEMA_MODELS and missing_model not in skipped_models:
                    skipped_models.add(missing_model)
                    pending = [record for record in pending if record["modelName"] != missing_model]
                    print(f"skip\t{missing_model}\tmodel is not deployed in AppSync yet; skipped optional records.")
                    continue
            missing_model = next(
                (
                    model_name
                    for model_name in OPTIONAL_SCHEMA_MODELS
                    if model_name not in skipped_models and is_missing_graphql_model_error(error, model_name)
                ),
                None,
            )
            if missing_model is None:
                raise
            skipped_models.add(missing_model)
            pending = [record for record in pending if record["modelName"] != missing_model]
            print(f"skip\t{missing_model}\tmodel is not deployed in AppSync yet; skipped optional records.")


def build_steering_config_record_changes(
    client: PapyrusGraphQLAuthoringClient,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for record in records:
        current = client.get_record(record["modelName"], record["expected"]["id"])
        if not current:
            changes.append({**record, "current": current, "action": "create"})
            continue
        action = (
            "noop"
            if current.get("name") == record["expected"].get("name")
            and current.get("role") == record["expected"].get("role")
            else "update"
        )
        expected = record["expected"]
        if action == "update":
            expected = {
                "id": expected["id"],
                "name": expected["name"],
                "role": expected["role"],
                "updatedAt": expected["updatedAt"],
            }
        changes.append(
            {
                "modelName": record["modelName"],
                "expected": expected,
                "current": current,
                "action": action,
            }
        )
    return changes


def build_record_changes_targeted_by_id(
    client: PapyrusGraphQLAuthoringClient,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for record in records:
        current = client.get_record(record["modelName"], record["expected"]["id"])
        changes.append(build_record_change_from_current(record["modelName"], record["expected"], current))
    return changes


def build_record_change_from_current(
    model_name: str,
    expected: dict[str, Any],
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    next_expected = strip_unsupported_payload_fields(model_name, dict(expected))
    if current and model_name in APPEND_ONLY_EXISTING_NOOP_MODELS:
        return {"modelName": model_name, "expected": current, "current": current, "action": "noop"}
    action = "create" if not current else ("noop" if records_equal_for_model(model_name, current, next_expected) else "update")
    return {
        "modelName": model_name,
        "expected": next_expected,
        "current": current,
        "action": action,
    }


def records_equal_for_model(model_name: str, current: dict[str, Any], expected: dict[str, Any]) -> bool:
    ignored = {"updatedAt", "createdAt", "importedAt", "versionCreatedAt"}
    if model_name == "Reference":
        ignored |= {"newsroomFeedKey", "curationStatusUpdatedAt"}
    keys = {key for key in {*current.keys(), *expected.keys()} if key not in ignored}
    for key in sorted(keys):
        if normalize_compare_value(current.get(key)) != normalize_compare_value(expected.get(key)):
            return False
    return True


def normalize_compare_value(value: Any) -> Any:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.startswith("{") or trimmed.startswith("["):
            try:
                return json.loads(trimmed)
            except json.JSONDecodeError:
                return trimmed
        return trimmed
    return value


def build_record_changes(
    client: PapyrusGraphQLAuthoringClient,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prepared = prepare_versioned_knowledge_records(client, records)
    indexed = [normalize_operational_index_record(record) for record in prepared["records"]]
    expanded = dedupe_planned_records(expand_private_payload_records(indexed))
    existing_by_model = list_existing_records_by_model(client, expanded)
    changes: list[dict[str, Any]] = []
    for record in expanded:
        model_name = record["modelName"]
        expected = record["expected"]
        current = existing_by_model.get(model_name, {}).get(expected["id"])
        change = build_record_change_from_current(model_name, expected, current)
        if "attachmentBody" in record:
            change["attachmentBody"] = record["attachmentBody"]
        changes.append(change)
    changes.extend(prepared["postChanges"])
    return changes


def list_existing_records_by_model(
    client: PapyrusGraphQLAuthoringClient,
    records: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    existing_by_model: dict[str, dict[str, dict[str, Any]]] = {}
    seen_ids: set[tuple[str, str]] = set()
    for record in records:
        model_name = record["modelName"]
        record_id = str(record["expected"].get("id") or "")
        if not record_id:
            continue
        key = (model_name, record_id)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        current = client.get_record(model_name, record_id)
        if current:
            existing_by_model.setdefault(model_name, {})[record_id] = current
    return existing_by_model


def normalize_operational_index_record(record: dict[str, Any]) -> dict[str, Any]:
    if record["modelName"] != "Assignment":
        return record
    expected = dict(record["expected"])
    status = expected.get("status") or "open"
    section_key = expected.get("sectionKey") or expected.get("sectionId")
    queue_key = expected.get("queueKey")
    if queue_key:
        expected["queueStatusKey"] = expected.get("queueStatusKey") or f"{queue_key}#{status}"
    if section_key:
        expected["sectionStatusKey"] = expected.get("sectionStatusKey") or f"{section_key}#{status}"
        if queue_key:
            expected["sectionQueueStatusKey"] = (
                expected.get("sectionQueueStatusKey") or f"{section_key}#{queue_key}#{status}"
            )
    return {**record, "expected": expected}


def dedupe_planned_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        key = (record["modelName"], record["expected"]["id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def prepare_versioned_knowledge_records(
    client: PapyrusGraphQLAuthoringClient,
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    reference_records = [record for record in records if record["modelName"] == "Reference"]
    if not reference_records:
        return {"records": records, "postChanges": []}

    existing_references = client.list_records("Reference")
    current_by_lineage: dict[str, dict[str, Any]] = {}
    for reference in existing_references:
        lineage_id = reference.get("lineageId")
        if not lineage_id:
            continue
        current = current_by_lineage.get(lineage_id)
        if (
            reference.get("versionState") == "current"
            and (
                current is None
                or int(reference.get("versionNumber") or 0) > int(current.get("versionNumber") or 0)
            )
        ):
            current_by_lineage[lineage_id] = reference

    reference_id_map: dict[str, dict[str, Any]] = {}
    changed_lineages: set[str] = set()
    post_changes: list[dict[str, Any]] = []
    prepared_records: list[dict[str, Any]] = []

    for record in records:
        if record["modelName"] != "Reference":
            prepared_records.append(record)
            continue
        expected = dict(record["expected"])
        current = current_by_lineage.get(expected["lineageId"])
        if not current:
            if expected.get("lineageId") and expected.get("versionNumber") is not None:
                reference_id_map[expected["id"]] = expected
            prepared_records.append(record)
            continue
        if current.get("importRunId") and expected.get("importRunId") and current["importRunId"] == expected["importRunId"]:
            reference_id_map[expected["id"]] = current
            continue
        if current.get("contentHash") and current.get("contentHash") == expected.get("contentHash"):
            reference_id_map[expected["id"]] = current
            continue
        version_number = int(current.get("versionNumber") or 1) + 1
        next_reference = {
            **expected,
            "id": f"{expected['lineageId']}-v{version_number}",
            "versionNumber": version_number,
            "previousVersionId": current["id"],
            "versionState": "current",
        }
        reference_id_map[expected["id"]] = next_reference
        changed_lineages.add(expected["lineageId"])
        prepared_records.append({**record, "expected": next_reference})
        post_changes.append(
            build_record_change_from_current(
                "Reference",
                {
                    "id": current["id"],
                    "versionState": "superseded",
                    "updatedAt": expected.get("updatedAt") or expected.get("importedAt"),
                },
                current,
            )
        )

    mapped_records = []
    for record in prepared_records:
        if record["modelName"] == "SemanticRelation":
            mapped_records.append(
                {
                    **record,
                    "expected": remap_semantic_relation_references(record["expected"], reference_id_map),
                }
            )
        elif record["modelName"] == "ReferenceAttachment":
            mapped_records.append(
                {
                    **record,
                    "expected": remap_reference_attachment(record["expected"], reference_id_map),
                }
            )
        else:
            mapped_records.append(record)

    if changed_lineages:
        existing_relations = client.list_records("SemanticRelation")
        for relation in existing_relations:
            if relation.get("relationState") == "current" and relation.get("subjectLineageId") in changed_lineages:
                post_changes.append(
                    build_record_change_from_current(
                        "SemanticRelation",
                        {"id": relation["id"], "relationState": "superseded"},
                        relation,
                    )
                )

    return {"records": mapped_records, "postChanges": post_changes}


def remap_semantic_relation_references(
    relation: dict[str, Any],
    reference_id_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    next_relation = dict(relation)
    subject = reference_id_map.get(relation.get("subjectId"))
    if subject:
        next_relation.update(
            {
                "subjectId": subject["id"],
                "subjectVersionNumber": subject.get("versionNumber"),
                "subjectVersionKey": f"{relation.get('subjectKind')}#{subject['id']}",
            }
        )
    obj = reference_id_map.get(relation.get("objectId"))
    if obj:
        next_relation.update(
            {
                "objectId": obj["id"],
                "objectVersionNumber": obj.get("versionNumber"),
                "objectVersionKey": f"{relation.get('objectKind')}#{obj['id']}",
            }
        )
    if next_relation != relation:
        next_relation["id"] = (
            "semantic-relation-"
            + hash_short(
                [
                    next_relation.get("subjectVersionKey"),
                    next_relation.get("predicate"),
                    next_relation.get("objectVersionKey"),
                    next_relation.get("rank"),
                    next_relation.get("classifierId"),
                    next_relation.get("modelVersion"),
                ]
            )
        )
    return next_relation


def remap_reference_attachment(
    attachment: dict[str, Any],
    reference_id_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    reference = reference_id_map.get(attachment.get("referenceId"))
    if not reference:
        return attachment
    reference_version_key = f"reference#{reference['id']}"
    next_attachment = {
        **attachment,
        "referenceId": reference["id"],
        "referenceLineageId": reference["lineageId"],
        "referenceVersionNumber": reference.get("versionNumber"),
        "referenceVersionKey": reference_version_key,
    }
    next_attachment["id"] = (
        "reference-attachment-"
        + hash_short(
            [
                reference_version_key,
                next_attachment.get("role"),
                next_attachment.get("sortKey"),
                next_attachment.get("storagePath") or "",
                next_attachment.get("sourceUri") or "",
            ]
        )
    )
    return next_attachment


def apply_record_changes(
    client: PapyrusGraphQLAuthoringClient,
    changes: list[dict[str, Any]],
    *,
    max_parallel: int = 1,
    client_factory: Callable[[], PapyrusGraphQLAuthoringClient] | None = None,
) -> None:
    actionable = [change for change in changes if change.get("action") != "noop"]
    attachment_changes = [
        change
        for change in actionable
        if change["modelName"] == "ModelAttachment" and change.get("attachmentBody") is not None
    ]
    owner_changes = [change for change in actionable if change not in attachment_changes]

    parallel = max(1, int(max_parallel or 1))
    if parallel == 1 or not owner_changes:
        for change in owner_changes:
            _apply_change(client, change)
    else:
        if client_factory is None:
            raise ValueError("max_parallel > 1 requires client_factory for thread-local GraphQL clients.")
        errors: list[Exception] = []

        def apply_one(change: dict[str, Any]) -> None:
            worker_client = client_factory()
            _apply_change(worker_client, change)

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = [executor.submit(apply_one, change) for change in owner_changes]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as error:
                    errors.append(error)
        if errors:
            raise errors[0]

    for change in attachment_changes:
        # createModelAttachmentUpload/completeModelAttachmentUpload already upserts
        # the ModelAttachment record. Avoid a second direct model mutation here,
        # because ModelAttachment writes may be intentionally restricted to the
        # upload handlers.
        upload_attachment_body(client, change["expected"], change["attachmentBody"])


def _apply_change(client: PapyrusGraphQLAuthoringClient, change: dict[str, Any]) -> None:
    action = str(change.get("action") or "").strip().lower()
    try:
        if action == "create":
            client.create_record(change["modelName"], change["expected"])
        elif action == "update":
            client.update_record(change["modelName"], change["expected"])
        else:
            client.upsert(change["modelName"], change["expected"])
    except RuntimeError as error:
        if action == "create" and _is_conditional_conflict_error(error):
            try:
                client.update_record(change["modelName"], change["expected"])
                return
            except RuntimeError:
                pass
        raise RuntimeError(
            f"Failed to apply {change.get('action')} {change.get('modelName')} {change.get('expected', {}).get('id')}: {error}"
        ) from error


def _is_conditional_conflict_error(error: Exception) -> bool:
    message = str(error).lower()
    return "conditional request failed" in message or "conditionalcheckfailedexception" in message
