"""The link rule for a newsletter slot's blurb (PPY-cb3cc9): any link in it must point at the site's own Story page for that slot, or appear in that Story.

A blurb is the machine's or an editor's words for one entry. A link that is neither is an invented address in a mail that goes to subscribers, so the save is refused
naming each one.
"""

from __future__ import annotations

import re
from collections.abc import Collection

LINK = re.compile(r"""\]\(\s*<?([^)\s>]+)|https?://[^\s<>)\]"']+|\bwww\.[^\s<>)\]"']+""", re.IGNORECASE)


def _normal(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip(), flags=re.IGNORECASE).rstrip("/.,;:").lower()


def links_in(text: str) -> list[str]:
    """Every address the text carries, as written, in order and without repeats: Markdown link targets and bare addresses."""
    found: list[str] = []
    for match in LINK.finditer(text):
        url = match.group(1) or match.group(0)
        if url not in found:
            found.append(url)
    return found


def link_problems(blurb: str, *, story_url: str, story_text: str = "", story_links: Collection[str] = ()) -> list[str]:
    """One plain sentence for each link in ``blurb`` that is not the slot's own Story page (``story_url``) and does not appear in the Story (its text or ``story_links``)."""
    allowed = {_normal(story_url)} | {_normal(url) for url in story_links} | {_normal(url) for url in links_in(story_text)}
    return [f"The link {url} is neither this Story's page nor in the Story" for url in links_in(blurb) if _normal(url) not in allowed]
