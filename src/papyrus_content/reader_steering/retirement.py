"""The Prospectus retired-subject poll: fetch retirements, then drop or re-key what the site holds for those readers.

Prospectus tells a reader site which of its siteSubjects were retired (``GET /v1/accounts/site-subjects/retired``). It
admits one caller per site, the CMS compute role, so the scheduled run reaches it through the CMS route
``/api/reader/retired`` with a shared secret (docs/reader-steering.md). :class:`HttpRetirementPoll` is that client;
:func:`apply_retirements` is the data work; :func:`run_retirement_poll` pages through ``more`` and keeps the cursor.

Every record is applied as "ensure dropped" or "ensure re-keyed", so a repeat, or a retry after a failure part way, changes nothing more.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

SITE_SUBJECT = re.compile(r"ss1_[A-Za-z0-9_-]{43}")
REASON_DELETED = "deleted"
REASON_MERGED = "merged"
POLL_PATH = "/api/reader/retired"
POLL_SECRET_HEADER = "x-papyrus-reader-poll-secret"
CURSOR_KEY = "retirement-cursor"
MAXIMUM_PAGES_PER_RUN = 50
STATE_ORDER = {"active": 0, "limited": 1, "banned": 2}


class RetirementPollError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetiredSubject:
    site_subject: str
    reason: str
    surviving_site_subject: str | None = None
    retired_at: str = ""


@dataclass(frozen=True)
class RetiredPage:
    retired: tuple[RetiredSubject, ...] = ()
    cursor: str | None = None
    more: bool = False


class RetirementPoll(Protocol):
    enabled: bool

    def fetch(self, since: str | None) -> RetiredPage: ...


class DisabledRetirementPoll:
    enabled = False

    def fetch(self, since: str | None) -> RetiredPage:
        return RetiredPage(cursor=since)


def parse_page(body: Mapping[str, Any]) -> RetiredPage:
    """Validates Prospectus's answer: a malformed record stops the poll rather than being half applied."""
    records: list[RetiredSubject] = []
    for entry in body.get("retired") or []:
        subject, reason, survivor = entry.get("siteSubject"), entry.get("reason"), entry.get("survivingSiteSubject")
        if not isinstance(subject, str) or not SITE_SUBJECT.fullmatch(subject):
            raise RetirementPollError("a retired record has no valid siteSubject")
        if reason not in (REASON_DELETED, REASON_MERGED):
            raise RetirementPollError("a retired record has an unknown reason")
        if reason == REASON_MERGED and (not isinstance(survivor, str) or not SITE_SUBJECT.fullmatch(survivor) or survivor == subject):
            raise RetirementPollError("a merged record has no valid surviving siteSubject")
        records.append(RetiredSubject(subject, reason, survivor if reason == REASON_MERGED else None, str(entry.get("retiredAt") or "")))
    cursor = body.get("cursor")
    return RetiredPage(tuple(records), cursor if isinstance(cursor, str) and cursor else None, body.get("more") is True)


class HttpRetirementPoll:
    """Calls the site's own CMS route with the shared poll secret."""

    enabled = True

    def __init__(self, base_url: str, secret: str, opener: Callable[..., Any] = urllib.request.urlopen, timeout: float = 20.0) -> None:
        if not base_url.startswith("https://") or not secret:
            raise RetirementPollError("the retirement poll needs an https site origin and the poll secret")
        self._url = base_url.rstrip("/") + POLL_PATH
        self._secret = secret
        self._opener = opener
        self._timeout = timeout

    def fetch(self, since: str | None) -> RetiredPage:
        url = self._url + (f"?{urllib.parse.urlencode({'since': since})}" if since else "")
        request = urllib.request.Request(url, headers={POLL_SECRET_HEADER: self._secret, "accept": "application/json"}, method="GET")
        try:
            with self._opener(request, timeout=self._timeout) as response:
                return parse_page(json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as error:
            code = ""
            try:
                code = str(json.loads(error.read().decode("utf-8")).get("error", ""))
            except (ValueError, AttributeError):
                pass
            raise RetirementPollError(f"the retirement poll answered {error.code} {code}".strip()) from None
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise RetirementPollError(f"the retirement poll failed ({type(error).__name__})") from None


@dataclass(frozen=True)
class ReaderTableNames:
    profile: str
    handle: str
    vote: str
    state: str


@dataclass
class RetirementReport:
    enabled: bool = False
    pages: int = 0
    deleted: int = 0
    merged: int = 0
    cursor_saved: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "pages": self.pages,
            "deleted": self.deleted,
            "merged": self.merged,
            "cursorSaved": self.cursor_saved,
            "error": self.error,
        }


def scan_matching(table: Any, **filter_arguments: Any) -> list[dict]:
    rows: list[dict] = []
    kwargs: dict[str, Any] = dict(filter_arguments)
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def votes_of(resource: Any, names: ReaderTableNames, reader_id: str) -> list[dict]:
    from boto3.dynamodb.conditions import Attr

    return scan_matching(resource.Table(names.vote), FilterExpression=Attr("readerId").eq(reader_id))


