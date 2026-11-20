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

from papyrus_content.run_outcomes import OUTCOME_SHOWN  # noqa: E402

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
