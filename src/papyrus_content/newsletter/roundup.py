"""Assembling a roundup draft: the items published since the last sent issue, grouped by section, as a Markus Item.

No LLM. The draft is an ``Item`` of the list's ``issueType`` in the list's archive section (so the editor writes it in the
newsroom editor), plus an ``ISSUE#`` row. One draft per list and ISO week: ``ROUNDUP#<listId>`` / ``PERIOD#<yyyy-ww>``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from papyrus_content.item_front_matter import front_matter as _front_matter, item_path
from papyrus_content.item_language import localization_original
from papyrus_content.item_stars import effective_rating
from papyrus_content.publishing import ItemFields, save_item

from .confirmation import markus_text
from .issues import IssueService, log, new_issue_id, new_issue_row
from .selection import Candidate, Selection, eligible_at, select
from .store import _ser, iso

INTRO_PLACEHOLDER = "Write a short introduction for this issue here, then delete this line."
DEK_FIELDS = ("description", "summary", "excerpt", "blurb", "dek", "deck", "standfirst")
OTHER_SECTION = "More"
LEFT_OUT_HEADING = "Left out"
LEFT_OUT_NOTE = "These are not in this issue, each for the reason shown. Delete this section before sending."
FLOOR_NOTE = " The site's floor of {floor} stars applies."


def archive_section(archive_path: str) -> str:
    """The Item section (and the ``urls.sections`` key) of a list's archive: ``/roundup/`` is ``roundup``."""
    return archive_path.strip("/")


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


