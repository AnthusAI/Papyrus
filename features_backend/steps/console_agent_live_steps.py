from __future__ import annotations

import json
import os
import re
from pathlib import Path

from behave import given, then, when

from live_console_agent_smoke import run_scenario


@given("live console agent tests are enabled")
def step_live_console_agent_tests_enabled(context) -> None:
    assert (
        os.environ.get("PAPYRUS_LIVE_AGENT_BDD") == "1"
    ), "Set PAPYRUS_LIVE_AGENT_BDD=1 to run live LLM/AppSync console-agent BDD tests."


@when('I run the live console agent smoke scenario "{scenario}"')
def step_run_live_console_agent_smoke_scenario(context, scenario: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    keep = os.environ.get("PAPYRUS_LIVE_AGENT_CLEANUP") != "1"
    retryable_scenarios = {
        "create-research-assignment",
        "docs-progressive",
        "unsupported-snippet-retry",
        "list-research-assignments",
        "get-research-assignment",
        "update-research-assignment",
        "invalid-assignment-input",
        "discuss-reference",
        "list-recent-references",
        "get-specific-reference",
        "knowledge-query-single-reference",
        "knowledge-query-three-references",
        "rate-reference-quality",
        "review-reference-curation-accept",
        "review-reference-curation-reject",
        "review-reference-curation-archive",
        "review-reference-curation-reopen",
        "note-reference",
        "curate-reference-refresh",
    }
    attempts = 3 if scenario in retryable_scenarios else 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            context.live_console_agent_smoke_result = run_scenario(
                scenario,
                repo_root=repo_root,
                keep=keep,
            )
            return
        except RuntimeError as error:
            last_error = error
    assert last_error is not None
    raise last_error


@then("the live console agent smoke scenario should pass")
def step_live_console_agent_smoke_scenario_should_pass(context) -> None:
    assert context.live_console_agent_smoke_result.get("ok") is True


@then('the live console agent response should include "{needle}"')
def step_live_console_agent_response_should_include(context, needle: str) -> None:
    content = str(context.live_console_agent_smoke_result.get("content") or "")
    assert needle.lower() in content.lower(), f'Expected "{needle}" in response; saw "{content}"'


@then('the live console agent response should equal "{expected}"')
def step_live_console_agent_response_should_equal(context, expected: str) -> None:
    content = str(context.live_console_agent_smoke_result.get("content") or "")
    assert content == expected, f'Expected exact response "{expected}"; saw "{content}"'


@then('the live console agent response should match regex "{pattern}"')
def step_live_console_agent_response_should_match_regex(context, pattern: str) -> None:
    content = str(context.live_console_agent_smoke_result.get("content") or "")
    assert re.fullmatch(pattern, content), f'Response "{content}" does not match regex "{pattern}"'


@then('the live console agent smoke result should include tool call "{tool_call}"')
def step_live_console_agent_smoke_should_include_tool_call(context, tool_call: str) -> None:
    api_calls = context.live_console_agent_smoke_result.get("apiCalls") or []
    assert tool_call in api_calls, f"Expected {tool_call}; saw {', '.join(api_calls)}"


@then('the live console agent smoke result should include no tool call "{tool_call}"')
def step_live_console_agent_smoke_should_exclude_tool_call(context, tool_call: str) -> None:
    api_calls = context.live_console_agent_smoke_result.get("apiCalls") or []
    assert tool_call not in api_calls, f"Expected no {tool_call}; saw {', '.join(api_calls)}"


@then("the live console agent smoke result should include no tool calls")
def step_live_console_agent_smoke_should_include_no_tool_calls(context) -> None:
    api_calls = context.live_console_agent_smoke_result.get("apiCalls") or []
    assert not api_calls, f"Expected no tool calls; saw {', '.join(api_calls)}"


@then('the live console agent smoke result should include tool calls in order "{first}" then "{second}"')
def step_live_console_agent_smoke_should_include_ordered_tool_calls(context, first: str, second: str) -> None:
    api_calls = context.live_console_agent_smoke_result.get("apiCalls") or []
    try:
        first_index = api_calls.index(first)
    except ValueError as error:
        raise AssertionError(f"Expected first tool call {first}; saw {', '.join(api_calls)}") from error
    try:
        second_index = api_calls.index(second, first_index + 1)
    except ValueError as error:
        raise AssertionError(
            f"Expected second tool call {second} after {first}; saw {', '.join(api_calls)}"
        ) from error
    assert first_index < second_index, f"Expected {first} before {second}; saw {', '.join(api_calls)}"


@then("the live console agent smoke result should include exactly {count:d} assignment")
def step_live_console_agent_smoke_should_include_assignments(context, count: int) -> None:
    assignment_ids = context.live_console_agent_smoke_result.get("assignmentIds") or []
    assert len(assignment_ids) == count, f"Expected {count} assignments; saw {len(assignment_ids)}"


@then("the live console agent smoke result should include a structured error")
def step_live_console_agent_smoke_should_include_structured_error(context) -> None:
    errors = context.live_console_agent_smoke_result.get("errors") or []
    assert errors, "Expected at least one structured error."
    first = errors[0]
    assert isinstance(first, dict), f"Error must be object-shaped, got: {type(first)}"
    assert first.get("code"), f"Error code missing: {first}"
    assert first.get("message"), f"Error message missing: {first}"


@then("the live console agent smoke result should include no structured errors")
def step_live_console_agent_smoke_should_include_no_structured_errors(context) -> None:
    errors = context.live_console_agent_smoke_result.get("errors") or []
    assert not errors, f"Expected no structured errors; saw {errors}"


@then('the live console agent smoke result should default to model "{model}"')
def step_live_console_agent_smoke_should_default_model(context, model: str) -> None:
    resolved = context.live_console_agent_smoke_result.get("model")
    assert resolved == model, f"Expected model {model}; saw {resolved}"


@then('the live console agent model context should include "{needle}"')
def step_live_console_agent_model_context_should_include(context, needle: str) -> None:
    model_context = context.live_console_agent_smoke_result.get("modelContext")
    assert model_context is not None, "Model context snapshot is missing from smoke result."
    serialized = json.dumps(model_context, ensure_ascii=False)
    assert needle in serialized, f'Expected "{needle}" in model context; saw {serialized}'


@then('the live console agent model context should include role "{role}" containing "{needle}"')
def step_live_console_agent_model_context_role_contains(context, role: str, needle: str) -> None:
    model_context = context.live_console_agent_smoke_result.get("modelContext")
    assert isinstance(model_context, dict), f"Model context must be an object; saw {type(model_context)}"
    attempts = model_context.get("attempts")
    assert isinstance(attempts, list), f"Model context attempts missing or invalid: {model_context}"
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        messages = attempt.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "") != role:
                continue
            content = str(message.get("content") or "")
            if needle in content:
                return
    raise AssertionError(f'Expected role "{role}" context containing "{needle}", saw {json.dumps(model_context, ensure_ascii=False)}')


