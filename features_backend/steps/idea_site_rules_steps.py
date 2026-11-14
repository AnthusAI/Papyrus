"""A site's idea rules (features_backend/idea-site-rules.feature). The scenarios call the helpers of procedures/newsroom/tests/test_idea_site_rules.py: the
backend, the pages and the model are fakes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, REPO_ROOT / "procedures" / "newsroom" / "tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

import test_idea_site_rules as helpers  # noqa: E402
from papyrus_content import monitoring_stories  # noqa: E402
from papyrus_content.ideas import monitor_stories  # noqa: E402
from papyrus_content.ideas.rules import DEFAULT, IdeaRules, rules_of  # noqa: E402

RESTATES = {**helpers.PACK_ADDS, "verdict": "restates", "claim": ""}


@given("a site whose monitor settings carry no idea rules")
def step_no_rules(context):
    context.rules = rules_of(monitoring_stories.validate_monitor_stories("p", {"singleItem": True})["ideaRules"])


@then('the idea rules are two References, a joint sentence, only the verdict "adds" and the evidence mode')
def step_standard(context):
    assert context.rules == DEFAULT == IdeaRules(2, True, ("adds",), True, True, "evidence"), context.rules


@given("a site whose monitor settings set the minimum number of References to 0")
def step_bad_rules(context):
    try:
        monitoring_stories.validate_monitor_stories("p", {"ideaRules": {"minimumReferences": 0}})
        context.refusal = None
    except ValueError as error:
        context.refusal = str(error)


@then('the settings are refused and the message names "{name}"')
def step_refused(context, name):
    assert context.refusal and name in context.refusal, context.refusal


def write(context, rules, idea, verdict=helpers.PACK_ADDS):
    context.result, context.transport = helpers.write_pack(rules, idea, verdict)


@when("a context pack idea whose sentences each cite one Reference is written under the standard rules")
def step_apart_standard(context):
    write(context, DEFAULT, helpers.apart())


@when("a context pack idea whose sentences each cite one Reference is written under rules that need no joint sentence")
def step_apart_relaxed(context):
    write(context, IdeaRules(require_joint_sentence=False), helpers.apart())


@when("a context pack idea citing two References is written under rules that need three")
def step_two_of_three(context):
    write(context, IdeaRules(minimum_references=3), helpers.joined("Synthetic voices spread"))


@when("a context pack idea that only restates its sources is written under the standard rules")
def step_restates_standard(context):
    write(context, DEFAULT, helpers.joined("Synthetic voices spread"), RESTATES)


@when('the same idea is written under rules whose passing verdicts are "adds" and "restates"')
def step_restates_passing(context):
    write(context, IdeaRules(passing_verdicts=("adds", "restates")), helpers.joined("Synthetic voices spread"), RESTATES)


@then("the idea was dropped for citing fewer than {count:d} accepted References")
def step_fewer(context, count):
    reasons = [problem["reason"] for problem in context.result.dropped[0]["citationCheck"]["problems"]]
    assert f"fewer_than_{count}_accepted_references_cited" in reasons, reasons


@when("a premise-led run drafts an idea from a Reference that has no editor reason or comment")
def step_premise_run(context):
    context.run, context.client, context.model = helpers.premise_run(helpers.premise_story(), reason=False)


@when("a premise-led run is answered with an empty premise")
def step_premise_empty(context):
    context.run, context.client, context.model = helpers.premise_run({**helpers.premise_story(), "premise": " "})


@when("a run in the default mode drafts an idea")
def step_default_run(context):
    context.run, context.client, context.model = helpers.premise_run(helpers.story(), mode="evidence")


@then("the drafting run files {count:d} idea")
def step_run_files(context, count):
    assert len(context.run["drafts"]) == count and len(context.client.filed) == count, context.run["invalid"]


@then("the drafting run files no idea and skips the Reference as \"{reason}\"")
def step_run_none(context, reason):
    assert context.client.filed == [] and [row["reason"] for row in context.run["skipped"]] == [reason], context.run["skipped"]


@then("the idea records the premise as invented, apart from the sentences that rest on the source")
def step_premise_recorded(context):
    filed = context.client.filed[0]
    evidence = json.loads(filed["evidence"])
    assert evidence["mode"] == "premise-led" and evidence["premise"] == helpers.PREMISE, evidence
    assert "## Invented premise" in filed["body"] and "This premise is invented" in filed["body"]
    assert monitor_stories.PREMISE_PROMPT == context.model.drafting[0]["instructions"]


@then("no point check was asked")
def step_no_check(context):
    assert context.model.checks == []


@then("the idea is judged for a point and records no premise")
def step_judged(context):
    assert len(context.model.checks) == 1 and "premise" not in json.loads(context.client.filed[0]["evidence"])
