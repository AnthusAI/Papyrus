from __future__ import annotations

import json
import os
from typing import Any


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    if isinstance(event.get("Records"), list):
        record = event["Records"][0]
        body = record.get("body") if isinstance(record, dict) else None
        if isinstance(body, str):
            event = json.loads(body)
        elif isinstance(body, dict):
            event = body

    message_id = str(event.get("messageId") or event.get("message_id") or "").strip()
    if not message_id:
        raise ValueError("messageId is required.")

    if event.get("sendFeedbackOnly") or event.get("send_feedback_only"):
        from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
        from papyrus_newsroom.email_submissions import send_submission_feedback_for_message

        endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip()
        client = PapyrusGraphQLAuthoringClient(endpoint=endpoint or None)
        return send_submission_feedback_for_message(client, message_id=message_id)

    corpus_key = str(
        event.get("corpusKey")
        or event.get("corpus_key")
        or os.environ.get("PAPYRUS_INBOUND_EMAIL_CORPUS_KEY")
        or ""
    ).strip()
    if not corpus_key:
        raise ValueError("corpusKey or PAPYRUS_INBOUND_EMAIL_CORPUS_KEY is required.")

    from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient
    from papyrus_newsroom.email_submissions import process_email_submission_message

    endpoint = os.environ.get("PAPYRUS_GRAPHQL_ENDPOINT", "").strip()
    client = PapyrusGraphQLAuthoringClient(endpoint=endpoint or None)
    return process_email_submission_message(
        client,
        message_id=message_id,
        corpus_key=corpus_key,
        apply=True,
    )
