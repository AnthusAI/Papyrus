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

from ..projection.source import summary_from_row
from ..publishing import published_item_id_for
from .retirement import (
    DisabledRetirementPoll,
    HttpRetirementPoll,
    ReaderTableNames,
    RetirementPoll,
    RetirementReport,
    run_retirement_poll,
)
from .extraction import ExtractionReport, ExtractionSetup, extraction_from_environment, run_extraction
from .proposals import FROZEN_STATES, VoteCounts, build_proposal_files
from .review import ReviewReport, review_comments, review_submissions
from .signals import submission_signals
from .snapshot import (
    COMMENTS_DIRECTORY,
    BOARD_FILE,
    iso as snapshot_iso,
    ITEMS_FILE,
    READERS_FILE,
    SUBJECTS_FILE,
    SUBMISSIONS_FILE,
    SnapshotSettings,
    build_snapshot,
    comments_key,
    encoded,
    settings_from_mapping,
    vote_subject_type,
    votes_key,
)

SETTINGS_ENV = "PAPYRUS_READER_SNAPSHOT_SETTINGS"
PROFILE_TABLE_ENV = "PAPYRUS_READER_PROFILE_TABLE"
VOTE_TABLE_ENV = "PAPYRUS_READER_VOTE_TABLE"
HANDLE_TABLE_ENV = "PAPYRUS_READER_HANDLE_TABLE"
SUBMISSION_TABLE_ENV = "PAPYRUS_READER_SUBMISSION_TABLE"
COMMENT_TABLE_ENV = "PAPYRUS_READER_COMMENT_TABLE"
FLAG_TABLE_ENV = "PAPYRUS_READER_FLAG_TABLE"
STATE_TABLE_ENV = "PAPYRUS_READER_RATE_TABLE"
PROPOSAL_TABLE_ENV = "PAPYRUS_READER_PROPOSAL_TABLE"
PUBLISH_PROPOSALS_ENV = "PAPYRUS_READER_PUBLISH_PROPOSALS"
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
    comment_files: int
    proposals: int
    purged: list[str]
    purge_error: str | None
    retirement_poll: RetirementReport
    review: ReviewReport
    extraction: ExtractionReport

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "written": self.written,
            "subjects": self.subjects,
            "readers": self.readers,
            "karmaUpdated": self.karma_updated,
            "commentFiles": self.comment_files,
            "proposals": self.proposals,
            "purged": self.purged,
            "purgeError": self.purge_error,
            "retirementPoll": self.retirement_poll.to_dict(),
            "review": self.review.to_dict(),
            "extraction": self.extraction.to_dict(),
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


def published_entries(client: Any, projector: Any) -> list[dict]:
    """The page facts of each published item that has a page: ``{subject, title, url, section, date, publishedAt}``.

    ``subject`` is the lineage id, the key votes use. The URL is the one the projector places the page at; an item without a page
    (a link-only section) is left out. Nothing here is private: every field is already on the public page.
    """
    policy = getattr(projector, "policy", None)
    entries: list[dict] = []
    for row in client.list_published_item_summaries():
        if row.get("status") != "published":
            continue
        summary = summary_from_row(row)
        keys = projector.item_page_paths(summary)
        if not keys:
            continue
        title = str(summary.front_matter.get("title") or summary.page_title or summary.title or summary.slug).strip()
        published_at = row.get("publishedAt")
        entries.append(
            {
                "subject": row.get("itemLineageId") or summary.item_id,
                "title": title,
                "url": policy.url_for_key(keys[0]) if policy is not None else "/" + keys[0],
                "section": summary.section,
                "date": published_at[:10] if published_at else None,
                "publishedAt": published_at,
            }
        )
    return entries


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


def without_generated_at(payload: Mapping) -> dict:
    return {key: value for key, value in payload.items() if key != "generatedAt"}


