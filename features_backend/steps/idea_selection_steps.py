import copy
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from behave import given, then, when

from papyrus_content import story_selection as selection

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def ago(**kwargs):
    return (NOW - timedelta(**kwargs)).isoformat().replace("+00:00", "Z")


class Store:
    tenant_id = None

    def __init__(self):
        self.items = {}
        self.updates = []

    def list_by_index(self, index, key):
        assert index == "itemsByStage", index
        return [{"id": row["id"], "lineageId": row["lineageId"], "versionState": "current", "type": "article", "section": "law", "stage": row["stage"]}
                for row in self.items.values() if row["stage"] == key]

    def get_records_by_id(self, model, ids):
        return {record_id: copy.deepcopy(self.items[record_id]) for record_id in ids if record_id in self.items}

    def update_record(self, model, payload):
        self.updates.append(payload)
        self.items[payload["id"]].update(payload)


def idea(store, name, day, **extra):
    store.items[f"{name}-v1"] = {"id": f"{name}-v1", "lineageId": name, "stage": "idea", "status": "draft", "headline": f"Headline {name}", "deck": f"Deck {name}",
                                 "bodyMarkus": f"Body {name}", "updatedAt": ago(days=day), **extra}


@given("a section with three ideas, the oldest of them rated by an editor")
def step_ideas(context):
    context.store = Store()
    idea(context.store, "first", 3, starRating=4, starRatedAt=ago(days=3), starRatedBy="editor")
    idea(context.store, "second", 1)
    idea(context.store, "third", 2)
    context.answer = {"decisions": []}
    context.calls = []
    context.assigned = []
    context.moves = []
    context.packs = []
    context.error = None

    def llm(system, user, schema):
        context.calls.append({"system": system, "user": user})
        return context.answer

    def assign(client, options):
        context.assigned.append(options)
        return {"assignmentId": f"assignment-{len(context.assigned)}"}

    def move(client, lineage, stage, **kwargs):
        context.moves.append((lineage, stage, kwargs["actor"]))
        return {}

    def pack(client, **kwargs):
        context.packs.append(kwargs)
        return {"system": "ROLE AND MISSION", "user": "WHAT IS PUBLISHED", "contextHash": "hash-1"}

    context.llm = llm
    for patch in (mock.patch.object(selection, "find_section", side_effect=lambda client, value: {"id": value} if value == "law" else None),
                  mock.patch.object(selection, "create_research_assignment", side_effect=assign),
                  mock.patch.object(selection, "move_story_stage", side_effect=move),
                  mock.patch.object(selection, "build_context_pack", side_effect=pack),
                  mock.patch("papyrus_content.newsroom_context_pack.find_section", side_effect=lambda client, value: {"id": value} if value == "law" else None)):
        patch.start()
        context.add_cleanup(patch.stop)


def decisions(picks, declines=()):
    return {"decisions": [*({"handle": handle, "verdict": "pick", "reason": f"Best: {handle}", "direction": direction} for handle, direction in picks),
                          *({"handle": handle, "verdict": "decline", "reason": f"Repeats published work: {handle}", "direction": ""} for handle in declines)]}


# Read order: stars first, then the newest: I1 first, I2 second, I3 third.
@given("the model picks the second idea and declines the others")
def step_pick_second(context):
    context.answer = decisions([("I2", "Find the court records")], ["I1", "I3"])


@given("the model declines every idea")
def step_decline(context):
    context.answer = decisions([], ["I1", "I2", "I3"])


@given("the model picks all three ideas")
def step_pick_all(context):
    context.answer = decisions([("I1", "One"), ("I2", "Two"), ("I3", "Three")])


@given("the model picks the first idea with no direction")
def step_pick_no_direction(context):
    context.answer = decisions([("I1", "")], ["I2", "I3"])


def left_idea(context, name, **when_ago):
    idea(context.store, name, 1, stage="reporting", metadata=json.dumps({"stageMoves": [{"from": "idea", "to": "assignment", "at": ago(**when_ago), "by": "a person"}]}))


@given("a Story in the section left the idea stage an hour ago")
def step_left_hour(context):
    left_idea(context, "started", hours=1)


@given("a Story in the section left the idea stage three days ago")
def step_left_days(context):
    left_idea(context, "started", days=3)


def run(context, *, section="law", settings=None, apply=True, again=False):
    context.calls_before = len(context.calls)
    context.error = None
    try:
        context.outcome = selection.select_ideas(context.store, section, llm=context.llm, settings=settings or selection.SelectionSettings(), apply=apply, again=again, now=NOW)
    except ValueError as error:
        context.error = str(error)


@when("the selection runs")
def step_run(context):
    run(context)


@when("the selection runs a second time")
def step_run_second(context):
    run(context)


@when("the selection runs again with again set")
def step_run_again(context):
    run(context, again=True)


@when("the selection runs as a dry run")
def step_run_dry(context):
    run(context, apply=False)


@when("the selection runs with a window of {days:d} days and a limit of {limit:d}")
def step_run_window(context, days, limit):
    run(context, settings=selection.SelectionSettings(max_new_stories=limit, per_days=days), again=True)


