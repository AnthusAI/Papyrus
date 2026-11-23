from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.run_outcomes import OUTCOME_SHOWN, WAITING_MARK, outcome_shown  # noqa: E402

SVG = re.compile(r"<svg[\s\S]*?</svg>")
TEXT_MARKS = tuple(mark for mark, _ in OUTCOME_SHOWN.values())


@given("the server's outcome lines for acted, nothing, asked, failed and unknown")
def server_lines(context):
    context.lines = {outcome: f"{mark} {words}" for outcome, (mark, words) in OUTCOME_SHOWN.items()}


@when("the console renders each outcome")
def render(context):
    done = subprocess.run(["npx", "tsx", str(REPO_ROOT / "scripts" / "run-outcome-probe.ts"), json.dumps(context.lines)],
                          cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    context.html = json.loads(done.stdout)


@then("each outcome shows an icon and its words")
def icon_and_words(context):
    for outcome, markup in context.html.items():
        words = OUTCOME_SHOWN[outcome][1]
        assert SVG.search(markup), f"{outcome} has no icon"
        assert words in SVG.sub("", markup), f"{outcome} does not show {words!r}"


@then("no outcome shows the command line's text mark")
def no_text_mark(context):
    for outcome, markup in context.html.items():
        shown = re.sub(r"<[^>]+>", "", SVG.sub("", markup))
        assert not shown.startswith(TEXT_MARKS), f"{outcome} shows a text mark: {shown!r}"


@then("the five icons have five different shapes")
def five_shapes(context):
    shapes = {re.sub(r' data-outcome-mark="[^"]*"', "", SVG.search(markup).group(0)) for markup in context.html.values()}
    assert len(shapes) == len(OUTCOME_SHOWN) == 5, shapes


# --- the procedure's Recent Runs panel, from the run records ---------------------------------------------------------------------------------------

RECENT_RUNS = [
    {"id": "run-acted", "runStatus": "completed", "outcome": "acted"},
    {"id": "run-nothing", "runStatus": "completed", "outcome": "nothing", "outcomeReason": "no_new_filing"},
    {"id": "run-asked", "runStatus": "completed", "outcome": "asked", "outcomeReason": "human_required"},
    {"id": "run-failed", "runStatus": "failed", "outcome": "failed", "outcomeReason": "procedure_error"},
    {"id": "run-unknown", "runStatus": "failed", "outcome": "unknown", "outcomeReason": "no_result_recorded"},
    {"id": "run-waiting", "runStatus": "waiting", "waitingFor": "budget cycle", "dueAt": "2026-12-01T00:00:00Z"},
    {"id": "run-started", "runStatus": "started"},
    {"id": "run-old", "runStatus": "completed"},
]
RUN_TEXT_MARKS = TEXT_MARKS + (WAITING_MARK,)


def _without_mark(line: str) -> str:
    for mark in RUN_TEXT_MARKS:
        if line.startswith(f"{mark} "):
            return line[len(mark) + 1:]
    return line


@given("a procedure's recent runs that did it, had nothing to do, asked, failed, have an unknown outcome, wait for the budget cycle, are not finished and were recorded before outcomes")
def recent_runs(context):
    context.recent_runs = [{"procedureId": "procedure-1", "procedureKey": "example.procedure", "procedureVersionId": "version-1",
                            "requestedAt": "2026-11-23T09:00:00Z", "attempt": 1, **run} for run in RECENT_RUNS]


@when("the console renders the procedure's Recent Runs panel")
def render_recent_runs(context):
    done = subprocess.run(["npx", "tsx", str(REPO_ROOT / "scripts" / "procedure-recent-runs-probe.ts"), json.dumps(context.recent_runs)],
                          cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    context.run_html = json.loads(done.stdout)


@then("each run shows an icon and the words the command line shows for that run, without the text mark")
def run_icon_and_words(context):
    for run in context.recent_runs:
        markup = context.run_html[run["id"]]
        outcome_cell = re.search(r"<dt>([\s\S]*?)</dt>", markup).group(1)
        assert SVG.search(outcome_cell), f"{run['id']} has no icon: {markup}"
        shown = re.sub(r"<[^>]+>", "", SVG.sub("", outcome_cell))
        assert shown == _without_mark(outcome_shown(run)), (run["id"], shown, outcome_shown(run))


@then("the five outcomes have five different shapes in the panel too")
def five_run_shapes(context):
    shapes = {re.sub(r' data-outcome-mark="[^"]*"', "", SVG.search(context.run_html[f"run-{outcome}"]).group(0)) for outcome in OUTCOME_SHOWN}
    assert len(shapes) == 5, shapes
