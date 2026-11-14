import json
from pathlib import Path
import sys

from behave import given, then

TESTS = Path(__file__).resolve().parents[2] / "procedures" / "newsroom" / "tests"
sys.path.insert(0, str(TESTS))
import test_automations as ta  # noqa: E402


@given("a site backend with the fact-check automation that starts when a story enters reporting")
def stage_backend(context):
    context.client, context.reader = ta.stage_world(
        ta.fx.usage_summary(toolsUsed={"papyrus_fetch_pdf_text": 2, "papyrus_story_version": 1}))


@given('the fact-check bot has run on the story "{first}" and on the story "{second}"')
def stage_runs(context, first, second):
    assert (first, second) == ("story-a", "story-gone")   # the fixture's two stage-entry rows


def line_for(context, story):
    return next(line for line in context.cli_output.splitlines() if line.startswith("run\t") and f"\t{story}" in line)


@then("the output lists {count:d} runs started because a story entered reporting")
def listed(context, count):
    lines = [line for line in context.cli_output.splitlines() if "story entered reporting" in line]
    assert len(lines) == count, context.cli_output


@then('the run for "{story}" shows its run id')
def run_id(context, story):
    assert "run-s" in line_for(context, story)


@then('the run for "{story}" says it used "{tools}"')
def used(context, story, tools):
    assert f"tools: {tools}" in line_for(context, story)


@then('the run for "{story}" says no tools were recorded')
def no_tools(context, story):
    assert "tools: none recorded" in line_for(context, story)


@then('the run for "{story}" says the story was deleted')
def deleted(context, story):
    assert "(story deleted)" in line_for(context, story)


@then('the run for "{story}" does not say the story was deleted')
def not_deleted(context, story):
    assert "(story deleted)" not in line_for(context, story)


@then('the output says "{text}"')
def says(context, text):
    assert text in context.cli_output, context.cli_output
