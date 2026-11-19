"""Convert the kept alert de-dup rows into Announcements (PPY-58d962).

Until PPY-e3bb2b a publish raised an alert for each alert list whose rule matched, and kept a row ``ALERT#<listId>`` / ``ITEM#<lineageId>`` (with the id of the alert
issue) so a Story never alerted a list twice. An alert is now the email Delivery of the Announcement whose once-only key is ``story-published:<lineage>``. This turns
each kept row into that decision, **keys only**:

* all the kept rows of one Story become one Announcement, ``story-published:<lineage>``, with one email Delivery whose audience is the lists that had a row;
* a Delivery whose alert issue went is ``sent`` (its attempt log has one entry naming the conversion), and its words are the issue's Markus body, which moves to the
  Delivery's text file in S3. Every attempt, send and reader of the old alert stays in the newsletter table's own issue row. A kept row whose alert never went (a
  cancelled or never-approved alert, or a row whose issue was never written) is converted to a ``withdrawn`` Delivery: the Story was decided, and it is not alerted now;
* the announce agent looks the Story up by its once-only key, finds the Announcement, and makes nothing, so nothing alerts twice.

Run it once per site; running it again finds every Announcement and changes nothing (the same once-only keys, the same Delivery ids). A Delivery that was left ``drafted``
by a crash between the two writes is finished by the next run, and it is made ``drafted`` first so that nothing can send it in between.

``python -m papyrus_content.announcements.alert_conversion plan|run [--dry-run]`` reads the site's newsletter table and writes through the signed-in client (the
environment is the announce agent's: ``PAPYRUS_TENANT_ID`` names the sending account).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from papyrus_content.newsletter.store import _de, _ser

from . import records
from .decisions import Announcements
from .deliveries import Plan
from .link_reads import StoryRef
from .records import ATTEMPT_SENT, DELIVERY_WITHDRAWN, DRAFTED, EMAIL, NONE, SENT

BY = "alert-conversion"
POLICY = "converted from the kept alert rows (PPY-58d962)"
ALERT_PREFIX, ITEM_PREFIX = "ALERT#", "ITEM#"
SENT_STATUS = "sent"


@dataclass(frozen=True)
class KeptRow:
    """One kept de-dup row: the list that was alerted, the Story, the alert issue and when the row was taken."""

    list_id: str
    lineage: str
    issue_id: str
    at: str


@dataclass(frozen=True)
class Conversion:
    """What one Story's kept rows become."""

    lineage: str
    lists: tuple[str, ...]
    rows: tuple[KeptRow, ...]


def read_rows(client: Any, table: str, list_ids: Sequence[str]) -> list[KeptRow]:
    """The kept rows of the given alert lists: one query on each list's partition (``ALERT#<listId>``), never a scan."""
    found: list[KeptRow] = []
    for list_id in list_ids:
        start: dict[str, Any] | None = None
        while True:
            page = client.query(TableName=table, KeyConditionExpression="pk = :p AND begins_with(sk, :s)",
                                ExpressionAttributeValues=_ser({":p": ALERT_PREFIX + list_id, ":s": ITEM_PREFIX}), ConsistentRead=True, **({"ExclusiveStartKey": start} if start else {}))
            for raw in page.get("Items", []):
                row = _de(raw)
                found.append(KeptRow(list_id, str(row["sk"])[len(ITEM_PREFIX):], str(row.get("issueId") or ""), str(row.get("at") or "")))
            start = page.get("LastEvaluatedKey")
            if not start:
                break
    return found


def plan(rows: Sequence[KeptRow]) -> list[Conversion]:
    """One conversion for each Story, the lists that kept a row for it in order. Nothing is read or written."""
    by_story: dict[str, list[KeptRow]] = {}
    for row in rows:
        by_story.setdefault(row.lineage, []).append(row)
    return [Conversion(lineage, tuple(sorted({row.list_id for row in kept})), tuple(sorted(kept, key=lambda row: (row.at, row.list_id)))) for lineage, kept in sorted(by_story.items())]


@dataclass
class Result:
    announcements: int = 0     # made by this run
    deliveries_sent: int = 0
    deliveries_withdrawn: int = 0
    unchanged: int = 0         # Stories whose Announcement and finished Delivery were already there

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def _issue_of(conversion: Conversion, read_issue: Callable[[str], Mapping[str, Any] | None]) -> Mapping[str, Any] | None:
    """The alert issue the Story's earliest kept row names that still exists and went; the other lists' issues carry the same words."""
    issues = [issue for row in conversion.rows if row.issue_id and (issue := read_issue(row.issue_id)) is not None]
    return next((issue for issue in issues if issue.get("status") == SENT_STATUS), issues[0] if issues else None)


