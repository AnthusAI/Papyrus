"""``build_runtime`` over moto: the environment names the plugin sets are the ones the runtime reads."""

from __future__ import annotations

import json
from typing import Any

import boto3
import pytest
from moto import mock_aws

from papyrus_content.notifications import handler as notifications_handler
from papyrus_content.notifications import runtime as runtime_module
from papyrus_content.notifications.notifications_test import THEME, Site

REGION = "us-east-1"
OPERATORS = "/papyrus/alpha/notifications/operators"
KEY = "/papyrus/alpha/notifications/recipient-key"


@pytest.fixture
def aws(monkeypatch: pytest.MonkeyPatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        yield


def environment(queue_url: str) -> dict[str, str]:
    return {
        "SITE_ID": "alpha",
        "SITE_ORIGIN": "https://alpha.example.test",
        "SITE_BASE_PATH": "",
        "FROM_NAME": "Alpha News",
        "FROM_ADDRESS": "notify@alpha.example.test",
        "CONFIGURATION_SET": "papyrus-alpha",
        "ITEM_URL_STYLE": "html",
        "THEME_JSON": json.dumps(THEME),
        "LISTS_JSON": json.dumps([{"id": "stories", "name": "New stories", "description": "", "rule": {}, "approval": "admin"}]),
        "TABLE_NAME": "notifications-alpha",
        "EMAIL_QUEUE_URL": queue_url,
        "OPERATORS_PARAMETER": OPERATORS,
        "RECIPIENT_KEY_PARAMETER": KEY,
    }


def create_table() -> None:
    boto3.client("dynamodb").create_table(
        TableName="notifications-alpha",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": name, "AttributeType": "S"} for name in ("pk", "sk", "recipientKey", "queuedAt")],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "byRecipient",
                "KeySchema": [{"AttributeName": "recipientKey", "KeyType": "HASH"}, {"AttributeName": "queuedAt", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )


def test_the_real_runtime_routes_a_story_to_the_operator_in_parameter_store(aws: None, monkeypatch: pytest.MonkeyPatch) -> None:
    create_table()
    queue_url = boto3.client("sqs").create_queue(QueueName="notifications-alpha-email")["QueueUrl"]
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name=OPERATORS, Type="StringList", Value="operator@alpha.example.test")
    ssm.put_parameter(Name=KEY, Type="SecureString", Value="secret-for-the-test")
    donor = Site()
    lineage = donor.add_story("Rates held steady", "news")
    monkeypatch.setattr(runtime_module, "published_item_reader", lambda: donor.rows.get)
    monkeypatch.setenv("TABLE_NAME", "unused")  # the explicit environment below wins; the real one is never read
    rt = runtime_module.build_runtime(environment(queue_url))

    answer = notifications_handler.route(rt, Site.announcement(lineage))
    assert answer["status"] == "accepted" and answer["deliveries"] == 1
    messages: list[Any] = boto3.client("sqs").receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1).get("Messages", [])
    assert len(messages) == 1
    body = json.loads(messages[0]["Body"])
    assert body["eventId"] == "story.published:" + lineage

    assert notifications_handler.route(rt, Site.announcement(lineage))["status"] == "duplicate"
    # The delivery is in the site's table, found through the byRecipient index.
    (row,) = [item for item in rt.store.query("EVENT#" + body["eventId"], "DELIVERY#")]
    assert row["status"] == "queued" and row["kind"] == "story.published"
    assert rt.store.by_recipient(row["recipientKey"])[0]["deliveryId"] == row["deliveryId"]
