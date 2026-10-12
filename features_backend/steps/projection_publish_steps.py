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
PUBLICATION_ENVIRONMENT = {
    "PAPYRUS_PUBLICATION_KIND": "s3-projection",
    "PAPYRUS_SITE_BUCKET": "site-bucket",
    "PAPYRUS_EDGE_DISTRIBUTION_ID": "EDISTRIBUTION",
    "PAPYRUS_PROJECTION_DLQ_URL": "https://sqs.example/projection-dlq",
    "PAPYRUS_SITE_PUBLIC_URL": "https://site.example",
}


class FakeS3:
    def __init__(self, rejects_writes: bool = False) -> None:
        self.objects: dict[str, dict] = {}
        self.rejects_writes = rejects_writes

    def put_object(self, **arguments) -> None:
        if self.rejects_writes:
            raise RuntimeError("AccessDenied")
        self.objects[arguments["Key"]] = arguments

    def delete_object(self, **arguments) -> None:
        self.objects.pop(arguments["Key"], None)


class FakeCloudFront:
    def __init__(self) -> None:
        self.invalidations: list[dict] = []

    def create_invalidation(self, **arguments) -> None:
        self.invalidations.append(arguments)


class FakeSqs:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send_message(self, **arguments) -> None:
        self.messages.append(arguments)


def start_backend(context, *, publication: bool, rejects_writes: bool = False) -> None:
    specification = importlib.util.spec_from_file_location("projection_publish_handler", HANDLER_PATH)
    context.handler_module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(context.handler_module)
    context.client = FakeAuthoringClient()
    context.s3 = FakeS3(rejects_writes)
    context.cloudfront = FakeCloudFront()
    context.sqs = FakeSqs()
    context.environment = dict(PUBLICATION_ENVIRONMENT) if publication else {}
    context.responses = []


def call_action(context, field: str, payload: dict) -> dict:
    event = {"fieldName": field, "arguments": {"input": json.dumps(payload)}, "identity": {"username": "behave-editor"}}
    clients = {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs}
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "boto3.client", side_effect=lambda name, **_kwargs: clients[name]
    ), mock.patch.dict("os.environ", context.environment, clear=False):
        response = context.handler_module.handler(event, None)
    context.response = response
    return response


def save_draft(context, body: str = "Hello.\n") -> dict:
    return call_action(
        context,
        "saveItemDraft",
        {
            "id": "item-articles-hello",
            "type": "article",
            "slug": "hello",
            "section": "articles",
            "frontMatterYaml": "title: Hello\n",
            "bodyMarkus": body,
        },
    )


@given("a content actions backend with an s3-projection publication")
def backend_with_publication(context) -> None:
    start_backend(context, publication=True)


@given("a content actions backend with an s3-projection publication whose bucket rejects writes")
def backend_with_rejecting_bucket(context) -> None:
    start_backend(context, publication=True, rejects_writes=True)


@given("a content actions backend without a publication")
def backend_without_publication(context) -> None:
    start_backend(context, publication=False)


@given("the editor publishes a new article")
@when("the editor publishes a new article")
def save_and_publish(context) -> None:
    saved = save_draft(context)
    context.response = call_action(context, "publishItem", {"id": saved["item"]["id"]})


@when("the editor saves the live article with a new body")
def save_live_article(context) -> None:
    context.response = save_draft(context, "A new body.\n")


@when("the editor saves a draft article")
def save_draft_article(context) -> None:
    context.response = save_draft(context)


@when("the editor unpublishes the article")
def unpublish_article(context) -> None:
    context.response = call_action(context, "unpublishItem", {"id": "item-articles-hello"})


@then("the publish response succeeds")
def response_ok(context) -> None:
    assert context.response["ok"] is True, context.response


@then('the publish response says the item is live at "{url}"')
def response_live_at(context, url: str) -> None:
    assert context.response["live"] is True, context.response
    assert context.response["url"] == url, context.response
    assert "articles/hello.html" in context.response["paths"], context.response


@then("the publish response says the item is not live")
def response_not_live(context) -> None:
    assert context.response["live"] is False, context.response
    assert context.response["projected"] is False, context.response
    assert context.response["error"], context.response


@then("the save response says the item is live")
def save_response_live(context) -> None:
    assert context.response["ok"] is True and context.response["live"] is True, context.response


@then("the publish response has no projection fields")
def response_without_projection(context) -> None:
    assert not {"live", "projected", "paths", "url"} & set(context.response), context.response


@then('the site bucket holds "{key}" with the published version')
def bucket_holds_with_version(context, key: str) -> None:
    stored = context.s3.objects[key]
    published = context.client.get_record("PublishedItem", "published-item-articles-hello")
    assert stored["Metadata"] == {"papyrus-version": str(published["versionNumber"])}, stored
    assert stored["ContentType"] == "text/html; charset=utf-8"
    assert stored["CacheControl"] == "public, max-age=0, s-maxage=86400"


@then('the edge distribution was invalidated for "{path}"')
def distribution_invalidated(context, path: str) -> None:
    assert len(context.cloudfront.invalidations) == 1, context.cloudfront.invalidations
    invalidation = context.cloudfront.invalidations[0]
    assert invalidation["DistributionId"] == "EDISTRIBUTION"
    assert path in invalidation["InvalidationBatch"]["Paths"]["Items"], invalidation


@then('the site bucket page "{key}" contains "{text}"')
def bucket_page_contains(context, key: str, text: str) -> None:
    assert text in context.s3.objects[key]["Body"].decode("utf-8")


@then("the site bucket holds no pages")
def bucket_empty(context) -> None:
    assert context.s3.objects == {}, list(context.s3.objects)


@then('the site bucket no longer holds "{key}"')
def bucket_lacks(context, key: str) -> None:
    assert key not in context.s3.objects, list(context.s3.objects)


@then("the failure was queued on the projection dead letter queue")
def failure_queued(context) -> None:
    assert len(context.sqs.messages) == 1, context.sqs.messages
    body = json.loads(context.sqs.messages[0]["MessageBody"])
    assert body["itemId"] == "item-articles-hello" and body["unpublished"] is False and body["error"], body
