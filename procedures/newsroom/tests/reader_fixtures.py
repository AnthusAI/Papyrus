"""The reader-actions function against moto DynamoDB tables shaped like the Amplify model tables."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import boto3
from moto import mock_aws

from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.urls import UrlPolicy
from papyrus_content.publishing import published_item_id_for
from papyrus_content.reader_steering.task import (
    HANDLE_TABLE_ENV,
    PROFILE_TABLE_ENV,
    SETTINGS_ENV,
    STATE_TABLE_ENV,
    COMMENT_TABLE_ENV,
    FLAG_TABLE_ENV,
    SUBMISSION_TABLE_ENV,
    VOTE_TABLE_ENV,
    run_reader_snapshot,
)

HANDLER_PATH = Path(__file__).resolve().parents[3] / "amplify" / "plugins" / "reader-steering" / "function" / "handler.py"
_specification = importlib.util.spec_from_file_location("reader_actions_handler", HANDLER_PATH)
reader_handler = importlib.util.module_from_spec(_specification)
sys.modules["reader_actions_handler"] = reader_handler
_specification.loader.exec_module(reader_handler)

START_SECONDS = 1_800_000_000.0
OLD_ACCOUNT_SECONDS = 3 * 24 * 3600
PUBLISHED_SUBJECTS = ("item-one", "item-two")
TABLE_NAMES = {
    "profile": "ReaderProfile-test",
    "handle": "ReaderHandle-test",
    "vote": "ReaderVote-test",
    "published": "PublishedItem-test",
    "rate": "RateWindows-test",
    "submission": "ReaderSubmission-test",
    "comment": "ReaderComment-test",
    "report": "ReaderReport-test",
    "flag": "ReaderFlag-test",
    "action": "ModerationAction-test",
    "item": "Item-test",
}


def subject_for(name: str, prefix: str = "ss1_") -> str:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return prefix + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


SNAPSHOT_FUNCTION_ARN = "arn:aws:lambda:us-east-1:123456789012:function:content-actions-test"
SCHEDULER_ROLE_ARN = "arn:aws:iam::123456789012:role/reader-snapshot-scheduler-test"


class ScriptedRetirementPoll:
    """A stand-in for the CMS retired-subject route: answers the pages it was given, in order."""

    enabled = True

    def __init__(self, *pages: Any) -> None:
        self.pages = list(pages)
        self.asked: list[str | None] = []

    def fetch(self, since: str | None) -> Any:
        self.asked.append(since)
        page = self.pages.pop(0)
        if isinstance(page, Exception):
            raise page
        return page


class ReaderBackend:
    def __init__(self, *, dimensions=("real", "useful"), allow_interim=False, actions_per_hour=120, snapshot_enabled=True, **settings) -> None:
        self.settings = reader_handler.ReaderSettings(
            dimensions=tuple(dimensions), actions_per_hour=actions_per_hour, allow_interim_subjects=allow_interim, **settings
        )
        self.snapshot_target = reader_handler.SnapshotTarget(SNAPSHOT_FUNCTION_ARN, SCHEDULER_ROLE_ARN) if snapshot_enabled else None
        self.now = START_SECONDS
        self._mock = mock_aws()

    def __enter__(self) -> "ReaderBackend":
        self._mock.start()
        self.resource = boto3.resource("dynamodb", region_name="us-east-1")
        self.scheduler_client = boto3.client("scheduler", region_name="us-east-1")
        for key, table_name in TABLE_NAMES.items():
            attribute = "pk" if key == "rate" else "id"
            definitions = [{"AttributeName": attribute, "AttributeType": "S"}]
            indexes = {}
            if key == "profile":
                definitions += [{"AttributeName": "readerId", "AttributeType": "S"}]
                indexes = {
                    "GlobalSecondaryIndexes": [
                        {"IndexName": reader_handler.PROFILE_READER_INDEX, "KeySchema": [{"AttributeName": "readerId", "KeyType": "HASH"}], "Projection": {"ProjectionType": "ALL"}}
                    ]
                }
            if key == "report":
                definitions += [{"AttributeName": "target", "AttributeType": "S"}, {"AttributeName": "createdAt", "AttributeType": "S"}]
                indexes = {
                    "GlobalSecondaryIndexes": [
                        {
                            "IndexName": reader_handler.REPORT_TARGET_INDEX,
                            "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}, {"AttributeName": "createdAt", "KeyType": "RANGE"}],
                            "Projection": {"ProjectionType": "ALL"},
                        }
                    ]
                }
            if key == "submission":
                definitions += [{"AttributeName": "domain", "AttributeType": "S"}, {"AttributeName": "createdAt", "AttributeType": "S"}]
                indexes = {
                    "GlobalSecondaryIndexes": [
                        {
                            "IndexName": reader_handler.SUBMISSION_DOMAIN_INDEX,
                            "KeySchema": [{"AttributeName": "domain", "KeyType": "HASH"}, {"AttributeName": "createdAt", "KeyType": "RANGE"}],
                            "Projection": {"ProjectionType": "ALL"},
                        }
                    ]
                }
            self.resource.create_table(
                TableName=table_name,
                KeySchema=[{"AttributeName": attribute, "KeyType": "HASH"}],
                AttributeDefinitions=definitions,
                BillingMode="PAY_PER_REQUEST",
                **indexes,
            )
        self.store = reader_handler.DynamoReaderStore(
            resource=self.resource,
            profile_table=TABLE_NAMES["profile"],
            handle_table=TABLE_NAMES["handle"],
            vote_table=TABLE_NAMES["vote"],
            published_item_table=TABLE_NAMES["published"],
            rate_table=TABLE_NAMES["rate"],
            submission_table=TABLE_NAMES["submission"],
            comment_table=TABLE_NAMES["comment"],
            report_table=TABLE_NAMES["report"],
            action_table=TABLE_NAMES["action"],
            item_table=TABLE_NAMES["item"],
            flag_table=TABLE_NAMES["flag"],
        )
        for subject in PUBLISHED_SUBJECTS:
            self.publish(subject)
        return self

    def __exit__(self, *exc: object) -> None:
        self._mock.stop()

    def table(self, key: str) -> Any:
        return self.resource.Table(TABLE_NAMES[key])

    def publish(self, subject: str, status: str = "published") -> None:
        self.table("published").put_item(Item={"id": reader_handler.PUBLISHED_ID_PREFIX + subject, "status": status})

    def call(self, subject: str, action: str, payload: dict | None = None, *, staff: bool = False, bypass_scheduling: bool = False) -> dict:
        scheduler = reader_handler.snapshot_scheduler(self.store, self.settings, self.now, self.snapshot_target, self.scheduler_client)
        event = {"publication": "example.test", "siteSubject": subject, "isStaff": staff, "action": action, "payload": payload or {}}
        return reader_handler.handle_event(event, store=self.store, settings=self.settings, now_seconds=self.now, schedule_snapshot=scheduler)

    def schedules(self) -> list[dict]:
        """The one-off schedules that are waiting, each with its target, oldest first."""
        names = sorted(entry["Name"] for entry in self.scheduler_client.list_schedules()["Schedules"])
        return [self.scheduler_client.get_schedule(Name=name) for name in names]

    def age_everyone(self) -> None:
        self.now += OLD_ACCOUNT_SECONDS

    def votes(self) -> list[dict]:
        return self.table("vote").scan()["Items"]

    def submissions(self) -> list[dict]:
        return self.table("submission").scan()["Items"]

    def comments(self) -> list[dict]:
        return self.table("comment").scan()["Items"]

    def flags(self) -> list[dict]:
        return self.table("flag").scan()["Items"]

    def reports(self) -> list[dict]:
        return self.table("report").scan()["Items"]

    def actions(self) -> list[dict]:
        return sorted(self.table("action").scan()["Items"], key=lambda row: (row["at"], row["id"]))

    def items(self) -> list[dict]:
        return self.table("item").scan()["Items"]

    def staff_call(self, action: str, target_type: str, target: str, *, reason: str | None = None, undo_of: str | None = None, groups=("editor",), sub: str = "staff-sub-1") -> dict:
        """The moderateReader mutation as AppSync delivers it to the function."""
        event = {
            "arguments": {"action": action, "targetType": target_type, "target": target, **({"reason": reason} if reason is not None else {}), **({"undoOf": undo_of} if undo_of else {})},
            "identity": {"sub": sub, "claims": {"cognito:groups": list(groups), "sub": sub}},
            "info": {"fieldName": "moderateReader"},
        }
        return reader_handler.handle_staff_event(event, store=self.store, settings=self.settings, now_seconds=self.now)


def iso_at(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def url_policy(base_path: str = "") -> UrlPolicy:
    urls = {"basePath": base_path} if base_path else {}
    return UrlPolicy(standard_settings_from_mapping({"site": {"name": "Example"}, "urls": urls}))


def run_snapshot(
    backend: "ReaderBackend",
    writer: Any,
    *,
    base_path: str = "",
    invalidate: Any = None,
    published: tuple[str, ...] = PUBLISHED_SUBJECTS,
    dimensions: tuple[str, ...] = ("real", "useful"),
    submitter_of: Any = None,
    retirement_poll: Any = None,
    poll_retirements: bool = False,
    hype_gap: dict | None = None,
    review_signals: Any = None,
    comment_signals: Any = None,
    section_of: dict | None = None,
    ranking: dict | None = None,
    subject_types: tuple[str, ...] | None = None,
):
    """The reader-snapshot task against the backend's moto tables and a page writer, one minute after the backend's clock."""
    published_ids = {published_item_id_for(subject) for subject in published}
    section_of = section_of or {}
    now = backend.now + 60
    policy = url_policy(base_path)
    rows = [
        {"id": published_item_id_for(subject), "sourceItemId": subject, "itemLineageId": subject, "type": "article", "status": "published", "slug": subject, "section": section_of.get(subject),
         "title": f"Title of {subject}", "publishedAt": iso_at(now - (5 + index) * 3600), "metadata": "{}"}
        for index, subject in enumerate(published)
    ]
    client = SimpleNamespace(
        get_record=lambda model, record_id: {"status": "published", "publishedAt": iso_at(now - 5 * 3600)} if model == "PublishedItem" and record_id in published_ids else None,
        list_published_item_summaries=lambda: rows,
    )
    projector = SimpleNamespace(policy=policy, item_page_paths=lambda summary: (policy.item_key(None, summary.slug),))
    context = SimpleNamespace(projector=projector, writer=writer, invalidate=invalidate)
    environment = {
        SETTINGS_ENV: json.dumps({"dimensions": list(dimensions), "karma": {"upvoteWeight": 1, "usedItWeight": 2}, "ranking": ranking or {}, "limits": {"newAccountHours": 24}, "hypeMinimum": 5, "retirementPoll": retirement_poll is not None, **({"subjects": {"types": list(subject_types)}} if subject_types else {}), **({"hypeGap": hype_gap} if hype_gap else {})}),
        VOTE_TABLE_ENV: TABLE_NAMES["vote"],
        PROFILE_TABLE_ENV: TABLE_NAMES["profile"],
        HANDLE_TABLE_ENV: TABLE_NAMES["handle"],
        STATE_TABLE_ENV: TABLE_NAMES["rate"],
        SUBMISSION_TABLE_ENV: TABLE_NAMES["submission"],
        COMMENT_TABLE_ENV: TABLE_NAMES["comment"],
        FLAG_TABLE_ENV: TABLE_NAMES["flag"],
    }
    return run_reader_snapshot(
        context,
        client,
        environment=environment,
        resource=backend.resource,
        now_seconds=now,
        submitter_of=submitter_of,
        review_signals=review_signals,
        comment_signals=comment_signals,
        retirement_poll=retirement_poll,
        poll_retirements=poll_retirements,
    )
