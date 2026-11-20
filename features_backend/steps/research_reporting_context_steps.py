from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.cloud_procedures import write_llm_context_trace_artifacts


@given("sample cloud procedure stdout with one LLM payload and one execute_tactus call")
def step_given_sample_cloud_stdout(context):
    context.sample_stdout = "\n".join(
        [
            "Running procedure: reporter.tac (lua format)",
            "2026-05-27 00:10:52,799 DEBUG tactus.dspy.agent: Agent 'newsroom_reporter' turn 1",
            "2026-05-27 00:10:52,801 DEBUG tactus.dspy.module: [RAWMODULE] LLM messages payload:",
            "[",
            '  {"role": "system", "content": "Reporter system prompt"},',
            '  {"role": "user", "content": "Build reporting context"}',
            "]",
            "→ Agent newsroom_reporter: Waiting for response...",
            "→ Tool execute_tactus",
            "  Args: {",
            '  "harness": "raw",',
            '  "assignment_id": "assignment-ctx-1",',
            '  "corpus_key": "AI-ML-research",',
            '  "tactus": "return assignment_context{ id = \\\"assignment-ctx-1\\\" }"',
            "}",
            "  Result: {'ok': True, 'value': {'assignment_context': {}}}",
            json.dumps({"reporting_context_packet": {"summary": "ok"}, "assignment_item_id": "assignment-ctx-1"}),
        ]
    )


@when("I build llm-context trace artifacts")
def step_when_build_llm_context_artifacts(context):
    tempdir = tempfile.TemporaryDirectory()
    context._tempdir = tempdir
    run_dir = Path(tempdir.name)
    stdout_path = run_dir / "reporting.stdout.log"
    stdout_path.write_text(context.sample_stdout, encoding="utf-8")
    context.trace_result = write_llm_context_trace_artifacts(
        run_dir=run_dir,
        alias="assignments.run-reporting",
        procedure_key="newsroom.reporting.context",
        run_id="procedure-run-test",
        input_payload={"assignment_item_id": "assignment-ctx-1"},
        stdout=context.sample_stdout,
        stdout_path=stdout_path,
    )


@then("the summary includes one llm call and one execute_tactus call")
def step_then_trace_summary_counts(context):
    summary = json.loads(Path(context.trace_result["llmContextSummaryPath"]).read_text(encoding="utf-8"))
    assert summary["llmCallCount"] == 1
    assert summary["executeTactusCallCount"] == 1


@then("llm-context calls.jsonl exists with one record")
def step_then_llm_calls_file_exists(context):
    llm_calls_path = Path(context.trace_result["llmContextLlmCallsPath"])
    assert llm_calls_path.exists(), "llm calls trace file missing"
    lines = [line for line in llm_calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, "expected one llm call trace record"


@then("llm-context execute_tactus_calls.jsonl exists with one record")
def step_then_execute_tactus_calls_file_exists(context):
    execute_calls_path = Path(context.trace_result["llmContextCallsPath"])
    assert execute_calls_path.exists(), "execute_tactus trace file missing"
    lines = [line for line in execute_calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1, "expected one execute_tactus trace record"
