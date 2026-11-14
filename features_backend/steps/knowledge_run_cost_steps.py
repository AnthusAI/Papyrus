from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_cloud import stages as stages_module  # noqa: E402
from papyrus_content.knowledge_cloud.ai_review_test import node  # noqa: E402
from papyrus_content.knowledge_cloud.config import STAGES  # noqa: E402
from papyrus_content.knowledge_cloud.cost_test import HOUR, UsageModel, prepare_review, row, run_all, stored_cost  # noqa: E402
from papyrus_content.knowledge_cloud.fakes import STAGE_SECONDS, make_run  # noqa: E402
from papyrus_content.knowledge_cloud.runs import knowledge_runs  # noqa: E402
from papyrus_content.knowledge_cloud.stages_test import FakeServices  # noqa: E402

QUOTE = "OpenBMB released VoxCPM2, a 2B-parameter text-to-speech model"


def close(a, b):
    return abs(a - b) < 1e-5


@given("the AI review will run with a model that reports {inp:d} input tokens, {cached:d} of them cached, and {out:d} output tokens per call")
def step_usage(context, inp, cached, out):
    context.usage = {"input_tokens": inp, "output_tokens": out, "input_tokens_details": {"cached_tokens": cached}}
    context.per_call = (inp - cached, cached, out)
    arrange_review(context, context.usage)


@given("the AI review will run with a model that reports no usage")
def step_no_usage(context):
    arrange_review(context, None)


def arrange_review(context, usage):
    import papyrus_content.records as records

    prepare_review(context.run_)
    original = records.apply_record_changes
    records.apply_record_changes = lambda client, changes: None
    context.add_cleanup(lambda: setattr(records, "apply_record_changes", original))
    services = FakeServices([node("VoxCPM2"), node("27B")], {"VoxCPM2": {"verdict": "accept", "evidence": [QUOTE]}})
    services.model = lambda api_key, guidance: UsageModel(services.answers, usage)
    context.run_.services = services


@when("the AI review stage runs")
def step_run_review(context):
    context.code = stages_module.run_stage("ai-review", context.run_)
    assert context.code == 0


@then('the cost of "{stage}" says it ran {seconds:d} seconds on {cpu:d} vCPU and {memory:d} GB')
def step_size(context, stage, seconds, cpu, memory):
    spent = stored_cost(context.run_, stage)
    assert (spent["computeSeconds"], spent["vCpu"], spent["memoryGiB"]) == (seconds, cpu, memory), spent


@then('the compute cost of "{stage}" is the ARM rate for that size and time')
def step_compute(context, stage):
    assert close(stored_cost(context.run_, stage)["computeUsd"], HOUR * STAGE_SECONDS / 3600)


@then('the cost of "{stage}" says it made no model calls and its total is the compute cost')
def step_no_calls(context, stage):
    spent = stored_cost(context.run_, stage)
    assert spent["llm"]["calls"] == 0 and spent["totalUsd"] == spent["computeUsd"], spent


@then('the cost of "{stage}" counts the model calls and their tokens')
def step_counts(context, stage):
    llm = stored_cost(context.run_, stage)["llm"]
    inp, cached, out = context.per_call
    assert llm["calls"] >= 1 and llm["inputTokens"] == (inp + cached) * llm["calls"] and llm["outputTokens"] == out * llm["calls"], llm


@then('the model cost of "{stage}" is priced from the model price table')
def step_priced(context, stage):
    llm = stored_cost(context.run_, stage)["llm"]
    inp, cached, out = context.per_call
    assert close(llm["usd"], (inp * 0.10 + cached * 0.01 + out * 0.50) / 1_000_000 * llm["calls"]), llm


@then('the cost of "{stage}" lists the calls by model')
def step_by_model(context, stage):
    llm = stored_cost(context.run_, stage)["llm"]
    assert sum(entry["calls"] for entry in llm["byModel"].values()) == llm["calls"] and llm["byModel"], llm


