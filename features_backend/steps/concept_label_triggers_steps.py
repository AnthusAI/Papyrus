"""features_backend/concept-label-triggers.feature: the triggers over an in-memory site; the naming procedure is a spy that records who asked."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.entity_labels.fakes import FakeSite  # noqa: E402
from papyrus_content.entity_labels.keys import entity_key  # noqa: E402
from papyrus_content.entity_labels.store import LabelStore  # noqa: E402
from papyrus_content.entity_labels.triggers import name_concepts_for_story  # noqa: E402


def _label(context, language: str, state: str) -> None:
    LabelStore(context.site).create({"id": f"concept#pi#{language}", "entityKind": "concept", "entityId": "pi", "entityKey": entity_key("concept", "pi"), "language": language,
                                     "role": "preferred", "text": "inyección de prompt", "nameKey": f"k#{language}", "sortKey": f"{language}#preferred#x", "syncState": state})


@given('a site whose primary language is "{primary}" and which serves "{served}"')
def step_site(context, primary, served):
    context.site = FakeSite(primary=primary)
    context.node = context.site.add_node("pi", "topic--prompt-injection", "prompt injection")
    context.asked = []


@given('the concept "{name}" has no "{language}" label')
def step_none(context, name, language):
    pass


@given('the concept "{name}" has a current "{language}" label')
def step_current(context, name, language):
    context.site = FakeSite()
    context.node = context.site.add_node("pi", "topic--prompt-injection", name)
    context.asked = []
    _label(context, language, "current")


@given('the concept "{name}" has a held "{language}" label with an open review request')
def step_held(context, name, language):
    context.site = FakeSite()
    context.node = context.site.add_node("pi", "topic--prompt-injection", name)
    context.asked = []
    _label(context, language, "held")
    context.requests = ["open review request"]


@when('a Story in "{language}" is tagged with the concept "{name}"')
def step_tagged(context, language, name):
    def spy(client, node, tag):
        context.asked.append(tag)
        return [{"language": tag, "state": "current"}]

    context.report = name_concepts_for_story(context.site, story_language=language, nodes=[context.node], localize=spy)


@then('the concept is named in "{language}"')
def step_named(context, language):
    assert context.asked == [language], context.asked


@then("no other language is asked for")
def step_no_other(context):
    assert len(context.asked) == 1


@then("no concept is named")
@then("the model is asked nothing")
def step_nothing(context):
    assert context.asked == [] and context.report == []


@then("the review request is still the only one")
def step_one_request(context):
    assert context.requests == ["open review request"] and context.asked == []
