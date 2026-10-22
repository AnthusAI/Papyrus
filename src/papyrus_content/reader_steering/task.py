"""The ``reader-snapshot`` projection task of the content-actions function.

It reads votes and profiles with the function's IAM role, builds the three public files, writes them to the site
store under the URL policy, materialises karma on the profiles and purges the three paths on the edge when the
backend knows the distribution. A debounced invoke from reader-actions and an EventBridge rule every few hours both start it.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..publishing import published_item_id_for
from .retirement import (
    DisabledRetirementPoll,
    HttpRetirementPoll,
    ReaderTableNames,
    RetirementPoll,
    RetirementReport,
    run_retirement_poll,
)
from .review import ReviewReport, review_submissions
from .signals import submission_signals
from .snapshot import (
    BOARD_FILE,
    iso as snapshot_iso,
    ITEMS_FILE,
    READERS_FILE,
    SUBMISSIONS_FILE,
    SnapshotSettings,
    build_snapshot,
    encoded,
    settings_from_mapping,
)

SETTINGS_ENV = "PAPYRUS_READER_SNAPSHOT_SETTINGS"
PROFILE_TABLE_ENV = "PAPYRUS_READER_PROFILE_TABLE"
VOTE_TABLE_ENV = "PAPYRUS_READER_VOTE_TABLE"
HANDLE_TABLE_ENV = "PAPYRUS_READER_HANDLE_TABLE"
SUBMISSION_TABLE_ENV = "PAPYRUS_READER_SUBMISSION_TABLE"
STATE_TABLE_ENV = "PAPYRUS_READER_RATE_TABLE"
POLL_URL_ENV = "PAPYRUS_READER_POLL_URL"
POLL_SECRET_PARAMETER_ENV = "PAPYRUS_READER_POLL_SECRET_PARAMETER"
TASK_NAME = "reader-snapshot"
SUBMISSION_SUBJECT = re.compile(r"sub-[0-9a-f]{24}")


class ReaderSnapshotNotEnabled(RuntimeError):
    pass


@dataclass
class ReaderSnapshotReport:
    written: list[str]
    subjects: int
    readers: int
    karma_updated: int
    purged: list[str]
    purge_error: str | None
    retirement_poll: RetirementReport
    review: ReviewReport

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "written": self.written,
            "subjects": self.subjects,
            "readers": self.readers,
            "karmaUpdated": self.karma_updated,
            "purged": self.purged,
            "purgeError": self.purge_error,
            "retirementPoll": self.retirement_poll.to_dict(),
            "review": self.review.to_dict(),
        }


def snapshot_settings_from_environment(environment: Mapping[str, str]) -> SnapshotSettings:
    raw = (environment.get(SETTINGS_ENV) or "").strip()
    if not raw:
        raise ReaderSnapshotNotEnabled(f"{SETTINGS_ENV} is not set; this site does not enable the reader-steering plugin.")
    return settings_from_mapping(json.loads(raw))


def retirement_poll_from_environment(environment: Mapping[str, str], ssm_client: Any = None) -> RetirementPoll:
    """The HTTP poll when the site enabled it and the run asked for it; the secret is read from SSM at run time."""
    parameter = environment.get(POLL_SECRET_PARAMETER_ENV, "")
    origin = environment.get(POLL_URL_ENV, "")
    if not parameter or not origin:
        return DisabledRetirementPoll()
    if ssm_client is None:
        import boto3

        ssm_client = boto3.client("ssm")
    secret = ssm_client.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"].strip()
    return HttpRetirementPoll(origin, secret)


def scan_table(resource: Any, table_name: str) -> list[dict]:
    table = resource.Table(table_name)
    rows: list[dict] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = table.scan(**kwargs)
        rows.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def plain_row(row: Mapping) -> dict:
    return {key: (int(value) if hasattr(value, "to_integral_value") and value == value.to_integral_value() else value) for key, value in row.items()}


def published_times(client: Any, subjects: set[str]) -> dict[str, str | None]:
    """The publication time of each subject that is still published; unpublished subjects are left out."""
    published: dict[str, str | None] = {}
    for subject in sorted(subjects):
        if SUBMISSION_SUBJECT.fullmatch(subject):
            continue
        row = client.get_record("PublishedItem", published_item_id_for(subject))
        if row is not None and row.get("status") == "published":
            published[subject] = row.get("publishedAt")
    return published


def snapshot_key(projector: Any, site_key: str) -> str:
    """The object key under the site's URL policy (``urls.basePath``); a projector without a policy serves from the root."""
    policy = getattr(projector, "policy", None)
    return policy.key(site_key) if policy is not None else site_key


