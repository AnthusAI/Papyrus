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


def run(source_path: Path, inputs: dict) -> dict:
    from tactus.adapters.memory import MemoryStorage
    from tactus.core import TactusRuntime
    from tactus.core.mocking import MockManager, set_current_mock_manager
    from tactus.protocols.result import TactusResult

    runtime = TactusRuntime(procedure_id=f"papyrus-procedure-{source_path.parent.name}", storage_backend=MemoryStorage(),
                            openai_api_key=os.environ.get("OPENAI_API_KEY"), source_file_path=str(source_path))
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
            "toolsUsed": json_safe(result.get("tools_used") or []), "iterations": result.get("iterations")}


def main(argv: list[str]) -> int:
    source_path, input_path, result_path = (Path(argument) for argument in argv)
    try:
        outcome = run(source_path, json.loads(input_path.read_text(encoding="utf-8")))
    except Exception as error:
        outcome = {"success": False, "error": f"{type(error).__name__}: {error}", "logTail": traceback.format_exc()[-4000:]}
    result_path.write_text(json.dumps(outcome), encoding="utf-8")
    return 0 if outcome["success"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
