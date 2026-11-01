"""References linked to References and concepts (features_backend/reference-links.feature). The backend is an in-memory fake."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.reference_links import decide, link_concept, link_references  # noqa: E402
from procedures.newsroom.tests.test_reference_links import FakeClient  # noqa: E402

NOW = "2026-11-01T12:00:00Z"


def state(context):
    if not hasattr(context, "rl"):
        context.rl = type("State", (), {"client": FakeClient(), "node": {"id": "node-voice-v1", "lineageId": "node-voice", "versionNumber": 1}})()
    return context.rl


def only_row(context):
    rows = list(state(context).client.tables["SemanticRelation"].values())
    assert len(rows) == 1, f"expected one relation, found {len(rows)}"
    return rows[0]


@given('the References "{first}", "{second}" and the concept "{node}"')
def step_given_references(context, first, second, node):
    state(context)


@given('the newsroom suggested "{first}" and "{second}" as related')
def step_given_suggested(context, first, second):
    link_references(state(context).client, first, second, "related_to", "suggested", actor="auto:vector", now=NOW)


@when('an editor links "{first}" and "{second}" as related')
def step_link(context, first, second):
    link_references(state(context).client, first, second, "related_to", "human", actor="editor", now=NOW)


@when('the newsroom suggests "{first}" and "{second}" as related with a similarity of {score:f}')
def step_suggest(context, first, second, score):
    link_references(state(context).client, first, second, "related_to", "suggested", actor="auto:vector", score=score, classifier_id="vector:text-embedding-3-small", now=NOW)


@when('an editor accepts the link with the reason "{reason}"')
def step_accept(context, reason):
    decide(state(context).client, only_row(context)["id"], "accepted", reason, None, "editor", now=NOW)


@when('an editor rejects the link with the reason "{reason}"')
def step_reject(context, reason):
    decide(state(context).client, only_row(context)["id"], "rejected", reason, None, "editor", now=NOW)


@when('an editor tags "{reference}" with the concept "{node}"')
def step_tag(context, reference, node):
    link_concept(state(context).client, reference, state(context).node, "human", actor="editor", now=NOW)


@then("there is exactly one link between them")
def step_one(context):
    only_row(context)


@then("the link is current")
def step_current(context):
    assert only_row(context)["relationState"] == "current"


@then("the link is a suggestion")
def step_suggestion(context):
    assert only_row(context)["relationState"] == "suggested"


@then("the link is rejected")
def step_rejected(context):
    assert only_row(context)["relationState"] == "rejected"


@then('"{reference}" has no current links')
def step_no_current(context, reference):
    assert state(context).client.current_edges("reference", reference) == []


@then('"{reference}" has one current link')
def step_one_current(context, reference):
    assert len(state(context).client.current_edges("reference", reference)) == 1


@then('the link records who decided and the reason "{reason}"')
def step_decided(context, reason):
    metadata = json.loads(only_row(context)["metadata"])
    assert metadata["decidedBy"] == "editor" and metadata["reasonCode"] == reason, metadata


@then("the link goes from the Reference to the concept")
def step_direction(context):
    row = only_row(context)
    assert (row["subjectKind"], row["objectKind"]) == ("reference", "semanticNode")


@then('the link uses the "{predicate}" relation')
def step_predicate(context, predicate):
    assert only_row(context)["predicate"] == predicate
