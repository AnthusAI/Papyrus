"""The reader-actions function against moto DynamoDB tables shaped like the Amplify model tables."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import boto3
from moto import mock_aws

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
}


def subject_for(name: str, prefix: str = "ss1_") -> str:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return prefix + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class RecordingLambda:
    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    def invoke(self, **arguments: Any) -> dict[str, Any]:
        self.invocations.append(arguments)
        return {"StatusCode": 202}


class ReaderBackend:
    def __init__(self, *, dimensions=("real", "useful"), allow_interim=False, actions_per_hour=120, snapshot_function="content-actions-test") -> None:
        self.settings = reader_handler.ReaderSettings(
            dimensions=tuple(dimensions), actions_per_hour=actions_per_hour, allow_interim_subjects=allow_interim
        )
        self.snapshot_function = snapshot_function
        self.now = START_SECONDS
        self.lambda_client = RecordingLambda()
        self._mock = mock_aws()

    def __enter__(self) -> "ReaderBackend":
        self._mock.start()
        self.resource = boto3.resource("dynamodb", region_name="us-east-1")
        for key, table_name in TABLE_NAMES.items():
            attribute = "pk" if key == "rate" else "id"
            self.resource.create_table(
                TableName=table_name,
                KeySchema=[{"AttributeName": attribute, "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": attribute, "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        self.store = reader_handler.DynamoReaderStore(
            resource=self.resource,
            profile_table=TABLE_NAMES["profile"],
            handle_table=TABLE_NAMES["handle"],
            vote_table=TABLE_NAMES["vote"],
            published_item_table=TABLE_NAMES["published"],
            rate_table=TABLE_NAMES["rate"],
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
        scheduler = reader_handler.snapshot_scheduler(self.store, self.settings, self.now, self.snapshot_function, self.lambda_client)
        event = {"publication": "example.test", "siteSubject": subject, "isStaff": staff, "action": action, "payload": payload or {}}
        return reader_handler.handle_event(event, store=self.store, settings=self.settings, now_seconds=self.now, schedule_snapshot=scheduler)

    def age_everyone(self) -> None:
        self.now += OLD_ACCOUNT_SECONDS

    def votes(self) -> list[dict]:
        return self.table("vote").scan()["Items"]
