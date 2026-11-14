"""The monitor-stories step of the knowledge run (features_backend/knowledge-run-monitor-stories.feature). DynamoDB is moto; the command is a fake."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import boto3
from behave import given, then, when
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud.ledger import from_dynamo, run_key  # noqa: E402

_spec = importlib.util.spec_from_file_location("monitor_stories_job_steps", REPO_ROOT / "infra" / "knowledge-run" / "monitor_stories.py")
job = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(job)

ENDPOINT = "https://imnmexcbrzcddk2g4vl6hsn7ie.appsync-api.us-east-1.amazonaws.com/graphql"
TASK = {"vCpu": 4.0, "memoryGiB": 16.0, "ephemeralStorageGiB": 40, "startedAt": None}
CALL = {"model": "gpt-6-luna", "promptTokens": 2000, "completionTokens": 400, "cachedTokens": 0}


@given('an execution of the knowledge run for "{site}" that started on {day}')
def step_execution(context, site, day):
    for name, value in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        os.environ.setdefault(name, value)
    context.moto = mock_aws()
    context.moto.start()
    context.add_cleanup(context.moto.stop)
    context.table_ = boto3.resource("dynamodb", region_name="us-east-1").create_table(
        TableName="knowledge-ledger",
        KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}, {"AttributeName": "runKey", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}, {"AttributeName": "runKey", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    context.environment = {
        "KNOWLEDGE_PUBLICATION": site, "KNOWLEDGE_EXECUTION_NAME": "scheduled-1", "KNOWLEDGE_EXECUTION_START": f"{day}T05:00:12Z",
        "KNOWLEDGE_OPENAI_KEY_PARAMETER": f"/papyrus/{site}/openai-api-key", "KNOWLEDGE_LEDGER_TABLE": "knowledge-ledger",
        "MONITOR_STORIES_ENDPOINT": ENDPOINT, "AWS_REGION": "us-east-1",
    }
    context.calls, context.calls_made, context.drafted, context.command_fails, context.accounting_fails = [], 0, 3, False, False
    context.outcome = context.skip = context.failure = None


@given("the site's monitorStories limit is {limit:d}")
def step_limit(context, limit):
    context.environment["MONITOR_STORIES_LIMIT"] = str(limit)


@given('the task is configured with the knowledge corpus key "{key}"')
def step_corpus_key(context, key):
    context.environment["KNOWLEDGE_CORPUS_KEY"] = key


@given("the command drafted {drafts:d} stories with {calls:d} model calls")
def step_drafted(context, drafts, calls):
    context.drafted, context.calls_made = drafts, calls


@given("the command fails")
def step_fails(context):
    context.command_fails = True


@given("the cost accounting fails")
def step_accounting(context):
    context.accounting_fails = True


@given("the setting {setting} is {value}")
def step_setting(context, setting, value):
    context.environment[setting] = "" if value == "empty" else value


def fake_command(context):
    def execute(args, environment):
        context.calls.append((args, dict(environment)))
        if context.command_fails:
            return 3, ""
        run = {"attempted": context.drafted, "invalid": [], "skipped": [], "duplicates": [], "inputs": {"candidates": 9, "alreadyDrafted": 0},
               "drafts": [{"ideaId": f"idea-{n}", "body": "x" * 3000} for n in range(context.drafted)], "review": {"status": "requested"},
               "modelCalls": [CALL] * (context.calls_made or context.drafted)}
        return 0, "announcement\n" + json.dumps({"ok": True, "run": run})

    return execute


@when("the monitor-stories step runs")
def step_run(context):
    import unittest.mock as mock

    patches = []
    if context.accounting_fails:
        patches.append(mock.patch("papyrus_content.knowledge_cloud.cost.stage_cost", side_effect=RuntimeError("no price file")))
    for patch in patches:
        patch.start()
        context.add_cleanup(patch.stop)
    import contextlib
    import io

    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            context.outcome = job.run(context.environment, read_key=lambda name: "sk-test-key", execute=fake_command(context), task_info=lambda: dict(TASK))
    except job.Skip as skip:
        context.skip = str(skip)
    except Exception as error:  # noqa: BLE001
        context.failure = error
    context.logged = printed.getvalue()
    if context.failure is not None:  # main() turns a failure into a log line and a zero exit
        error = io.StringIO()
        with contextlib.redirect_stderr(error), mock.patch.object(job, "run", side_effect=context.failure):
            context.exit_code = job.main()
        context.logged = error.getvalue()


def row(context):
    key = {"publication": context.environment["KNOWLEDGE_PUBLICATION"], "runKey": run_key("2026-W44", "scheduled-1", "monitor-stories")}
    item = context.table_.get_item(Key=key).get("Item")
    return from_dynamo(item) if item else None


@then('the command "papyrus ideas monitor-stories" runs once for "{site}" with the limit {limit:d} and the Proposals store')
def step_command(context, site, limit):
    assert len(context.calls) == 1
    args = context.calls[0][0]
    assert args[:5] == ["papyrus", "ideas", "monitor-stories", "--site", site] and args[args.index("--limit") + 1] == str(limit) and args[args.index("--store") + 1] == "items", args


@then("the command runs with the limit {limit:d}")
def step_default(context, limit):
    args = context.calls[0][0]
    assert args[args.index("--limit") + 1] == str(limit)


@then("the command runs as the task role and the key is only in its environment")
def step_environment(context):
    args, environment = context.calls[0]
    assert environment["PAPYRUS_GRAPHQL_AUTH"] == "iam" and environment["PAPYRUS_GRAPHQL_ENDPOINT"] == ENDPOINT and environment["OPENAI_API_KEY"] == "sk-test-key"
    assert "sk-test-key" not in " ".join(args)


@then('the ledger has a succeeded "monitor-stories" row for the week "{week}" and the execution')
def step_row(context, week):
    saved = row(context)
    assert saved and (saved["status"], saved["week"], saved["execution"]) == ("succeeded", week, "scheduled-1"), saved


@then("the row records the model calls, their tokens and their cost, and the compute cost of the step")
def step_cost(context):
    cost = row(context)["details"]["cost"]
    assert cost["llm"]["calls"] == context.calls_made or cost["llm"]["calls"] == context.drafted
    assert cost["llm"]["inputTokens"] > 0 and cost["llm"]["usd"] > 0 and cost["computeUsd"] > 0 and cost["totalUsd"] > 0


@then("the row records how many stories were filed but not the stories themselves")
def step_result(context):
    saved = row(context)
    assert saved["details"]["result"]["filed"] == context.drafted and "x" * 100 not in json.dumps(saved)


@then('the ledger has a failed "monitor-stories" row with the error')
def step_failed(context):
    saved = row(context)
    assert saved["status"] == "failed" and "exited with 3" in saved["error"]


@then("the step logs the failure and exits successfully")
def step_logged(context):
    assert context.exit_code == 0 and "monitor-stories: failed:" in context.logged


@then('the ledger has a succeeded "monitor-stories" row without a cost')
def step_no_cost(context):
    saved = row(context)
    assert saved["status"] == "succeeded" and "cost" not in saved["details"]


@then("the step logs that cost accounting was skipped")
def step_accounting_logged(context):
    assert context.outcome and "cost accounting skipped" in context.logged


@then("the step is skipped, nothing is called and the ledger has no row")
def step_skipped(context):
    assert context.skip and context.calls == [] and context.table_.scan()["Items"] == []


@then('the command was given the corpus key "{key}" beside the site "{site}"')
def step_corpus_args(context, key, site):
    args = context.calls[0][0]
    assert args[args.index("--corpus-key") + 1] == key and args[args.index("--site") + 1] == site, args


@then("the command was not given a corpus key")
def step_no_corpus_args(context):
    assert "--corpus-key" not in context.calls[0][0], context.calls[0][0]
