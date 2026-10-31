from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import publish_gate, review_requests  # noqa: E402
from papyrus_content.publishing import DryRunClient, ItemFields, PublishError, publish_item, save_item, unpublish_item  # noqa: E402
from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

ITEM_ID = "item-articles-gate"
NOW = "2026-10-05T12:00:00Z"
HANDLER_PATH = REPO_ROOT / "amplify/functions/content-actions/handler.py"


def article(body: str = "Hello world.\n") -> ItemFields:
    return ItemFields(type="article", slug="gate", section="articles", front_matter_yaml="title: Gate\n", body_markus=body, aliases=[], id=ITEM_ID)


def reviews(context) -> list[dict]:
    return review_requests.list_reviews(context.client)


def attempt(context, **options) -> None:
    context.error = None
    try:
        context.result = publish_item(options.pop("client", context.client), ITEM_ID, actor="automation:newsroom", now=NOW, **options)
    except PublishError as error:
        context.error = error


@given("a site with no publish gate setting")
def no_setting(context) -> None:
    context.client = FakeAuthoringClient()


@given("a saved draft article on a site with no publish gate setting")
def draft_no_setting(context) -> None:
    no_setting(context)
    save_item(context.client, article(), actor="behave", now=NOW)


@given("a saved draft article on a site that requires approval to publish")
def draft_required(context) -> None:
    draft_no_setting(context)
    publish_gate.set_publish_approval(context.client, "required", by="behave", now=NOW)


@given("a published article on a site that requires approval to publish")
def published_required(context) -> None:
    draft_no_setting(context)
    publish_item(context.client, ITEM_ID, actor="behave", now=NOW)
    publish_gate.set_publish_approval(context.client, "required", by="behave", now=NOW)


@given("an automation has tried to publish the item")
@when("an automation publishes the item")
def automation_publishes(context) -> None:
    attempt(context)


@when("a signed-in editor publishes the item from the console")
def editor_publishes(context) -> None:
    attempt(context, approved_by="editor-sub-1")


@when("the operator previews publishing the item")
def operator_previews(context) -> None:
    attempt(context, client=DryRunClient(context.client))


@when("the operator unpublishes the item")
def operator_unpublishes(context) -> None:
    unpublish_item(context.client, ITEM_ID, actor="operator", now=NOW)


@given("a person approves the review request")
@when("a person approves the review request")
def approve(context) -> None:
    (request,) = reviews(context)
    review_requests.answer_review(context.client, request["id"], decision="approve", by="editor-sub-1", roles=["editor"])


@when("a person rejects the review request")
def reject(context) -> None:
    (request,) = reviews(context)
    review_requests.answer_review(context.client, request["id"], decision="reject", by="editor-sub-1", feedback="Not yet.", roles=["editor"])


@when("the article text changes")
def text_changes(context) -> None:
    save_item(context.client, article("Hello again, world.\n"), actor="behave", now=NOW)


@when("the content actions publish the item without a signed-in editor")
def content_actions_publish(context) -> None:
    call_content_actions(context, {"username": "iam-role"})


@when("the content actions publish the item for a signed-in editor")
def content_actions_publish_editor(context) -> None:
    call_content_actions(context, {"sub": "editor-sub-1", "username": "editor", "issuer": "https://cognito-idp.example/pool"})


def call_content_actions(context, identity: dict) -> None:
    specification = importlib.util.spec_from_file_location("content_actions_gate_steps", HANDLER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    event = {"fieldName": "publishItem", "arguments": {"input": json.dumps({"id": ITEM_ID})}, "identity": identity}
    with mock.patch.object(module, "create_authoring_client", return_value=(context.client, {})):
        context.response = module.handler(event, None)


@when('an operator sets the publish approval setting to "{value}"')
def operator_sets(context, value: str) -> None:
    publish_gate.set_publish_approval(context.client, value, by="operator", now=NOW)


@when('an operator tries to give the publish approval setting the value "{value}"')
def operator_tries(context, value: str) -> None:
    context.error = None
    try:
        publish_gate.set_publish_approval(context.client, value, by="operator", now=NOW)
    except publish_gate.PublishGateError as error:
        context.error = error


@then("the item is published")
def item_published(context) -> None:
    assert context.error is None, context.error
    assert ("PublishedItem", "published-" + ITEM_ID) in {(model, key) for model, rows in context.client.tables.items() for key in rows}
    assert context.client.tables["Item"][ITEM_ID]["status"] == "published"


@then("the item is not published")
def item_not_published(context) -> None:
    assert "published-" + ITEM_ID not in context.client.tables.get("PublishedItem", {})
    assert context.client.tables["Item"][ITEM_ID]["status"] != "published"


@then('the publish is refused with code "{code}"')
def refused(context, code: str) -> None:
    assert context.error is not None and context.error.code == code, context.error


@then('the content actions refuse with code "{code}"')
def actions_refuse(context, code: str) -> None:
    assert context.response["ok"] is False and context.response["errors"][0]["code"] == code, context.response


@then("the content actions report the item published")
def actions_published(context) -> None:
    assert context.response["ok"] is True and context.response["changed"] is True, context.response
    assert context.client.tables["Item"][ITEM_ID]["status"] == "published"


@then("no review request exists")
def no_reviews(context) -> None:
    assert reviews(context) == []


@then("no review request is open")
def none_open(context) -> None:
    assert [request for request in reviews(context) if request["state"] == "open"] == []


@then("one open hard gate review request is about the item")
def one_open(context) -> None:
    (request,) = reviews(context)
    assert request["state"] == "open" and request["mode"] == "hard_gate", request
    assert request["raisedBy"] == "publish-gate" and request["subject"]["type"] == "story", request
    assert any(link.get("id") == ITEM_ID for link in request["links"]), request


@then("there are {count:d} review requests")
@then("there is {count:d} review request")
def count_reviews(context, count: int) -> None:
    assert len(reviews(context)) == count, reviews(context)


@then('the publish approval setting reads "{value}"')
def approval_reads(context, value: str) -> None:
    assert publish_gate.publish_approval(context.client) == value


@then("the setting is refused")
def setting_refused(context) -> None:
    assert isinstance(context.error, publish_gate.PublishGateError)
    assert publish_gate.publish_approval(context.client) == "not_required"