def write_karma(resource: Any, table_name: str, profiles: list[dict], karma: Mapping[str, int]) -> int:
    table = resource.Table(table_name)
    updated = 0
    for profile in profiles:
        value = karma.get(profile["readerId"], 0)
        if int(profile.get("karma") or 0) == value:
            continue
        table.update_item(
            Key={"id": profile["id"]},
            UpdateExpression="SET karma = :karma",
            ConditionExpression="attribute_exists(id)",
            ExpressionAttributeValues={":karma": value},
        )
        updated += 1
    return updated


def run_reader_snapshot(
    context: Any,
    client: Any,
    *,
    environment: Mapping[str, str] | None = None,
    resource: Any = None,
    now_seconds: float | None = None,
    retirement_poll: RetirementPoll | None = None,
    poll_retirements: bool = False,
    submitter_of: Callable[[str], str | None] | None = None,
    review_signals: Callable[..., list[dict]] | None = None,
) -> ReaderSnapshotReport:
    environment = os.environ if environment is None else environment
    settings = snapshot_settings_from_environment(environment)
    if resource is None:
        import boto3

        resource = boto3.resource("dynamodb")
    retirement = RetirementReport()
    if poll_retirements and settings.retirement_poll:
        try:
            poll = retirement_poll or retirement_poll_from_environment(environment)
            retirement = run_retirement_poll(
                poll,
                resource,
                ReaderTableNames(
                    profile=environment[PROFILE_TABLE_ENV],
                    handle=environment[HANDLE_TABLE_ENV],
                    vote=environment[VOTE_TABLE_ENV],
                    state=environment[STATE_TABLE_ENV],
                    submission=environment.get(SUBMISSION_TABLE_ENV, ""),
                ),
            )
        except Exception as error:  # noqa: BLE001 - a poll that cannot start must not stop the numbers
            retirement = RetirementReport(enabled=True, error=type(error).__name__)
    votes = [plain_row(row) for row in scan_table(resource, environment[VOTE_TABLE_ENV])]
    profiles = [plain_row(row) for row in scan_table(resource, environment[PROFILE_TABLE_ENV])]
    submissions = [plain_row(row) for row in scan_table(resource, environment[SUBMISSION_TABLE_ENV])] if environment.get(SUBMISSION_TABLE_ENV) else []
    now = time.time() if now_seconds is None else now_seconds
    review = ReviewReport()
    if submissions:
        try:
            review.submissions = review_submissions(resource, environment[SUBMISSION_TABLE_ENV], submissions, now_iso=snapshot_iso(now), signals=review_signals or submission_signals)
        except Exception as error:  # noqa: BLE001 - signals are advice; a failure must not stop the numbers
            review.error = type(error).__name__
    snapshot = build_snapshot(
        votes,
        profiles,
        published_at=published_times(client, {vote["subjectKey"] for vote in votes}),
        now_seconds=now,
        settings=settings,
        submitter_of=submitter_of,
        submissions=submissions,
    )
    keys: list[str] = []
    files = [(ITEMS_FILE, snapshot.items), (BOARD_FILE, snapshot.board), (READERS_FILE, snapshot.readers)]
    if environment.get(SUBMISSION_TABLE_ENV):
        files.append((SUBMISSIONS_FILE, snapshot.submissions))
    for site_key, payload in files:
        key = snapshot_key(context.projector, site_key)
        context.writer.put(key, encoded(payload))
        keys.append(key)
    karma_updated = write_karma(resource, environment[PROFILE_TABLE_ENV], profiles, snapshot.karma)
    purged: list[str] = []
    purge_error: str | None = None
    if context.invalidate is not None:
        try:
            purged = context.invalidate(keys)
        except Exception as error:  # noqa: BLE001 - the files are written; a purge that fails only delays them by the cache lifetime
            purge_error = type(error).__name__
    return ReaderSnapshotReport(
        written=keys,
        subjects=len(snapshot.items["items"]),
        readers=len(snapshot.readers["readers"]),
        karma_updated=karma_updated,
        purged=purged,
        purge_error=purge_error,
        retirement_poll=retirement,
        review=review,
    )
