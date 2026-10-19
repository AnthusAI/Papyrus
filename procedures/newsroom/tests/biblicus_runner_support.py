"""Shared fakes that stand in for the Biblicus subprocess behind BiblicusRunner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from papyrus_content import biblicus_runner

FAKE_BIBLICUS_EXECUTABLE_NAME = "biblicus"


def completed(*, stdout: str = "", stderr: str = "", returncode: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def fake_biblicus_subprocess(
    monkeypatch: Any,
    workdir: Path,
    handler: Callable[..., SimpleNamespace],
) -> list[dict[str, Any]]:
    """
    Configure BIBLICUS_WORKDIR and replace the runner's subprocess with ``handler``.

    :return: Recorded calls, each with ``command`` and the subprocess keyword arguments.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    executable = workdir / FAKE_BIBLICUS_EXECUTABLE_NAME
    monkeypatch.setenv("BIBLICUS_WORKDIR", str(workdir))
    monkeypatch.setattr(biblicus_runner, "resolve_biblicus_executable", lambda: executable)
    calls: list[dict[str, Any]] = []

    def run(command, **keywords):
        calls.append({"command": list(command), **keywords})
        return handler(command, **keywords)

    monkeypatch.setattr(biblicus_runner.subprocess, "run", run)
    return calls
