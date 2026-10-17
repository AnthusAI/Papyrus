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

from procedures.newsroom.tests.fake_client import FakeAuthoringClient  # noqa: E402

HANDLER_PATH = REPO_ROOT / "amplify/functions/content-actions/handler.py"
FRONT_MATTER = "title: Hello\n"
BODY = "Hello **world**.\n"


def load_handler_module():
    specification = importlib.util.spec_from_file_location("content_actions_handler_steps", HANDLER_PATH)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def call_action(context, field: str, payload: dict) -> dict:
    event = {
        "fieldName": field,
        "arguments": {"input": json.dumps(payload)},
        "identity": {"username": "behave-editor"},
    }
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})):
        return context.handler_module.handler(event, None)


def draft_payload(**changes) -> dict:
    values = {
        "id": None,
        "type": "article",
        "slug": "hello",
        "section": "articles",
        "frontMatterYaml": FRONT_MATTER,
        "bodyMarkus": BODY,
        "aliases": [],
        "expectedContentHash": None,
    }
    values.update(changes)
    return values


@given("a content actions backend")
def content_actions_backend(context) -> None:
    context.client = FakeAuthoringClient()
    context.handler_module = load_handler_module()


@given("the editor has saved the article as a draft")
@when("the editor saves the article as a draft")
def save_draft(context) -> None:
    context.response = call_action(context, "saveItemDraft", draft_payload())
    context.item = context.response.get("item")


@when("the editor derives the article body")
def derive(context) -> None:
    context.response = call_action(context, "deriveMarkus", {"frontMatterYaml": FRONT_MATTER, "bodyMarkus": BODY})


@when("the editor publishes the saved article")
def publish(context) -> None:
    context.response = call_action(context, "publishItem", {"id": context.item["id"]})


@when("the editor unpublishes the saved article")
def unpublish(context) -> None:
    context.response = call_action(context, "unpublishItem", {"id": context.item["id"]})


@when("the editor saves again with a stale content hash")
def save_stale(context) -> None:
    context.response = call_action(
        context,
        "saveItemDraft",
        draft_payload(id=context.item["id"], bodyMarkus="Changed.\n", expectedContentHash="sha256:stale"),
    )


@then("the derive response is ok")
def derive_ok(context) -> None:
    assert context.response["ok"] is True and context.response["bodyIrBytes"] > 0, context.response


@then("the save response reports a draft item")
def save_reports_draft(context) -> None:
    assert context.response["ok"] is True, context.response
    assert context.response["item"]["status"] == "draft", context.response


@then("the publish response reports version {version:d}")
def publish_version(context, version: int) -> None:
    assert context.response["ok"] is True and context.response["versionNumber"] == version, context.response


@then("a published item exists")
def published_exists(context) -> None:
    assert context.response["publishedId"] in context.client.tables.get("PublishedItem", {})


@then("no published item exists in the content actions backend")
def no_published(context) -> None:
    assert not context.client.tables.get("PublishedItem"), context.client.tables.get("PublishedItem")


@then('the response fails with code "{code}"')
def fails_with(context, code: str) -> None:
    assert context.response["ok"] is False and context.response["errors"][0]["code"] == code, context.response
