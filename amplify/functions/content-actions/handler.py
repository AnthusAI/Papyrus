from __future__ import annotations

import json
from typing import Any

from papyrus_content.graphql_authoring import create_authoring_client
from papyrus_content.markus_renderer.derive import derive_body
from papyrus_content.publishing import (
    ItemFields,
    PublishError,
    publish_item,
    save_item,
    unpublish_item,
)


def parse_input(raw: Any) -> dict:
    parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if not isinstance(parsed, dict):
        raise PublishError("invalid-input", "The input must be a JSON object.")
    return parsed


def actor_from_event(event: dict) -> str:
    identity = event.get("identity") or {}
    return identity.get("username") or identity.get("sub") or "unknown"


def failure_response(error: PublishError) -> dict:
    if error.errors:
        errors = [body_error.to_dict() for body_error in error.errors]
    else:
        errors = [{"code": error.code, "message": error.message, "line": None}]
    return {"ok": False, "errors": errors}


def derive_markus_action(arguments: dict) -> dict:
    derivation = derive_body(arguments.get("frontMatterYaml"), arguments.get("bodyMarkus") or "")
    if not derivation.ok:
        return {"ok": False, "errors": [body_error.to_dict() for body_error in derivation.errors]}
    response = {
        "ok": True,
        "bodyIrBytes": len(json.dumps(derivation.body_ir, separators=(",", ":")).encode("utf-8")),
        "errors": [],
    }
    if arguments.get("includeIr") is True:
        response["bodyIr"] = derivation.body_ir
    return response


def save_item_draft_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    fields = ItemFields(
        type=arguments["type"],
        slug=arguments["slug"],
        section=arguments.get("section"),
        front_matter_yaml=arguments.get("frontMatterYaml"),
        body_markus=arguments.get("bodyMarkus") or "",
        aliases=list(arguments.get("aliases") or []),
        id=arguments.get("id"),
    )
    record = save_item(client, fields, actor=actor, expected_content_hash=arguments.get("expectedContentHash"))
    return {
        "ok": True,
        "item": {
            "id": record["id"],
            "contentHash": record["contentHash"],
            "status": record["status"],
            "slug": record["slug"],
            "versionNumber": record.get("versionNumber"),
        },
    }


def publish_item_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    result = publish_item(client, arguments["id"], actor=actor)
    return {
        "ok": True,
        "changed": result.changed,
        "publishedId": result.published_item_id,
        "versionNumber": result.version_number,
    }


def unpublish_item_action(arguments: dict, actor: str) -> dict:
    client, _claims = create_authoring_client()
    result = unpublish_item(client, arguments["id"], actor=actor)
    return {"ok": True, "changed": result.changed}


def handler(event, context):
    field = event["fieldName"]
    arguments = parse_input(event["arguments"]["input"])
    actor = actor_from_event(event)
    try:
        if field == "deriveMarkus":
            return derive_markus_action(arguments)
        if field == "saveItemDraft":
            return save_item_draft_action(arguments, actor)
        if field == "publishItem":
            return publish_item_action(arguments, actor)
        if field == "unpublishItem":
            return unpublish_item_action(arguments, actor)
    except PublishError as error:
        return failure_response(error)
    raise ValueError(f"Unsupported field {field}")
