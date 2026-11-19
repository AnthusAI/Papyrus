"""The account's pace, the blocked list, the retry and the connect link (features_backend/announcement-operations.feature). The world is the one announcements_steps.py builds."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent))
from announcements_steps import NOW_ISO, run_cli, x_row  # noqa: E402
from papyrus_content import console_links, env  # noqa: E402
from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.announcements.deliveries import Plan  # noqa: E402
from papyrus_content.announcements.link_reads import StoryRef  # noqa: E402

PREVIOUS_CYCLE = "2026-10-15T09:00:00Z"   # the billing cycle starts on the 1st: 15 October is the cycle before 13 November


def _sent_post(context, number, at):
    lineage = f"pace-{number}"
    context.backend.add_story(lineage, stars=5, summary="A summary.")
    ref = StoryRef(lineage, f"{lineage}-v1", 1)
    plan = Plan(channel="x", account_id="mom", approval="none", approval_policy="publication policy", text="A post", audience=())
    made = context.announcements.announce(dedupe_key=records.story_published_key(lineage), kind="story_published", stories=[ref], plans=[plan], created_by="announce",
                                          trigger="page_live", now=at)
    row = next(row for row in context.backend.rows("Delivery") if row["announcementId"] == made.announcement["id"] and row["channel"] == "x")
    entry = {"number": 1, "at": at, "eventId": f"delivery:{row['id']}:a1", "outcome": "sent", "closedAt": at}
    context.deliveries._change(row, {"state": "sent", "attempts": [entry]}, by="deliver", note="attempt 1 sent", now=at)
    context.sent_rows = [*getattr(context, "sent_rows", []), row["id"]]


@given("the account sent {count:d} X posts this cycle, each for a different Announcement")
def _posts(context, count):
    for number in range(count):
        _sent_post(context, number, NOW_ISO)


@given("the account sent {count:d} X posts in the cycle before this one")
def _earlier(context, count):
    for number in range(count):
        _sent_post(context, number, PREVIOUS_CYCLE)


@given("that post was deleted afterwards")
def _deleted(context):
    row = context.deliveries.get(context.sent_rows[-1])
    context.deliveries._change(row, {"state": "withdrawn"}, by="ada", note="withdrawn: the post was deleted", now=NOW_ISO)


@given("the site has entered no prices")
def _no_prices(context):
    document = context.functions.settings.store.document
    document["prices"] = {}
    context.functions.settings.store.put(document)


@then("the status counts {count:d} posts this cycle")
def _count(context, count):
    assert context.cli_answer["result"]["postCount"] == count, context.cli_answer


@then('the status suggests "{sentence}"')
def _suggests(context, sentence):
    assert context.cli_answer["result"]["suggestion"]["sentence"] == sentence, context.cli_answer


@then("the status has no suggestion")
def _no_suggestion(context):
    assert "suggestion" not in context.cli_answer["result"], context.cli_answer


@then('the blocked list has the Article with the words "{words}"')
def _blocked_has(context, words):
    blocked = context.cli_answer["result"]["blocked"]
    assert len(blocked) == 1 and blocked[0]["words"] == words and blocked[0]["stories"] == [{"lineageId": context.lineage}], blocked


@then("the blocked list is empty")
def _blocked_empty(context):
    assert context.cli_answer["result"]["blocked"] == [], context.cli_answer


@given("a failed X Delivery")
def _failed(context):
    _sent_post(context, 90, NOW_ISO)
    row = context.deliveries.get(context.sent_rows[-1])
    context.failed_id = row["id"]
    entry = {"number": 1, "at": NOW_ISO, "eventId": f"delivery:{row['id']}:a1", "outcome": "refused", "code": "403 Forbidden", "closedAt": NOW_ISO}
    context.deliveries._change(row, {"state": "failed", "attempts": [entry]}, by="deliver", note="attempt 1 refused", now=NOW_ISO)


@when("a person retries that Delivery")
def _person_retries(context):
    run_cli(context, f"papyrus announcements retry '{getattr(context, 'failed_id', None) or x_row(context)['id']}'")


@when("an AI agent retries that Delivery")
def _agent_retries(context):
    run_cli(context, f"papyrus announcements retry '{context.failed_id}'", agent=True)


@then("the retried Delivery is ready and keeps its attempt in the log")
def _retried(context):
    row = context.deliveries.get(context.failed_id)
    assert row["state"] == "ready" and len(records.attempt_log(row)) == 1, row
    assert context.cli_answer["result"] == {"id": context.failed_id, "state": "ready"}, context.cli_answer


@given('the console address is "{address}"')
def _console(context, address):
    patcher = mock.patch.dict("os.environ", {console_links.CONSOLE_URL_VARIABLE: address})
    patcher.start()
    context.add_cleanup(patcher.stop)


@given("the console address is unknown")
def _console_unknown(context):
    patcher = mock.patch.dict("os.environ", {}, clear=False)
    patcher.start()
    context.add_cleanup(patcher.stop)
    import os

    os.environ.pop(console_links.CONSOLE_URL_VARIABLE, None)
    published = mock.patch.object(env, "site_published", lambda name: None)
    published.start()
    context.add_cleanup(published.stop)


@then('the announcement answer\'s address is "{address}"')
def _address(context, address):
    assert context.cli_answer["result"]["url"] == address, context.cli_answer


# --- retiring a Story (features_backend/announcement-retire-withdraws.feature) ----------------------------------------------------------------------------


@when("the Article is retired with `papyrus stories retire`")
def _retire(context):
    import contextlib
    import io

    from papyrus_content import story_retire

    context.backend.retire(context.lineage)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        story_retire.withdraw_announcements(context.backend, context.lineage, "tester")
    context.retire_lines = [line.split("\t") for line in output.getvalue().splitlines()]


@then('the retire command printed "{label}" for the X Delivery')
def _printed(context, label):
    assert [line[2:4] for line in context.retire_lines] == [[label, x_row(context)["id"]]], context.retire_lines


@then('the retire command printed "NOT withdrawn" for the X Delivery, saying it needs the site\'s own X channel')
def _printed_not(context):
    assert len(context.retire_lines) >= 1
    lines = [line for line in context.retire_lines if line[3] == x_row(context)["id"]]
    assert len(lines) == 1 and lines[0][2] == "NOT withdrawn" and "own x channel" in lines[0][4].lower(), context.retire_lines


@then("the retire command printed nothing about announcements")
def _printed_nothing(context):
    assert context.retire_lines == [], context.retire_lines


@given("a roundup Announcement about that Article and a second live Article")
def _roundup(context):
    first = context.lineage
    context.backend.add_story("live-two", stars=5, summary="Another.")
    refs = [StoryRef(first, f"{first}-v1", 1), StoryRef("live-two", "live-two-v1", 1)]
    plan = Plan(channel="x", account_id="mom", approval="none", approval_policy="publication policy", text="A roundup", audience=())
    made = context.announcements.announce(dedupe_key="roundup:test", kind="story_published", stories=refs, plans=[plan], created_by="announce", trigger="page_live", now=NOW_ISO)
    context.roundup_delivery = next(row["id"] for row in made.deliveries)


@then("the roundup's Delivery is not withdrawn")
def _roundup_stays(context):
    assert context.deliveries.get(context.roundup_delivery)["state"] != "withdrawn"
    assert all(line[3] != context.roundup_delivery for line in context.retire_lines), context.retire_lines
