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


class StubAmplify:
    def __init__(self, statuses, start_error=None):
        self.statuses = statuses
        self.start_error = start_error
        self.started = []

    def list_jobs(self, **kwargs):
        return {"jobSummaries": [{"jobId": "9", "status": status} for status in self.statuses]}

    def start_job(self, **kwargs):
        if self.start_error:
            raise self.start_error
        self.started.append(kwargs)
        return {"jobSummary": {"jobId": "42"}}


def call_action(context, field: str, payload: dict) -> dict:
    event = {
        "info": {"fieldName": field},
        "arguments": {"input": json.dumps(payload)},
        "identity": {"username": "behave-editor"},
    }
    with mock.patch.object(context.handler_module, "create_authoring_client", return_value=(context.client, {})), mock.patch(
        "papyrus_content.rebuild_trigger._create_amplify_client", return_value=context.amplify
    ), mock.patch.dict("os.environ", {"PAPYRUS_READER_AMPLIFY_APP_ID": "reader1"}):
        return context.handler_module.handler(event, None)


def start_backend(context, amplify: StubAmplify) -> None:
    specification = importlib.util.spec_from_file_location("rebuild_on_publish_handler", HANDLER_PATH)
    context.handler_module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(context.handler_module)
    context.client = FakeAuthoringClient()
    context.amplify = amplify


@given("a content actions backend with a reader app and no pending build")
def backend_no_pending(context) -> None:
    start_backend(context, StubAmplify(["SUCCEED"]))


@given("a content actions backend with a reader app and a pending build")
def backend_pending(context) -> None:
    start_backend(context, StubAmplify(["PENDING"]))


@given("a content actions backend with a reader app whose build start fails")
def backend_failing(context) -> None:
    start_backend(context, StubAmplify(["SUCCEED"], start_error=RuntimeError("no repository connected")))


@when("the editor saves and publishes an article")
def save_and_publish(context) -> None:
    saved = call_action(
        context,
        "saveItemDraft",
        {"type": "article", "slug": "hello", "section": "articles", "frontMatterYaml": "title: Hello\n", "bodyMarkus": "Hello.\n"},
    )
    context.response = call_action(context, "publishItem", {"id": saved["item"]["id"]})


@then("the publish response reports a started rebuild")
def reports_started(context) -> None:
    assert context.response["rebuild"] == {"started": True, "jobId": "42"}, context.response


@then("the publish response reports the rebuild was skipped because a build is pending")
def reports_skipped(context) -> None:
    assert context.response["rebuild"]["reason"] == "pending-job-exists", context.response


@then("the publish response is ok")
def publish_ok(context) -> None:
    assert context.response["ok"] is True, context.response


@then("the publish response reports a rebuild error")
def reports_error(context) -> None:
    rebuild = context.response["rebuild"]
    assert rebuild["started"] is False and "no repository connected" in rebuild["error"], rebuild


@then("exactly {count:d} build was started")
@then("exactly {count:d} builds were started")
def build_count(context, count: int) -> None:
    assert len(context.amplify.started) == count, context.amplify.started
