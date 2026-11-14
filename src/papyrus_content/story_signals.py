"""The signals the layouts order Stories by, as the Story commands and MCP tools name them: ``bucket``, ``stars`` (the effective quality rating),
``section`` and ``type``, then newest first.

``stories list --sort rank`` is the order the Articles and Posts pages show: it calls ``rank_entries`` (``projection/standard/story_order.py``), the code the
projection runs, over the same signals (the Story's date, its rating, the site's bucket). It does not reimplement the ranking. The ratings are
read from the Item rows ``stories list`` already reads (the rating lives on the current version row), so a list costs no request per Story and no read
of the private rating map. Ratings are private newsroom data: nothing here writes to a published row, a projection or a feed.

The CLI (``story_commands.py``) and the MCP tools (``story_signals_mcp.py``) both call the functions here, so they share one vocabulary.
Not exposed yet: the Cyclotron prediction and confidence (a Reference signal, not a Story one), tags, and the listing ``featuredCount``.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any

from .home_page.ordering import rolling_age, utc_today
from .item_stars import effective_rating
from .options import normalize_string

SORTS = ("updated", "stars", "rank")
MINIMUM_STARS, MAXIMUM_STARS = 0, 5
UNDATED = "undated"
OLDEST_WINDOW = 2**31


def validated_stars(value: Any, label: str = "--stars") -> int:
    """A whole number from 0 (unrated; clears when setting) to 5, else a plain error."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        number = None
    if number is None or not MINIMUM_STARS <= number <= MAXIMUM_STARS:
        raise ValueError(f"{label} must be a whole number from {MINIMUM_STARS} to {MAXIMUM_STARS} (0 means unrated, and clears a rating when you set it); got {value!r}.")
    return number


def _front_matter_date(item: dict) -> str:
    metadata = item.get("metadata")
    try:
        metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
        import yaml

        from .projection.standard.entries import calendar_date

        return calendar_date((yaml.safe_load(metadata.get("frontMatterYaml") or "") or {}).get("date"))
    except Exception:  # an unreadable date means "no date", never a failed list
        return ""


def story_moment(item: dict) -> str:
    """The date a Story is bucketed and ordered by, as the page does: its front-matter date, else when it was published; empty when it has neither."""
    from .projection.standard.entries import calendar_date

    return _front_matter_date(item) or calendar_date(item.get("publishedAt"))


def signals(item: dict, bucket: str, as_of: date) -> dict[str, Any]:
    """One Story's signals: type, section, bucket (``week:0`` is the last seven days, ``week:1`` the seven before; ``none``; ``undated``), the effective
    rating (stars, source, votes), word count, and the last-published date."""
    moment = story_moment(item)
    age = rolling_age(moment, bucket, as_of) if moment and bucket != "none" else None
    return {
        "lineageId": item.get("lineageId") or item["id"], "stage": item.get("stage") or "", "section": item.get("section") or "", "type": item.get("type") or "",
        "title": item.get("headline") or item.get("title") or "", **effective_rating(item),
        "bucket": "none" if bucket == "none" else (UNDATED if age is None else f"{bucket}:{age}"),
        "words": len((item.get("bodyMarkus") or "").split()), "published": str(item.get("publishedAt") or ""), "date": moment,
        "ratedBy": item.get("starRatedBy") or "", "ratedAt": item.get("starRatedAt") or "", "updatedAt": str(item.get("updatedAt") or ""),
    }