def period_start(moment: datetime) -> float:
    """The start of the list's current period: Monday 00:00 of the ISO week of ``moment`` in its own zone."""
    monday = (moment - timedelta(days=moment.isoweekday() - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.timestamp()


def sent_issues(service: IssueService, list_id: str) -> list[dict[str, Any]]:
    return [row for row in service.issues.list_all() if row.get("listId") == list_id and row.get("status") == "sent"]


def window_start(service: IssueService, list_id: str, now: float, zone: ZoneInfo) -> float:
    """The end of the list's last sent issue, else the start of the first period. No number of days is configured anywhere."""
    sent = [_epoch(row.get("sentAt")) for row in sent_issues(service, list_id)]
    latest = max((value for value in sent if value is not None), default=None)
    return latest if latest is not None else period_start(datetime.fromtimestamp(now, tz=zone))


def issue_types(settings: Any) -> set[str]:
    return {entry["issueType"] for entry in settings.lists if entry.get("kind") == "roundup" and entry.get("issueType")}


def declared_types(entry: Mapping[str, Any]) -> list[str]:
    """The Story types a roundup list carries. There is no default of everything: a list that declares none cannot assemble."""
    types = entry.get("types")
    if not isinstance(types, list) or not types or not all(isinstance(name, str) and name for name in types):
        raise ValueError(f"The roundup list {entry.get('id')} must declare the Story types it carries, for example \"types\": [\"article\"].")
    return types


def head_version(content: Any, row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The current published version of the Story a published row belongs to."""
    lineage = row.get("itemLineageId")
    if not lineage:
        return None
    return next((version for version in content.list_by_index("itemsByLineageAndVersion", lineage) if version.get("versionState") == "current" and version.get("stage") == "published"), None)


def stars_of(content: Any, row: Mapping[str, Any]) -> int:
    """The effective human rating (0: unrated) on the current published version of the Story a published row belongs to."""
    return int(effective_rating(head_version(content, row))["stars"])


def candidates(service: IssueService, group_of: Callable[[Mapping[str, Any]], str | None] = lambda _row: None) -> list[Candidate]:
    """Every published Story of the site that is not an issue or a translation, with its rating and when it became eligible. With no floor no rating is read."""
    excluded = issue_types(service.settings)
    floor = service.settings.floor_stars
    found = []
    for row in service.content.list_published_item_summaries():
        published = _epoch(row.get("publishedAt"))
        if published is None or row.get("type") in excluded or localization_original(row) is not None:
            continue   # a translation is not a Story of its own: the roundup names the original
        head = head_version(service.content, row) if floor is not None else None
        stars = int(effective_rating(head)["stars"])
        found.append(Candidate(row, stars, published, eligible_at(published, _epoch((head or {}).get("starRatedAt")), stars, floor), group_of(row)))
    return found


def select_for(service: IssueService, entry: Mapping[str, Any], since: float, until: float) -> Selection:
    """What the list's next issue holds: the standing rules over the site's Stories, minus what earlier sent issues of the list already carried."""
    pool = candidates(service)
    sent = sent_issues(service, entry["id"])
    sent_ids = {item_id for row in sent for item_id in row.get("entryIds", ())}
    sent_groups = {candidate.group for candidate in pool if candidate.id in sent_ids and candidate.group is not None}
    return select(pool, types=declared_types(entry), floor=service.settings.floor_stars, since=since, until=until, sent_ids=sent_ids, sent_groups=sent_groups)


def section_heading(section: str | None) -> str:
    """A section name as a heading: ``security-notes`` becomes ``Security Notes`` (names with capitals are kept)."""
    if not section:
        return OTHER_SECTION
    words = section.replace("-", " ").replace("_", " ").replace("/", " ").split()
    return " ".join(word.capitalize() if word.islower() else word for word in words) or OTHER_SECTION


def _item_line(settings: Any, row: Mapping[str, Any]) -> str:
    front_matter = _front_matter(row)
    title = " ".join(str(row.get("title") or front_matter.get("title") or str(row.get("slug") or "")).split())
    url = settings.site_origin.rstrip("/") + item_path(row.get("section") or None, str(row.get("slug") or ""), settings.item_url_style)
    dek = _dek(front_matter)
    return f"- [{markus_text(title)}]({url})" + (f": {markus_text(dek)}" if dek else "")


def draft_body(settings: Any, selection: Selection) -> str:
    """Markus: an intro placeholder line, then the selected items by section slot, in the shared quality order. What the rules left out follows under its own heading with
    the reason on each line, which the editor deletes before sending: a person sees what was refused and why, and a reader never gets it unless an editor moves it."""
    lines = [INTRO_PLACEHOLDER, ""]
    for section, slot in selection.included.items():
        lines += [f"## {markus_text(section_heading(section))}", ""]
        lines += [_item_line(settings, candidate.row) for candidate in slot]
        lines.append("")
    if selection.left_out:
        note = LEFT_OUT_NOTE + (FLOOR_NOTE.format(floor=settings.floor_stars) if settings.floor_stars is not None else "")
        lines += [f"## {LEFT_OUT_HEADING}", "", note, ""]
        lines += [f"{_item_line(settings, left.candidate.row)} ({markus_text(left.reason)})" for left in selection.left_out]
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
    since = window_start(service, entry["id"], now, zone)
    selection = select_for(service, entry, since, now)
    if not selection.count and not manual:
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
        body_markus=draft_body(settings, selection),
        aliases=[],
        id=item_id,
    )
    save_item(service.content, fields, actor=actor)
    row = new_issue_row(issue_id, list_id=entry["id"], kind="roundup", subject=title, now=now, item_id=item_id)
    row["entryIds"] = [candidate.id for slot in selection.included.values() for candidate in slot]   # what this issue carries, so a later issue never offers it again
    created = service.issues.create(row)
    log("roundup_drafted", issue_id, listId=entry["id"], items=selection.count, manual=manual)
    return {"status": "created" if created else "exists", "issueId": issue_id, "itemId": item_id, "items": selection.count}


def _free_item_id(service: IssueService, section: str, slug: str, *, unique: bool) -> tuple[str, str]:
    """The Item id and slug for a dated issue. A manual draft never overwrites an earlier one of the same day."""
    from papyrus_content.publishing import item_id_for

    candidate, suffix = slug, 1
    while unique and service.content.get_record("Item", item_id_for(section, candidate)) is not None:
        suffix += 1
        candidate = f"{slug}-{suffix}"
    return item_id_for(section, candidate), candidate