def write_comment_files(context: Any, files: Mapping[str, dict], generated_at: str) -> list[str]:
    """Writes the comment file of each subject whose comments changed, and empties the file of a subject that has none any more.

    Only changed files are written (and so purged on the edge): the freshness stamp alone is not a change.
    A file is emptied rather than deleted, so a page that asks for it still gets valid JSON.
    """
    prefix = snapshot_key(context.projector, COMMENTS_DIRECTORY) + "/"
    existing = {entry.key for entry in context.writer.list(prefix)}
    current: dict[str, dict] = {}
    for subject, payload in files.items():
        key = comments_key(subject)
        if key is not None:
            current[snapshot_key(context.projector, key)] = payload
    for key in sorted(existing - set(current)):
        previous = json.loads(context.writer.get(key) or b"{}")
        if previous.get("comments"):
            current[key] = {"generatedAt": generated_at, "subject": previous.get("subject"), "comments": []}
    written: list[str] = []
    for key in sorted(current):
        old = context.writer.get(key)
        if old is not None and without_generated_at(json.loads(old)) == without_generated_at(current[key]):
            continue
        context.writer.put(key, encoded(current[key]))
        written.append(key)
    return written


def freeze_community_results(resource: Any, table_name: str, rows: list[dict], counts: VoteCounts, now_iso: str) -> int:
    """Records the votes a proposal had when the snapshot first saw it in editor review or later, once; it is never overwritten."""
    table = resource.Table(table_name)
    frozen = 0
    for row in rows:
        if row.get("state") not in FROZEN_STATES or row.get("communityResult"):
            continue
        result = {**counts.votes(row["id"]), "at": now_iso}
        try:
            table.update_item(
                Key={"id": row["id"]},
                UpdateExpression="SET communityResult = :result",
                ConditionExpression="attribute_not_exists(communityResult)",
                ExpressionAttributeValues={":result": json.dumps(result)},
            )
        except Exception as error:  # noqa: BLE001 - another run froze it first, which is fine
            if getattr(error, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            continue
        row["communityResult"] = json.dumps(result)
        frozen += 1
    return frozen


def record_attention(resource: Any, table_name: str, rows: list[dict], attention: Mapping[str, list[dict]], now_iso: str) -> int:
    """Stores, on each proposal row, the reasons an editor should look at it (``needsLook``), and clears it when none is left.

    The field is private (staff-readable like the rest of the model) and never reaches a public file. A row is written only when
    its reasons changed, so a quiet proposal costs no writes; ``at`` is when the current reasons were first found.
    """
    table = resource.Table(table_name)
    changed = 0
    for row in rows:
        reasons = attention.get(row["id"], [])
        stored = json.loads(row["needsLook"]) if isinstance(row.get("needsLook"), str) else row.get("needsLook")
        if (stored or {}).get("reasons", []) == reasons and (stored is None) == (not reasons):
            continue
        if reasons:
            table.update_item(Key={"id": row["id"]}, UpdateExpression="SET needsLook = :look", ExpressionAttributeValues={":look": json.dumps({"reasons": reasons, "at": now_iso})})
        else:
            table.update_item(Key={"id": row["id"]}, UpdateExpression="REMOVE needsLook")
        changed += 1
    return changed


def write_proposal_files(context: Any, files: Mapping[str, dict]) -> list[str]:
    """Writes the proposal files that changed (the freshness stamp alone is not a change), so only they are purged on the edge."""
    written: list[str] = []
    for site_key in sorted(files):
        key = snapshot_key(context.projector, site_key)
        old = context.writer.get(key)
        if old is not None and without_generated_at(json.loads(old)) == without_generated_at(files[site_key]):
            continue
        context.writer.put(key, encoded(files[site_key]))
        written.append(key)
    return written


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
    comment_signals: Callable[[str], list[dict]] | None = None,
    extraction: ExtractionSetup | None = None,
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
                    comment=environment.get(COMMENT_TABLE_ENV, ""),
                ),
            )
        except Exception as error:  # noqa: BLE001 - a poll that cannot start must not stop the numbers
            retirement = RetirementReport(enabled=True, error=type(error).__name__)
    votes = [plain_row(row) for row in scan_table(resource, environment[VOTE_TABLE_ENV])]
    profiles = [plain_row(row) for row in scan_table(resource, environment[PROFILE_TABLE_ENV])]
    submissions = [plain_row(row) for row in scan_table(resource, environment[SUBMISSION_TABLE_ENV])] if environment.get(SUBMISSION_TABLE_ENV) else []
    flags = [plain_row(row) for row in scan_table(resource, environment[FLAG_TABLE_ENV])] if environment.get(FLAG_TABLE_ENV) else []
    now = time.time() if now_seconds is None else now_seconds
    proposal_rows = [plain_row(row) for row in scan_table(resource, environment[PROPOSAL_TABLE_ENV])] if environment.get(PROPOSAL_TABLE_ENV) else []
    comments = [plain_row(row) for row in scan_table(resource, environment[COMMENT_TABLE_ENV])] if environment.get(COMMENT_TABLE_ENV) else []
    review = ReviewReport()
    try:
        if submissions:
            review.submissions = review_submissions(resource, environment[SUBMISSION_TABLE_ENV], submissions, now_iso=snapshot_iso(now), signals=review_signals or submission_signals)
        if comments:
            review.comments = review_comments(resource, environment[COMMENT_TABLE_ENV], comments, now_iso=snapshot_iso(now), **({"signals": comment_signals} if comment_signals else {}))
    except Exception as error:  # noqa: BLE001 - signals are advice; a failure must not stop the numbers
        review.error = type(error).__name__
    snapshot = build_snapshot(
        votes,
        profiles,
        published_at=published_times(client, {vote["subjectKey"] for vote in votes if vote_subject_type(vote) == "item"} | {comment["subjectKey"] for comment in comments}),
        now_seconds=now,
        settings=settings,
        submitter_of=submitter_of,
        submissions=submissions,
        comments=comments,
        published_items=published_entries(client, context.projector),
        flags=flags,
        proposals=proposal_rows,
    )
    keys: list[str] = []
    files = [(ITEMS_FILE, snapshot.items), (BOARD_FILE, snapshot.board), (READERS_FILE, snapshot.readers), (SUBJECTS_FILE, snapshot.subjects)]
    if environment.get(SUBMISSION_TABLE_ENV):
        files.append((SUBMISSIONS_FILE, snapshot.submissions))
    for site_key, payload in files:
        key = snapshot_key(context.projector, site_key)
        context.writer.put(key, encoded(payload))
        keys.append(key)
    for kind, payload in snapshot.votes.items():
        key = snapshot_key(context.projector, votes_key(kind))
        context.writer.put(key, encoded(payload))
        keys.append(key)
    comment_keys = write_comment_files(context, snapshot.comments, snapshot.items["generatedAt"])
    keys.extend(comment_keys)
    proposal_keys: list[str] = []
    if proposal_rows:
        counts = VoteCounts.from_items_file(snapshot.items)
        freeze_community_results(resource, environment[PROPOSAL_TABLE_ENV], proposal_rows, counts, snapshot.items["generatedAt"])
        record_attention(resource, environment[PROPOSAL_TABLE_ENV], proposal_rows, snapshot.proposal_attention, snapshot.items["generatedAt"])
        if (environment.get(PUBLISH_PROPOSALS_ENV) or "").strip().lower() == "true":
            proposal_keys = write_proposal_files(context, build_proposal_files(proposal_rows, counts, snapshot.items["generatedAt"], snapshot.proposal_exclusions))
            keys.extend(proposal_keys)
    karma_updated = write_karma(resource, environment[PROFILE_TABLE_ENV], profiles, snapshot.karma)
    purged: list[str] = []
    purge_error: str | None = None
    if context.invalidate is not None:
        try:
            purged = context.invalidate(keys)
        except Exception as error:  # noqa: BLE001 - the files are written; a purge that fails only delays them by the cache lifetime
            purge_error = type(error).__name__
    extraction_report = ExtractionReport()
    if submissions:
        # Last, after the public files are written and purged: the extraction is private and can take as long as the budget allows.
        try:
            setup = extraction or extraction_from_environment(environment, client)
            if setup is not None:
                extraction_report = run_extraction(resource, environment[SUBMISSION_TABLE_ENV], submissions, setup, now_iso=snapshot_iso(now))
        except Exception as error:  # noqa: BLE001 - extraction is advice for the reader; a failure must not fail the run
            extraction_report = ExtractionReport(enabled=True, error=type(error).__name__)
    return ReaderSnapshotReport(
        written=keys,
        subjects=len(snapshot.items["items"]),
        readers=len(snapshot.readers["readers"]),
        karma_updated=karma_updated,
        comment_files=len(comment_keys),
        proposals=len(proposal_rows),
        purged=purged,
        purge_error=purge_error,
        retirement_poll=retirement,
        review=review,
        extraction=extraction_report,
    )