def list_stories(client, *, stage: str | None = None, section: str | None = None, story_type: str | None = None, stars: int | None = None,
                 min_stars: int | None = None, max_stars: int | None = None, sort: str = "updated", bucket: str | None = None,
                 limit: int = 50, as_of: date | None = None) -> tuple[list[dict], int]:
    """``(rows, total)``: Stories (each one's newest version that is not superseded: current or draft) with their signals. ``stars`` 0 finds unrated Stories; ``min_stars``/``max_stars`` match rated ones only."""
    from .content_item_lifecycle import CONTENT_ITEM_STAGES, SYSTEM_ITEM_TYPES, require_content_item_stage
    from .editorial_context import find_section
    from .projection.standard.config import DEFAULT_STORY_BUCKET, STORY_BUCKETS
    from .projection.standard.story_order import rank_entries

    if sort not in SORTS:
        raise ValueError(f"--sort must be one of {', '.join(SORTS)}; got {sort!r}.")
    bucket = bucket or DEFAULT_STORY_BUCKET
    if bucket not in STORY_BUCKETS:
        raise ValueError(f"--bucket must be one of {', '.join(STORY_BUCKETS)}; got {bucket!r}.")
    if stage:
        require_content_item_stage(stage)
    stages = [stage] if stage else [name for name in CONTENT_ITEM_STAGES if name not in ("held", "spiked")]
    section_id = None
    if section:
        found = find_section(client, section)
        if not found:
            raise ValueError(f"Unknown NewsroomSection {section}.")
        section_id = found["id"]
    rows = []
    for name in stages:
        rows += client.list_by_index("itemsByStage", name)
    # The Story's head is its newest row that is not superseded: `current` once it has been published, `draft` until then (every Story filed from the CLI or
    # the console starts as a draft). The Stories board filters the same way (`boardStoryFilter`), so the list and the board agree.
    rows = [row for row in rows if row.get("versionState", "current") != "superseded" and row.get("type") not in SYSTEM_ITEM_TYPES
            and (section_id is None or row.get("section") == section_id) and (not story_type or row.get("type") == story_type)]
    found_items = client.get_records_by_id("Item", [row["id"] for row in rows])   # one batched read; the rating is on these rows
    heads: dict[str, dict] = {}
    for row in rows:   # one row per Story: a draft saved over a published version leaves two rows that are not superseded; the higher version is the head
        item = found_items.get(row["id"])
        lineage = row.get("lineageId") or row["id"]
        if item and int(item.get("versionNumber") or 0) >= int((heads.get(lineage) or {}).get("versionNumber") or -1):
            heads[lineage] = item
    day = as_of or utc_today()
    stories = [signals(item, bucket, day) for item in heads.values()]
    if stars is not None:
        stories = [story for story in stories if story["stars"] == stars]
    if min_stars is not None:
        stories = [story for story in stories if story["stars"] and story["stars"] >= min_stars]
    if max_stars is not None:
        stories = [story for story in stories if story["stars"] and story["stars"] <= max_stars]
    stories.sort(key=lambda story: story["updatedAt"], reverse=True)
    if sort == "stars":
        stories.sort(key=lambda story: story["stars"] or -1, reverse=True)   # stable: equal ratings stay newest change first; unrated last
    elif sort == "rank":
        stories.sort(key=lambda story: story["date"], reverse=True)   # the page's input: newest first
        entries = [SimpleNamespace(summary=SimpleNamespace(lineage_id=story["lineageId"]), date=story["date"], story=story) for story in stories]
        rated = {story["lineageId"]: story["stars"] for story in stories if story["stars"]}
        stories = [entry.story for entry in rank_entries(entries, rated, bucket, day)]
    return stories[:max(limit, 1)], len(stories)


def set_story_stars(client, lineage_id: str, stars: int, *, apply: bool, agent: str | None = None) -> dict[str, Any]:
    """Sets the EDITOR's rating (0 clears) through ``setItemStars``, the newsroom mutation the editors call: it also tells the site to re-render the listing
    pages whose order changed. Returns ``{lineageId, previous, stars, applied}``. The effective rating can differ from the editor's value once votes aggregate."""
    from .story_reporting import current_story_version

    stars = validated_stars(stars)
    current = current_story_version(client, lineage_id)
    result = {"lineageId": lineage_id, "previous": effective_rating(current)["stars"], "stars": stars, "applied": False, "setting": "editor value"}
    if not apply:
        return result
    data = client.graphql(SET_ITEM_STARS_MUTATION, {"itemId": current["id"], "stars": stars or None, "agentLabel": agent or None})
    if not (data.get("setItemStars") or {}).get("ok"):
        raise ValueError(f"The newsroom did not confirm the rating of {lineage_id}.")
    result["applied"] = True
    return result


SET_ITEM_STARS_MUTATION = """
mutation SetItemStars($itemId: ID!, $stars: Int, $agentLabel: String) {
  setItemStars(itemId: $itemId, stars: $stars, agentLabel: $agentLabel) {
    ok
    itemId
    lineageId
    stars
  }
}
"""


def optional_stars(options: dict, name: str) -> int | None:
    value = normalize_string(options.get(name))
    return None if value is None else validated_stars(value, f"--{name}")
