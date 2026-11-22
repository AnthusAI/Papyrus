from __future__ import annotations

import json
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import boto3
from behave import given, then, when
from moto import mock_aws

from papyrus_content.announcements.actions import PAID_SEARCH, handle_event
from papyrus_content.announcements.opportunity_search import NoRedirects
from papyrus_content.announcements.spend import SpendLedger
from papyrus_content.appsync_event import amplify_function_event, user_pool_identity

QUERY = "independent audit"
TOKEN = "test-token-not-for-the-response"
PERSON_ENV = {"PERSON_ONLY_CLIENT_IDS": "human-console", "PAPYRUS_TENANT_ID": "alpha", "PAPYRUS_TENANCY_MODE": "dedicated"}
RESPONSE = {"data": [
    {"id": "100", "conversation_id": "100", "author_id": "1", "text": "Can we get an independent audit?"},
    {"id": "200", "author_id": "2", "text": "protected content"},
    {"id": "300", "author_id": "3", "text": "visibility is not known"},
    {"id": "400", "author_id": "4", "text": "withheld post", "withheld": {"country_codes": ["XX"]}},
], "includes": {"users": [{"id": "1", "protected": False, "description": "not needed"},
                          {"id": "2", "protected": True},
                          {"id": "4", "protected": False}]}, "meta": {"next_token": "never returned"}}


def identity(role="editor", tenant="alpha", client="human-console"):
    value = user_pool_identity("tester", [role])
    value["claims"].update({"client_id": client, f"papyrus_tenant_{role}": tenant})
    return value


def call(context, who, payload=None, operation=PAID_SEARCH):
    body = {"query": QUERY, "maxResults": 10} if payload is None else payload
    return handle_event(amplify_function_event("Mutation", operation, {"input": json.dumps(body)}, who),
                        context.opp_accounts, context.opp_settings, context.opp_ledger, account_id="123456789012")


@given("a dedicated site has an existing connected X account and a search cap for one page")
def site_ready(context):
    stack = ExitStack()
    context.add_cleanup(stack.close)
    stack.enter_context(patch.dict("os.environ", PERSON_ENV))
    stack.enter_context(mock_aws())
    table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
        TableName="opportunities-ledger", BillingMode="PAY_PER_REQUEST",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
    )
    context.opp_ledger = Mock(return_value=SpendLedger(table, "alpha"))
    context.opp_table = table
    context.opp_accounts = Mock()
    context.opp_accounts.status.return_value = {"connection": "connected", "accountId": "5", "scopes": ["tweet.read", "users.read", "tweet.write"]}
    context.opp_accounts.access_token.return_value = TOKEN
    context.opp_settings = Mock()
    context.opp_settings.read.return_value = {"mode": "off", "billingCycleDay": 1, "opportunities": {
        "enabled": True, "budget": "0.15", "postPrice": "0.005", "userPrice": "0.010",
    }}
    context.opp_opener = stack.enter_context(patch("papyrus_content.announcements.opportunity_search.build_opener"))
    context.opp_open = context.opp_opener.return_value.open
    context.opp_open.side_effect = lambda *_a, **_kw: BytesIO(json.dumps(RESPONSE).encode())


@when("a signed-in editor requests opportunities")
def request_once(context):
    context.opp_answer = call(context, identity())


@then("only a public author's post and an estimated-cost receipt are returned")
def public_capture(context):
    answer = context.opp_answer
    assert answer["ok"], answer
    assert answer["capture"][QUERY]["data"] == [{"id": "100", "conversation_id": "100", "text": "Can we get an independent audit?"}]
    assert answer["capture"][QUERY]["meta"] == {"result_count": 1, "more_available": True}
    assert answer["receipt"] == {"postsReturnedByX": 4, "usersReturnedByX": 3, "publicPosts": 1,
                                 "reservedUsd": "0.150", "reservedThisCycleUsd": "0.15", "estimatedUsd": "0.050"}
    assert all(item not in json.dumps(answer) for item in (TOKEN, "protected content", "not needed", "never returned"))


@then("X receives one fixed GET search without a second page")
def x_read_only(context):
    context.opp_accounts.access_token.assert_called_once_with(expected_account_id="5")
    context.opp_open.assert_called_once()
    assert isinstance(context.opp_opener.call_args.args[0], NoRedirects)
    request = context.opp_open.call_args.args[0]
    url = urlsplit(request.full_url)
    assert request.get_method() == "GET"
    assert (url.scheme, url.netloc, url.path) == ("https", "api.x.com", "/2/tweets/search/recent")
    assert parse_qs(url.query)["max_results"] == ["10"]
    assert parse_qs(url.query)["expansions"] == ["author_id"]
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    rows = context.opp_table.scan()["Items"]
    assert len(rows) == 1 and rows[0]["pk"].startswith("SPEND#alpha#x:5:opportunities#")
    assert int(rows[0]["microUsd"]) == 150000


@when("a CLI credential, a reader, an IAM role, and a foreign editor try to search")
def request_denied(context):
    iam = {"accountId": "123456789012", "userArn": "arn:aws:iam::123456789012:role/operator"}
    context.opp_denials = [call(context, who) for who in (identity(client="agent-cli"), identity(role="member"), iam, identity(tenant="beta"))]
    context.opp_denials.append(call(context, identity(), {"query": QUERY, "maxResults": 10, "tenantId": "beta"}))
    with patch.dict("os.environ", {"PAPYRUS_TENANCY_MODE": "shared"}):
        context.opp_denials.append(call(context, identity()))


@then("the search is refused without reserving money or touching X")
def no_spend(context):
    assert [result["error"] for result in context.opp_denials] == [
        "person_only", "forbidden", "forbidden", "forbidden", "search_invalid_input", "not_configured",
    ]
    context.opp_ledger.assert_not_called()
    context.opp_accounts.access_token.assert_not_called()
    context.opp_open.assert_not_called()
    assert not context.opp_table.scan()["Items"]


@when("a signed-in editor requests opportunities twice")
def two_searches(context):
    context.opp_results = [call(context, identity()), call(context, identity())]


@then("the second search is stopped before contacting X")
def hit_limit(context):
    first, second = context.opp_results
    assert first["ok"], first
    assert second["error"] == "search_budget_exhausted"
    context.opp_accounts.access_token.assert_called_once()
    context.opp_open.assert_called_once()
    assert int(context.opp_table.scan()["Items"][0]["microUsd"]) == 150000


@when("an admin's CLI credential tries to change the stored search settings")
def unauthorized_settings(context):
    changed = {"settings": {"opportunities": {"enabled": True, "budget": "10", "postPrice": "0.001", "userPrice": "0.001"}}}
    context.opp_answer = call(context, identity(role="admin", client="agent-cli"), changed, operation="announcementsSaveSettings")
    context.opp_foreign_change = call(context, identity(role="admin", tenant="beta"), changed, operation="announcementsSaveSettings")


@then("the search allowance and price are unchanged")
def search_settings_unchanged(context):
    assert context.opp_answer["error"] == "person_only", context.opp_answer
    assert context.opp_foreign_change["error"] == "forbidden"
    context.opp_settings.save.assert_not_called()
    context.opp_ledger.assert_not_called()
    context.opp_open.assert_not_called()
