"""Assembling a roundup draft: the items published since the last sent issue, grouped by section, as a Markus Item.

No LLM. The draft is an ``Item`` of the list's ``issueType`` in the list's archive section (so the editor writes it in the
newsroom editor), plus an ``ISSUE#`` row. One draft per list and ISO week: ``ROUNDUP#<listId>`` / ``PERIOD#<yyyy-ww>``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from papyrus_content.publishing import ItemFields, save_item

from .confirmation import markus_text
from .issues import IssueService, log, new_issue_id, new_issue_row
from .store import _ser, iso

DEFAULT_WINDOW_SECONDS = 7 * 24 * 60 * 60
INTRO_PLACEHOLDER = "Write a short introduction for this issue here, then delete this line."
DEK_FIELDS = ("description", "summary", "excerpt", "blurb", "dek", "deck", "standfirst")
OTHER_SECTION = "More"


def archive_section(archive_path: str) -> str:
    """The Item section (and the ``urls.sections`` key) of a list's archive: ``/roundup/`` is ``roundup``."""
    return archive_path.strip("/")


def item_path(section: str | None, slug: str, url_style: str) -> str:
    base = f"/{section}" if section else ""
    if url_style == "directory":
        return f"{base}/{slug}/"
    if url_style == "clean":
        return f"{base}/{slug}"
    return f"{base}/{slug}.html"


