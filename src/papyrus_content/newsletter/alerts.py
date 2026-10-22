"""Publish-triggered alerts: the ``item-published`` task (PPY-d415c0).

The site's content-actions function invokes the newsletter function once per real publish. For every alert list whose rule
matches the published item, this takes a dedupe row (``ALERT#<listId>`` / ``ITEM#<lineageId>``, kept for good, so a
republish, an edit or a repeated event never alerts twice) and writes an alert issue. The issue has no Item and no archive:
its subject, Markus body and preheader live on the ``ISSUE#`` row. Unless the list is allowed to send instantly
(``approval`` "none" on a site with ``instantAlerts``) it waits as ``awaiting_approval`` for an admin.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from papyrus_content.publishing import PUBLISHED_ID_PREFIX

from .compose import IssueSource, content_hash, one_line, render
from .confirmation import markus_text
from .issues import IssueService, log, new_issue_id, new_issue_row
from .roundup import _dek, _front_matter, issue_types, item_path
from .store import _ser, iso

SYSTEM_ACTOR = "system:instant-alert"
LINEAGE = re.compile(r"[A-Za-z0-9._:-]{1,200}")
MAXIMUM_PARAGRAPH_CHARACTERS = 600
MAXIMUM_PREHEADER_CHARACTERS = 200
#: A block that starts like this is structure (a heading, list, quote, table, code, image, directive), not a paragraph of prose.
STRUCTURE = re.compile(r"^\s*(?:[#>|`!:<{@~$\[\]*+=_-]|\d+[.)]\s)", re.MULTILINE)


def dedupe_key(list_id: str, lineage_id: str) -> dict[str, str]:
    return {"pk": f"ALERT#{list_id}", "sk": f"ITEM#{lineage_id}"}


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


class PublishedItemSummary:
    """What an alert needs from the published item."""

    def __init__(self, row: Mapping[str, Any], settings: Any) -> None:
        front_matter = _front_matter(row)
        self.section = row.get("section") or None
        self.item_type = row.get("type")
        self.tags = tags_of(front_matter)
        slug = str(row.get("slug") or "")
        self.title = one_line(str(row.get("title") or row.get("headline") or front_matter.get("title") or slug))
        self.dek = one_line(str(row.get("deck") or "")) or _dek(front_matter)
        self.url = settings.site_origin.rstrip("/") + item_path(self.section, slug, settings.item_url_style)
        self.paragraph = first_paragraph(row.get("bodyMarkus"))


def _claim(service: IssueService, list_id: str, lineage_id: str, issue_id: str, now: float) -> str | None:
    """Take the dedupe row. Returns the issue id to create, or None when that alert exists already.

    A row whose issue never got written (a crash between the two writes) is finished, not skipped.
    """
    key = dedupe_key(list_id, lineage_id)
    client, table = service.issues.client, service.issues.table
    try:
        client.put_item(TableName=table, Item=_ser({**key, "issueId": issue_id, "at": iso(now)}), ConditionExpression="attribute_not_exists(pk)")
        return issue_id
    except client.exceptions.ConditionalCheckFailedException:
        pass
    earlier = client.get_item(TableName=table, Key=_ser(key), ConsistentRead=True)["Item"]["issueId"]["S"]
    return None if service.issues.get(earlier) is not None else earlier


def _source(service: IssueService, entry: Mapping[str, Any], summary: PublishedItemSummary) -> tuple[IssueSource, str]:
    """The body, with the first paragraph only if the whole alert still renders with it (it is raw Markus from another page)."""
    site_name = service.settings.from_name
    preheader = summary.dek[:MAXIMUM_PREHEADER_CHARACTERS]
    for paragraph in (summary.paragraph, ""):
        body = alert_body(site_name, summary.title, summary.url, summary.dek, paragraph)
        source = IssueSource(subject=summary.title, markus=body, preheader=preheader)
        try:
            render(service.settings, entry["name"], source, "Postal address placeholder", kind="alert")
        except Exception:  # noqa: BLE001 - retry without the paragraph; an unrenderable alert is left for the admin to see
            continue
        return source, paragraph
    return IssueSource(subject=summary.title, markus=alert_body(site_name, summary.title, summary.url, summary.dek, ""), preheader=preheader), ""


def _create(service: IssueService, entry: Mapping[str, Any], issue_id: str, source_item_id: str, lineage_id: str, summary: PublishedItemSummary) -> dict[str, Any]:
    now = service.clock()
    source, _paragraph = _source(service, entry, summary)
    row = new_issue_row(
        issue_id, list_id=entry["id"], kind="alert", subject=source.subject, now=now, source_item_id=source_item_id,
        status="awaiting_approval",
    )
    row.update(lineageId=lineage_id, bodyMarkus=source.markus, preheader=source.preheader)
    service.issues.create(row)
    log("alert_raised", issue_id, listId=entry["id"])
    instant = entry.get("approval") == "none" and bool(service.settings.instant_alerts)
    if not instant:
        return {"listId": entry["id"], "issueId": issue_id, "status": "awaiting_approval"}
    return {"listId": entry["id"], "issueId": issue_id, **_send_now(service, issue_id, source, now)}


def _send_now(service: IssueService, issue_id: str, source: IssueSource, now: float) -> dict[str, Any]:
    """Approve as the system actor and start the send. The start-send guards (hash, postal address, site paused) all still run."""
    from .send import start_send

    approved = service.issues.update(
        issue_id,
        {
            "status": "scheduled",
            "contentHash": content_hash(source.subject, source.markus),
            "approvedBy": SYSTEM_ACTOR,
            "approvedAt": iso(now),
            "sendAt": iso(now),
        },
        expect="awaiting_approval",
    )
    if not approved:
        return {"status": "awaiting_approval"}
    log("alert_approved", issue_id, by="system")
    return {"status": start_send(service, issue_id)["status"], "instant": True}


def raise_alerts(service: IssueService, event: Mapping[str, Any]) -> dict[str, Any]:
    """The ``item-published`` task. Raises after trying every list when one failed, so Lambda's retry finishes the rest (the dedupe row makes that safe)."""
    lineage_id = event.get("lineageId")
    item_id = event.get("itemId")
    if not isinstance(lineage_id, str) or not LINEAGE.fullmatch(lineage_id) or not isinstance(item_id, str):
        return {"status": "ignored", "reason": "bad_event"}
    alert_lists = [entry for entry in service.settings.lists if entry.get("kind") == "alert"]
    if not alert_lists:
        return {"status": "ignored", "reason": "no_alert_lists"}
    published_id = event.get("publishedItemId")
    if not isinstance(published_id, str) or not published_id:
        published_id = PUBLISHED_ID_PREFIX + lineage_id
    row = service.content.get_record("PublishedItem", published_id)
    if row is None or row.get("status") not in (None, "published"):
        return {"status": "ignored", "reason": "not_published"}
    if row.get("type") in issue_types(service.settings):
        return {"status": "ignored", "reason": "issue_type"}
    summary = PublishedItemSummary(row, service.settings)
    created: list[dict[str, Any]] = []
    failure: Exception | None = None
    for entry in alert_lists:
        if not rule_matches(entry.get("rule"), section=summary.section, tags=summary.tags, item_type=summary.item_type):
            continue
        try:
            issue_id = _claim(service, entry["id"], lineage_id, new_issue_id(), service.clock())
            if issue_id is None:
                continue
            created.append(_create(service, entry, issue_id, item_id, lineage_id, summary))
        except Exception as error:  # noqa: BLE001 - the other lists still get their alert; the retry finishes this one
            log("alert_failed", "-", listId=entry["id"], error=type(error).__name__)
            failure = failure or error
    if failure is not None:
        raise failure
    return {"status": "done", "alerts": created}
