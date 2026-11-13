"""story_localize.tac run through Tactus: the procedure calls its one tool and answers with the contract (no model, no network)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest import mock

import pytest

OUTPUT = {"story": "story-a--zh-Hans", "language": "zh-Hans", "version": "story-a--zh-Hans-v1", "hold": True, "reason": "faithfulness: numbers",
          "outcome": "held", "published": False, "rounds": 2, "revertedBlocks": 1, "costUsd": 0.004, "sourceCharacters": 5200, "findings": {},
          "runKey": "k"}


def run_procedure(inputs):
    pytest.importorskip("tactus")
    from tactus.adapters.memory import MemoryStorage
    from tactus.core import TactusRuntime
    from tactus.core.mocking import MockManager, set_current_mock_manager
    from tactus.protocols.result import TactusResult

    source = Path(__file__).resolve().parents[3] / "procedures/newsroom/story_localize.tac"
    runtime = TactusRuntime(procedure_id="papyrus-procedure-newsroom", storage_backend=MemoryStorage(), openai_api_key="unused", source_file_path=str(source))
    runtime.dependency_mode = "none"
    manager = MockManager()
    manager.disable_mock()
    runtime.mock_manager = manager
    set_current_mock_manager(manager)
    calls = []

    def tool(**kwargs):
        calls.append(kwargs)
        return dict(OUTPUT)

    with mock.patch("papyrus_content.graphql_authoring.create_authoring_client", return_value=(object(), None)), \
            mock.patch("papyrus_content.localize.run.localize_story", side_effect=lambda client, **kwargs: tool(**kwargs)):
        result = asyncio.run(runtime.execute(source.read_text(encoding="utf-8"), inputs, format="lua"))
    output = result.get("result")
    return result, (output.output if isinstance(output, TactusResult) else output), calls


def test_the_procedure_translates_through_its_tool_and_answers_with_the_contract():
    result, output, calls = run_procedure({"story": "story-a", "language": "zh-Hans", "ceilingUsd": 1})
    assert result.get("success"), result.get("error")
    assert calls == [{"story": "story-a", "language": "zh-Hans", "ceiling_usd": 1}]
    assert output["story"] == "story-a--zh-Hans" and output["hold"] is True and output["published"] is False and output["rounds"] == 2
    assert output["sourceCharacters"] == 5200 and output["costUsd"] == 0.004
