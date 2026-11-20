"""Translate on publish: the request side of the automatic trigger (``languages.auto``, docs/story-translation-procedure.md).

When a Story written in the site's primary language is published (a new version, or its first), :func:`request_translations` writes one desired-state
record per enabled language other than the primary (``desired_state.want``): the newest published source version to translate, the Automation that runs
the translation procedure and whether a clean result publishes. Nothing here calls a model or starts a run. The records are the durable trigger: the
dispatcher (``dispatch.py``) reacts to them on the site's runner, and ``papyrus stories localize --all`` finds anything a failure left behind.

Once per change: a record already naming this very source text (same content hash) is left alone unless its run failed or stopped, so a publish that
changes nothing, or the same version announced twice, requests nothing. A newer publish overwrites the record (coalescing): an older run that is still
working stops at its next check and saves nothing (``run.py``).
"""
from __future__ import annotations

import json
from typing import Any

from ..content_item_lifecycle import is_story_item_type
from ..editorial_checks import GraphQLEditorialStore, settings_from
from ..item_language import ItemLanguageMissing, item_language
from ..language_serving import serving_languages
from ..localization_publish import original_of
from ..story_reporting import published_story_version
from . import desired_state

REQUESTED_BY = "publish"
#: A record in one of these states is asked for again when the Story is published again at the same text: its run did not finish.
RETRY_STATES = ("failed", "stopped")


def _skipped(reason: str) -> dict[str, Any]:
    return {"requested": [], "reason": reason}


def request_translations(client, item_id: str, *, settings: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
    """After ``item_id`` was published: request its translations. Returns ``{"requested": [record ids], "reason": why none}``. Raises when a record cannot be
    written (the caller reports it; the publish itself is already done and the next ``papyrus stories localize --all`` writes what is missing)."""
    settings = settings or settings_from(GraphQLEditorialStore(execute=client.graphql, tenant_id=getattr(client, "tenant_id", None)))
    serving = serving_languages(settings)
    if serving.auto is None:
        return _skipped("translation on publish is off")
    item = client.get_record("Item", item_id)
    if item is None:
        return _skipped("the published version was not found")
    if original_of(client, item) is not None:
        return _skipped("a translation is never translated again")   # only primary publishes enqueue translation
    if not is_story_item_type(item.get("type")):
        return _skipped("only Stories are translated")
    try:
        if item_language(item) != serving.primary:
            return _skipped(f"written in {item_language(item)}, not the primary language {serving.primary}")
    except ItemLanguageMissing as error:
        return _skipped(str(error))
    metadata = json.loads(item["metadata"]) if isinstance(item.get("metadata"), str) and item["metadata"].strip() else (item.get("metadata") or {})
    if metadata.get("doNotLocalize"):
        return _skipped("marked do not localize")
    source = published_story_version(client, item.get("lineageId") or item_id)
    if source is None or source["id"] != item_id:
        return _skipped("a different version is the published one now")
    requested = []
    for language in serving.enabled:
        if language == serving.primary:
            continue
        from ..authored_editions import current_companion, is_authored
        if is_authored(current_companion(client, source["lineageId"], language)):
            continue
        existing = desired_state.current(client, source["lineageId"], language)
        if (existing is not None and str(existing.get("sourceContentHash") or "") == str(source.get("contentHash") or "")
                and existing.get("state") not in RETRY_STATES):
            continue
        record = desired_state.want(client, source=source, language=language, requested_by=REQUESTED_BY, automation_id=serving.auto.automation,
                                    publish=serving.auto.publish, now=now)
        requested.append(record["id"])
    return {"requested": requested, "reason": "" if requested else "every language is already requested for this text"}
