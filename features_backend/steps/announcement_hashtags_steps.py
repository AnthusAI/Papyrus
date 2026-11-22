"""Hashtags for X announcements (features_backend/announcements/announcement-hashtags.feature): the concept reader over an in-memory client, and the draft with a stand-in model."""
from __future__ import annotations

import json
import re

from behave import given, then, when

from papyrus_content.announcements import drafting, hashtags
from papyrus_content.announcements.eligibility import StoryFacts
TAGGED_WITH = "tagged_with"


class ConceptClient:
    """list_by_index and get_records_by_id over a handful of tagged concepts."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.relations: list[dict] = []

    def tag(self, story: str, name: str, *, status: str = "accepted", used_by: int = 1) -> None:
        lineage = f"node-{name}"
        self.nodes[lineage] = {"id": lineage, "lineageId": lineage, "nodeKey": f"concept--{name}", "status": status}
        for number in range(used_by):
            subject = story if number == 0 else f"other-{name}-{number}"
            self.relations.append({"id": f"{subject}-{name}", "predicate": TAGGED_WITH, "subjectKind": "item", "subjectLineageId": subject, "objectKind": "semanticNode",
                                   "objectId": lineage, "objectLineageId": lineage})

    def list_by_index(self, index: str, key: str, **options):
        if index == "semanticRelationsBySubjectState":
            lineage = key.split("#")[1]
            return [row for row in self.relations if row["subjectLineageId"] == lineage]
        if index == "semanticRelationsByObjectState":
            lineage = key.split("#")[1]
            return [row for row in self.relations if row["objectLineageId"] == lineage]
        return []

    def get_records_by_id(self, model: str, ids: list[str]) -> dict[str, dict]:
        return {identifier: self.nodes[identifier] for identifier in ids if identifier in self.nodes}


def _words(text: str) -> list[str]:
    return re.findall(r'"([^"]+)"', text)


@given('a Story "{story}" tagged with the accepted concepts "{first}" used by {first_uses:d} Stories and "{second}" used by {second_uses:d} Stories')
def _two_concepts(context, story, first, first_uses, second, second_uses):
    context.concepts = ConceptClient()
    context.concepts.tag(story, first, used_by=first_uses)
    context.concepts.tag(story, second, used_by=second_uses)


@given('a Story "{story}" tagged with the accepted concept "{name}" used by {uses:d} Stories')
def _one_concept(context, story, name, uses):
    context.concepts = ConceptClient()
    context.concepts.tag(story, name, used_by=uses)


@given('"{story}" is also tagged with the concept "{name}" that is only suggested')
def _suggested(context, story, name):
    context.concepts.tag(story, name, status="suggested")


@when('the hashtags of "{story}" are read')
def _read(context, story):
    context.read_hashtags = hashtags.story_hashtags(context.concepts, story)


@then("the hashtags are {expected}")
def _hashtags_are(context, expected):
    assert context.read_hashtags == _words(expected), context.read_hashtags


STORY = StoryFacts(lineage_id="story-1", item_id="story-1-v1", version_number=1, story_type="article", section=None, published=True, retired=False, stars=4,
                   title="Reporters learn to direct machines", dek="", summary="Newsrooms are learning what programmers learned.", body="", path="/story-1", rated_by="ellie")


def _judge(claim, cited, info=None):
    return {"verdict": "supported", "quotes": [" ".join(cited.values()).split("\n")[0]], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


@given("the Story offers no hashtags")
def _offers_none(context):
    context.offered = []


@given("the Story offers the hashtags {tags}")
def _offers(context, tags):
    context.offered = _words(tags)


@when("the draft chooses the hashtags {tags}")
def _chooses(context, tags):
    _draft(context, _words(tags))


@when("the draft chooses no hashtags")
def _chooses_none(context):
    _draft(context, [])


@when("words that leave no room are drafted and the hashtags {tags} are chosen")
def _chooses_without_room(context, tags):
    _draft(context, _words(tags), text="Newsrooms are learning what programmers learned. " + "x" * (drafting.DRAFT_WEIGHT - 51))


def _draft(context, chosen, text="Newsrooms are learning what programmers learned."):
    seen = {}

    def llm(system, user, schema):
        seen["system"] = system
        return {"text": text, "hashtags": chosen}

    context.model_saw = seen
    context.draft = drafting.draft_announcement(STORY, "https://example.test/story-1", guidelines="Voice: plain.", llm=llm, judge=getattr(context, "judge", _judge),
                                                hashtags=context.offered)


@then('the post text ends with "{ending}"')
def _ends(context, ending):
    assert context.draft.text.endswith(ending), context.draft.text


@then("the post text has no hashtag")
def _no_tag(context):
    assert "#" not in context.draft.text, context.draft.text


@then("every check passes")
def _all_pass(context):
    assert context.draft.passed, context.draft.failures


@then('the check "{name}" fails saying "{words}"')
def _fails(context, name, words):
    check = next(check for check in context.draft.checks if check["name"] == name)
    assert not check["passed"] and any(words in problem for problem in check["problems"]), check


@then("the model was told the Story offers no hashtags")
def _told_none(context):
    assert "offers no hashtags" in context.model_saw["system"], context.model_saw["system"]


# --- the one redraft for a draft that is only too long ---------------------------------------------------------------------------------------------------------

SHORT = "Newsrooms are learning what programmers learned."
LONG = SHORT + " " + "x" * (drafting.DRAFT_WEIGHT + 20)


@given("the model's first text is too long and its second is short enough")
def _long_then_short(context):
    context.texts, context.hashtags_chosen = [LONG, SHORT], []


@given("the model's texts are both too long")
def _long_twice(context):
    context.texts, context.hashtags_chosen = [LONG, LONG], []


@given('the model chooses the hashtags "{tag}" in a short text')
def _wrong_tag(context, tag):
    context.texts, context.hashtags_chosen = [SHORT, SHORT], [tag]


@when("the announcement draft is written")
def _written(context):
    context.requests = []

    def llm(system, user, schema):
        context.requests.append(user)
        text = context.texts[min(len(context.requests), len(context.texts)) - 1]
        return {"text": text, "hashtags": context.hashtags_chosen}

    context.draft = drafting.draft_announcement(STORY, "https://example.test/story-1", guidelines="Voice: plain.", llm=llm, judge=getattr(context, "judge", _judge),
                                                hashtags=context.offered)


@then("the draft model was asked twice and the second request named the overrun")
def _asked_twice_with_overrun(context):
    assert len(context.requests) == 2 and "tooLongBy" in context.requests[1] and "tooLongBy" not in context.requests[0], context.requests


@then("the draft model was asked two times")
def _asked_twice(context):
    assert len(context.requests) == 2, len(context.requests)


@then("the draft model was asked one time")
def _asked_once(context):
    assert len(context.requests) == 1, len(context.requests)


OVERSTATED = "All newsrooms are learning what programmers learned."


def _judge_refusing_overstatement(claim, cited, info=None):
    if claim.startswith("All "):
        return {"verdict": "not_supported", "quotes": [], "explanation": "The Story does not say all newsrooms.", "attribution_lost": False, "claim_is_only_about_source_limits": False}
    return _judge(claim, cited, info)


@given("the model's first text overstates the Story and its second keeps the Story's words")
def _overstated_then_faithful(context):
    context.texts, context.hashtags_chosen, context.judge = [OVERSTATED, SHORT], [], _judge_refusing_overstatement


@then("the draft model was asked twice and the second request named the unsupported sentence")
def _asked_twice_with_unsupported(context):
    assert len(context.requests) == 2, context.requests
    second = json.loads(context.requests[1])
    assert any(OVERSTATED in problem for problem in second["unsupported"]) and "unsupported" not in json.loads(context.requests[0]), second


@when("the announcement prompt is built")
def _prompt_built(context):
    context.system, context.user = drafting.prompt(STORY, "Voice: plain.", hashtags=context.offered)


@then('the weight limit given to the model leaves room for "{tag}"')
def _limit_leaves_room(context, tag):
    limit = drafting.DRAFT_WEIGHT - drafting.weighted_length(f" {tag}") - drafting.COUNTING_MARGIN
    assert f"at most {limit} on X" in context.system, context.system