@then('the live console agent model context should include tool result entries in order "{first}" then "{second}"')
def step_live_console_agent_model_context_tool_entries_in_order(context, first: str, second: str) -> None:
    model_context = context.live_console_agent_smoke_result.get("modelContext")
    assert isinstance(model_context, dict), f"Model context must be an object; saw {type(model_context)}"
    attempts = model_context.get("attempts")
    assert isinstance(attempts, list), f"Model context attempts missing or invalid: {model_context}"
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        messages = attempt.get("messages")
        if not isinstance(messages, list):
            continue
        tool_contents: list[str] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "") != "tool":
                continue
            content = str(message.get("content") or "")
            if content:
                tool_contents.append(content)
        if not tool_contents:
            continue
        first_index = next((idx for idx, text in enumerate(tool_contents) if first in text), None)
        if first_index is None:
            continue
        second_index = next(
            (idx for idx, text in enumerate(tool_contents[first_index + 1 :], start=first_index + 1) if second in text),
            None,
        )
        if second_index is not None and first_index < second_index:
            return
    raise AssertionError(
        f'Expected tool-result sequence "{first}" then "{second}" in model context; saw {json.dumps(model_context, ensure_ascii=False)}'
    )


@then('the live console agent model context should include execute_tactus tool call entries')
def step_live_console_agent_model_context_should_include_execute_tactus_calls(context) -> None:
    model_context = context.live_console_agent_smoke_result.get("modelContext")
    assert isinstance(model_context, dict), f"Model context must be an object; saw {type(model_context)}"
    attempts = model_context.get("attempts")
    assert isinstance(attempts, list), f"Model context attempts missing or invalid: {model_context}"
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        messages = attempt.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "") != "assistant":
                continue
            names = message.get("toolCallNames")
            if isinstance(names, list) and any(str(name) == "execute_tactus" for name in names):
                return
    raise AssertionError(
        f'Expected assistant tool call entries with "execute_tactus" in model context; saw {json.dumps(model_context, ensure_ascii=False)}'
    )
