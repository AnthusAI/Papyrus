"""Hashtags for X announcements (features_backend/announcements/announcement-hashtags.feature): the concept reader over an in-memory client, and the draft with a stand-in model."""
from __future__ import annotations

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


def _draft(context, chosen):
    seen = {}

    def llm(system, user, schema):
        seen["system"] = system
        return {"text": "Newsrooms are learning what programmers learned.", "hashtags": chosen}

    context.model_saw = seen
    context.draft = drafting.draft_announcement(STORY, "https://example.test/story-1", guidelines="Voice: plain.", llm=llm, judge=_judge, hashtags=context.offered)


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
