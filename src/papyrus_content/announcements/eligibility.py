"""Is this Story announced? Only the site's own rules decide, and only a human rating counts.

A Story is eligible when it is published and not retired, its type (and section, when the site limits them) is announced, and its effective human rating
(``item_stars.effective_rating``, the one reader of quality) is at or above the site's announcement bar. Unrated is 0 and never qualifies; a model's prediction is
not a rating and never qualifies. References are not Stories and are never announced. A Story that is not eligible leaves no trace: it is not listed as waiting.

The trigger is the later of two events, first publication and the rating reaching the bar. Both end in the same call, so this module only asks "is it eligible now";
the announcement id (``<accountId>#<lineageId>``) is what keeps a second event, a new version or a republish from posting again.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content.content_item_lifecycle import RETIRED_INTO_KEY, RETIRED_STAGE, is_story_item_type
from papyrus_content.item_stars import effective_rating
from papyrus_content.newsletter.roundup import _front_matter, item_path
from papyrus_content.story_reporting import current_story_version, published_story_version

from .settings import OFF


@dataclass(frozen=True)
class Verdict:
    eligible: bool
    reason: str  # a short code: eligible, off, not_a_story, not_published, retired, type_not_announced, section_not_announced, below_bar


@dataclass(frozen=True)
class StoryFacts:
    """What announcing needs from a Story: nothing else is read."""

    lineage_id: str
    item_id: str
    version_number: int
    story_type: str
    section: str | None
    published: bool
    retired: bool
    stars: int
    title: str
    dek: str
    summary: str
    body: str
    path: str


def _line(value: Any) -> str:
    return " ".join(str(value or "").split())


def load_story(client: Any, lineage_id: str, *, item_url_style: str) -> StoryFacts:
    """The facts of one Story: its head (rating, retirement), its live version (text). Two lineage queries and one get; no table is listed."""
    head = current_story_version(client, lineage_id)
    live = published_story_version(client, lineage_id)
    source = live or head
    front = _front_matter(source)
    summary = _line(front.get("summary") or front.get("description") or "")
    retired = head.get("stage") == RETIRED_STAGE and bool(_metadata(head).get(RETIRED_INTO_KEY))
    return StoryFacts(
        lineage_id=lineage_id,
        item_id=str(source["id"]),
        version_number=int(source.get("versionNumber") or 0),
        story_type=str(head.get("type") or ""),
        section=head.get("section") or None,
        published=live is not None and not retired,
        retired=retired,
        stars=effective_rating(head)["stars"],
        title=_line(source.get("title") or source.get("headline") or front.get("title") or source.get("slug")),
        dek=_line(source.get("deck") or front.get("dek") or front.get("deck") or ""),
        summary=summary,
        body=str(source.get("bodyMarkus") or ""),
        path=item_path(source.get("section") or None, str(source.get("slug") or ""), item_url_style),
    )


def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    from papyrus_content.publishing import _parse_json_object

    return _parse_json_object(row.get("metadata"))


def verdict(story: StoryFacts, settings: Mapping[str, Any]) -> Verdict:
    if settings.get("mode", OFF) == OFF:
        return Verdict(False, "off")
    if not is_story_item_type(story.story_type):
        return Verdict(False, "not_a_story")
    if story.retired:
        return Verdict(False, "retired")
    if not story.published:
        return Verdict(False, "not_published")
    if story.story_type not in (settings.get("storyTypes") or []):
        return Verdict(False, "type_not_announced")
    sections = settings.get("sections")
    if sections and story.section not in sections:
        return Verdict(False, "section_not_announced")
    bar = settings.get("minStars")
    if bar is None or story.stars == 0 or story.stars < bar:
        return Verdict(False, "below_bar")
    return Verdict(True, "eligible")
