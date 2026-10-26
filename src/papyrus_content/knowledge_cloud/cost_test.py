import datetime as dt
import json
import itertools

import pytest
from moto import mock_aws

from . import cost
from .ai_review_test import Model
from .config import STAGES
from .fakes import STAGE_SECONDS, make_run
from .ledger import run_key
from .stages import run_stage

# 4 vCPU, 16 GB, 40 GiB of storage (20 GiB over the free allowance) for one hour
HOUR = 4 * 0.03238 + 16 * 0.00356 + 20 * 0.000111
KEY = {"publication": "shipped"}


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    for name, value in {"AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(name, value)
    with mock_aws():
        yield


def row(run, stage):
    return run.ledger.table.get_item(Key={**KEY, "runKey": run_key("2026-W44", run.config.execution_name, stage)})["Item"]


def stored_cost(run, stage):
    from .ledger import from_dynamo

    return from_dynamo(row(run, stage)["details"]["cost"])


class UsageModel(Model):
    """The reviewer with an API that reports usage, as the Responses API does."""

    def __init__(self, answers, usage=None, **kwargs):
        super().__init__(answers, **kwargs)
        self.usage_body = usage

    def transport(self, url, headers, payload):
        body = super().transport(url, headers, payload)
        if self.usage_body is not None:
            body = {**body, "model": "gpt-6-luna-2026-09-01", "usage": self.usage_body}
        return body


def test_fargate_arm_rates_price_a_task_by_the_second():
    assert cost.compute_usd(3600, 4, 16, 40) == pytest.approx(HOUR, abs=1e-6)
    assert cost.compute_usd(3600, 4, 16, 20) == pytest.approx(4 * 0.03238 + 16 * 0.00356, abs=1e-6)  # 20 GiB is free


def test_a_stage_records_its_compute_with_the_size_of_the_task(tmp_path):
    run, _shell = make_run(tmp_path)
    assert run_stage("corpus-sync", run) == 0
    spent = stored_cost(run, "corpus-sync")
    assert (spent["computeSeconds"], spent["vCpu"], spent["memoryGiB"], spent["ephemeralStorageGiB"]) == (STAGE_SECONDS, 4, 16, 40)
    assert spent["computeUsd"] == pytest.approx(HOUR * STAGE_SECONDS / 3600, abs=1e-6)
    assert spent["llm"] == {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "usd": 0.0, "byModel": {}}
    assert spent["totalUsd"] == spent["computeUsd"] and "partial" not in spent and "2026-10-26" in spent["priceBasis"]


def test_fargate_bills_at_least_a_minute_and_from_the_image_pull_when_the_platform_says_so():
    now = dt.datetime(2026, 10, 26, 6, tzinfo=dt.timezone.utc)
    quick = cost.stage_cost(elapsed_seconds=3, task={"vCpu": 1, "memoryGiB": 2, "ephemeralStorageGiB": 20, "startedAt": None}, now=now, calls=[])
    assert quick["computeSeconds"] == 60 and quick["computeBasis"] == "stage"
    pulled = cost.stage_cost(elapsed_seconds=100, task={"vCpu": 1, "memoryGiB": 2, "ephemeralStorageGiB": 20, "startedAt": now - dt.timedelta(seconds=190)}, now=now, calls=[])
    assert pulled["computeSeconds"] == 190 and pulled["computeBasis"] == "task"


def test_an_unknown_task_size_gives_a_null_compute_cost_with_the_reason():
    spent = cost.stage_cost(elapsed_seconds=100, task={}, now=dt.datetime.now(dt.timezone.utc), calls=[])
    assert spent["computeUsd"] is None and "task size is unknown" in spent["computeReason"]
    assert spent["totalUsd"] == 0.0 and spent["partial"] is True


def test_the_task_size_comes_from_the_ecs_task_metadata():
    metadata = {"Limits": {"CPU": 4, "Memory": 16384}, "EphemeralStorageMetrics": {"Utilized": 300, "Reserved": 40960}, "PullStartedAt": "2026-10-26T05:58:11.44527186Z"}
    task = cost.task_resources({}, fetch=lambda _env: metadata)
    assert (task["vCpu"], task["memoryGiB"], task["ephemeralStorageGiB"]) == (4.0, 16.0, 40)
    assert task["startedAt"] == dt.datetime(2026, 10, 26, 5, 58, 11, 445271, tzinfo=dt.timezone.utc)
    assert cost.task_resources({"KNOWLEDGE_TASK_VCPU": "2", "KNOWLEDGE_TASK_MEMORY_MIB": "8192"}, fetch=lambda _e: {})["memoryGiB"] == 8.0

    def broken(_env):
        raise OSError("no endpoint")

    assert cost.task_resources({}, fetch=broken)["vCpu"] is None


def prepare_review(run):
    from .ai_review_test import TEXT, TYPED

    for stage in ("corpus-sync", "topic-model", "typed-extraction"):
        run_stage(stage, run)
    (run.run_dir / "typed").mkdir(parents=True, exist_ok=True)
    (run.run_dir / "typed" / "output.json").write_text(json.dumps(TYPED))
    texts = run.corpus / "extracted" / "pipeline" / "ext1" / "text"
    texts.mkdir(parents=True)
    (texts / "i1.txt").write_text(TEXT)
    run.push(corpus=True, run=True)


def review(tmp_path, monkeypatch, usage):
    from .ai_review_test import node
    from .stages_test import FakeServices

    run, _shell = make_run(tmp_path)
    prepare_review(run)
    monkeypatch.setattr("papyrus_content.records.apply_record_changes", lambda client, changes: None)
    quote = "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model"
    services = FakeServices([node("VoxCPM2"), node("27B")], {"VoxCPM2": {"verdict": "accept", "evidence": [quote]}})
    services.model = lambda api_key, guidance: UsageModel(services.answers, usage)
    run.services = services
    assert run_stage("ai-review", run) == 0
    return run


def test_the_ai_review_records_the_usage_the_api_reported_priced_per_model(tmp_path, monkeypatch):
    run = review(tmp_path, monkeypatch, {"input_tokens": 1000, "output_tokens": 100, "input_tokens_details": {"cached_tokens": 200}})
    spent = stored_cost(run, "ai-review")
    llm = spent["llm"]
    assert llm["calls"] >= 1
    per_call = (800 * 0.10 + 200 * 0.01 + 100 * 0.50) / 1_000_000
    assert llm["inputTokens"] == 1000 * llm["calls"] and llm["outputTokens"] == 100 * llm["calls"] and llm["cachedInputTokens"] == 200 * llm["calls"]
    assert llm["usd"] == pytest.approx(per_call * llm["calls"], abs=1e-6)
    assert list(llm["byModel"]) == ["gpt-6-luna-2026-09-01"] and llm["byModel"]["gpt-6-luna-2026-09-01"]["calls"] == llm["calls"]
    assert spent["totalUsd"] == pytest.approx(spent["computeUsd"] + llm["usd"], abs=1e-6) and "partial" not in spent


def test_a_response_without_usage_counts_the_call_with_a_null_price_and_a_reason(tmp_path, monkeypatch):
    run = review(tmp_path, monkeypatch, None)
    spent = stored_cost(run, "ai-review")
    assert spent["llm"]["calls"] >= 1 and spent["llm"]["usd"] is None and "no usage object" in spent["llm"]["reason"]
    assert spent["partial"] is True and spent["totalUsd"] == spent["computeUsd"]


def test_a_model_with_no_price_is_counted_and_left_unpriced():
    calls = [{"model": "mystery-1", "promptTokens": 10, "completionTokens": 5, "cachedTokens": 0}]
    llm = cost.llm_cost(calls, prices={})
    assert llm["calls"] == 1 and llm["inputTokens"] == 10 and llm["usd"] is None and "no price for model mystery-1" in llm["reason"]


def test_usage_is_read_from_the_responses_body():
    body = {"model": "gpt-6-luna", "usage": {"input_tokens": 7, "output_tokens": 3, "input_tokens_details": {"cached_tokens": 2}}}
    assert cost.usage_entry("x", body) == {"model": "gpt-6-luna", "promptTokens": 7, "completionTokens": 3, "cachedTokens": 2}
    assert cost.usage_entry("gpt-6-luna", {}) == {"model": "gpt-6-luna", "usageMissing": True}


def test_a_failed_attempt_is_paid_for_and_the_retry_adds_to_it(tmp_path):
    run, shell = make_run(tmp_path)
    shell.fail_on = "knowledge snapshot"
    assert run_stage("snapshot", run) == 1
    failed = row(run, "snapshot")
    assert failed["status"] == "failed" and failed["details"]["cost"]["computeSeconds"] == STAGE_SECONDS
    shell.fail_on = None
    assert run_stage("snapshot", run) == 0
    spent = stored_cost(run, "snapshot")
    assert spent["attempts"] == 2 and spent["computeSeconds"] == 2 * STAGE_SECONDS
    assert spent["computeUsd"] == pytest.approx(HOUR * 2 * STAGE_SECONDS / 3600, abs=1e-6)


def test_cost_accounting_never_fails_a_stage(tmp_path):
    run, _shell = make_run(tmp_path)

    def broken():
        raise RuntimeError("metadata endpoint down")

    run.task_info = broken
    assert run_stage("snapshot", run) == 0
    assert "cost" not in row(run, "snapshot")["details"]


def run_all(run):
    for stage in STAGES:
        functions = {"ai-review": lambda _run: {}} if stage == "ai-review" else None
        assert run_stage(stage, run, functions) == 0, stage


def test_the_last_stage_sums_the_run_into_a_run_row_and_the_state_bucket(tmp_path):
    run, _shell = make_run(tmp_path)
    run_all(run)
    total = stored_cost(run, "run")
    stages = [stored_cost(run, stage)["totalUsd"] for stage in STAGES]
    assert total["status"] == "succeeded" and list(total["stages"]) == list(STAGES)
    assert total["totalUsd"] == pytest.approx(sum(stages), abs=1e-5) and total["computeSeconds"] == len(STAGES) * STAGE_SECONDS
    assert total["llm"]["calls"] == 0 and "partial" not in total
    report = json.loads(run.state.read_text("runs/2026-W44/cost-manual-1.json"))
    assert report["execution"] == "manual-1" and report["cost"]["totalUsd"] == total["totalUsd"]
    assert row(run, "run")["stage"] == "run"


def test_a_run_that_stops_early_has_no_run_row_but_its_stages_still_have_cost(tmp_path):
    run, shell = make_run(tmp_path)
    shell.fail_on = "knowledge snapshot"
    run_stage("corpus-sync", run)
    assert run_stage("snapshot", run) == 1
    assert "Item" not in run.ledger.table.get_item(Key={**KEY, "runKey": run_key("2026-W44", "manual-1", "run")})
    assert stored_cost(run, "snapshot")["computeSeconds"] == STAGE_SECONDS


def test_a_stage_from_before_cost_accounting_makes_the_total_partial():
    rows = [{"stage": "corpus-sync", "status": "succeeded", "startedAt": "2026-10-26T05:00:00Z", "finishedAt": "2026-10-26T05:03:00Z", "details": {}}]
    total = cost.run_total(rows, STAGES)
    assert total["partial"] is True and total["totalUsd"] == 0.0 and total["durationSeconds"] == 180 and total["status"] == "running"