@then('the total cost of "{stage}" is compute plus model')
def step_total(context, stage):
    spent = stored_cost(context.run_, stage)
    assert close(spent["totalUsd"], spent["computeUsd"] + spent["llm"]["usd"]), spent


@then('the cost of "{stage}" counts the model calls and says the price is unknown because the responses carried no usage')
def step_unknown(context, stage):
    llm = stored_cost(context.run_, stage)["llm"]
    assert llm["calls"] >= 1 and llm["usd"] is None and "no usage object" in llm["reason"], llm


@then('the cost of "{stage}" is marked partial and its total is the compute cost')
def step_partial(context, stage):
    spent = stored_cost(context.run_, stage)
    assert spent["partial"] is True and spent["totalUsd"] == spent["computeUsd"], spent


@then('the ledger row of "{stage}" holds the cost of {seconds:d} seconds')
def step_failed_cost(context, stage, seconds):
    item = row(context.run_, stage)
    assert item["status"] == "failed" and int(item["details"]["cost"]["computeSeconds"]) == seconds, item


@when('the command "{text}" works again')
def step_works(context, text):
    context.shell.fail_on = None


@then('the cost of "{stage}" says {attempts:d} attempts and {seconds:d} seconds')
def step_attempts(context, stage, attempts, seconds):
    spent = stored_cost(context.run_, stage)
    assert (spent["attempts"], spent["computeSeconds"]) == (attempts, seconds), spent


@given("the task size cannot be read")
def step_unreadable(context):
    def broken():
        raise RuntimeError("metadata endpoint down")

    context.run_.task_info = broken


@then('the ledger row of "{stage}" holds no cost')
def step_no_cost(context, stage):
    assert "cost" not in row(context.run_, stage)["details"]


@then('the ledger row of "{stage}" holds a cost')
def step_has_cost(context, stage):
    assert "cost" in row(context.run_, stage)["details"]


@given("every stage of the run has succeeded")
@when("every stage of the run has succeeded")
def step_all(context):
    run_all(context.run_)


@given('every stage of execution "{execution}" has succeeded')
def step_all_other(context, execution):
    other, _shell = make_run(context.work / execution, execution=execution)
    run_all(other)


@then("the run row says succeeded with the total of the stages and {seconds:d} seconds of compute")
def step_run_row(context, seconds):
    total = stored_cost(context.run_, "run")
    stages = sum(stored_cost(context.run_, stage)["totalUsd"] for stage in STAGES)
    assert total["status"] == "succeeded" and total["computeSeconds"] == seconds and close(total["totalUsd"], stages), total


@then("the report lists every stage")
def step_report(context):
    report = json.loads(context.run_.state.read_text("runs/2026-W44/cost-manual-1.json"))
    assert set(report["cost"]["stages"]) == set(STAGES), report


@then("there is no run row")
def step_no_run_row(context):
    assert "Item" not in context.run_.ledger.table.get_item(Key={"publication": "shipped", "runKey": "2026-W44#manual-1#run"})


@when('an operator lists the runs with "papyrus {command}"')
def step_operator(context, command):
    words = command.split()
    assert words[:2] == ["knowledge", "runs"], command
    context.output = []
    knowledge_runs(words[2:], table=context.run_.ledger.table, out=context.output.append)
    context.shown = "\n".join(context.output)


@then("the output starts with the week, the execution, the status and the total cost")
def step_header(context):
    first = context.shown.splitlines()[0]
    assert first.startswith("2026-W44  manual-1  succeeded") and "total $" in first, first


@then("the output has a line for every stage with its time and cost")
def step_lines(context):
    lines = context.shown.splitlines()
    for stage in STAGES:
        line = next(line for line in lines if line.strip().startswith(stage))
        assert "$" in line, line


@then("the output is JSON for {count:d} run with its total cost")
def step_json(context, count):
    runs = json.loads(context.shown)
    assert len(runs) == count and runs[0]["totalUsd"] > 0 and runs[0]["status"] == "succeeded", runs
