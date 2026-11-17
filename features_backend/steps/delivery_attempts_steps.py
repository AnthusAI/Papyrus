"""The attempt log, the guard and the one worker for each channel account (features_backend/delivery-*attempt*.feature, delivery-one-consumer-per-account.feature).

The catalog, the Story and the Deliveries are made by announcement_records_steps.py. The channel is ``FakeChannel``: it dedupes on the event id like Caducus and
posts nothing until an event is handed over. No network, no AWS.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import parse
from behave import register_type, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.announcements.attempts import ANSWER_SENT, AccountWorker, Answer, Attempts, Wait, shown  # noqa: E402
from papyrus_content.announcements.attempts_fakes import FakeChannel  # noqa: E402
from papyrus_content.announcements.records import SUPERSEDED, attempt_log  # noqa: E402


@parse.with_pattern(r'[^"]*')
def parse_quoted(text):
    return text


register_type(Q=parse_quoted)


def attempt(context, action):
    context.error = None
    try:
        return action()
    except Exception as error:   # noqa: BLE001 - the specs ask what the call said
        context.error = error
        return None


def row_of(context, channel, account, generation=None):
    rows = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account]
    assert rows, f"no Delivery for {channel} {account}"
    if generation is not None:
        rows = [row for row in rows if int(row["generation"]) == generation]
        assert rows, f"no generation {generation} of {channel} {account}"
        return dict(rows[0])
    return dict(max(rows, key=lambda row: int(row["generation"])))


def log_of(context, channel, account, generation=None):
    return attempt_log(context.deliveries.get(row_of(context, channel, account, generation)["id"]))


def channel_of(context):
    if getattr(context, "fake_channel", None) is None:
        context.fake_channel = FakeChannel(context.deliveries)
        context.workers = {}
    return context.fake_channel


# --- setup ----------------------------------------------------------------------------------------------------------------------------------------


@step('one worker serves the channel "{channel:Q}" account "{account:Q}"')
def one_worker(context, channel, account):
    transport = channel_of(context)
    context.workers[(channel, account)] = AccountWorker(context.deliveries, transport, channel, account)
    context.worker = context.workers[(channel, account)]


@step('the channel answers the next new event with "{what:Q}"')
def next_event(context, what):
    channel_of(context).next_event(what)


@step('the channel answers the next new event with "{what:Q}" and "{detail:Q}"')
def next_event_detail(context, what, detail):
    channel_of(context).next_event(what, (detail, None) if what == "refused" else detail)


@step('the channel answers the next new event with "{what:Q}" until "{when:Q}"')
def next_event_until(context, what, when):
    channel_of(context).next_event(what, when)


@step('the channel answers the next new event with "{what:Q}" and "{code:Q}" until "{when:Q}"')
def next_event_code_until(context, what, code, when):
    channel_of(context).next_event(what, (code, when))


# --- acting ---------------------------------------------------------------------------------------------------------------------------------------


@step('the worker sends the Delivery "{channel:Q}" "{account:Q}"')
def worker_sends(context, channel, account):
    attempt(context, lambda: context.worker.send(row_of(context, channel, account)["id"], by="worker", now=context.now))


@step('the worker sends generation {generation:d} of "{channel:Q}" "{account:Q}"')
def worker_sends_generation(context, generation, channel, account):
    attempt(context, lambda: context.worker.send(row_of(context, channel, account, generation)["id"], by="worker", now=context.now))


@step('the worker for "{worker_channel:Q}" "{worker_account:Q}" sends the Delivery "{channel:Q}" "{account:Q}"')
def named_worker_sends(context, worker_channel, worker_account, channel, account):
    worker = context.workers[(worker_channel, worker_account)]
    attempt(context, lambda: worker.send(row_of(context, channel, account)["id"], by="worker", now=context.now))


@step('the worker settles the Delivery "{channel:Q}" "{account:Q}"')
def worker_settles(context, channel, account):
    attempt(context, lambda: context.worker.settle(row_of(context, channel, account)["id"], by="worker", now=context.now))


@step('an attempt is opened for the Delivery "{channel:Q}" "{account:Q}" and the worker dies before the call')
def open_and_die(context, channel, account):
    attempt(context, lambda: Attempts(context.deliveries).open(row_of(context, channel, account)["id"], by="worker", now=context.now))
    assert context.error is None, context.error


@step('the person "{who:Q}" sets the Delivery "{channel:Q}" "{account:Q}" ready to try again')
def person_retries(context, who, channel, account):
    attempt(context, lambda: context.deliveries.retry(context.deliveries.get(row_of(context, channel, account)["id"]), by=who, now=context.now))
    assert context.error is None, context.error


@step('the person "{who:Q}" lifts the pause on the Delivery "{channel:Q}" "{account:Q}"')
def person_resumes(context, who, channel, account):
    attempt(context, lambda: context.deliveries.resume(context.deliveries.get(row_of(context, channel, account)["id"]), by=who, now=context.now))
    assert context.error is None, context.error


@when('the attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}" is closed as "{outcome:Q}"')
def close_attempt(context, number, channel, account, outcome):
    attempt(context, lambda: Attempts(context.deliveries).close(row_of(context, channel, account)["id"], number, outcome, by="worker", now=context.now))


@when('the attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}" is closed as "refused" with the code "rate limit" and no time')
def close_rate_limit_without_time(context, number, channel, account):
    attempt(context, lambda: Attempts(context.deliveries).close(row_of(context, channel, account)["id"], number, "refused", by="worker", now=context.now, code="rate limit",
                                                                wait=Wait("rate limit", None)))


@when('Caducus records the post for attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
@step('Caducus records the post for attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}"')
def caducus_records_post(context, number, channel, account):
    event = log_of(context, channel, account)[number - 1]["eventId"]
    channel_of(context).finish(event, Answer(ANSWER_SENT, provider_id=f"post-{len(channel_of(context).posts) + 1}", cost="0.200"))


@when('Caducus records that attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}" was refused with "{code:Q}"')
def caducus_records_refusal(context, number, channel, account, code):
    event = log_of(context, channel, account)[number - 1]["eventId"]
    channel_of(context).finish(event, Answer("failed", code=code))


@step('the log of the Delivery "{channel:Q}" "{account:Q}" is remembered')
def remember_log(context, channel, account):
    context.remembered = [dict(entry) for entry in log_of(context, channel, account)]


@then('the remembered entries of the Delivery "{channel:Q}" "{account:Q}" are exactly as they were')
def remembered_unchanged(context, channel, account):
    now = log_of(context, channel, account)
    assert now[:len(context.remembered)] == context.remembered, (context.remembered, now)


@step('the words file of the Delivery "{channel:Q}" "{account:Q}" is lost')
def words_lost(context, channel, account):
    context.files.texts.pop(row_of(context, channel, account)["id"])


@step('the words file of the Delivery "{channel:Q}" "{account:Q}" is replaced by "{words:Q}"')
def words_replaced(context, channel, account, words):
    context.files.texts[row_of(context, channel, account)["id"]] = words


@step('the Delivery "{channel:Q}" "{account:Q}" is marked superseded by a correction made elsewhere')
def marked_superseded(context, channel, account):
    row = context.deliveries.get(row_of(context, channel, account)["id"])
    context.deliveries._change(row, {"state": SUPERSEDED, "supersededBy": f"{row['id']}-elsewhere"}, by="ellie", note="corrected elsewhere", now=context.now)


@step('the Delivery "{channel:Q}" "{account:Q}" changes under the worker just before the close')
def changes_under_the_worker(context, channel, account):
    backend, target = context.backend, row_of(context, channel, account)["id"]
    original = backend.update_record_if
    state = {"done": False}

    def update_record_if(model, record, condition):
        if model == "Delivery" and record["id"] == target and "attempts" in record and not state["done"]:
            state["done"] = True
            marked_superseded(context, channel, account)
        return original(model, record, condition)

    backend.update_record_if = update_record_if


@when('two workers read the Delivery "{channel:Q}" "{account:Q}" and both open an attempt')
def two_workers_open(context, channel, account):
    delivery = row_of(context, channel, account)["id"]
    attempts = Attempts(context.deliveries)
    read_by_both = context.deliveries.get(delivery)
    outcomes = []
    original = context.deliveries.get
    context.deliveries.get = lambda row_id: dict(read_by_both) if row_id == delivery else original(row_id)
    try:
        for who in ("first", "second"):
            attempt(context, lambda: attempts.open(delivery, by=who, now=context.now))
            outcomes.append(context.error)
    finally:
        context.deliveries.get = original
    context.outcomes_of_two = outcomes


@then("exactly one attempt is written and the other is told the Delivery changed")
def one_wins(context):
    errors = context.outcomes_of_two
    assert errors[0] is None and type(errors[1]).__name__ == "Conflict", errors
    assert len(attempt_log(context.deliveries.get(row_of(context, "x", "handle-1")["id"]))) == 1


# --- reading --------------------------------------------------------------------------------------------------------------------------------------


@then('the Delivery "{channel:Q}" "{account:Q}" is "{state:Q}"')
def delivery_is(context, channel, account, state):
    assert row_of(context, channel, account)["state"] == state, row_of(context, channel, account)["state"]


@then('the Delivery "{channel:Q}" "{account:Q}" generation {generation:d} is "{state:Q}"')
def generation_is(context, channel, account, generation, state):
    assert row_of(context, channel, account, generation)["state"] == state


@then('the Delivery "{channel:Q}" "{account:Q}" has these attempts')
def has_attempts(context, channel, account):
    check_attempts(context, log_of(context, channel, account), context.table)


@then('generation {generation:d} of "{channel:Q}" "{account:Q}" has these attempts')
def generation_has_attempts(context, generation, channel, account):
    check_attempts(context, log_of(context, channel, account, generation), context.table)


def check_attempts(context, log, table):
    expected = list(table)
    assert len(log) == len(expected), (len(log), [entry["outcome"] for entry in log])
    for entry, want in zip(log, expected):
        assert int(entry["number"]) == int(want["number"]), entry
        assert entry["outcome"] == want["outcome"], (entry, want)
        if "code" in table.headings:
            assert (entry.get("code") or "") == want["code"], (entry, want)


@then('the Delivery "{channel:Q}" "{account:Q}" has {count:d} attempt')
@then('the Delivery "{channel:Q}" "{account:Q}" has {count:d} attempts')
def attempt_count(context, channel, account, count):
    assert len(log_of(context, channel, account)) == count, log_of(context, channel, account)


@then('the Delivery "{channel:Q}" "{account:Q}" has no attempts')
def no_attempts(context, channel, account):
    assert log_of(context, channel, account) == []


@then('generation {generation:d} of "{channel:Q}" "{account:Q}" has no attempts')
def generation_no_attempts(context, generation, channel, account):
    assert log_of(context, channel, account, generation) == []


@then('the Delivery "{channel:Q}" "{account:Q}" shows "{words:Q}" for attempt {number:d}')
def shows(context, channel, account, words, number):
    assert shown(log_of(context, channel, account)[number - 1])[1] == words


@then("every attempt of the Delivery \"{channel:Q}\" \"{account:Q}\" has the event id delivery:<the Delivery id>:a<its number>")
def event_ids_shape(context, channel, account):
    row = row_of(context, channel, account)
    log = log_of(context, channel, account)
    assert log
    for entry in log:
        assert entry["eventId"] == f"delivery:{row['id']}:a{entry['number']}", entry


@then('the channel was handed the events of attempts "{numbers:Q}" of the Delivery "{channel:Q}" "{account:Q}" in that order')
def handed_in_order(context, numbers, channel, account):
    log = log_of(context, channel, account)
    wanted = [log[int(number) - 1]["eventId"] for number in numbers.split(",")]
    assert channel_of(context).submissions == wanted, (channel_of(context).submissions, wanted)


@then('no event of the Delivery "{channel:Q}" "{account:Q}" carries a round suffix')
def no_round_suffix(context, channel, account):
    for entry in log_of(context, channel, account):
        assert not re.search(r":r\d+$", entry["eventId"]) and "round" not in entry["eventId"], entry


@then('the entry for attempt {number:d} of the Delivery "{channel:Q}" "{account:Q}" was already "{outcome:Q}" when the channel was called')
def started_first(context, number, channel, account, outcome):
    event = log_of(context, channel, account)[number - 1]["eventId"]
    seen = [what for called, what in channel_of(context).started_when_called if called == event]
    assert seen and seen[0] == outcome, channel_of(context).started_when_called


@then("exactly {count:d} post was made")
@then("exactly {count:d} posts were made")
def posts_made(context, count):
    assert len(channel_of(context).posts) == count, channel_of(context).posts


@then("nothing was sent")
def nothing_sent(context):
    assert channel_of(context).submissions == [], channel_of(context).submissions


@then('exactly 1 flag was raised about generation {generation:d} of "{channel:Q}" "{account:Q}"')
def one_flag_generation(context, generation, channel, account):
    flags_about(context, row_of(context, channel, account, generation)["id"], 1)


@then('exactly 1 flag was raised about the Delivery "{channel:Q}" "{account:Q}"')
def one_flag(context, channel, account):
    flags_about(context, row_of(context, channel, account)["id"], 1)


@then("no flag was raised")
def no_flag(context):
    assert context.backend.rows("ReviewRequest") == []


def flags_about(context, delivery, count):
    import json

    found = [row for row in context.backend.rows("ReviewRequest") if json.loads(row["subject"]) == {"type": "delivery", "id": delivery}]
    assert len(found) == count, found
    assert all(row["mode"] == "flag" and row["state"] == "open" for row in found), found
    assert records  # the module is the one the flag names its Delivery by


@then('the worker for "{channel:Q}" "{account:Q}" handled {count:d} attempt')
@then('the worker for "{channel:Q}" "{account:Q}" handled {count:d} attempts')
def handled(context, channel, account, count):
    assert len(context.workers[(channel, account)].handled) == count, context.workers[(channel, account)].handled
