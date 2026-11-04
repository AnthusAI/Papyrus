from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.cloud_procedures import write_llm_context_trace_artifacts


@given("the newsroom sections seed file")
def step_given_newsroom_sections_seed(context):
    sections_path = REPO_ROOT / "corpora" / "threat-intelligence-newsroom-sections.yml"
    parsed = yaml.safe_load(sections_path.read_text(encoding="utf-8"))
    sections = parsed.get("sections") if isinstance(parsed, dict) else None
    assert isinstance(sections, list) and sections, "sections seed must contain non-empty sections list"
    context.sections_seed = sections


@when('I read the section with id "{section_id}"')
def step_when_read_section(context, section_id):
    section = next((entry for entry in context.sections_seed if str(entry.get("id")) == section_id), None)
    assert section is not None, f"section {section_id} not found in seed"
    context.selected_section = section


@then(
    "its editorial policy prefers journalistic and official sources over academic papers as the default"
)
def step_then_section_policy_prefers_journalistic_sources(context):
    policy = context.selected_section.get("editorialPolicy") or context.selected_section.get("policies") or []
    if isinstance(policy, str):
        policy_text = policy
    elif isinstance(policy, list):
        policy_text = "\n".join(str(line) for line in policy)
    else:
        policy_text = str(policy)
    required_fragments = [
        "journalistic",
        "official",
        "academic",
        "background",
    ]
    for fragment in required_fragments:
        assert fragment in policy_text.lower(), f"expected '{fragment}' in news section policy"


@given("the seeded newsroom procedure sources")
def step_given_seeded_newsroom_procedure_sources(context):
    context.research_procedure_source = (REPO_ROOT / "procedures" / "newsroom" / "research_explorer.tac").read_text(
        encoding="utf-8"
    )
    context.reporting_procedure_source = (REPO_ROOT / "procedures" / "newsroom" / "reporter.tac").read_text(
        encoding="utf-8"
    )


@then("the research explorer procedure requires one broad knowledge_query before web search")
def step_then_research_requires_broad_knowledge_first(context):
    source = context.research_procedure_source
    broad_index = source.find("Run one broad knowledge_query")
    web_index = source.find("web.search")
    assert broad_index >= 0, "research_explorer.tac must require one broad knowledge_query"
    assert web_index >= 0, "research_explorer.tac must define web search guidance"
    assert broad_index < web_index, "knowledge_query orientation must appear before web search guidance"


@then("the reporter procedure requires one broad knowledge_query before optional web checks")
def step_then_reporter_requires_broad_knowledge_first(context):
    source = context.reporting_procedure_source
    broad_index = source.find("one broad knowledge_query")
    web_index = source.find("web freshness checks")
    if web_index < 0:
        web_index = source.find("web.search")
    assert broad_index >= 0, "reporter.tac must require one broad knowledge_query"
    assert web_index >= 0, "reporter.tac must define optional web checks guidance"
    assert broad_index < web_index, "knowledge_query orientation must appear before optional web checks"


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
