"""A person's Message is created through the ``postMessage`` mutation, never through ``createMessage``.

The backend stamps the author from the signed-in identity (``authorSub``), whatever the caller sends: the mutation has no author
argument, and ``authorLabel`` is only a label. This mirrors ``lib/post-message.ts``, which the browser uses.
"""

from __future__ import annotations

import re
from typing import Any

POST_MESSAGE_ARGUMENT_TYPES = {
    "id": "ID!",
    "threadId": "ID!",
    "content": "String",
    "messageKind": "String!",
    "messageDomain": "String!",
    "summary": "String",
    "parentMessageId": "ID",
    "sequenceNumber": "Int",
    "messageType": "String",
    "role": "String",
    "source": "String",
    "authorLabel": "String",
    "semanticLayer": "String",
    "searchVisibility": "String",
    "responseTarget": "String",
    "responseStatus": "String",
    "responseOwner": "String",
    "responseStartedAt": "AWSDateTime",
    "responseCompletedAt": "AWSDateTime",
    "metadata": "AWSJSON",
    "newsroomFeedKey": "String",
}

POST_MESSAGE_SELECTION = "id messageKind summary authorSub authorLabel threadId sequenceNumber role createdAt"
# The same words lib/conversation.ts looks for: a create that lost a race for its sequence number is refused as already existing.
_SEQUENCE_CONFLICT = re.compile(r"conditional|already exists|duplicate|ConditionalCheckFailed|Conflict", re.IGNORECASE)


def post_message_arguments(record: dict[str, Any]) -> dict[str, Any]:
    """The arguments of ``postMessage`` from a Message record. Anything else on the record (authorSub, createdAt, updatedAt) is dropped."""
    return {key: record[key] for key in POST_MESSAGE_ARGUMENT_TYPES if record.get(key) is not None}


def post_message_mutation(arguments: dict[str, Any]) -> str:
    declared = ", ".join(f"${key}: {POST_MESSAGE_ARGUMENT_TYPES[key]}" for key in arguments)
    passed = ", ".join(f"{key}: ${key}" for key in arguments)
    return f"mutation PostMessage({declared}) {{ postMessage({passed}) {{ {POST_MESSAGE_SELECTION} }} }}"


def post_message(client: Any, record: dict[str, Any]) -> dict[str, Any]:
    arguments = post_message_arguments(record)
    data = client.graphql(post_message_mutation(arguments), arguments)
    return data.get("postMessage") or {}


def is_sequence_conflict(error: BaseException) -> bool:
    return bool(_SEQUENCE_CONFLICT.search(str(error)))