def _parse_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _front_matter(row: Mapping[str, Any]) -> dict[str, Any]:
    text = _parse_object(row.get("metadata")).get("frontMatterYaml")
    if not isinstance(text, str) or not text.strip():
        return {}
    import yaml

    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _dek(front_matter: Mapping[str, Any]) -> str:
    for name in DEK_FIELDS:
        value = front_matter.get(name)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _epoch(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp()


def window_start(service: IssueService, list_id: str, now: float) -> float:
    """The end of the list's last sent issue, else seven days ago."""
    sent = [_epoch(row.get("sentAt")) for row in service.issues.list_all() if row.get("listId") == list_id and row.get("status") == "sent"]
    latest = max((value for value in sent if value is not None), default=None)
    return latest if latest is not None else now - DEFAULT_WINDOW_SECONDS


def issue_types(settings: Any) -> set[str]:
    return {entry["issueType"] for entry in settings.lists if entry.get("kind") == "roundup" and entry.get("issueType")}


def items_in_window(service: IssueService, since: float, until: float) -> list[dict[str, Any]]:
    """Published, non-issue items published after ``since`` and up to ``until``, oldest first."""
    excluded = issue_types(service.settings)
    chosen = []
    for row in service.content.list_published_item_summaries():
        published = _epoch(row.get("publishedAt"))
        if published is None or not since < published <= until:
            continue
        if row.get("status") not in (None, "published") or row.get("type") in excluded:
            continue
        chosen.append((published, row))
    chosen.sort(key=lambda pair: (pair[0], str(pair[1].get("slug"))))
    return [row for _published, row in chosen]


def section_heading(section: str | None) -> str:
    """A section name as a heading: ``security-notes`` becomes ``Security Notes`` (names with capitals are kept)."""
    if not section:
        return OTHER_SECTION
    words = section.replace("-", " ").replace("_", " ").replace("/", " ").split()
    return " ".join(word.capitalize() if word.islower() else word for word in words) or OTHER_SECTION


def draft_body(settings: Any, rows: list[dict[str, Any]]) -> str:
    """Markus: an intro placeholder line, then the items grouped by section (alphabetical, unsectioned last)."""
    groups: dict[str | None, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row.get("section") or None, []).append(row)
    lines = [INTRO_PLACEHOLDER, ""]
    for section in sorted(groups, key=lambda name: (name is None, name or "")):
        lines += [f"## {markus_text(section_heading(section))}", ""]
        for row in groups[section]:
            front_matter = _front_matter(row)
            title = " ".join(str(row.get("title") or front_matter.get("title") or str(row.get("slug") or "")).split())
            url = settings.site_origin.rstrip("/") + item_path(section, str(row.get("slug") or ""), settings.item_url_style)
            dek = _dek(front_matter)
            lines.append(f"- [{markus_text(title)}]({url})" + (f": {markus_text(dek)}" if dek else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def date_range(start: float, end: float, zone: ZoneInfo) -> str:
    first, last = datetime.fromtimestamp(start, tz=zone), datetime.fromtimestamp(end, tz=zone)
    left = f"{first:%b} {first.day}" + (f", {first.year}" if first.year != last.year else "")
    return f"{left} to {last:%b} {last.day}, {last.year}"


def period_key(moment: datetime) -> str:
    year, week, _day = moment.isocalendar()
    return f"{year}-{week:02d}"


def _claim_period(service: IssueService, list_id: str, period: str, issue_id: str, now: float) -> str | None:
    """Claim the week. Returns the issue id to create, or None when that issue is complete already."""
    key = {"pk": f"ROUNDUP#{list_id}", "sk": f"PERIOD#{period}"}
    client, table = service.issues.client, service.issues.table
    try:
        client.put_item(
            TableName=table, Item=_ser({**key, "issueId": issue_id, "at": iso(now)}), ConditionExpression="attribute_not_exists(pk)"
        )
        return issue_id
    except client.exceptions.ConditionalCheckFailedException:
        pass
    existing = client.get_item(TableName=table, Key=_ser(key), ConsistentRead=True)["Item"]
    earlier = existing["issueId"]["S"]
    # A claim whose issue row never got written (a crash between the two writes) is finished, not skipped.
    return None if service.issues.get(earlier) is not None else earlier


def assemble(service: IssueService, entry: Mapping[str, Any], *, manual: bool, actor: str) -> dict[str, Any]:
    """Create the draft Item and its issue row. The scheduled run is idempotent per ISO week and does nothing for an empty window."""
    settings = service.settings
    now = service.clock()
    zone = ZoneInfo(entry.get("timezone") or "UTC")
    since = window_start(service, entry["id"], now)
    rows = items_in_window(service, since, now)
    if not rows and not manual:
        log("roundup_empty", "-", listId=entry["id"])
        return {"status": "empty"}
    issue_id = new_issue_id()
    if not manual:
        issue_id = _claim_period(service, entry["id"], period_key(datetime.fromtimestamp(now, tz=zone)), issue_id, now)  # type: ignore[assignment]
        if issue_id is None:
            return {"status": "exists"}
    title = f"{entry['name']}: {date_range(since, now, zone)}"
    section = archive_section(entry["archivePath"])
    local_date = datetime.fromtimestamp(now, tz=zone).date()
    item_id, slug = _free_item_id(service, section, local_date.isoformat(), unique=manual)
    fields = ItemFields(
        type=entry["issueType"],
        slug=slug,
        section=section,
        front_matter_yaml=f"title: {json.dumps(title)}\ndate: {local_date.isoformat()}\n",
        body_markus=draft_body(settings, rows),
        aliases=[],
        id=item_id,
    )
    save_item(service.content, fields, actor=actor)
    created = service.issues.create(new_issue_row(issue_id, list_id=entry["id"], kind="roundup", subject=title, now=now, item_id=item_id))
    log("roundup_drafted", issue_id, listId=entry["id"], items=len(rows), manual=manual)
    return {"status": "created" if created else "exists", "issueId": issue_id, "itemId": item_id, "items": len(rows)}


def _free_item_id(service: IssueService, section: str, slug: str, *, unique: bool) -> tuple[str, str]:
    """The Item id and slug for a dated issue. A manual draft never overwrites an earlier one of the same day."""
    from papyrus_content.publishing import item_id_for

    candidate, suffix = slug, 1
    while unique and service.content.get_record("Item", item_id_for(section, candidate)) is not None:
        suffix += 1
        candidate = f"{slug}-{suffix}"
    return item_id_for(section, candidate), candidate
