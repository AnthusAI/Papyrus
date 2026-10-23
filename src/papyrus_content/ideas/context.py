"""What synthesis reads besides the digest: the site's mission and policy, its sections, and its recent and in-flight stories."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..newsroom_doctrine import DOCTRINE_DEFINITION_BY_KIND
from ..tenancy import rows_for_tenant
from .digest import CORPUS_PREFIX, corpus_key, parse_time

STORY_TYPES = {"article", "story"}
IN_FLIGHT_STATUSES = {"draft", "review", "in_review", "scheduled"}
STORY_DAYS = 90
STORY_FIELDS = "id lineageId versionState type status stage section title deck headline publishedAt updatedAt tenantId"
STORIES_QUERY = f"""
query ListStories($limit: Int, $nextToken: String) {{
  listItems(limit: $limit, nextToken: $nextToken) {{
    items {{ {STORY_FIELDS} }}
    nextToken
  }}
}}
"""


def hosted_corpora(client: Any) -> list[dict[str, Any]]:
    return [row for row in client.list_records("KnowledgeCorpus") if str(row.get("id") or "").startswith(CORPUS_PREFIX)]


def corpus_ids_for(corpora: list[dict[str, Any]], publication: str) -> list[str]:
    """The corpus ids of the asked-for publication; an operator error that lists the real keys when none matches."""
    matching = [row["id"] for row in corpora if corpus_key(row["id"]) == publication]
    if not matching:
        keys = ", ".join(sorted(corpus_key(row["id"]) for row in corpora)) or "none"
        raise ValueError(f"This backend has no publication {publication!r}. Its knowledge corpora are: {keys}.")
    return matching


def _text(record: dict[str, Any]) -> str:
    if record.get("bodyMarkus"):
        return str(record["bodyMarkus"]).strip()
    body = record.get("body") or []
    if isinstance(body, str):
        return body.strip()
    return "\n\n".join(str(part).strip() for part in body if str(part).strip())


def doctrine_texts(client: Any) -> dict[str, str | None]:
    """The current private mission and policy, or None for a kind the site has not written."""
    found: dict[str, str | None] = {}
    for kind, definition in DOCTRINE_DEFINITION_BY_KIND.items():
        rows = [
            row for row in client.list_by_index("itemBySlug", definition["slug"])
            if row.get("type") == "doctrine" and row.get("status") == "private" and row.get("versionState") == "current"
        ]
        found[kind] = _text(rows[0]) or None if rows else None
    return found


def list_stories(client: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    token = None
    while True:
        page = client.graphql(STORIES_QUERY, {"limit": 100, "nextToken": token}).get("listItems") or {}
        items.extend(row for row in page.get("items") or [] if row)
        token = page.get("nextToken")
        if not token:
            break
    return rows_for_tenant("Item", getattr(client, "tenant_id", None), items)


def story_entry(row: dict[str, Any]) -> dict[str, Any]:
    published = row.get("status") == "published"
    moment = row.get("publishedAt") if published else row.get("updatedAt")
    return {
        "id": row.get("lineageId") or row["id"],
        "title": str(row.get("title") or row.get("headline") or "").strip(),
        "summary": str(row.get("deck") or "").strip() or None,
        "section": row.get("section"),
        "state": "published" if published else (row.get("stage") or row.get("status") or "draft"),
        "date": (moment or "")[:10] or None,
    }


def sections_for(client: Any, stories: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The site's enabled newsroom sections; a site with none uses the sections its stories already sit in."""
    rows = [row for row in client.list_records("NewsroomSection") if row.get("enabled") is not False]
    if rows:
        return sorted(({"id": row["id"], "title": str(row.get("title") or row["id"])} for row in rows), key=lambda row: row["title"])
    names = sorted({str(story["section"]) for story in stories if story.get("section")})
    return [{"id": name, "title": name} for name in names]


def load_context(client: Any, *, now: datetime, story_days: int = STORY_DAYS) -> dict[str, Any]:
    rows = [row for row in list_stories(client) if row.get("versionState") == "current" and row.get("type") in STORY_TYPES]
    all_stories = [story_entry(row) for row in rows]
    cutoff = now - timedelta(days=story_days)
    stories = [
        story for story in all_stories
        if story["title"]
        and (story["state"] != "published" or (parse_time(story["date"]) or cutoff) >= cutoff)
    ]
    stories.sort(key=lambda story: (story["date"] or "", story["title"]), reverse=True)
    doctrine = doctrine_texts(client)
    return {
        "mission": doctrine.get("mission"),
        "policy": doctrine.get("policy"),
        "sections": sections_for(client, all_stories),
        "stories": stories,
        "storyDays": story_days,
    }
