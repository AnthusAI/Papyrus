"""features_backend/concept-alias-remove.feature: the patch the command writes, over a concept row."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot.actors import Actor, decode_review  # noqa: E402
from papyrus_content.knowledge_snapshot.entity_review import EntityReviewError, alias_remove_patches  # noqa: E402

NOW = "2026-11-16T12:00:00Z"


@given('a concept "{name}" with the aliases "{first}" and "{second}"')
def step_two(context, name, first, second):
    context.node = {"id": "n1", "nodeKey": "topic--x", "displayName": name, "aliases": [first, second]}


@given('a concept "{name}" with the aliases "{first}"')
def step_one(context, name, first):
    context.node = {"id": "n1", "nodeKey": "topic--x", "displayName": name, "aliases": [first]}


@when('the actor "{kind}" removes the alias "{alias}"')
def step_remove(context, kind, alias):
    context.error, context.patches = None, []
    try:
        context.patches = alias_remove_patches(context.node, alias, actor=Actor(kind, "tester" if kind == "ai" else None, "2026-11-16"), now=NOW)
    except EntityReviewError as error:
        context.error = str(error)


@then('the concept\'s aliases are "{aliases}"')
def step_aliases(context, aliases):
    assert context.patches[0]["expected"]["aliases"] == aliases.split(", "), context.patches


@then('the change is recorded as made by "{kind}"')
def step_recorded(context, kind):
    marks = decode_review(context.patches[0]["expected"]["changeReason"])
    assert marks.aliased_by is not None and marks.aliased_by.actor == kind, marks


@then("nothing is changed")
def step_nothing(context):
    assert context.patches == [] and context.error is None


@then("it is refused saying the name is not an alias and the concept is to be renamed")
def step_refused(context):
    assert context.error and "not an alias" in context.error and "rename" in context.error, context.error
