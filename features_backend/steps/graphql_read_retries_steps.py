"""A read that fails for a moment is sent again with a growing pause (features_backend/graphql-read-retries.feature)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient  # noqa: E402

STORY = {"getItem": {"id": "story-1"}}
TIMEOUT = {"errors": [{"errorType": "DynamoDB:SdkClientException", "message": "Unable to execute HTTP request: connection timed out after 1000 ms"}], "data": None}


class Site:
    """The connection to a site: ``script`` is what each attempt does, an exception to raise or an answer (status, body)."""

    def __init__(self, script):
        self.script, self.attempts = list(script), 0

    def request(self, _method, _path, body=None, headers=None):
        self.attempts += 1
        step = self.script[min(self.attempts, len(self.script)) - 1]
        self.step = step
        if isinstance(step, Exception):
            raise step

    def getresponse(self):
        status, body = self.step
        return SimpleNamespace(status=status, reason="x", read=lambda: json.dumps(body).encode("utf-8"))

    def close(self):
        pass


class Client(PapyrusGraphQLAuthoringClient):
    def __init__(self, site):
        super().__init__(endpoint="https://example.test/graphql", header_factory=lambda _payload: {}, tenant_id="mom")
        self.site, self.pauses = site, []
        self._connection = site

    def _open_connection(self):
        self._connection = self.site
        return self.site

    def _pause_before_retry(self, attempt):
        self.pauses.append(min(0.5 * 2 ** attempt, 8.0))


def _site(context, script):
    context.client = Client(Site(script))


@given("a site whose connection resets twice and then answers")
def step_resets_twice(context):
    _site(context, [ConnectionResetError(54, "Connection reset by peer")] * 2 + [(200, {"data": STORY})])


@given("a site whose first answer reports a DynamoDB client timeout and whose second answer is the Story")
def step_timeout_inside(context):
    _site(context, [(200, TIMEOUT), (200, {"data": STORY})])


@given("a site that answers a read with a validation error")
def step_validation(context):
    _site(context, [(200, {"errors": [{"errorType": "ValidationError", "message": "Field 'nope' is undefined"}], "data": None})])


@given("a site whose connection always resets")
def step_always_resets(context):
    _site(context, [ConnectionResetError(54, "Connection reset by peer")])


def _call(context, query):
    context.result = context.error = None
    try:
        context.result = context.client.graphql(query, {})
    except Exception as error:   # noqa: BLE001 - the scenario asserts on the failure
        context.error = error


@when("the client reads a Story")
def step_read(context):
    _call(context, "query GetItem { getItem(id: \"story-1\") { id } }")


@when("the client writes a Story")
def step_write(context):
    _call(context, "mutation UpdateItem { updateItem(input: {id: \"story-1\"}) { id } }")


@then("the read returns the Story")
def step_returns(context):
    assert context.error is None, context.error
    assert context.result == STORY


@then("the client attempted the read {count:d} times")
def step_attempts(context, count):
    assert context.client.site.attempts == count, context.client.site.attempts


@then("it paused {count:d} times, the second pause longer than the first")
def step_pauses(context, count):
    assert len(context.client.pauses) == count and context.client.pauses[1] > context.client.pauses[0], context.client.pauses


@then("the read fails with the validation error")
def step_validation_error(context):
    assert context.error is not None and "Field 'nope' is undefined" in str(context.error), context.error


@then('the read fails mentioning "{text}"')
def step_read_fails(context, text):
    assert context.error is not None and text in str(context.error), context.error


@then('the write fails mentioning "{text}"')
def step_write_fails(context, text):
    assert context.error is not None and text in str(context.error), context.error
