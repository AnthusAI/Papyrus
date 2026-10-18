"""Stamp historic reference curation with who made it, for editors a person names.

Curation recorded before the human-only label rule has no ``actorKind``, so it
never teaches the cyclotron. Only a person can say which author labels were
people, so the backfill stamps ``human`` solely on curation whose author label
is in the list the caller names. Everything else is left alone and reported.
Dry run by default.
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .model_attachments import attachment_record, build_json_model_payload_attachment
from .relevance_decisions import HUMAN_CURATION_ACTOR_KIND


def plan_actor_kind_stamps(curation_messages: Sequence[Mapping[str, Any]], *,
                           human_author_labels: Sequence[str]) -> dict[str, Any]:
    """Which curation messages to stamp human, and a count of authors left unstamped."""
    named_people = {label.strip() for label in human_author_labels if label.strip()}
    to_stamp, unstamped_authors, already_stamped, inline_metadata_skipped = [], Counter(), 0, 0
    for message in curation_messages:
        if (message.get("metadata") or {}).get("actorKind"):
            already_stamped += 1
        elif str(message.get("authorLabel") or "") not in named_people:
            unstamped_authors[str(message.get("authorLabel") or "(none)")] += 1
        elif message.get("hasInlineMetadata"):
            inline_metadata_skipped += 1
        else:
            to_stamp.append(message)
    return {"toStamp": to_stamp, "alreadyStamped": already_stamped, "inlineMetadataSkipped": inline_metadata_skipped,
            "unstampedAuthors": dict(unstamped_authors.most_common())}


def actor_kind_stamp_record(message: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    """The metadata attachment that replaces the message's, with the human stamp added."""
    return attachment_record(build_json_model_payload_attachment({
        "ownerKind": "message",
        "ownerId": message["id"],
        "ownerLineageId": message["id"],
        "role": "metadata",
        "sortKey": "metadata",
        "content": {**(message.get("metadata") or {}), "actorKind": HUMAN_CURATION_ACTOR_KIND,
                    "actorKindStampedBy": "backfill:named-editor"},
        "now": now,
    }))


def references_stamp_curation_actor_kind(flags: list[str]) -> None:
    """papyrus references stamp-curation-actor-kind --human-authors <label,label,...> [--config <steering.yml>] [--apply]

    Dry run by default: prints how many curation messages would be stamped as
    made by a person and which other author labels exist, so a person can name
    them. ``--apply`` writes the stamps.
    """
    from .graphql_authoring import create_authoring_client
    from .ids import knowledge_corpus_id
    from .options import parse_options
    from .relevance_sweep import REVIEWED_STATUSES, _apply, _curation_messages, _current
    from .steering import require_corpus_config, require_steering_config

    options = parse_options(flags)
    if not isinstance(options.get("human-authors"), str):
        raise ValueError("references stamp-curation-actor-kind requires --human-authors <label,label,...>.")
    steering_config = require_steering_config(options.get("config"))
    corpus = require_corpus_config(dict(steering_config), steering_config["canonicalTopicSet"]["corpusKey"],
                                   "canonicalTopicSet.corpusKey")
    corpus_id = knowledge_corpus_id(corpus)
    client, _ = create_authoring_client()
    curation_messages = []
    for status in REVIEWED_STATUSES:
        for reference in _current(client.list_by_index("referencesByCurationStatusKey", f"{corpus_id}#{status}")):
            curation_messages += _curation_messages(client, reference["lineageId"])
    plan = plan_actor_kind_stamps(curation_messages, human_author_labels=options["human-authors"].split(","))
    print(f"references\tstamp-curation-actor-kind\tto-stamp\t{len(plan['toStamp'])}")
    print(f"references\tstamp-curation-actor-kind\talready-stamped\t{plan['alreadyStamped']}")
    print(f"references\tstamp-curation-actor-kind\tinline-metadata-skipped\t{plan['inlineMetadataSkipped']}")
    for author, count in plan["unstampedAuthors"].items():
        print(f"references\tstamp-curation-actor-kind\tunstamped-author\t{author}\t{count}")
    if options.get("apply"):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _apply(client, [actor_kind_stamp_record(message, now=now) for message in plan["toStamp"]])
        print(f"references\tstamp-curation-actor-kind\tstamped\t{len(plan['toStamp'])}")
