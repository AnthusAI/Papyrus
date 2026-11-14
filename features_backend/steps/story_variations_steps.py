"""Story variations (features_backend/story-variations.feature). The backend is a small in-memory stand-in holding only the variation rows."""

from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.story_variations import VariationRefused, decide_variation, offer_variation, variations_of  # noqa: E402

STORY = "item-story-1"
REFERENCE = {"kind": "reference", "id": "reference-1", "title": "A Reference"}
CONCEPT = {"kind": "concept", "id": "concept-1", "title": "A Concept"}
OTHER_STORY = {"kind": "story", "id": "item-story-2", "title": "Another Story"}


class VariationBackend:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def list_by_index(self, index_name, key_value, **_):
        assert index_name == "storyVariationsByStoryAndNumber"
        return [dict(row) for row in self.rows.values() if row["storyLineageId"] == key_value]

    def get_record(self, model_name, record_id):
        assert model_name == "StoryVariation"
        return dict(self.rows[record_id]) if record_id in self.rows else None

    def create_record(self, model_name, payload):
        assert model_name == "StoryVariation"
        self.rows[payload["id"]] = dict(payload)

    def update_record(self, model_name, payload):
        assert model_name == "StoryVariation"
        self.rows[payload["id"]].update(payload)


def numbered(context, number):
    return variations_of(context.backend, STORY)[int(number) - 1]


def attempt(context, **fields):
    context.refusal = None
    try:
        offer_variation(context.backend, STORY, **fields)
    except VariationRefused as refusal:
        context.refusal = str(refusal)


@given("a Story at the idea stage")
def story_at_idea(context):
    context.backend = VariationBackend()


@given('a run offered variations "{first}" and "{second}"')
def offered_two(context, first, second):
    offer_variation(context.backend, STORY, point=first, headline=first, connections=[REFERENCE])
    offer_variation(context.backend, STORY, point=second, headline=second, connections=[CONCEPT])


@when('a run offers a variation with the point "{point}" connecting to a Reference and a Concept')
def offers_reference_and_concept(context, point):
    attempt(context, point=point, headline=point, connections=[REFERENCE, CONCEPT])


@when('a run offers a variation with the point "{point}" connecting to another Story')
def offers_story(context, point):
    attempt(context, point=point, headline=point, connections=[OTHER_STORY])


@when('a run offers a variation with the point "{point}" connecting to nothing')
def offers_nothing(context, point):
    attempt(context, point=point, headline=point, connections=[])


@when("a run offers a variation with no point")
def offers_no_point(context):
    attempt(context, point="  ", headline="A headline", connections=[REFERENCE])


@when('an editor writes a variation with the point "{point}"')
def editor_writes(context, point):
    attempt(context, point=point, headline=point, connections=[], origin="person")


@when("a variation combining them is requested by a Message")
def requested(context):
    ids = [row["id"] for row in variations_of(context.backend, STORY)]
    attempt(context, point="Combined", headline="Combined", connections=[REFERENCE, CONCEPT], origin="requested", based_on=ids, request_message_id="message-1")


@when("a variation combining them is requested with no Message")
def requested_no_message(context):
    ids = [row["id"] for row in variations_of(context.backend, STORY)]
    attempt(context, point="Combined", headline="Combined", connections=[REFERENCE], origin="requested", based_on=ids)


@when("a variation is requested based on a variation this Story does not have")
def requested_foreign(context):
    attempt(context, point="Combined", headline="Combined", connections=[REFERENCE], origin="requested", based_on=["variation-elsewhere"], request_message_id="message-1")


@when('an editor {verb} variation {number:d} saying "{reason}"')
def editor_decides(context, verb, number, reason):
    decision = {"accepts": "accepted", "rejects": "rejected"}[verb]
    decide_variation(context.backend, numbered(context, number)["id"], decision, decided_by_sub="editor-sub", decided_by_label="An Editor", reason=reason)


@then("the Story has {count:d} variation")
@then("the Story has {count:d} variations")
def story_has(context, count):
    assert len(variations_of(context.backend, STORY)) == count


@then("variation {number:d} is on offer")
def on_offer(context, number):
    assert numbered(context, number)["status"] == "offered"


@then("variation {number:d} is accepted")
def is_accepted(context, number):
    assert numbered(context, number)["status"] == "accepted"


@then("variation {number:d} is rejected")
def is_rejected(context, number):
    assert numbered(context, number)["status"] == "rejected"


@then('variation {number:d} has the point "{point}"')
def has_point(context, number, point):
    assert numbered(context, number)["point"] == point


@then('variation {number:d} connects to a "{first}" and a "{second}"')
def connects_two(context, number, first, second):
    assert [row["kind"] for row in numbered(context, number)["connections"]] == [first, second]


@then('variation {number:d} connects to a "{kind}"')
def connects_one(context, number, kind):
    assert [row["kind"] for row in numbered(context, number)["connections"]] == [kind]


@then('variation {number:d} came from a "{origin}"')
def came_from(context, number, origin):
    assert numbered(context, number)["origin"] == origin


@then("variation {number:d} is based on variations {first:d} and {second:d}")
def based_on(context, number, first, second):
    assert numbered(context, number)["basedOnVariationIds"] == [numbered(context, first)["id"], numbered(context, second)["id"]]


@then("variation {number:d} records the Message that asked")
def records_message(context, number):
    assert numbered(context, number)["requestMessageId"] == "message-1"


@then('variation {number:d} records the editor and the reason "{reason}"')
def records_decision(context, number, reason):
    row = numbered(context, number)
    assert (row["decidedBySub"], row["decidedByLabel"], row["decisionReason"]) == ("editor-sub", "An Editor", reason)
    assert row["decidedAt"]


@then("the variation is refused because {why}")
def refused(context, why):
    expected = {
        "it must make a point": "must make a point", "it must name what it connects to": "must name what it connects to",
        "it must name the Message": "must name the Message", "this Story does not have it": "does not have",
    }[why]
    assert context.refusal and expected in context.refusal, context.refusal
