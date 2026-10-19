from __future__ import annotations

from typing import Any

import pytest

from papyrus_content import assignment_executors


def run_with_plan(monkeypatch: pytest.MonkeyPatch, command_plan: list[Any]) -> dict[str, Any]:
    monkeypatch.setattr(
        assignment_executors,
        "assignment_metadata",
        lambda client, assignment: {"commandPlan": command_plan},
    )
    return assignment_executors.execute_analysis_reindex_assignment(
        None, {"id": "assignment-1", "status": "claimed", "assignmentTypeKey": "analysis-reindex"}, {}
    )


@pytest.mark.parametrize(
    "command",
    [
        {"label": "reindex", "argv": ["uv", "run", "biblicus", "reindex"], "cwd": "../Biblicus"},
        {"label": "extract", "executable": "uv", "args": ["run", "biblicus", "extract"]},
        {"label": "empty", "arguments": []},
        "not-a-command",
    ],
)
def test_a_plan_from_before_the_runner_is_refused_with_a_regenerate_message(
    monkeypatch: pytest.MonkeyPatch, command: Any
) -> None:
    with pytest.raises(ValueError) as caught:
        run_with_plan(monkeypatch, [command])
    message = str(caught.value)
    assert "assignment-1" in message
    assert "predates the BiblicusRunner" in message
    assert "regenerate the plan" in message


def test_an_empty_plan_still_completes_without_commands(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(assignment_executors, "PAPYRUS_ROOT", tmp_path)
    result = run_with_plan(monkeypatch, [])
    assert result["commandResults"] == []