@when("the selection runs with recent meaning {section} in the section and {site} in the site")
def step_run_recent(context, section, site):
    run(context, settings=selection.SelectionSettings(recent_section=selection.parse_recent(section), recent_site=selection.parse_recent(site)))


@when("the selection runs for a section that does not exist")
def step_run_unknown(context):
    run(context, section="nowhere")


def meta(context, name):
    return json.loads(context.store.items[f"{name}-v1"].get("metadata") or "{}")


@then("the model was asked to be picky, with room for {room:d} pick, and given every idea with its stars")
@then("the model was asked to be picky, with room for {room:d} picks, and given every idea with its stars")
def step_asked(context, room):
    call = context.calls[-1]
    assert "very picky" in call["system"] and f"At most {room} of these" in call["system"] and "ROLE AND MISSION" in call["system"], call["system"]
    assert "WHAT IS PUBLISHED" in call["user"] and "Editor stars: 4" in call["user"], call["user"]
    assert call["user"].index("Headline first") < call["user"].index("Headline second") < call["user"].index("Headline third"), call["user"]


@then("the picked idea has a research assignment with the model's direction")
def step_assignment(context):
    assert [row["direction"] for row in context.assigned] == ["Find the court records"], context.assigned
    assert context.assigned[0]["content-item"] == "second" and context.assigned[0]["context-profile"] == "reporter", context.assigned


@then("the picked idea moved to the assignment stage as the editor agent")
def step_moved(context):
    assert context.moves == [("second", "assignment", selection.ACTOR)], context.moves


@then("the picked idea records its reason, the pack and the settings")
def step_recorded(context):
    record = meta(context, "second")["selection"]
    assert record["verdict"] == "picked" and "Best" in record["reason"] and record["contextHash"] == "hash-1" and record["settings"]["maxNewStories"] == 1, record


@then("the declined ideas stay at the idea stage with their reasons")
def step_declined(context):
    for name in ("first", "third"):
        assert context.store.items[f"{name}-v1"]["stage"] == "idea"
        assert meta(context, name)["selection"]["verdict"] == "declined" and "Repeats" in meta(context, name)["selection"]["reason"]


@then("no idea is spiked")
def step_not_spiked(context):
    assert all(stage != "spiked" for _, stage, _ in context.moves) and all(row.get("stage") != "spiked" for row in context.store.items.values())


@then("no research assignment is created")
def step_no_assignment(context):
    assert not context.assigned and not context.moves


@then("every idea records why it was declined")
def step_all_declined(context):
    assert all(meta(context, name)["selection"]["verdict"] == "declined" for name in ("first", "second", "third"))


@then("no model was called")
def step_no_model(context):
    assert not context.calls


@then("the outcome says the rate limit was reached")
def step_limit(context):
    assert context.outcome["stopped"] == "rate limit reached", context.outcome


@then("the model was called")
def step_model_called(context):
    assert len(context.calls) == 1, context.calls


@then("only the first pick starts research")
def step_only_first(context):
    assert [row["content-item"] for row in context.assigned] == ["first"], context.assigned


@then("the other picks are reported as over the limit and record nothing")
def step_over(context):
    verdicts = {row["lineage"]: row["verdict"] for row in context.outcome["decisions"]}
    assert verdicts == {"first": "picked", "second": "over_limit", "third": "over_limit"}, verdicts
    assert "selection" not in meta(context, "second") and "selection" not in meta(context, "third")


@then("the idea records that it was not started")
def step_not_started(context):
    assert "not started" in meta(context, "first")["selection"]["reason"]


@then("the selection wrote nothing")
def step_nothing(context):
    assert not context.store.updates and not context.assigned and not context.moves


@then("the outcome still holds the decisions")
def step_holds(context):
    assert {row["verdict"] for row in context.outcome["decisions"]} == {"picked", "declined"}


@then("the second run had no idea to decide on")
def step_second(context):
    assert context.outcome["stopped"] == "no idea to decide on" and len(context.calls) == context.calls_before, context.outcome


@then("the model was called again")
def step_called_again(context):
    assert len(context.calls) == context.calls_before + 1


@then("the pack was asked for the 5 newest Stories in the section and 7 days in the site")
def step_pack_recent(context):
    assert context.packs[-1]["recent"] == {"desk_published": {"stories": 5}, "publication_published": {"days": 7}}, context.packs[-1]


@then("each idea records those settings")
def step_settings_recorded(context):
    assert meta(context, "first")["selection"]["settings"]["recentSection"] == {"stories": 5}


@then('"{text}" means {number:d} {unit}')
def step_means(context, text, number, unit):
    assert selection.parse_recent(text) == {unit: number}


@then('"{text}" is refused as a recent setting')
def step_refused_recent(context, text):
    try:
        selection.parse_recent(text)
    except ValueError:
        return
    raise AssertionError("not refused")


@then("the selection is refused naming the section")
def step_refused_section(context):
    assert context.error and "nowhere" in context.error, context.error
