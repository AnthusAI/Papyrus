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
    context.site.served = [served]
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
    def spy(client, node, tag, **kw):
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
    assert context.asked == [] and getattr(context, "report", []) == [] and getattr(context, "model_asks", []) == []


@then("the review request is still the only one")
def step_one_request(context):
    assert context.requests == ["open review request"] and context.asked == []


# ---- the queue of wanted names ---------------------------------------------------------------------------------------------------------------------------------

from papyrus_content.entity_labels.keys import WANTED  # noqa: E402
from papyrus_content.entity_labels.wanted import drain, record_wanted  # noqa: E402

NODES = {"prompt injection": ("pi", "topic--prompt-injection"), "gradient descent": ("gd", "technique--gradient-descent"), "data poisoning": ("dp", "topic--data-poisoning")}


def _nodes(context, names):
    for name in names:
        lineage, key = NODES[name]
        context.nodes = getattr(context, "nodes", {})
        context.nodes[name] = next((row for row in context.site.tables["SemanticNode"].values() if row["lineageId"] == lineage), None) or context.site.add_node(lineage, key, name)


def _list(text):
    return [part.strip().strip('"') for part in text.replace(" and ", ", ").split(",") if part.strip()]


def _spy_localize(context, cost):
    context.model_asks = []

    def localize(client, node, language, dry_run=False):
        context.model_asks.append(node["displayName"])
        LabelStore(client).create({"id": f"concept#{node['lineageId']}#{language}", "entityKind": "concept", "entityId": node["lineageId"],
                                   "entityKey": entity_key("concept", node["lineageId"]), "language": language, "role": "preferred", "text": "traducido",
                                   "nameKey": f"k#{node['lineageId']}#{language}", "sortKey": f"{language}#preferred#t", "syncState": "current"})
        return [{"concept": node["displayName"], "language": language, "state": "current", "costUsd": cost}]

    return localize


@when('a page in "{language}" needs the concept "{name}" twice')
def step_needs_twice(context, language, name):
    _nodes(context, [name])
    for _ in range(2):
        record_wanted(context.site, language=language, nodes=[context.nodes[name]], now="2026-11-16T00:00:00Z")


@given('pages in "{language}" need the concepts {names}')
def step_pages_need(context, language, names):
    _nodes(context, _list(names))
    context.language = language
    record_wanted(context.site, language=language, nodes=[context.nodes[name] for name in _list(names)], now="2026-11-16T00:00:00Z")


@given('the concept "{name}" is named in "{language}" by a person')
def step_named_by_person(context, name, language):
    node = context.nodes[name]
    LabelStore(context.site).create({"id": f"concept#{node['lineageId']}#{language}", "entityKind": "concept", "entityId": node["lineageId"],
                                     "entityKey": entity_key("concept", node["lineageId"]), "language": language, "role": "preferred", "text": "a mano",
                                     "nameKey": f"k#{node['lineageId']}#{language}", "sortKey": f"{language}#preferred#a", "syncState": "current", "pinned": True})


@when("the wanted concept names are drained")
def step_drain(context):
    context.drain = drain(context.site, languages=["es-419"], localize=_spy_localize(context, 0.0))


@when("the wanted concept names are drained with a ceiling of {ceiling} dollars and each name costs {cost}")
def step_drain_ceiling(context, ceiling, cost):
    context.drain = drain(context.site, languages=["es-419"], ceiling_usd=float(ceiling), localize=_spy_localize(context, float(cost)))


def _wanted(context):
    return [row for row in context.site.tables["EntityLabel"].values() if row.get("syncState") == WANTED]


@then('the work list of "{language}" holds one wanted row for "{name}"')
def step_one_wanted(context, language, name):
    rows = _wanted(context)
    assert [row["text"] for row in rows] == [name] and rows[0]["workKey"], rows


@then("no name has been written")
def step_no_name(context):
    assert not [row for row in context.site.tables["EntityLabel"].values() if row["role"] == "preferred"]


@then('the work list of "{language}" holds no wanted row')
def step_no_wanted(context, language):
    assert _wanted(context) == [], _wanted(context)


@then('both concepts are named in "{language}"')
@then('all three concepts are named in "{language}"')
def step_all_named(context, language):
    named = {row["entityId"] for row in context.site.tables["EntityLabel"].values() if row["role"] == "preferred" and row["language"] == language}
    assert named == {NODES[name][0] for name in context.nodes}, named


@then("draining again asks the model nothing")
def step_drain_again(context):
    before = list(context.model_asks)
    drain(context.site, languages=["es-419"], localize=_spy_localize(context, 0.0))
    assert context.model_asks == [] and before


@then("one concept is named and the drain says it stopped")
def step_stopped(context):
    assert context.drain["named"] == 1 and context.drain["stopped"] is True, context.drain


@then("two wanted rows remain")
def step_two_remain(context):
    assert len(_wanted(context)) == 2 and context.drain["remaining"] == 2


@given('an English Story tagged with "{name}" that has a published translation in "{language}"')
def step_story_with_translation(context, name, language):
    from procedures.newsroom.tests.fake_client import FakeAuthoringClient
    from src.papyrus_content import localization_publish_test as fixtures

    context.site = FakeAuthoringClient()
    fixtures.english(context.site)
    fixtures._tagged_original(context.site)
    context.translation = fixtures.translation(context.site)
    context.fixtures = fixtures


@when('the translation is published and then the Story is tagged again with "{name}"')
def step_publish_and_tag(context, name):
    from papyrus_content.entity_labels.wanted import record_wanted_for_tagging
    from papyrus_content.publishing import publish_item

    publish_item(context.site, context.translation["id"], actor="An Editor", by_person="An Editor")
    record_wanted_for_tagging(context.site, context.fixtures.ORIGINAL, [context.site.tables["SemanticNode"]["pi-v1"]], now="2026-11-16T00:00:00Z")


@when('the page of the concept "{name}" is published')
def step_page_published(context, name):
    from papyrus_content.entity_labels.wanted import record_wanted_for_page

    node = context.node
    context.site.tables["SemanticNode"][node["id"]]["versionState"] = "current"
    record_wanted_for_page(context.site, "topic--prompt-injection" if name == "prompt injection" else "topic--bicycle", now="2026-11-16T00:00:00Z")


@given('the concepts "{with_page}" (with a page) and "{without}" (without one) exist')
def step_pages(context, with_page, without):
    _nodes(context, [with_page])
    context.site.add_node("bk", "topic--bicycle", "bicycle")
    context.site.page_keys = ["topic--prompt-injection"]


def _sweep(context, language):
    from unittest import mock

    from papyrus_content.entity_labels.wanted import record_wanted_for_language

    with mock.patch("papyrus_content.concept_tags.concept_page_keys", lambda client: set(context.site.page_keys)):
        return record_wanted_for_language(context.site, language, now="2026-11-16T00:00:00Z")


@when('"{language}" is swept')
def step_sweep(context, language):
    context.swept = _sweep(context, language)


@then('sweeping "{language}" again records nothing')
def step_sweep_again(context, language):
    assert _sweep(context, language)["recorded"] == 0
