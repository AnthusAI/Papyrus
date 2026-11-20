"""Which saved translations may be published, decided in one place (docs/story-translation-procedure.md, "Publishing a translation").

A translation run never publishes. Publishing is a separate act, by a person or by one of the two automatic callers: the dispatcher (``dispatch.py``,
for a site that turned on ``languages.auto``) and ``papyrus stories localize --publish-clean``. Both ask :func:`publishable` which version, if any, a
request's translation may publish, and then publish it through the ordinary path (``publishing.publish_item``), so the checklist, the hold rule, the
original-published rule and the site's approval gate apply as to any publish.

A translation is publishable when all of these hold:

* its language is one the site writes in;
* the Story it translates is still published at the very source version the request names (a republished Story has a newer request and its own run);
* its newest version came from that source and its run saved it cleanly (``metadata.localization.outcome`` is ``saved``): a held translation waits for a
  person to answer its review request, and nothing here clears it;
* it is not already live at that text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..editorial_languages import LanguageNotEnabled, site_language
from ..item_language import localization_lineage_id
from ..publishing import published_item_id_for
from ..story_reporting import published_story_version, story_versions


@dataclass(frozen=True)
class Publishable:
    """``version`` is the Item row to publish, or None with the ``reason`` it is not (and ``done``: the translation is already live at this text)."""

    version: dict[str, Any] | None
    reason: str
    done: bool = False
    held: bool = False   # a person has to answer the translation's review request first


def _localization(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata.strip() else (metadata or {})
    return metadata.get("localization") or {}


def publishable(client, request: dict[str, Any], settings: dict[str, Any]) -> Publishable:
    """The version of ``request``'s translation that may be published now, or why none may."""
    group, language = request["languageGroupId"], request["language"]
    try:
        site_language(language, settings)
    except LanguageNotEnabled as error:
        return Publishable(None, str(error))
    source = published_story_version(client, group)
    if source is None:
        return Publishable(None, f"{group} is not published, so its translation is not published either")
    if str(source.get("contentHash") or "") != str(request.get("sourceContentHash") or ""):
        return Publishable(None, f"{group} was published again after this translation was requested; the newer request has its own run")
    versions = story_versions(client, localization_lineage_id(group, language))
    current = next((row for row in versions if row.get("versionState") == "current"), versions[0] if versions else None)
    if current is None:
        return Publishable(None, "no translation has been saved")
    if str(current.get("sourceContentHash") or "") != str(request.get("sourceContentHash") or ""):
        return Publishable(None, "the newest translation is of another version of the Story than this request names")
    localization = _localization(current)
    if localization.get("outcome") != "saved":
        held = localization.get("outcome") == "held"
        return Publishable(None, f"the translation is {localization.get('outcome') or 'not saved cleanly'}: a person answers its review request before it is published", held=held)
    live = client.get_record("PublishedItem", published_item_id_for(current.get("lineageId") or current["id"]))
    live_hash = (json.loads(live["metadata"]) if isinstance(live.get("metadata"), str) else (live.get("metadata") or {})).get("sourceContentHash") if live else None
    if live is not None and live.get("status") in (None, "published") and live_hash == current.get("contentHash"):
        return Publishable(current, "already published", done=True)
    return Publishable(current, "ready")
