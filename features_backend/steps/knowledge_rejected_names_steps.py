from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.knowledge_snapshot import commands  # noqa: E402


def call(context, function, *flags):
    context.error = None
    captured = io.StringIO()
    try:
        with mock.patch.object(commands, "create_authoring_client", lambda *args, **kwargs: (context.client, {})), contextlib.redirect_stdout(captured):
            function(list(flags))
    except ValueError as error:
        context.error = str(error)
    context.output = captured.getvalue()


def typed_file(context, kind, text, item):
    entity = {"id": "e1", "kind": kind, "text": text, "state": "proposed", "entity_key": None, "span": None, "score": 0.9}
    path = context.work / f"entities-{len(list(context.work.glob('entities-*.json')))}.json"
    path.write_text(json.dumps({"schema_version": 1, "items": [{"item_id": f"item-{item}", "entities": [entity], "relations": []}]}))
    return path


def nodes_named(context, name):
    return [row for row in context.client.rows.get("SemanticNode", {}).values() if row["displayName"] == name]


def links_of(context, node):
    return {row["id"] for row in context.client.rows.get("SemanticRelation", {}).values() if row["objectLineageId"] == node["lineageId"]}


@given('the extractor proposed the {kind} "{text}" in the item "{item}" and the run was imported')
def step_first(context, kind, text, item):
    call(context, commands.knowledge_publish_run, "--entities", str(typed_file(context, kind, text, item)), "--apply")
    assert context.error is None, context.error


def review(context, name, command, actor):
    [node] = nodes_named(context, name)
    call(context, command, "--key", node["nodeKey"], "--actor", actor)
    assert context.error is None, context.error
    context.before = dict(context.client.rows["SemanticNode"][node["id"]])
    context.links_before = links_of(context, node)


@given('the AI review rejected the concept "{name}"')
def step_ai_rejected(context, name):
    review(context, name, commands.knowledge_entities_reject, "ai")


@given('a person rejected the concept "{name}"')
def step_person_rejected(context, name):
    review(context, name, commands.knowledge_entities_reject, "human")


@given('a person accepted the concept "{name}"')
def step_person_accepted(context, name):
    review(context, name, commands.knowledge_entities_accept, "human")


@when('the extractor proposes the {kind} "{text}" in the item "{item}" and the run is imported')
def step_again(context, kind, text, item):
    call(context, commands.knowledge_publish_run, "--entities", str(typed_file(context, kind, text, item)), "--apply")
    assert context.error is None, context.error


@then('the rejected concept "{name}" is exactly as it was and has no new link')
def step_rejected_same(context, name):
    [node] = nodes_named(context, name)
    assert dict(node) == context.before and links_of(context, node) == context.links_before


@then('the accepted concept "{name}" is exactly as it was')
def step_accepted_same(context, name):
    [node] = nodes_named(context, name)
    assert dict(node) == context.before


@then('the import report lists "{name}" as dropped because it was rejected earlier')
def step_report(context, name):
    assert f"dropped\tmodel\t{name}\trejected earlier" in context.output, context.output


@then('the map has the concept "{name}" as a model and as an organization')
def step_both_kinds(context, name):
    assert sorted(row["nodeKind"] for row in nodes_named(context, name)) == ["model", "organization"]
