from __future__ import annotations

import hashlib
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
from procedures.newsroom.tests.no_lock_parameter import NoLockParameter  # noqa: E402

HANDLER_PATH = REPO_ROOT / "amplify/functions/content-actions/handler.py"
PUBLICATION_ENVIRONMENT = {
    "PAPYRUS_PUBLICATION_KIND": "s3-projection",
    "PAPYRUS_SITE_BUCKET": "site-bucket",
    "PAPYRUS_EDGE_DISTRIBUTION_ID": "EDISTRIBUTION",
    "PAPYRUS_PROJECTION_DLQ_URL": "https://sqs.example/projection-dlq",
    "PAPYRUS_SITE_PUBLIC_URL": "https://site.example",
    "AWS_LAMBDA_FUNCTION_NAME": "content-actions-function",
}


class FakeClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


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

    def get_object(self, **arguments) -> dict:
        stored = self.objects.get(arguments["Key"])
        if stored is None:
            raise FakeClientError("NoSuchKey")
        body = stored["Body"]
        return {"Body": type("Body", (), {"read": lambda _self, body=body: body})()}

    def head_object(self, **arguments) -> dict:
        stored = self.objects.get(arguments["Key"])
        if stored is None:
            raise FakeClientError("404")
        return {"ETag": f'"{hashlib.md5(stored["Body"]).hexdigest()}"', "Metadata": stored.get("Metadata", {})}

    def list_objects_v2(self, **arguments) -> dict:
        prefix = arguments.get("Prefix", "")
        return {
            "Contents": [
                {"Key": key, "ETag": f'"{hashlib.md5(stored["Body"]).hexdigest()}"'}
                for key, stored in sorted(self.objects.items())
                if key.startswith(prefix)
            ],
            "IsTruncated": False,
        }


class FakeCloudFront:
    def __init__(self) -> None:
        self.invalidations: list[dict] = []
        self.rejects_invalidations = False

    def create_invalidation(self, **arguments) -> None:
        if self.rejects_invalidations:
            raise RuntimeError("AccessDenied")
        self.invalidations.append(arguments)


class FakeLambda:
    def __init__(self) -> None:
        self.invocations: list[dict] = []

    def invoke(self, **arguments) -> None:
        self.invocations.append({**arguments, "Payload": json.loads(arguments["Payload"])})


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
    context.lambda_client = FakeLambda()
    context.environment = dict(PUBLICATION_ENVIRONMENT) if publication else {}
    context.responses = []


def call_action(context, field: str, payload: dict) -> dict:
    event = {"fieldName": field, "arguments": {"input": json.dumps(payload)}, "identity": {"username": "behave-editor"}}
    clients = {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}
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
    assert stored["CacheControl"] == "public, max-age=0, s-maxage=300, stale-while-revalidate=60"


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


@then("one asynchronous retry of the projection was scheduled for the item")
def retry_scheduled(context) -> None:
    assert len(context.lambda_client.invocations) == 1, context.lambda_client.invocations
    invocation = context.lambda_client.invocations[0]
    assert invocation["FunctionName"] == "content-actions-function"
    assert invocation["InvocationType"] == "Event"
    task = invocation["Payload"]["projectionTask"]
    assert task["task"] == "item" and task["itemId"] == "item-articles-hello" and task["unpublished"] is False, task


@then("nothing was queued on the projection dead letter queue")
def nothing_dead_lettered(context) -> None:
    assert context.sqs.messages == [], context.sqs.messages


@when("the scheduled projection task runs with a working bucket")
def run_scheduled_task(context) -> None:
    task = context.lambda_client.invocations[-1]["Payload"]
    context.s3.rejects_writes = False
    context.lambda_client.invocations.clear()
    event = dict(task)
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "boto3.client",
        side_effect=lambda name, **_kwargs: {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}[name],
    ), mock.patch.dict("os.environ", context.environment, clear=False):
        context.task_result = context.handler_module.handler(event, None)


@when("the scheduled projection task runs while the bucket still rejects writes")
def run_failing_scheduled_task(context) -> None:
    task = context.lambda_client.invocations[-1]["Payload"]
    context.task_error = None
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "boto3.client",
        side_effect=lambda name, **_kwargs: {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}[name],
    ), mock.patch.dict("os.environ", context.environment, clear=False):
        try:
            context.handler_module.handler(dict(task), None)
        except Exception as error:  # noqa: BLE001 - the step records what Lambda would see
            context.task_error = error


@then("the projection task succeeds")
def task_succeeds(context) -> None:
    assert context.task_result["ok"] is True, context.task_result


@then("the projection task raises so that Lambda retries it and then dead letters it")
def task_raises(context) -> None:
    assert context.task_error is not None
    assert type(context.task_error).__name__ == "ProjectionTaskFailed" or "AccessDenied" in str(context.task_error), context.task_error


