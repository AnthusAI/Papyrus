"""A published story as a Caducus ``story.published`` event.

The id comes from the story's lineage, so a republish, an edit or a repeated announcement is a duplicate in the site's table
and mails nobody twice. A story that no list's rule matches raises no event.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from papyrus_content.newsletter.alerts import PublishedItemSummary, rule_matches

from .settings import Settings

KIND = "story.published"
PRODUCT = "papyrus"
EVENT_ID = re.compile(r"story\.published:[A-Za-z0-9._:-]{1,200}")


def matching_lists(settings: Settings, summary: PublishedItemSummary) -> list[Mapping[str, Any]]:
    return [
        entry
        for entry in settings.lists
        if rule_matches(entry.get("rule"), section=summary.section, tags=summary.tags, item_type=summary.item_type)
    ]


def story_published_detail(row: Mapping[str, Any], *, event_id: str, settings: Settings, occurred_at: str) -> dict[str, Any] | None:
    """The event ``detail`` for a published item, or ``None`` when no list's rule matches it."""
    summary = PublishedItemSummary(row, settings)
    if not matching_lists(settings, summary):
        return None
    facts: dict[str, Any] = {"title": summary.title or "Untitled", "url": summary.url}
    blurb = summary.dek or summary.paragraph
    if blurb:
        facts["summary"] = blurb
    return {
        "schema": 1,
        "eventId": event_id,
        "kind": KIND,
        "product": PRODUCT,
        "site": settings.site_id,
        "occurredAt": occurred_at,
        "severity": "info",
        "facts": facts,
    }
