"""Usage reports to Prospectus through the Python sender, with a fake queue (no AWS)."""
import importlib.util
import json
import os
import pathlib
import uuid
from unittest import mock

from behave import given, then, when

from papyrus_cost_usage import SiteUsage, UsageError, UsageSender

PROSPECTUS_ACCOUNT = "111122223333"
# A made-up Account UUID, derived so no identifier is written into the repository.
VERIFIED_ACCOUNT = str(uuid.uuid5(uuid.NAMESPACE_URL, "https://accounts.example.test/verified"))


def _queue_url(product):
    return f"https://sqs.us-east-1.amazonaws.com/{PROSPECTUS_ACCOUNT}/prospectus-usage-{product}"


class FakeQueue:
    def __init__(self):
        self.messages = []
        self.attempts = []
        self.failures_left = 0

    def send(self, queue_url, body):
        self.attempts.append(json.loads(body))
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("queue unavailable")
        self.messages.append((queue_url, json.loads(body)))


def _site_environment(site_id, product=None):
    return {
        "PROSPECTUS_USAGE_QUEUE_URL": _queue_url(product or f"papyrus-{site_id}"),
        "PAPYRUS_SITE_ID": site_id,
    }


@given('a dedicated site "{site_id}"')
def step_site(context, site_id):
    context.site_id = site_id
    context.queue = FakeQueue()
    context.environment = _site_environment(site_id)


@given("its usage queue fails the first send")
def step_fail_first(context):
    context.queue.failures_left = 1


def _usage(context):
    if not hasattr(context, "usage"):
        context.usage = SiteUsage.from_environment(context.environment, send=context.queue.send)
    return context.usage


@when("an editorial check makes two Jev classifier calls of {first:d} and {second:d} input tokens")
def step_two_checks(context, first, second):
    usage = _usage(context)
    for tokens in (first, second):
        usage.record_humanus_check({"findings": [], "usage": {"classifierRequests": 1, "classifierInputTokens": tokens}})


@when("an embeddings call reports {tokens:d} prompt tokens")
def step_embeddings(context, tokens):
    _usage(context).record_openai({"prompt_tokens": tokens, "total_tokens": tokens})


@when("a chat call reports {input_tokens:d} input tokens and {output_tokens:d} output tokens")
def step_chat(context, input_tokens, output_tokens):
    _usage(context).record_openai({"input_tokens": input_tokens, "output_tokens": output_tokens})


@when("the function flushes before returning")
def step_flush(context):
    _usage(context).flush()


@when("the next invocation flushes again")
def step_flush_again(context):
    _usage(context).flush()


@then("the queue holds exactly one message with operation ID unchanged from the failed send")
def step_one_message(context):
    assert len(context.queue.messages) == 1, context.queue.messages
    assert len(context.queue.attempts) == 2, context.queue.attempts
    assert context.queue.attempts[0]["operationId"] == context.queue.messages[0][1]["operationId"]
    assert context.usage.sender.backlog == 0


@then('the message is for app "{app}", deployment "{deployment}" and account "{account}"')
def step_attribution(context, app, deployment, account):
    queue_url, message = context.queue.messages[0]
    assert queue_url == _queue_url(f"papyrus-{deployment}")
    assert (message["version"], message["app"], message["deployment"], message["accountId"]) == (1, app, deployment, account)


def _quantities(context):
    assert len(context.queue.messages) == 1, context.queue.messages
    return {item["itemKind"]: item["quantity"] for item in context.queue.messages[0][1]["items"]}


@then('it reports {quantity:d} "{kind}" and no dollar amount')
def step_reports(context, quantity, kind):
    assert _quantities(context) == {kind: quantity}
    body = json.dumps(context.queue.messages[0][1]).lower()
    assert "usd" not in body and "dollar" not in body and "cost" not in body


@then('the message reports {input_tokens:d} "{input_kind}" and {output_tokens:d} "{output_kind}"')
def step_reports_two(context, input_tokens, input_kind, output_tokens, output_kind):
    assert _quantities(context) == {input_kind: input_tokens, output_kind: output_tokens}


@when('its usage queue URL names the queue of product "{product}"')
def step_wrong_queue(context, product):
    context.environment = _site_environment(context.site_id, product=product)
    try:
        SiteUsage.from_environment(context.environment, send=context.queue.send)
        context.error = None
    except UsageError as error:
        context.error = str(error)


@then("the sender refuses to start, saying the URL must be this product's own usage queue")
def step_refused(context):
    assert context.error and "this product's Prospectus usage queue" in context.error, context.error


@given("a local run with no usage queue configured")
def step_local(context):
    context.queue = FakeQueue()
    context.environment = {"PAPYRUS_SITE_ID": "dataparade"}


@when("an editorial check reports Jev classifier tokens")
def step_local_check(context):
    usage = _usage(context)
    usage.record_humanus_check({"usage": {"classifierInputTokens": 900}})
    usage.flush()


@then("nothing is recorded and nothing is sent")
def step_nothing(context):
    assert not context.usage.active
    assert context.queue.attempts == []


@when('the Next.js server, after Prospectus authorized the signed-in person for a verified Account, reports {tokens:d} "{kind}"')
def step_verified(context, tokens, kind):
    _usage(context).record([{"itemKind": kind, "quantity": tokens}], account_id=VERIFIED_ACCOUNT)


@then("the message is for that verified Account")
def step_account(context):
    assert len(context.queue.messages) == 1, context.queue.messages
    assert context.queue.messages[0][1]["accountId"] == VERIFIED_ACCOUNT


@given("a sender with no deployment")
def step_no_deployment(context):
    context.sender = UsageSender(product="cyclotron", app="cyclotron",
                                 queue_url="https://sqs.us-east-1.amazonaws.com/111122223333/prospectus-usage-cyclotron", send=lambda *_: None)


@when('usage is recorded for account "owner"')
def step_owner_without_deployment(context):
    try:
        context.sender.record("owner", [{"itemKind": "jev.tokens", "quantity": 1}])
        context.error = None
    except UsageError as error:
        context.error = str(error)


@then('it fails saying "owner" needs a deployment')
def step_owner_error(context):
    assert context.error and '"owner" needs a deployment' in context.error, context.error


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@given("a site backend built without PAPYRUS_COST_TAG_WAVE, so its functions have no PAPYRUS_SITE_ID or PROSPECTUS_USAGE_QUEUE_URL")
def step_no_usage_environment(context):
    context.cleared = ("PAPYRUS_COST_TAG_WAVE", "PAPYRUS_SITE_ID", "PROSPECTUS_USAGE_QUEUE_URL")


@when("the editorial-checks and knowledge-query functions start and flush")
def step_handlers_start(context):
    environment = {key: value for key, value in os.environ.items() if key not in context.cleared}
    context.handler_usage = []
    with mock.patch.dict(os.environ, environment, clear=True):
        for name in ("editorial-checks", "knowledge-query"):
            path = REPO_ROOT / "amplify" / "functions" / name / "handler.py"
            spec = importlib.util.spec_from_file_location(f"cost_off_{name.replace('-', '_')}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.USAGE.flush()
            context.handler_usage.append(module.USAGE)


@then("both start, their usage senders are inactive, and nothing is sent")
def step_handlers_inactive(context):
    assert len(context.handler_usage) == 2
    assert not any(usage.active for usage in context.handler_usage)
