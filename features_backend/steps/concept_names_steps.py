"""features_backend/concept-names.feature: the concept name rows, with an in-memory site (no network, no AWS)."""
from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.entity_labels.backfill import backfill_entity_labels  # noqa: E402
from papyrus_content.entity_labels.fakes import FakeSite  # noqa: E402
from papyrus_content.entity_labels.keys import name_key  # noqa: E402
from papyrus_content.entity_labels.lookup import find_concepts  # noqa: E402
from papyrus_content.entity_labels.primary import primary_text_hash, sync_node  # noqa: E402
from papyrus_content.entity_labels.store import LabelStore  # noqa: E402

NOW = "2026-11-15T12:00:00Z"


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


def _node(context, name):
    return next(node for node in context.site.tables["SemanticNode"].values() if node["displayName"] == name)


@given('a site that writes in "{language}"')
def step_site(context, language):
    context.site = FakeSite(primary=language)


@given('the concept "{name}" with the other name "{alias}" and the hashtag "{tag}"')
def step_concept_alias(context, name, alias, tag):
    context.site.add_node(_slug(name), f"editor_concept--{tag}", name, aliases=[alias], description="People keep authority.")


@given('the concept "{name}"')
def step_concept(context, name):
    context.site.add_node(_slug(name), f"editor_concept--{_slug(name)}", name)


def _sync(context):
    context.counts = [sync_node(context.site, node, primary_language=context.site.primary, now=NOW) for node in list(context.site.tables["SemanticNode"].values())]


@given("the concept names are synchronised")
@when("the concept names are synchronised")
def step_sync(context):
    _sync(context)


@then('the concept "{name}" has the language "{language}"')
def step_language(context, name, language):
    assert _node(context, name)["language"] == language


@then('its names are "{first}", "{second}" and "{third}"')
def step_names(context, first, second, third):
    rows = LabelStore(context.site).of_entity("concept#human-oversight")
    assert {row["text"] for row in rows} == {first, second, third}, rows


@then("a second synchronisation writes nothing")
def step_idempotent(context):
    before = len(context.site.writes)
    _sync(context)
    assert len(context.site.writes) == before


@when('an editor looks up "{one}", "{two}" and "{three}"')
def step_lookup(context, one, two, three):
    context.site.scans = 0
    context.found = {text: [node["displayName"] for node in find_concepts(context.site, text)] for text in (one, two, three)}


@then('each finds "{name}"')
def step_each(context, name):
    assert all(found == [name] for found in context.found.values()), context.found


@then("the concept table was not listed")
def step_not_listed(context):
    assert context.site.scans == 0


@when('the concept "{name}" is renamed "{new}" and loses its other name')
def step_rename(context, name, new):
    node = _node(context, name)
    node.update(displayName=new, aliases=[])


@then('looking up "{text}" finds nothing')
def step_nothing(context, text):
    assert find_concepts(context.site, text) == []


@then('looking up "{text}" finds "{name}"')
def step_finds(context, text, name):
    assert [node["displayName"] for node in find_concepts(context.site, text)] == [name]


def _translated(context, name, language, text, pinned):
    node = _node(context, name)
    LabelStore(context.site).create({"id": f"concept#{node['lineageId']}#{language}", "entityKind": "concept", "entityId": node["lineageId"], "entityKey": f"concept#{node['lineageId']}",
                                     "language": language, "role": "preferred", "text": text, "nameKey": name_key(language, text), "sortKey": f"{language}#preferred#{text.lower()}",
                                     "origin": "human" if pinned else "machine", "pinned": pinned, "syncState": "current", "sourceContentHash": primary_text_hash(node)})


@given('the concept "{name}" has a machine-made "{language}" name "{text}" made from its current words')
def step_machine(context, name, language, text):
    _translated(context, name, language, text, False)


@given('the concept "{name}" has a pinned "{language}" name "{text}" made from its current words')
def step_pinned(context, name, language, text):
    _translated(context, name, language, text, True)


@when('the description of "{name}" changes')
def step_description(context, name):
    _node(context, name)["description"] = "People keep the authority to stop the system."


def _label(context, name, language):
    return context.site.tables["EntityLabel"][f"concept#{_node(context, name)['lineageId']}#{language}"]


@then('the "{language}" name of "{name}" is stale and appears in the work list of "{same}"')
def step_stale(context, language, name, same):
    row = _label(context, name, language)
    assert row["syncState"] == "stale"
    assert [item["id"] for item in LabelStore(context.site).needing_work(same, "stale")] == [row["id"]]


@then('the "{language}" name of "{name}" is in conflict and the wording is unchanged')
def step_conflict(context, language, name):
    row = _label(context, name, language)
    assert row["syncState"] == "conflict" and row["text"] == "人类监督"


@then('the name key of the concept "{name}" differs from the name key of the section "{same}"')
def step_kinds(context, name, same):
    assert name_key("en", name, None, "concept") != name_key("en", same, None, "section")


@when("the backfill is dry run")
def step_dry(context):
    context.report = backfill_entity_labels(context.site, apply=False, now=NOW)
    context.writes = len(context.site.writes)


@then("it reports {count:d} concepts to change and writes nothing")
def step_dry_report(context, count):
    assert context.report["wouldChange"] == count and context.writes == 0


@when("the backfill is applied")
def step_apply(context):
    context.report = backfill_entity_labels(context.site, apply=True, now=NOW)


@when("the backfill is applied again")
def step_apply_again(context):
    context.report = backfill_entity_labels(context.site, apply=True, now=NOW)


@then("the second run created nothing")
def step_nothing_created(context):
    assert context.report["created"] == 0 and context.report["language"] == 0
