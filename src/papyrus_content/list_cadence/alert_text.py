"""The words of an every-item email alert, and the rule a list uses to carry a Story (PPY-58d962).

An alert is the email Delivery of a ``story-published:<lineage>`` Announcement. Its Markus body is the Delivery's text file in S3 (``Deliveries.create`` writes it): the
title as a link, the dek, the first paragraph of plain prose if the Story has one, and a "Read it on <site>" link. The drafter here is a template, not a model: an
alert says what the Story says and nothing more, so there is nothing to check against the Story.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from papyrus_content.newsletter.confirmation import markus_text

MAXIMUM_PARAGRAPH_CHARACTERS = 600
#: A block that starts like this is structure (a heading, list, quote, table, code, image, directive), not a paragraph of prose.
STRUCTURE = re.compile(r"^\s*(?:[#>|`!:<{@~$\[\]*+=_-]|\d+[.)]\s)", re.MULTILINE)


def _names(values: Any) -> set[str]:
    items = [values] if isinstance(values, str) else list(values or [])
    return {str(value).strip().lower() for value in items if str(value).strip()}


def rule_matches(rule: Mapping[str, Any] | None, *, section: str | None, tags: Any, item_type: str | None) -> bool:
    """OR within a field, AND across the fields present. No rule (or an empty one) matches every item."""
    rule = rule or {}
    for field, actual in (("sections", section), ("tags", tags), ("types", item_type)):
        wanted = _names(rule.get(field))
        if wanted and not wanted & _names(actual):
            return False
    return True


def tags_of(front_matter: Mapping[str, Any]) -> list[str]:
    raw = front_matter.get("tags")
    values = raw.split(",") if isinstance(raw, str) else raw if isinstance(raw, list) else []
    return [str(value).strip() for value in values if str(value).strip()]


def first_paragraph(markus: Any) -> str:
    """The first block of plain prose in the body as one line, or ``""``. Lists, headings, quotes, tables and code are skipped."""
    if not isinstance(markus, str):
        return ""
    for block in re.split(r"\n\s*\n", markus.strip()):
        if not block.strip() or STRUCTURE.search(block):
            continue
        text = " ".join(block.split())
        if len(text) <= MAXIMUM_PARAGRAPH_CHARACTERS:
            return text
        clipped = text[:MAXIMUM_PARAGRAPH_CHARACTERS]
        cut = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
        return clipped[: cut + 1] if cut > 80 else ""
    return ""


def alert_body(site_name: str, title: str, url: str, dek: str, paragraph: str) -> str:
    """Markus: the title as a link, the dek, the first paragraph, then a "Read it on <site>" link."""
    lines = [f"## [{markus_text(title)}]({url})", ""]
    if dek:
        lines += [markus_text(dek), ""]
    if paragraph:
        lines += [paragraph, ""]
    lines += [f"[Read it on {markus_text(site_name)}]({url})", ""]
    return "\n".join(lines)


def alert_drafter(story_of: Callable[[str], Any], origin: Callable[[], str]) -> Callable[[Sequence[Any], Sequence[Any], Sequence[Any]], str]:
    """The drafter of the every-item email (``announce.Drafter``). ``story_of(lineage)`` gives the Story's facts (``eligibility.StoryFacts``) and ``origin()`` the site's
    public address; the site's name in "Read it on" is that address's host."""

    def draft(_lists: Sequence[Any], candidates: Sequence[Any], _notes: Sequence[Any]) -> str:
        (candidate,) = candidates   # an every-item email is about one Story
        story = story_of(candidate.story.lineage_id)
        base = origin().rstrip("/")
        return alert_body(urlsplit(base).netloc or base, story.title, base + story.path, story.dek, first_paragraph(story.body))

    return draft


LINK_LINE = re.compile(r"^## \[(?P<title>.*)\]\((?P<url>[^)]+)\)\s*$")


def alert_facts(_row: Mapping[str, Any], text: str) -> dict[str, str]:
    """What Caducus's ``story.published`` event says, read back from the alert's Markus body (``alert_body``): the title and its link, and the dek or first paragraph
    as the summary. This is ``CaducusEmail``'s ``facts_of`` for an every-item alert."""
    blocks = [block for block in re.split(r"\n\s*\n", text.strip()) if block.strip()]
    found = LINK_LINE.match(blocks[0].strip()) if blocks else None
    if found is None:
        raise ValueError("an alert's words begin with the Story's title as a link")
    facts = {"title": re.sub(r"\\(.)", r"\1", found["title"]), "url": found["url"]}
    if len(blocks) > 2:   # the title, the words, and the "Read it on" link
        facts["summary"] = re.sub(r"\\(.)", r"\1", " ".join(blocks[1].split()))
    return facts
