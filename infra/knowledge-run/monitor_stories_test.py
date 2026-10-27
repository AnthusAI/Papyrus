"""Tests for the monitor-stories job step (infra/knowledge-run/monitor_stories.py): the command it runs, its ledger row and its cost."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from papyrus_content.knowledge_cloud.ledger import from_dynamo, run_key

_spec = importlib.util.spec_from_file_location("monitor_stories_job", Path(__file__).with_name("monitor_stories.py"))
job = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(job)

ENDPOINT = "https://imnmexcbrzcddk2g4vl6hsn7ie.appsync-api.us-east-1.amazonaws.com/graphql"
BASE = {
    "KNOWLEDGE_PUBLICATION": "shipped",
    "KNOWLEDGE_EXECUTION_NAME": "scheduled-1",
    "KNOWLEDGE_EXECUTION_START": "2026-10-28T05:00:12.345Z",  # ISO week 2026-W44
    "KNOWLEDGE_OPENAI_KEY_PARAMETER": "/papyrus/shipped/openai-api-key",
    "KNOWLEDGE_LEDGER_TABLE": "knowledge-ledger",
    "MONITOR_STORIES_ENDPOINT": ENDPOINT,
    "AWS_REGION": "us-east-1",
}
TASK = {"vCpu": 4.0, "memoryGiB": 16.0, "ephemeralStorageGiB": 40, "startedAt": None}
RUN = {
    "kind": "monitor-stories-run", "attempted": 3, "invalid": [{"reason": "citation_check_failed"}], "skipped": [], "duplicates": [],
    "inputs": {"candidates": 9, "alreadyDrafted": 2}, "drafts": [{"ideaId": "a", "body": "x" * 5000}, {"ideaId": "b", "body": "y"}], "review": {"status": "requested"},
    "modelCalls": [{"model": "gpt-6-luna", "promptTokens": 2000, "completionTokens": 400, "cachedTokens": 0}] * 3,
}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="knowledge-ledger",
            KeySchema=[{"AttributeName": "publication", "KeyType": "HASH"}, {"AttributeName": "runKey", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "publication", "AttributeType": "S"}, {"AttributeName": "runKey", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield table


def row(table, execution="scheduled-1"):
    return from_dynamo(table.get_item(Key={"publication": "shipped", "runKey": run_key("2026-W44", execution, "monitor-stories")})["Item"])


def answer(run=RUN, status=0):
    return lambda args, env: (status, "announcement line\n" + json.dumps({"ok": True, "command": "ideas monitor-stories", "run": run}, indent=2))


def go(environment=BASE, **kwargs):
    return job.run(environment, read_key=kwargs.pop("read_key", lambda name: "sk-test"), task_info=lambda: dict(TASK), **kwargs)


def test_it_runs_the_command_once_with_iam_and_the_key_only_in_the_child_environment():
    calls = []
    outcome = go(execute=lambda args, env: calls.append((args, env)) or answer()(args, env))
    [(args, env)] = calls
    assert args == ["papyrus", "ideas", "monitor-stories", "--site", "shipped", "--store", "proposals", "--limit", "3", "--json"]
    assert env["PAPYRUS_GRAPHQL_AUTH"] == "iam" and env["PAPYRUS_GRAPHQL_ENDPOINT"] == ENDPOINT and env["OPENAI_API_KEY"] == "sk-test"
    assert "sk-test" not in " ".join(args) and "sk-test" not in outcome
    assert outcome.startswith("filed 2 of 9 candidates (3 attempted, 1 failed the check)")


def test_the_limit_is_configuration():
    calls = []
    go({**BASE, "MONITOR_STORIES_LIMIT": "5"}, execute=lambda args, env: calls.append(args) or answer()(args, env))
    assert calls[0][calls[0].index("--limit") + 1] == "5"


def test_the_step_writes_a_ledger_row_with_its_cost_like_a_stage(aws):
    go(execute=answer())
    saved = row(aws)
    assert (saved["status"], saved["stage"], saved["attempts"], saved["week"]) == ("succeeded", "monitor-stories", 1, "2026-W44")
    cost = saved["details"]["cost"]
    assert cost["llm"]["calls"] == 3 and (cost["llm"]["inputTokens"], cost["llm"]["outputTokens"]) == (6000, 1200)
    assert cost["llm"]["usd"] > 0 and cost["llm"]["byModel"]["gpt-6-luna"]["calls"] == 3
    assert cost["computeUsd"] > 0 and cost["totalUsd"] == pytest.approx(cost["computeUsd"] + cost["llm"]["usd"])
    assert saved["details"]["result"] == {"filed": 2, "attempted": 3, "candidates": 9, "alreadyDrafted": 2, "failedTheCheck": 1, "skipped": 0, "duplicates": 0, "review": "requested"}
    assert "x" * 100 not in json.dumps(saved), "the drafts themselves are not kept in the ledger"


def test_a_failed_command_marks_the_row_failed_with_the_cost_so_far_and_raises(aws):
    with pytest.raises(RuntimeError, match="exited with 3"):
        go(execute=lambda args, env: (3, ""))
    saved = row(aws)
    assert saved["status"] == "failed" and "exited with 3" in saved["error"]
    assert saved["details"]["cost"]["llm"]["calls"] == 0


def test_a_command_that_prints_no_run_is_a_failure(aws):
    with pytest.raises(ValueError, match="no JSON"):
        go(execute=lambda args, env: (0, "nothing useful"))
    assert row(aws)["status"] == "failed"


def test_accounting_that_goes_wrong_never_gets_in_the_way(aws, capsys, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("no price file")

    monkeypatch.setattr("papyrus_content.knowledge_cloud.cost.stage_cost", broken)
    outcome = go(execute=answer())
    assert outcome.startswith("filed 2")
    saved = row(aws)
    assert saved["status"] == "succeeded" and "cost" not in saved["details"]
    assert "cost accounting skipped" in capsys.readouterr().out


def test_the_ledger_is_opened_from_the_environment_when_none_is_given(aws):
    go(execute=answer(), ledger=None)
    assert row(aws)["status"] == "succeeded"


@pytest.mark.parametrize("change", [
    {"MONITOR_STORIES_ENDPOINT": ""},
    {"MONITOR_STORIES_ENDPOINT": "https://evil.example.com/graphql"},
    {"KNOWLEDGE_OPENAI_KEY_PARAMETER": ""},
    {"KNOWLEDGE_PUBLICATION": ""},
    {"KNOWLEDGE_EXECUTION_START": ""},
    {"MONITOR_STORIES_LIMIT": "many"},
    {"MONITOR_STORIES_LIMIT": "0"},
])
def test_missing_or_odd_configuration_is_a_skip_before_any_call_or_ledger_row(aws, change):
    def no_run(args, env):
        raise AssertionError("ran")

    with pytest.raises(job.Skip):
        go({**BASE, **change}, execute=no_run, read_key=lambda name: pytest.fail("read the key"))
    assert aws.scan()["Items"] == []


def test_main_never_fails_the_run(monkeypatch, capsys):
    monkeypatch.setattr(job, "run", lambda environment: (_ for _ in ()).throw(RuntimeError("boom")))
    assert job.main() == 0
    assert "monitor-stories: failed: RuntimeError: boom" in capsys.readouterr().err
    monkeypatch.setattr(job, "run", lambda environment: (_ for _ in ()).throw(job.Skip("MONITOR_STORIES_ENDPOINT is not an AppSync GraphQL address")))
    assert job.main() == 0
    assert "monitor-stories: skipped:" in capsys.readouterr().out


def test_a_corpus_key_of_its_own_is_passed_to_the_command_and_the_default_is_not():
    calls = []
    go({**BASE, "KNOWLEDGE_CORPUS_KEY": "ai-ml-research"}, execute=lambda args, env: calls.append(args) or answer()(args, env))
    assert calls[0][calls[0].index("--corpus-key") + 1] == "ai-ml-research" and calls[0][calls[0].index("--site") + 1] == "shipped"
    plain = []
    go({**BASE, "KNOWLEDGE_CORPUS_KEY": "shipped"}, execute=lambda args, env: plain.append(args) or answer()(args, env))
    assert "--corpus-key" not in plain[0], "a key equal to the publication is the default: the command line is what it was"
