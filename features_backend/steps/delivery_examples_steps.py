"""What a person changed in a Delivery and how far it reaches (features_backend/delivery-edit-capture.feature, PPY-627bbc).

The catalog, the Deliveries and the one door are built by announcement_records_steps.py and delivery_editing_steps.py; this file only records an edit and reads what was recorded.
No network, no AWS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, step, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from announcement_records_steps import attempt  # noqa: E402
from papyrus_content.announcements.delivery_versions import Versions  # noqa: E402
from delivery_editing_steps import _handlers, row_of  # noqa: E402
from papyrus_content.announcements import delivery_examples  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402


def examples_of(context):
    return delivery_examples.Examples(context.deliveries)


def _record(context, who, channel, account, scope, reason):
    delivery = row_of(context, channel, account)["id"]
    context.recorded = attempt(context, lambda: examples_of(context).record(delivery, by=who, scope=scope, reason=reason, now=context.now))


@step('the person "{who:Q}" records the edit of the Delivery "{channel:Q}" "{account:Q}" with the scope "{scope:Q}"')
def person_records(context, who, channel, account, scope):
    _record(context, who, channel, account, scope, None)


@step('the person "{who:Q}" records the edit of the Delivery "{channel:Q}" "{account:Q}" with the scope "{scope:Q}" and the reason "{reason:Q}"')
def person_records_with_reason(context, who, channel, account, scope, reason):
    _record(context, who, channel, account, scope, reason)


@step('the person "{who:Q}" records the edit of the Delivery "{channel:Q}" "{account:Q}" with no scope')
def person_records_no_scope(context, who, channel, account):
    _record(context, who, channel, account, None, None)


@step('the person "{who:Q}" records the edit of the Delivery "{channel:Q}" "{account:Q}" with no scope and the reason "{reason:Q}"')
def person_records_reason_no_scope(context, who, channel, account, reason):
    _record(context, who, channel, account, None, reason)


@step('the person "{who:Q}" asks the door to record the edit of the Delivery "{channel:Q}" "{account:Q}" with the scope "{scope:Q}"')
def person_door_records(context, who, channel, account, scope):
    context.envelope = execute("announcements_example", {"delivery": row_of(context, channel, account)["id"], "scope": scope}, Caller(kind="person", subject=who, is_admin=False),
                               _handlers(context))


@step('the announce agent asks the door to record the edit of the Delivery "{channel:Q}" "{account:Q}" with the scope "{scope:Q}"')
def agent_door_records(context, channel, account, scope):
    context.envelope = execute("announcements_example", {"delivery": row_of(context, channel, account)["id"], "scope": scope}, context.agent, _handlers(context))


@then('the Delivery "{channel:Q}" "{account:Q}" is {article} "{state:Q}" example with the scope "{scope:Q}"')
def is_example(context, channel, account, article, state, scope):
    assert context.error is None, repr(context.error)
    row = row_of(context, channel, account)
    assert row.get("exampleState") == state and row.get("exampleScope") == scope, (row.get("exampleState"), row.get("exampleScope"))


@then('the Delivery "{channel:Q}" "{account:Q}" is {article} "{state:Q}" example with no scope')
def is_example_without_scope(context, channel, account, article, state):
    row = row_of(context, channel, account)
    assert row.get("exampleState") == state and row.get("exampleScope") is None, (row.get("exampleState"), row.get("exampleScope"))


@then('the Delivery "{channel:Q}" "{account:Q}" records version {machine:d} as the machine\'s and version {final:d} as the final one')
def records_versions(context, channel, account, machine, final):
    row = row_of(context, channel, account)
    assert row.get("machineVersion") == machine and delivery_examples.final_version(row) == final, (row.get("machineVersion"), delivery_examples.final_version(row))


@then('the active example of the Delivery "{channel:Q}" "{account:Q}" is read from the partition "{partition:Q}"')
def read_from_partition(context, channel, account, partition):
    row = row_of(context, channel, account)
    assert row.get("exampleKey") == partition, row.get("exampleKey")


@then('the Delivery "{channel:Q}" "{account:Q}" is in no partition of active examples')
def in_no_partition(context, channel, account):
    assert row_of(context, channel, account).get("exampleKey") is None


@then('the record said "{text:Q}"')
def record_said(context, text):
    assert context.error is None, repr(context.error)
    assert not context.recorded.recorded and text in (context.recorded.reason or ""), context.recorded


@then('the reason of the Delivery "{channel:Q}" "{account:Q}" in S3 is "{reason:Q}"')
def reason_in_s3(context, channel, account, reason):
    assert examples_of(context).reason_of(row_of(context, channel, account)) == reason


@then('the Delivery row "{channel:Q}" "{account:Q}" holds none of "{words:Q}"')
def row_holds_none(context, channel, account, words):
    assert words not in json.dumps(row_of(context, channel, account)), "the reason is in the catalog row"


@then('the history of the Delivery "{channel:Q}" "{account:Q}" shows "{who:Q}" recorded it')
def history_shows_recorder(context, channel, account, who):
    lines = context.deliveries.history(row_of(context, channel, account))
    assert any(line["by"] == who and "example recorded" in line["note"] for line in lines), lines


# --- a preferred version ------------------------------------------------------------------------------------------------------------------------------


def _preferred(context, caller, channel, account, number, words, scope):
    arguments = {"delivery": row_of(context, channel, account)["id"], "replaces": number, "text": words}
    if scope:
        arguments["scope"] = scope
    context.envelope = execute("announcements_preferred", arguments, caller, _handlers(context))


@step('the person "{who:Q}" saves a preferred version over version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}"')
def person_saves_preferred(context, who, number, channel, account, words):
    _preferred(context, Caller(kind="person", subject=who, is_admin=False), channel, account, number, words, None)


@step('the person "{who:Q}" saves a preferred version over version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}" and the scope "{scope:Q}"')
def person_saves_preferred_with_scope(context, who, number, channel, account, words, scope):
    _preferred(context, Caller(kind="person", subject=who, is_admin=False), channel, account, number, words, scope)


@step('the announce agent asks the door to save a preferred version over version {number:d} of the Delivery "{channel:Q}" "{account:Q}" with the words "{words:Q}"')
def agent_saves_preferred(context, number, channel, account, words):
    _preferred(context, context.agent, channel, account, number, words, None)


@then('generation {generation:d} of "{channel:Q}" "{account:Q}" is still {article} "{state:Q}" example with the scope "{scope:Q}"')
def generation_still_example(context, generation, channel, account, article, state, scope):
    rows = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account and int(row["generation"]) == generation]
    assert rows and rows[0].get("exampleState") == state and rows[0].get("exampleScope") == scope, rows


# --- the drafter reads the examples (features_backend/drafter-examples.feature, PPY-d99bd0) -------------------------------------------------------------


def _announced_rewritten(context, who, text, scope, reason):
    import announcements_steps as base

    base.story(context, stars=5)
    base.wake(context)
    row = next(row for row in base.x_rows(context) if row["announcementId"] == base.announcement_of(context)["id"])
    versions = Versions(context.deliveries)
    link = base.post.LINK.search(context.deliveries.text(row)).group(0)   # a person's rewrite of a post keeps the Story's link, which the channel needs to send it
    versions.save(row["id"], replaces=int(row["version"]), text=base.post.compose(text, link), by=who)
    run = base.runner(context)
    run.send(row["id"], now=context.now)
    for event in list(context.x.events):
        if context.x.deliveries[event]["status"] == "queued":
            context.x.deliver(event)
    run.settle(row["id"], now=context.now)
    context.example_count = getattr(context, "example_count", 0) + 1
    context.example_ids = [*getattr(context, "example_ids", []), row["id"]]
    when = f"2026-11-17T09:{context.example_count:02d}:00Z"
    sent = context.deliveries.get(row["id"])
    assert sent["state"] == "sent", sent["state"]
    if scope:
        delivery_examples.Examples(context.deliveries).record(row["id"], by=who, scope=scope, reason=reason, now=when)
    else:
        delivery_examples.Examples(context.deliveries).record(row["id"], by=who, now=when)


@step('an Article was announced on X, rewritten by the person "{who:Q}" as "{text:Q}" and sent, who said it reaches the "{scope:Q}"')
def announced_rewritten(context, who, text, scope):
    _announced_rewritten(context, who, text, scope, None)


@step('an Article was announced on X, rewritten by the person "{who:Q}" as "{text:Q}" and sent, who said it reaches the "{scope:Q}" with the reason "{reason:Q}"')
def announced_rewritten_with_reason(context, who, text, scope, reason):
    _announced_rewritten(context, who, text, scope, reason)


@step('an Article was announced on X, rewritten by the person "{who:Q}" as "{text:Q}" and sent, with no scope chosen')
def announced_rewritten_no_scope(context, who, text):
    _announced_rewritten(context, who, text, None, None)


@step("a second 5-star Article is published")
def second_published(context):
    import announcements_steps as base

    base.story(context, stars=5)
    base.wake(context)


def _x_row_of_story(context):
    import announcements_steps as base

    return next(row for row in context.backend.rows("Delivery") if row["channel"] == "x" and row["announcementId"] == base.announcement_of(context)["id"])


@then('the model was told the person\'s version "{text:Q}"')
def told_version(context, text):
    assert f"Person's version: {text}" in context.model_system, context.model_system


@then('the model was told the reason "{text:Q}"')
def told_reason(context, text):
    assert f"Why: {text}" in context.model_system, context.model_system


@then('the model was shown the draft "{text:Q}"')
def shown_draft(context, text):
    assert f"Draft: {text}" in context.model_system, context.model_system


@then("the model was told no earlier drafts a person rewrote")
def told_none(context):
    assert "Earlier drafts a person rewrote" not in context.model_system, context.model_system


@then("the draft of the second Article lists the first Article's Delivery among the examples it read")
def lists_first(context):
    from papyrus_content.announcements.x_announce import recorded_inputs

    assert recorded_inputs(_x_row_of_story(context))["examples"] == [context.example_ids[0]], recorded_inputs(_x_row_of_story(context))


def _explained(context):
    from papyrus_content.announcements.explain import explain_delivery
    from papyrus_content.announcements.x_announce import recorded_inputs

    row = _x_row_of_story(context)
    named = (recorded_inputs(row) or {}).get("examples") or []
    return explain_delivery(row, [found for found in (context.deliveries.get(example) for example in named) if found])


@then('explaining the second Article\'s X Delivery names the example as "{state:Q}" for the "{scope:Q}"')
def explain_names(context, state, scope):
    answer = _explained(context)
    assert answer["examples"] == [{"delivery": context.example_ids[0], "state": state, "scope": scope}], answer


@then("explaining the X Delivery lists {count:d} examples")
def explain_lists(context, count):
    assert len(_explained(context)["examples"]) == count, _explained(context)


@given('the writing guidelines have the layers "{first:Q}" at version {v1:d} with the hash "{h1:Q}" and "{second:Q}" at version {v2:d} with the hash "{h2:Q}"')
def guideline_layers(context, first, v1, h1, second, v2, h2):
    context.guideline_layers = [{"scope": first, "itemId": f"item-{first}", "versionNumber": v1, "contentHash": h1},
                                {"scope": second, "itemId": f"item-{second}", "versionNumber": v2, "contentHash": h2}]


@then('explaining the X Delivery lists the guideline layers "{first:Q}" version {v1:d} and "{second:Q}" version {v2:d} with their hashes')
def explain_layers(context, first, v1, second, v2):
    layers = _explained(context)["guidelineLayers"]
    assert [(layer["scope"], layer["versionNumber"], layer["contentHash"]) for layer in layers] == [(first, v1, "ab12cd"), (second, v2, "ef34ab")], layers


def _loaded(context, channel, kind, budget=None):
    from papyrus_content.announcements import learned_examples
    from papyrus_content.announcements.post import LINK

    arguments = {"channel": channel, "kind": kind, "words_of": lambda text: LINK.sub("", text).strip()}
    if budget is not None:
        arguments["budget"] = budget
    return learned_examples.load(context.deliveries, **arguments)


@then('{count:d} example is loaded for the channel "{channel:Q}" and the kind "{kind:Q}"')
@then('{count:d} examples are loaded for the channel "{channel:Q}" and the kind "{kind:Q}"')
def examples_loaded(context, count, channel, kind):
    assert len(_loaded(context, channel, kind).examples) == count, _loaded(context, channel, kind).examples


@then('the examples loaded for the channel "{channel:Q}" and the kind "{kind:Q}" read newest first: {words}')
def examples_newest_first(context, channel, kind, words):
    wanted = [part.strip().strip('"') for part in words.split('", "')]
    assert [example.after for example in _loaded(context, channel, kind).examples] == [part.strip('"') for part in wanted], [example.after for example in _loaded(context, channel, kind).examples]


@when('the examples are loaded for the channel "{channel:Q}" and the kind "{kind:Q}" within a budget that holds two of them')
def examples_with_budget(context, channel, kind):
    everything = _loaded(context, channel, kind).examples
    two = everything[:2]
    context.read = _loaded(context, channel, kind, budget=sum(len(example.before) + len(example.after) for example in two))


@then("the examples loaded read: {words}")
def examples_read(context, words):
    wanted = [part.strip('"') for part in words.split('", "')]
    assert [example.after for example in context.read.examples] == wanted, [example.after for example in context.read.examples]


@then("{count:d} example was left out by the budget")
def left_out(context, count):
    assert context.read.dropped == count, context.read.dropped


@step('the person "{who:Q}" turns the first example off because "{why:Q}"')
def turn_off(context, who, why):
    context.recorded = attempt(context, lambda: delivery_examples.Examples(context.deliveries).stop(context.example_ids[0], delivery_examples.OFF, by=who, why=why, now="2026-11-18T09:00:00Z"))


@step("the first example is absorbed into an accepted guideline")
def absorb(context):
    delivery_examples.Examples(context.deliveries).stop(context.example_ids[0], delivery_examples.ABSORBED, by="learner", why="made into the guideline channel-x-voice", now="2026-11-18T09:00:00Z")


@then('the first example is "{state:Q}" and in no partition of active examples')
def first_is(context, state):
    row = context.deliveries.get(context.example_ids[0])
    assert row["exampleState"] == state and row.get("exampleKey") is None, row


@then('the first example\'s history says "{text:Q}"')
def first_history(context, text):
    assert any(text in line["note"] for line in context.deliveries.history(context.deliveries.get(context.example_ids[0]))), context.deliveries.history(context.deliveries.get(context.example_ids[0]))
