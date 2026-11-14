from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
sys.path.insert(0, str(REPO_ROOT / "procedures" / "newsroom" / "tests"))

from ideas_fixtures import NOW, FakeClient, story  # noqa: E402
from papyrus_content.ideas import duplicate_cut  # noqa: E402
from papyrus_content.ideas.context import load_context  # noqa: E402


class ItemClient(FakeClient):
    def __init__(self, items) -> None:
        super().__init__()
        self.items = items

    def list_records(self, model, *args, **kwargs):
        return list(self.items) if model == "Item" else super().list_records(model, *args, **kwargs)


TOPICS = ["quantum networking", "ocean cable repair", "wheat rust genetics", "tidal turbine safety", "bee hive sensors", "glacier core drilling",
          "rail signal software", "volcano gas monitoring", "desert solar tracking", "seed vault logistics"]


UNRELATED = ["Harbor pilots demand night rules", "Orchestra strikes over pensions", "Bakery chain buys mills", "Telescope grant stalls budget", "Marathon route crosses bridge",
             "Library lends garden tools", "Ferry fares double in spring", "Museum returns carved doors", "Chess league bans phones", "Brewery recycles heat for pools"]
UNRELATED_DECKS = ["Pilots say fog makes channel crossings unsafe", "Musicians reject the latest contract proposal", "Flour prices push a merger of rival bakers",
                   "Astronomers wait for funding to be released", "Runners face a closed lane on the old bridge", "Residents borrow spades and rakes from shelves",
                   "Commuters weigh the cost of seasonal crossings", "Curators agree to send ceremonial doors home", "Players must hand over devices at the door",
                   "Warm water from kettles now heats a public pool"]


def published(index: int) -> dict:
    topic = TOPICS[index % len(TOPICS)] + f" report {index}"
    return story(f"Study of {topic}", deck=f"Researchers describe {topic} in detail.", days_ago=100 + index)


def decided(identifier: str, title: str, deck: str, *, to: str, reason: str = "", created: float = 1) -> dict:
    moment = f"2026-10-{20 + int(created):02d}T00:00:00Z"
    return {
        "id": f"{identifier}-v1", "lineageId": identifier, "versionState": "current", "type": "article", "status": "draft", "stage": to, "title": title, "deck": deck,
        "versionCreatedAt": moment, "updatedAt": moment, "versionNumber": 1, "tenantId": None,
        "metadata": {"frontMatterYaml": f"title: {title}\ngenerated:\n  origin: monitor\n  ideaId: {identifier}\n",
                     "stageMoves": [{"from": "idea", "to": to, "reason": reason, "by": "editor", "at": moment}]},
    }


def build(context, duplicates: int, unrelated: int, other_reason: bool = False) -> None:
    stories = [published(n) for n in range(10)]
    items = list(stories)
    for n in range(duplicates):
        base = stories[n % 10]
        items.append(decided(f"dup-{n}", base["title"], base["deck"], to="spiked", reason="Duplicate of a published story" if not other_reason else "Off topic"))
    for n in range(unrelated):
        items.append(decided(f"fresh-{n}", f"{UNRELATED[n % len(UNRELATED)]} {n}", f"{UNRELATED_DECKS[n % len(UNRELATED)]} {n}.", to="reporting"))
    context.cut_client = ItemClient(items)


@given("a site whose editors spiked forty ideas as duplicates of stories and moved twenty unrelated ideas forward")
def step_sixteen(context):
    build(context, 40, 20)


@given("a site whose editors spiked one idea as a duplicate and moved one idea forward")
def step_two(context):
    build(context, 1, 1)


@given("a site whose editors spiked ideas for being off topic and moved ideas forward")
def step_off_topic(context):
    build(context, 8, 3, other_reason=True)


@when("the site's duplicate cut is learned")
def step_learn(context):
    context.cut = duplicate_cut.resolve_threshold(context.cut_client, None)


@when("the cut is resolved with an operator threshold of 0.7")
def step_operator(context):
    context.cut = duplicate_cut.resolve_threshold(context.cut_client, 0.7)


@then("the cut is learned from sixty decisions and lies above the unrelated ideas and at or below the duplicates")
def step_learned(context):
    assert context.cut.learned and context.cut.decisions == 60, context.cut.record()
    assert 0.1 < context.cut.threshold <= 1.0, context.cut.record()


@then("the run record reports the cut with the lower bound that justified it")
def step_record(context):
    record = context.cut.record()
    assert record["lowerBound"] >= record["precision"] and record["duplicates"] == record["above"] == 40, record


@then("the cut is 0.5 and not learned")
def step_fallback(context):
    assert context.cut.threshold == 0.5 and not context.cut.learned


@then('the run record says "no learned cut: too few decisions"')
def step_reason(context):
    assert context.cut.record()["reason"] == "no learned cut: too few decisions"


@then("the off topic spikes are not counted as decisions")
def step_off(context):
    assert context.cut.decisions == 3, context.cut.record()


@then("the cut is 0.7 and not learned")
def step_operator_cut(context):
    assert context.cut.threshold == 0.7 and not context.cut.learned


@given("a site with a story published two hundred days ago and one published ten days ago")
def step_old(context):
    context.cut_client = FakeClient(stories=[story("Old coverage of kelp farms", days_ago=200), story("Recent coverage of kelp farms", days_ago=10)])


@when("the story context is loaded without a window")
def step_context(context):
    context.story_context = load_context(context.cut_client, now=NOW)


@then("both stories are in the context and the window is the span of the site's own stories")
def step_both(context):
    assert len(context.story_context["stories"]) == 2 and 200 <= context.story_context["storyDays"] <= 201
