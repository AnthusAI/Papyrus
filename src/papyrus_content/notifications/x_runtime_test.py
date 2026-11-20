"""The site's x queue over moto and a fake X server on localhost: the stores of the announcements function (settings, connection, spend, SSM) read as the real runtime reads them."""

from __future__ import annotations

import json
import time
from decimal import Decimal

import boto3
import pytest
from caducus.notify.fakes import FakeX, X_TOKEN, X_USER_ID

from papyrus_content.announcements.channel import SENT, WITHDRAWN
from papyrus_content.announcements.settings import with_defaults
from papyrus_content.announcements.stores import DynamoSettings
from papyrus_content.notifications import handler as notifications_handler
from papyrus_content.notifications import runtime as runtime_module

from .runtime_test import KEY, OPERATORS, aws, create_table, environment, receive  # noqa: F401  (aws is a fixture)


def make_tables() -> None:
    dynamodb = boto3.client("dynamodb")
    for name in ("announcement-settings", "x-connection", "announcement-spend"):
        dynamodb.create_table(TableName=name, BillingMode="PAY_PER_REQUEST", AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}], KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}])


def x_environment(queue_url: str, x_queue_url: str, api_base: str) -> dict[str, str]:
    return {
        **environment(queue_url), "X_QUEUE_URL": x_queue_url, "X_API_BASE": api_base, "X_AUTHORIZE_URL": "https://x.example/authorize", "X_TOKEN_URL": "https://x.example/token",
        "X_REVOKE_URL": "https://x.example/revoke", "ANNOUNCEMENT_SETTINGS_TABLE": "announcement-settings", "X_CONNECTION_TABLE": "x-connection",
        "ANNOUNCEMENT_SPEND_TABLE": "announcement-spend", "X_REFRESH_LEASE_SECONDS": "28",
    }


def prepare(fake: FakeX) -> dict[str, str]:
    create_table()
    make_tables()
    sqs, ssm = boto3.client("sqs"), boto3.client("ssm")
    queue_url = sqs.create_queue(QueueName="email")["QueueUrl"]
    x_queue_url = sqs.create_queue(QueueName="x")["QueueUrl"]
    ssm.put_parameter(Name=OPERATORS, Type="StringList", Value="operator@alpha.example.test")
    ssm.put_parameter(Name=KEY, Type="SecureString", Value="secret-for-the-test")
    # The connection the announcements function keeps: the account, and an access token that has not expired.
    boto3.resource("dynamodb").Table("x-connection").put_item(Item={"id": "x", "status": "connected", "accountId": X_USER_ID, "handle": "@alpha_test", "clientId": "app"})
    ssm.put_parameter(Name=f"/papyrus/alpha/announcements/x/{X_USER_ID}/access-token", Type="SecureString", Value=json.dumps({"token": X_TOKEN, "expiresAt": time.time() + 3600}))
    DynamoSettings(boto3.resource("dynamodb").Table("announcement-settings"), time.time).put(with_defaults({"mode": "on", "budget": "10.00", "billingCycleDay": 1}))
    return x_environment(queue_url, x_queue_url, fake.url)


def test_the_x_queue_posts_what_the_broadcaster_hands_over_and_withdraws_it(aws: None) -> None:  # noqa: F811
    fake = FakeX()
    try:
        env = prepare(fake)
        rt = runtime_module.build_runtime(env)
        assert rt.broadcaster is not None and rt.x is not None
        rt.broadcaster.submit(account_id=X_USER_ID, event_id="delivery:d1:a1", text="A look at secrets https://alpha.example.test/a", url="https://alpha.example.test/a")
        rt.broadcaster.submit(account_id=X_USER_ID, event_id="delivery:d1:a1", text="A look at secrets https://alpha.example.test/a", url="https://alpha.example.test/a")  # the same event again
        (message,) = receive(env["X_QUEUE_URL"])
        assert rt.broadcaster.delivery("delivery:d1:a1").status == "queued"
        assert notifications_handler.x_with(rt, {"Records": [{"messageId": "1", "body": json.dumps(message)}]}) == {"batchItemFailures": []}
        view = rt.broadcaster.delivery("delivery:d1:a1")
        assert (view.status, view.post_id, Decimal(view.cost)) == (SENT, fake.posts[0]["id"], Decimal("0.2"))
        # The charge is on the spend counter the guard reads, through the function's own table.
        (spend,) = boto3.resource("dynamodb").Table("announcement-spend").scan()["Items"]
        assert Decimal(spend["total"]) == Decimal("0.2") and spend["accountId"] == X_USER_ID
        withdrawn = rt.broadcaster.withdraw("delivery:d1:a1", by="ada")
        assert (withdrawn.status, withdrawn.withdrawn_by) == (WITHDRAWN, "ada") and fake.posts == []
    finally:
        fake.close()


def test_a_site_without_an_x_queue_has_no_x_channel(aws: None) -> None:  # noqa: F811
    create_table()
    sqs, ssm = boto3.client("sqs"), boto3.client("ssm")
    queue_url = sqs.create_queue(QueueName="email")["QueueUrl"]
    ssm.put_parameter(Name=OPERATORS, Type="StringList", Value="operator@alpha.example.test")
    ssm.put_parameter(Name=KEY, Type="SecureString", Value="secret-for-the-test")
    rt = runtime_module.build_runtime(environment(queue_url))
    assert rt.x is None and rt.broadcaster is None and runtime_module.x_broadcaster(environment(queue_url)) is None
    with pytest.raises(RuntimeError, match="not wired for X"):
        notifications_handler.x_with(rt, {"Records": []})