@then("the projection task for the other item pages was scheduled")
def follow_up_scheduled(context) -> None:
    tasks = [invocation["Payload"]["projectionTask"] for invocation in context.lambda_client.invocations]
    assert any(task["task"] == "item-pages" for task in tasks), tasks


@given("the edge distribution rejects invalidations")
def edge_rejects_invalidations(context) -> None:
    context.cloudfront.rejects_invalidations = True


@given("edge invalidation is switched off for the site")
def edge_invalidation_off(context) -> None:
    context.environment["PAPYRUS_EDGE_INVALIDATION"] = "off"


@then('the page "{key}" is cached at the edge for {seconds:d} seconds with stale-while-revalidate')
def page_edge_lifetime(context, key: str, seconds: int) -> None:
    cache_control = context.s3.objects[key]["CacheControl"]
    assert cache_control == f"public, max-age=0, s-maxage={seconds}, stale-while-revalidate=60", cache_control


@then("the edge distribution was not invalidated")
def edge_not_invalidated(context) -> None:
    assert context.cloudfront.invalidations == [], context.cloudfront.invalidations


@then("the publish response says the item is live but the edge was not purged")
def live_but_not_purged(context) -> None:
    assert context.response["live"] is True and context.response["edgePurged"] is False, context.response


@then("an asynchronous invalidation of the written pages was scheduled")
def invalidation_task_scheduled(context) -> None:
    tasks = [invocation["Payload"]["projectionTask"] for invocation in context.lambda_client.invocations]
    invalidations = [task for task in tasks if task["task"] == "invalidate"]
    assert len(invalidations) == 1 and "articles/hello.html" in invalidations[0]["keys"], tasks


@given('the site bucket page "{key}" was removed')
def remove_bucket_page(context, key: str) -> None:
    del context.s3.objects[key]


@when('the deploy starts the "{task_name}" projection task')
def run_named_projection_task(context, task_name: str) -> None:
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "boto3.client",
        side_effect=lambda name, **_kwargs: {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}[name],
    ), mock.patch.dict("os.environ", context.environment, clear=False):
        context.task_result = context.handler_module.handler({"projectionTask": {"task": task_name}}, None)


@when("the scheduled invalidation task runs with a working edge")
def run_invalidation_task(context) -> None:
    task = next(
        invocation["Payload"]
        for invocation in context.lambda_client.invocations
        if invocation["Payload"]["projectionTask"]["task"] == "invalidate"
    )
    context.cloudfront.rejects_invalidations = False
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "boto3.client",
        side_effect=lambda name, **_kwargs: {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}[name],
    ), mock.patch.dict("os.environ", context.environment, clear=False):
        context.task_result = context.handler_module.handler(dict(task), None)


@when('the deploy starts the "{task_name}" projection task expecting failure')
def run_named_projection_task_expecting_failure(context, task_name: str) -> None:
    context.task_error = None
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "boto3.client",
        side_effect=lambda name, **_kwargs: {"s3": context.s3, "cloudfront": context.cloudfront, "sqs": context.sqs, "lambda": context.lambda_client, "ssm": NoLockParameter()}[name],
    ), mock.patch.dict("os.environ", context.environment, clear=False):
        try:
            context.handler_module.handler({"projectionTask": {"task": task_name}}, None)
        except Exception as error:  # noqa: BLE001 - the step records what Lambda would see
            context.task_error = error


@given('a stray page "{key}" in the site bucket')
def stray_bucket_page(context, key: str) -> None:
    context.s3.put_object(Bucket="site-bucket", Key=key, Body=b"<p>stale</p>", Metadata={"papyrus-version": "1"})


@when('the projection writes the pages "{first}" and "{second}"')
def projection_writes_pages(context, first: str, second: str) -> None:
    from papyrus_content.projection.writers import S3PageWriter

    writer = S3PageWriter("site-bucket", context.s3)
    for key in (first, second):
        writer.put(key, b"<p>page</p>")


@then('the stored page "{key}" has content type "{content_type}" and no cache header')
def stored_without_cache_header(context, key: str, content_type: str) -> None:
    stored = context.s3.objects[key]
    assert stored["ContentType"] == content_type, stored
    assert "CacheControl" not in stored, stored


@then('the stored page "{key}" has content type "{content_type}" and a cache header')
def stored_with_cache_header(context, key: str, content_type: str) -> None:
    stored = context.s3.objects[key]
    assert stored["ContentType"] == content_type, stored
    assert stored.get("CacheControl"), stored


@then("the deploy render report says nothing drifted")
def deploy_render_clean(context) -> None:
    assert context.task_result["drift"]["found"] is False, context.task_result


@then('the deploy render report says the page "{key}" drifted')
def deploy_render_orphan(context, key: str) -> None:
    drift = context.task_result["drift"]
    assert drift["found"] is True and key in drift["orphanPages"], context.task_result


@then('the site bucket still holds "{key}"')
def bucket_still_holds(context, key: str) -> None:
    assert key in context.s3.objects, list(context.s3.objects)
