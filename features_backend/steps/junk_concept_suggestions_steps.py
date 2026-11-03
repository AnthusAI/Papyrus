import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

import test_concept_kinds as tc  # noqa: E402
from papyrus_content.junk_suggestions import retire_junk_suggestions  # noqa: E402


@given('open vector suggestions to a paper author, a coverage question and the task "translation"')
def step_world(context):
    context.junk = type("Junk", (), {})()
    context.junk.client = tc.world()


@when("the tool runs without execute")
def step_dry(context):
    context.junk.result = retire_junk_suggestions(context.junk.client)


@when("the tool runs with execute")
def step_execute(context):
    context.junk.result = retire_junk_suggestions(context.junk.client, execute=True, now="2026-11-02T12:00:00Z")


@then("it lists the author and the coverage question")
def step_lists(context):
    assert [row["nodeKind"] for row in context.junk.result["rows"]] == ["personAuthor", "coverageQuestion"], context.junk.result


@then("no suggestion was changed")
def step_nothing(context):
    assert context.junk.client.updates == []


@then('the author and the coverage question suggestions are rejected by the cleanup with the reason "{reason}"')
def step_rejected(context, reason):
    updates = context.junk.client.updates
    assert [u["id"] for u in updates] == ["rel-1", "rel-2"], updates
    for update in updates:
        metadata = json.loads(update["metadata"])
        assert update["relationState"] == "rejected" and metadata["decidedBy"] == "auto:cleanup" and metadata["reasonCode"] == reason, update


@then("the suggestion to the task is untouched")
def step_task(context):
    assert "rel-3" not in [u["id"] for u in context.junk.client.updates]
