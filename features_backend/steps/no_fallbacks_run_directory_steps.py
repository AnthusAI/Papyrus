"""A run writes where it is told to, or stops (features_backend/no-fallbacks-run-directory.feature)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import assignments_workflow  # noqa: E402


def held(context) -> SimpleNamespace:
    if not hasattr(context, "rundir"):
        context.rundir = SimpleNamespace(base=None, result=None, error=None)
    return context.rundir


@given("PAPYRUS_RUNS_DIR names a writable directory")
def _writable(context):
    held(context).base = Path(tempfile.mkdtemp())


@given("PAPYRUS_RUNS_DIR names a directory that cannot be written")
def _unwritable(context):
    # A path under a regular file cannot be created.
    blocker = Path(tempfile.mkdtemp()) / "blocker"
    blocker.write_text("x", encoding="utf-8")
    held(context).base = blocker / "runs"


@when("a run directory is requested")
def _request(context):
    state = held(context)
    with mock.patch.dict(os.environ, {"PAPYRUS_RUNS_DIR": str(state.base)}):
        try:
            state.result = assignments_workflow.writable_run_dir("run-1")
        except Exception as error:  # the scenario asserts on it
            state.error = error


@then("the run directory is created under the configured directory")
def _created(context):
    state = held(context)
    assert state.error is None, state.error
    assert state.result == state.base / "run-1" and state.result.is_dir()


@then("the request fails and the error names PAPYRUS_RUNS_DIR")
def _fails(context):
    state = held(context)
    assert state.error is not None and "PAPYRUS_RUNS_DIR" in str(state.error), f"got {state.error!r}"
    assert state.result is None