def drop_votes(resource: Any, names: ReaderTableNames, votes: Iterable[Mapping]) -> None:
    table = resource.Table(names.vote)
    with table.batch_writer() as writer:
        for vote in votes:
            writer.delete_item(Key={"id": vote["id"]})


def vote_stamp(vote: Mapping) -> str:
    return str(vote.get("updatedAt") or vote.get("createdAt") or "")


def apply_deleted(resource: Any, names: ReaderTableNames, subject: str) -> bool:
    """Deletes the profile, handle claim, votes and ratings. The profile goes last, so a retry after a failure still finds it."""
    profiles = resource.Table(names.profile)
    profile = profiles.get_item(Key={"id": subject}, ConsistentRead=True).get("Item")
    if not profile:
        return False
    drop_votes(resource, names, votes_of(resource, names, profile["readerId"]))
    if profile.get("handle"):
        resource.Table(names.handle).delete_item(Key={"id": profile["handle"]})
    profiles.delete_item(Key={"id": subject})
    return True


def apply_merged(resource: Any, names: ReaderTableNames, subject: str, survivor: str) -> bool:
    """Moves what the retired subject held to the surviving subject. On a conflict the newer row wins for each item and dimension."""
    profiles = resource.Table(names.profile)
    old = profiles.get_item(Key={"id": subject}, ConsistentRead=True).get("Item")
    if not old:
        return False
    existing = profiles.get_item(Key={"id": survivor}, ConsistentRead=True).get("Item")
    if not existing:
        try:
            profiles.put_item(
                Item={**old, "id": survivor, "siteSubject": survivor}, ConditionExpression="attribute_not_exists(id)"
            )
            profiles.delete_item(Key={"id": subject})
            return True
        except Exception as error:
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = profiles.get_item(Key={"id": survivor}, ConsistentRead=True).get("Item")
    votes = resource.Table(names.vote)
    for vote in votes_of(resource, names, old["readerId"]):
        target_id = f"{vote['subjectKey']}#{existing['readerId']}#{vote['dimension']}"
        current = votes.get_item(Key={"id": target_id}, ConsistentRead=True).get("Item")
        if current is None or vote_stamp(vote) > vote_stamp(current):
            votes.put_item(Item={**vote, "id": target_id, "readerId": existing["readerId"]})
        votes.delete_item(Key={"id": vote["id"]})
    old_handle = old.get("handle")
    if old_handle and not existing.get("handle"):
        resource.Table(names.handle).update_item(
            Key={"id": old_handle}, UpdateExpression="SET readerId = :reader", ExpressionAttributeValues={":reader": existing["readerId"]}
        )
        profiles.update_item(Key={"id": survivor}, UpdateExpression="SET #h = :h", ExpressionAttributeNames={"#h": "handle"}, ExpressionAttributeValues={":h": old_handle})
    elif old_handle:
        resource.Table(names.handle).delete_item(Key={"id": old_handle})
    if STATE_ORDER.get(old.get("state"), 0) > STATE_ORDER.get(existing.get("state"), 0):
        profiles.update_item(Key={"id": survivor}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": old["state"]})
    profiles.delete_item(Key={"id": subject})
    return True


def apply_retirements(resource: Any, names: ReaderTableNames, retired: Iterable[RetiredSubject], report: RetirementReport) -> None:
    for record in retired:
        if record.reason == REASON_DELETED:
            report.deleted += apply_deleted(resource, names, record.site_subject)
        else:
            report.merged += apply_merged(resource, names, record.site_subject, record.surviving_site_subject or "")


def load_cursor(resource: Any, names: ReaderTableNames) -> str | None:
    item = resource.Table(names.state).get_item(Key={"pk": CURSOR_KEY}, ConsistentRead=True).get("Item")
    return item.get("cursor") if item else None


def save_cursor(resource: Any, names: ReaderTableNames, cursor: str) -> None:
    resource.Table(names.state).put_item(Item={"pk": CURSOR_KEY, "cursor": cursor})


def run_retirement_poll(poll: RetirementPoll, resource: Any, names: ReaderTableNames) -> RetirementReport:
    """Polls from the stored cursor, applies each page, saves the cursor after it and follows ``more`` (at most 50 pages a run).

    A failure ends the poll with the error name in the report and leaves the cursor at the last applied page, so the next run retries.
    """
    report = RetirementReport(enabled=getattr(poll, "enabled", True))
    if not report.enabled:
        return report
    try:
        cursor = load_cursor(resource, names)
        for _ in range(MAXIMUM_PAGES_PER_RUN):
            page = poll.fetch(cursor)
            report.pages += 1
            apply_retirements(resource, names, page.retired, report)
            if page.cursor and page.cursor != cursor:
                save_cursor(resource, names, page.cursor)
                report.cursor_saved = True
                cursor = page.cursor
            if not page.more:
                break
    except Exception as error:  # noqa: BLE001 - the snapshot still runs; the next scheduled run retries from the saved cursor
        report.error = type(error).__name__
    return report
