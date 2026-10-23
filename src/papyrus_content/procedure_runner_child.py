"""Runs one Tactus procedure in this process and writes its outcome as JSON.

Usage: python -m papyrus_content.procedure_runner_child <procedure.tac> <input.json> <result.json>
The procedure runner starts this in a separate process so its deadline can stop a run that overruns.
All tools are real (the equivalent of `tactus run --real-all`); the working directory is the run's own.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path


def json_safe(value):
    return json.loads(json.dumps(value, default=str))


class UsageCollector:
    """A Tactus log handler that keeps only the model usage of each call and ignores every other event.

    Tactus emits one cost event per model call (agent, model, provider, token counts). This keeps those counts, not
    Tactus's own prices: the runner prices them from the Papyrus table (model_cost.py)."""

    supports_streaming = False

    def __init__(self):
        self.cost_events: list = []
        self.calls: list[dict] = []

    def log(self, event) -> None:
        if not (hasattr(event, "prompt_tokens") and hasattr(event, "completion_tokens") and hasattr(event, "model")):
            return
        self.cost_events.append(event)
        self.calls.append({
            "agent": getattr(event, "agent_name", None), "model": event.model, "provider": getattr(event, "provider", None),
            "promptTokens": event.prompt_tokens, "completionTokens": event.completion_tokens,
            "cachedTokens": getattr(event, "cache_tokens", None) or 0})


def run(source_path: Path, inputs: dict, usage: UsageCollector | None = None) -> dict:
    from tactus.adapters.memory import MemoryStorage
    from tactus.core import TactusRuntime
    from tactus.core.mocking import MockManager, set_current_mock_manager
    from tactus.protocols.result import TactusResult

    usage = usage if usage is not None else UsageCollector()
    runtime = TactusRuntime(procedure_id=f"papyrus-procedure-{source_path.parent.name}", storage_backend=MemoryStorage(),
                            openai_api_key=os.environ.get("OPENAI_API_KEY"), source_file_path=str(source_path),
                            log_handler=usage)
    runtime.dependency_mode = "none"
    mock_manager = MockManager()
    mock_manager.disable_mock()
    runtime.mock_manager = mock_manager
    set_current_mock_manager(mock_manager)
    result = asyncio.run(runtime.execute(source_path.read_text(encoding="utf-8"), inputs, format="lua"))
    output = result.get("result")
    if isinstance(output, TactusResult):
        output = output.output
    return {"success": bool(result.get("success")), "output": json_safe(output),
            "error": None if result.get("success") else str(result.get("error") or "the procedure failed"),
            "toolsUsed": json_safe(result.get("tools_used") or []), "iterations": result.get("iterations"),
            "usage": json_safe(usage.calls)}


def main(argv: list[str]) -> int:
    source_path, input_path, result_path = (Path(argument) for argument in argv)
    usage = UsageCollector()
    try:
        outcome = run(source_path, json.loads(input_path.read_text(encoding="utf-8")), usage)
    except Exception as error:   # model calls made before the failure are still reported
        outcome = {"success": False, "error": f"{type(error).__name__}: {error}", "logTail": traceback.format_exc()[-4000:],
                   "usage": json_safe(usage.calls)}
    result_path.write_text(json.dumps(outcome), encoding="utf-8")
    return 0 if outcome["success"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