def convert(conversions: Sequence[Conversion], announcements: Announcements, *, read_issue: Callable[[str], Mapping[str, Any] | None],
            read_item: Callable[[str], Mapping[str, Any] | None], account_id: str, now: str | None = None) -> Result:
    """Make each Story's Announcement and its finished email Delivery. ``read_issue(issue id)`` is the alert issue row and ``read_item(item id)`` the Story's Item row."""
    result = Result()
    now = now or records.now_iso()
    for conversion in conversions:
        issue = _issue_of(conversion, read_issue)
        went = issue is not None and issue.get("status") == SENT_STATUS
        at = records.utc(conversion.rows[0].at) or now
        item = read_item(str(issue.get("sourceItemId"))) if issue and issue.get("sourceItemId") else None
        stories = [StoryRef(conversion.lineage, str(item["id"]), int(item.get("versionNumber") or 1))] if item else []
        words = str(issue.get("bodyMarkus") or "") if issue else ""
        # Drafted, never ready: nothing may send it between the two writes.
        draft = Plan(channel=EMAIL, account_id=account_id, approval=NONE, approval_policy=POLICY, text=words, audience=conversion.lists, drafted_by="machine", state=DRAFTED)
        key = records.story_published_key(conversion.lineage)
        outcome = announcements.announce(dedupe_key=key, kind="story_published", stories=stories, plans=[draft], created_by=BY, trigger="conversion", release_at=at, now=now,
                                         stories_optional=not stories)
        assert outcome is not None
        if outcome.created:
            result.announcements += 1
        (delivery,) = [row for row in outcome.deliveries if row["channel"] == EMAIL and row["accountId"] == account_id]
        if delivery["state"] != DRAFTED:
            result.unchanged += 1
            continue
        if went:
            entry = {"number": 1, "at": at, "outcome": ATTEMPT_SENT, "closedAt": at, "by": BY, "note": "sent by the alert issue " + str(issue.get("issueId") or issue.get("id") or "")}
            announcements.deliveries._change(delivery, {"attempts": [entry], "state": SENT}, by=BY, note="converted: the alert was sent before alerts were Announcements", now=now)
            result.deliveries_sent += 1
        else:
            announcements.deliveries.finish(delivery, DELIVERY_WITHDRAWN, by=BY, note="converted: the alert was never sent, and the Story is decided, so it is not alerted now", now=now)
            result.deliveries_withdrawn += 1
        row = announcements.get(outcome.announcement["id"])
        if row and row["state"] == records.PLANNED:
            announcements.release(row, max(now, at), by=BY)
    return result


def render(conversions: Sequence[Conversion]) -> str:
    if not conversions:
        return "No kept alert rows: nothing to convert."
    lines = [f"{len(conversions)} Stories to convert from {sum(len(item.rows) for item in conversions)} kept rows:"]
    lines += [f"  {item.lineage}: {', '.join(item.lists)}" for item in conversions]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, *, environment: Mapping[str, str] = os.environ, client_factory: Callable[[], Any] | None = None, table_client: Any = None, out: Any = None) -> int:
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="python -m papyrus_content.announcements.alert_conversion", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--newsletter-table", required=True, help="the site's newsletter DynamoDB table")
    parser.add_argument("--list", action="append", dest="lists", required=True, help="an alert list id (repeat for each)")
    parser.add_argument("--dry-run", action="store_true", help="read and print only")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    from papyrus_content.newsletter.store import Store

    store = Store(args.newsletter_table, table_client)
    found = plan(read_rows(store.client, args.newsletter_table, args.lists))
    if args.command == "plan" or args.dry_run:
        out.write((json.dumps([{"lineage": item.lineage, "lists": item.lists} for item in found], indent=2) if args.json else render(found)) + "\n")
        return 0
    account = (environment.get("PAPYRUS_TENANT_ID") or "").strip()
    if not account:
        parser.error("run writes: PAPYRUS_TENANT_ID names the site's sending account")
    from papyrus_content.newsletter.issues import IssueStore

    if client_factory is None:
        from papyrus_content.graphql_authoring import create_authoring_client

        def client_factory() -> Any:
            return create_authoring_client()[0]
    client = client_factory()
    issues = IssueStore(store)
    result = convert(found, Announcements(client), read_issue=issues.get, read_item=lambda item_id: client.get_record("Item", item_id), account_id=account)
    out.write((json.dumps(result.as_dict()) if args.json else f"Made {result.announcements} Announcements: {result.deliveries_sent} sent, {result.deliveries_withdrawn} withdrawn, {result.unchanged} already converted.") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
