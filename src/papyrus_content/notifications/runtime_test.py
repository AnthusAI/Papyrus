"""``build_runtime`` over moto: the environment names the plugin sets are the ones the runtime reads."""

from __future__ import annotations

import json
from typing import Any

import boto3
import pytest
from moto import mock_aws

from papyrus_content.notifications import handler as notifications_handler
from papyrus_content.notifications import runtime as runtime_module
from caducus.notify.audience import StaticDomains

from papyrus_content.notifications.notifications_test import CONSENT, THEME, Site

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
        "CONSENT": CONSENT,
        "CONFIRM_WINDOW_SECONDS": "259200",
    }


def create_table() -> None:
    boto3.client("dynamodb").create_table(
        TableName="notifications-alpha",
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[{"AttributeName": name, "AttributeType": "S"} for name in ("pk", "sk", "recipientKey", "queuedAt", "gsiList")],
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "byRecipient",
                "KeySchema": [{"AttributeName": "recipientKey", "KeyType": "HASH"}, {"AttributeName": "queuedAt", "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"},
            },
            {"IndexName": "byList", "KeySchema": [{"AttributeName": "gsiList", "KeyType": "HASH"}], "Projection": {"ProjectionType": "KEYS_ONLY"}},
        ],
    )


def receive(queue_url: str) -> list[dict[str, Any]]:
    sqs = boto3.client("sqs")
    found = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10).get("Messages", [])
    for message in found:
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
    return [json.loads(message["Body"]) for message in found]


def test_the_real_runtime_subscribes_a_reader_and_fans_a_story_out_to_them(aws: None, monkeypatch: pytest.MonkeyPatch) -> None:
    create_table()
    queue_url = boto3.client("sqs").create_queue(QueueName="notifications-alpha-email")["QueueUrl"]
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name=OPERATORS, Type="StringList", Value="operator@alpha.example.test")
    ssm.put_parameter(Name=KEY, Type="SecureString", Value="secret-for-the-test")
    donor = Site(readers=0)
    lineage = donor.add_story("Rates held steady", "news")
    monkeypatch.setattr(runtime_module, "published_item_reader", lambda: donor.rows.get)
    monkeypatch.setattr(runtime_module, "DnsDomainChecker", StaticDomains)  # no DNS from tests
    monkeypatch.setenv("TABLE_NAME", "unused")  # the explicit environment below wins; the real one is never read
    rt = runtime_module.build_runtime(environment(queue_url))

    answer = notifications_handler.route(
        rt, {"action": "subscribe", "email": "reader@example.test", "lists": ["stories"], "consent": CONSENT, "ip": "203.0.113.9"}
    )
    assert answer == {"statusCode": 202, "body": {"status": "check_email"}}
    (confirmation,) = receive(queue_url)
    assert confirmation["eventId"].startswith("audience.confirmation:")
    (content,) = rt.store.query("EVENT#" + confirmation["eventId"], "CONTENT#")
    token = content["items"][0]["facts"]["url"].split("token=", 1)[1]
    assert notifications_handler.route(rt, {"action": "confirm", "token": token})["body"]["status"] == "confirmed"

    assert notifications_handler.route(rt, Site.announcement(lineage))["status"] == "accepted"
    (page,) = receive(queue_url)
    assert page == {"fanout": "story.published:" + lineage, "list": "stories", "cursor": None}
    assert notifications_handler.email_with(rt, {"Records": [{"messageId": "1", "body": json.dumps(page)}]}) == {"batchItemFailures": []}
    (delivery,) = receive(queue_url)
    assert delivery["eventId"] == "story.published:" + lineage
    assert notifications_handler.route(rt, Site.announcement(lineage))["status"] == "duplicate"
    # The delivery is in the site's table, found through the byRecipient index.
    (row,) = rt.store.query("EVENT#" + delivery["eventId"], "DELIVERY#")
    assert row["status"] == "queued" and row["kind"] == "story.published" and row["class"] == "public"
    assert rt.store.by_recipient(row["recipientKey"])[-1]["deliveryId"] == row["deliveryId"]
