from __future__ import annotations

import sys
from pathlib import Path

import yaml
from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.relevance_cyclotron import build_relevance_cyclotron  # noqa: E402
from papyrus_content.steering import load_steering_config  # noqa: E402

BASE = {
    "schemaVersion": 1,
    "publication": {"name": "Example Publication"},
    "canonicalTopicSet": {"corpusKey": "example", "classifierId": "example"},
    "corpora": [{"key": "example", "name": "example", "path": "corpora/example", "role": "canonical"}],
}
BLOCK = {
    "question": "Should this candidate source become a reference for this publication?",
    "store": {"localPath": "var/cyclotrons/papyrus-relevance",
              "s3Prefix": "s3://example-private-media/cyclotrons/papyrus-relevance/"},
}
DOCTRINE = [
    {"kind": "mission", "body": ["Publish practical AI security analysis."]},
    {"kind": "policy", "body": ["Prefer primary evidence over vendor marketing."]},
]


def write_config(context, block):
    raw = dict(BASE)
    if block is not None:
        raw["relevanceCyclotron"] = block
    context.config_path = Path(context.tmp_dir) / "steering.yml"
    context.config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")


def before_each(context):
    import tempfile
    context.tmp_dir = tempfile.mkdtemp()


@given("a steering config with a relevance cyclotron block")
def step_config_with_block(context):
    before_each(context)
    write_config(context, dict(BLOCK))


@given("the publication doctrine")
def step_doctrine(context):
    context.doctrine = [dict(entry) for entry in DOCTRINE]


@when("the worker builds the relevance cyclotron")
def step_build(context):
    config = load_steering_config(str(context.config_path))
    context.plan = build_relevance_cyclotron(config, context.doctrine)
    context.first_plan = getattr(context, "first_plan", None) or context.plan


@when("the publication doctrine changes")
def step_doctrine_changes(context):
    context.doctrine = [{"kind": "mission", "body": ["Publish practical AI safety analysis."]},
                        {"kind": "policy", "body": ["Prefer incident reports."]}]


@when("the worker builds the relevance cyclotron again")
def step_build_again(context):
    step_build(context)


@then("the cyclotron asks one yes-or-no question with include as the yes")
def step_one_question(context):
    definition = context.plan.definition
    assert definition.id == "papyrus-relevance"
    assert len(definition.classifiers) == 1
    classifier = definition.classifiers[0]
    assert classifier.id == "relevant"
    assert classifier.labels == ("include", "exclude")
    assert classifier.positive_label == "include"


@then("the question does not contain the doctrine")
def step_question_without_doctrine(context):
    question = context.plan.definition.classifiers[0].question
    assert question == BLOCK["question"]
    assert "vendor marketing" not in question


@then("the first rubric is the publication doctrine")
def step_rubric_is_doctrine(context):
    rubric = context.plan.seed_rubrics["relevant"]
    assert "Publish practical AI security analysis." in rubric
    assert "Prefer primary evidence over vendor marketing." in rubric


@then("decisions use Jev and the LLM optimizer uses OpenAI")
def step_default_providers(context):
    assert context.plan.decision_model == {"provider": "jev", "model": "jev-1.13.0"}
    assert context.plan.optimizer == {"provider": "openai", "model": "gpt-6-luna", "maxCalls": 10}


@then("the cyclotron definition is unchanged")
def step_definition_unchanged(context):
    assert context.plan.definition.fingerprint == context.first_plan.definition.fingerprint


@then("the first rubric follows the new doctrine")
def step_rubric_follows(context):
    assert "Prefer incident reports." in context.plan.seed_rubrics["relevant"]
    assert context.plan.seed_rubrics != context.first_plan.seed_rubrics


@given("a steering config whose relevance cyclotron positive label is not one of its labels")
def step_bad_positive(context):
    before_each(context)
    write_config(context, {**BLOCK, "positiveLabel": "keep"})


@given("a steering config whose relevance cyclotron block contains an apiKey")
def step_key_in_config(context):
    before_each(context)
    write_config(context, {**BLOCK, "decisionModel": {"provider": "jev", "apiKey": "do-not-commit"}})


@given("a steering config without a relevance cyclotron block")
def step_without_block(context):
    before_each(context)
    write_config(context, None)


@when("the steering config is loaded")
def step_load(context):
    context.error = None
    try:
        context.loaded = load_steering_config(str(context.config_path))
    except ValueError as error:
        context.error = error


@then('loading fails naming "{field}"')
def step_fails_naming(context, field):
    assert context.error is not None and field in str(context.error), context.error


@then("loading fails saying keys come from the environment")
def step_fails_keys(context):
    assert context.error is not None and "environment" in str(context.error), context.error


@then("the publication has no relevance cyclotron")
def step_no_cyclotron(context):
    assert context.error is None
    assert context.loaded["relevanceCyclotron"] is None
