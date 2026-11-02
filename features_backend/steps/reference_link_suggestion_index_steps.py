"""The open-suggestion index (features_backend/reference-link-suggestion-index.feature). The backend is an in-memory fake."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.reference_links import NO_SCORE_SORT_VALUE, OPEN_SUGGESTION_KEY, decide, link_concept, link_references  # noqa: E402
from papyrus_content.reference_suggestion_backfill import backfill_suggestion_index  # noqa: E402
from procedures.newsroom.tests.test_reference_links import NODE, FakeClient  # noqa: E402

NOW = "2026-11-01T12:00:00Z"
LATER = "2026-11-02T12:00:00Z"
PAIRS = [("reference-a", "reference-b"), ("reference-a", "reference-c"), ("reference-b", "reference-c")]


def si(context):
    if not hasattr(context, "si"):
        context.si = type("State", (), {"client": FakeClient(), "backfill": None})()
    return context.si


def suggest(context, first, second, score, now=NOW):
    return link_references(si(context).client, first, second, "related_to", "suggested", actor="auto:vector", score=score, classifier_id="vector:text-embedding-3-small", now=now)


def scores(text):
    return [None if part.strip() == "none" else float(part) for part in text.replace(" and ", ",").split(",") if part.strip()]


def the_one_row(context):
    rows = list(si(context).client.tables["SemanticRelation"].values())
    assert len(rows) == 1, f"expected one relation, found {len(rows)}"
    return rows[0]


def index_scores(context):
    return [None if row["openSuggestionScore"] == NO_SCORE_SORT_VALUE else row["openSuggestionScore"] for row in si(context).client.open_suggestion_index()]


@given('the References "reference-a", "reference-b", "reference-c" and the concept "node-voice" for the suggestion index')
def step_background(context):
    si(context)


@when("the newsroom suggests three links with close matches {text}")
@given("the newsroom suggested three links with close matches {text}")
def step_three(context, text):
    first, second, third = scores(text)
    suggest(context, "reference-a", "reference-b", first)
    suggest(context, "reference-a", "reference-c", second)
    link_concept(si(context).client, "reference-b", NODE, "suggested", actor="auto:vector", score=third, now=NOW)


@given("the newsroom suggested two links with close matches {first:f} and {second:f}")
def step_two(context, first, second):
    suggest(context, "reference-a", "reference-b", first)
    suggest(context, "reference-a", "reference-c", second)


@when("the newsroom suggests the first pair again with a close match of {score:f}")
def step_first_again(context, score):
    suggest(context, "reference-a", "reference-b", score, LATER)


@given("the newsroom suggested a link with a close match of {score:f}")
def step_one(context, score):
    suggest(context, "reference-a", "reference-b", score)


@given("an editor rejected it")
@when("an editor rejects it")
def step_reject(context):
    decide(si(context).client, the_one_row(context)["id"], "rejected", None, None, "sub-1", now=LATER)


@when("an editor accepts it")
def step_accept(context):
    decide(si(context).client, the_one_row(context)["id"], "accepted", None, None, "sub-1", now=LATER)


@when("an editor links the same two References as related")
def step_link_over(context):
    link_references(si(context).client, "reference-b", "reference-a", "related_to", "human", actor="sub-1", now=LATER)


@when('an editor links "{first}" and "{second}" as related for the first time')
def step_link_new(context, first, second):
    link_references(si(context).client, first, second, "related_to", "human", actor="sub-1", now=NOW)


@when("the newsroom suggests the same pair again with a close match of {score:f}")
def step_same_again(context, score):
    suggest(context, "reference-a", "reference-b", score, "2026-11-03T12:00:00Z")


@given("suggestions with close matches {text} were written before the index existed, beside a rejected one and a link an editor made")
def step_legacy(context, text):
    client = si(context).client
    first, second, third = scores(text)
    suggest(context, "reference-a", "reference-b", first)
    suggest(context, "reference-a", "reference-c", second)
    link_concept(client, "reference-b", NODE, "suggested", actor="auto:vector", score=third, now=NOW)
    rejected = suggest(context, "reference-b", "reference-c", 0.9)["relationId"]
    decide(client, rejected, "rejected", None, None, "sub-1", now=NOW)
    link_references(client, "reference-a", "reference-c", "cites", "human", actor="sub-1", now=NOW)
    context.si.rejected_id = rejected
    for row in client.tables["SemanticRelation"].values():
        if row["relationState"] == "suggested":
            row.pop("openSuggestionKey")
            row.pop("openSuggestionScore")
    context.si.before = {key: dict(row) for key, row in client.tables["SemanticRelation"].items()}


@given("the rejected link carries a stray suggestion key")
def step_stray(context):
    si(context).client.tables["SemanticRelation"][context.si.rejected_id].update({"openSuggestionKey": OPEN_SUGGESTION_KEY, "openSuggestionScore": 0.9})


@given("the operator backfilled the suggestion index")
@when("the operator backfills the suggestion index")
def step_backfill(context):
    si(context).backfill = backfill_suggestion_index(si(context).client)


@when("the operator previews the backfill of the suggestion index")
def step_preview(context):
    si(context).backfill = backfill_suggestion_index(si(context).client, dry_run=True)


@then("reading the suggestion index returns the close matches {text}, in that order")
def step_order(context, text):
    assert index_scores(context) == scores(text), index_scores(context)


@then('every row in the index has the one shared partition value "{value}"')
def step_partition(context, value):
    assert value == OPEN_SUGGESTION_KEY
    assert {row["openSuggestionKey"] for row in si(context).client.open_suggestion_index()} == {value}


@then("the suggestion index is empty")
def step_empty(context):
    assert si(context).client.open_suggestion_index() == []


@then("the decided link is rejected")
def step_is_rejected(context):
    assert the_one_row(context)["relationState"] == "rejected"


@then("the decided link is current")
def step_is_current(context):
    assert the_one_row(context)["relationState"] == "current"


@then("the decided link is rejected and keeps its close match of {score:f}")
def step_rejected_keeps(context, score):
    row = the_one_row(context)
    assert (row["relationState"], row["score"]) == ("rejected", score)


@then("the rejected link and the editor's link are not in the index and nothing but the two index fields changed on any row")
def step_unchanged(context):
    rows = si(context).client.tables["SemanticRelation"]
    assert len(rows) == 5
    for key, row in rows.items():
        if row["relationState"] != "suggested":
            assert row.get("openSuggestionKey") is None
        strip = lambda value: {name: item for name, item in value.items() if not name.startswith("openSuggestion")}
        assert strip(row) == strip(context.si.before[key])


@then("it reports {keyed:d} suggestions to key and writes {written:d}")
def step_report(context, keyed, written):
    assert (si(context).backfill["keyed"], si(context).backfill["written"]) == (keyed, written)


@then("it writes {written:d} rows")
def step_writes(context, written):
    assert si(context).backfill["written"] == written


@then("the rejected link has no key and is still rejected")
def step_stray_gone(context):
    row = si(context).client.tables["SemanticRelation"][context.si.rejected_id]
    assert (row["relationState"], row["openSuggestionKey"], row["openSuggestionScore"]) == ("rejected", None, None)
