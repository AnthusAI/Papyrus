"""The counts of an email Delivery (features_backend/announcements/delivery-counts.feature).

Caducus runs in memory: its real router, delivery log, public audience and email channel, over its own in-memory store and queue, with the mailer replaced by a
recorder (``notifications_test.Site``). The Delivery catalog is the records fake of announcement_records_steps.py. Nothing is mailed and nothing reaches AWS.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from behave import given, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content import today  # noqa: E402
from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.announcements.attempts import AccountWorker  # noqa: E402
from papyrus_content.announcements.counts import counts_of, counts_text  # noqa: E402
from papyrus_content.announcements.email_channel import CaducusEmail  # noqa: E402
from papyrus_content.notifications import handler as notifications_handler  # noqa: E402

BY = "worker"


class TodayClient:
    """What Today may read: the announcement indexes through the records fake. The day's runs and the agents are not under test here, so they are empty."""

    tenant_id = None

    def __init__(self, backend):
        self.backend = backend

    def list_by_index(self, index, key, **options):
        return [] if index == "procedureRunsByStatus" else self.backend.list_by_index(index, key, **options)

    def list_tenant_rows(self, model, fields, **_):
        return []


def facts_of(row, text):
    return {"title": text.splitlines()[0], "url": f"https://alpha.example.test/{row['announcementId']}.html"}


def worker_of(context, account="alpha-send"):
    if getattr(context, "email_worker", None) is None:
        site = context.site
        context.email_channel = CaducusEmail(site.runtime.router, site.runtime.log, site.settings.site_id, facts_of, clock=site.clock)
        context.email_worker = AccountWorker(context.deliveries, context.email_channel, "email", account)
    return context.email_worker


def email_delivery(context, key):
    announcement = records.announcement_id(key)
    rows = [row for row in context.backend.rows("Delivery") if row["announcementId"] == announcement and row["channel"] == "email"]
    assert rows, f"no email Delivery for {key}"
    return dict(max(rows, key=lambda row: int(row["generation"])))


def fan_out_only(site):
    """Play only the fan-out pages of Caducus's queue, so each reader has a queued delivery and nothing has been mailed yet."""
    while True:
        pages = [(channel, body) for channel, body in site.queues.sent if "fanout" in body]
        if not pages:
            return
        site.queues.sent[:] = [item for item in site.queues.sent if item not in pages]
        batch = {"Records": [{"messageId": str(number), "body": json.dumps(body)} for number, (_channel, body) in enumerate(pages)]}
        assert notifications_handler.email_with(site.runtime, batch) == {"batchItemFailures": []}


@when('the worker sends the email Delivery of "{key}"')
def send(context, key):
    context.error = None
    worker = worker_of(context)
    try:
        worker.send(email_delivery(context, key)["id"], by=BY, now=context.now)
    except Exception as error:   # noqa: BLE001 - a spec may ask what the call said
        context.error = error


@when('the worker sends the email Delivery of "{key}" and Caducus works through its queue')
def send_and_play(context, key):
    send(context, key)
    assert context.error is None, context.error
    context.site.play_queue()
    worker_of(context).settle(email_delivery(context, key)["id"], by=BY, now=context.now)


@when("Caducus fans the event out to its readers but mails none yet")
def fan_out(context):
    fan_out_only(context.site)


@when("Caducus mails what it queued")
def mail_queue(context):
    context.site.play_queue()


@when('a complaint from an earlier message about "{address}" is recorded')
def earlier_complaint(context, address):
    audience = context.site.runtime.audience
    assert audience.provider_event(audience._keys.recipient(address), "complained") == "suppressed"


@when('the worker settles the email Delivery of "{key}"')
def settle(context, key):
    worker_of(context).settle(email_delivery(context, key)["id"], by=BY, now=context.now)


@when('the worker refreshes the counts of the email Delivery of "{key}"')
def refresh(context, key):
    worker_of(context).refresh_counts(email_delivery(context, key)["id"], by=BY, now=context.now)


def provider_event(context, kind, number, **extra):
    site = context.site
    event = site.ses_event(kind, f"fake-message-{number}", **extra)
    assert notifications_handler.ses_events_with(site.runtime, event) != "ignored"


@when("the provider reports a delivery of message {number:d}")
def provider_delivery(context, number):
    provider_event(context, "Delivery", number)


@when("the provider reports a permanent bounce of message {number:d}")
def provider_bounce(context, number):
    provider_event(context, "Bounce", number, bounce={"bounceType": "Permanent"})


@when("the provider reports a complaint about message {number:d}")
def provider_complaint(context, number):
    provider_event(context, "Complaint", number)


@when('the counts of the Delivery "{channel}" "{account}" are refreshed')
def refresh_other(context, channel, account):
    from papyrus_content.announcements.counts import DeliveryCounts

    row = next(row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account)
    context.error = None
    try:
        DeliveryCounts(context.deliveries).refresh(row["id"], source=None, by=BY, now=context.now)   # type: ignore[arg-type]
    except records.RecordError as error:
        context.error = error


@given('the Announcement of "{key}" is released')
def release(context, key):
    row = context.announcements.by_dedupe_key(key)
    context.announcements.release(row, context.now)


@when("Today is read for Tuesday 17 November 2026 in UTC")
def read_today(context):
    from datetime import datetime, timezone

    context.today_client = TodayClient(context.backend)
    context.backend.reads.clear()
    context.backend.gets.clear()
    context.today = today.today_overview(context.today_client, day="2026-11-17", time_zone="UTC", now=datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc))


@then('the Delivery of "{key}" counts "{text}"')
def counts(context, key, text):
    assert counts_text(counts_of(email_delivery(context, key))) == text, counts_text(counts_of(email_delivery(context, key)))


@then('Caducus\'s log for the Delivery of "{key}" holds {number:d} readers: "{statuses}"')
def log_holds(context, key, number, statuses):
    """The raw rows Caducus kept for the Delivery's attempts, grouped by their own statuses, compared to what the Delivery says."""
    events = [entry["eventId"] for entry in records.attempt_log(email_delivery(context, key))]
    rows = [row for event in events for row in context.site.runtime.log.for_event(event) if row["recipientKey"] != "NONE"]
    assert len(rows) == number, f"{len(rows)} readers in Caducus's log"
    found = Counter(row["status"] for row in rows)
    given_counts = {name: int(count) for name, count in (part.split() for part in statuses.split(", "))}
    assert dict(found) == given_counts, dict(found)


@then('the Delivery of "{key}" is "{state}"')
def delivery_state(context, key, state):
    assert email_delivery(context, key)["state"] == state, email_delivery(context, key)["state"]


@then("the Delivery's row holds no address and no words of the message")
def row_is_clean(context):
    for row in context.backend.rows("Delivery"):
        text = json.dumps(row)
        assert "@" not in text and "example.test" not in text.replace("alpha.example.test/", ""), text
        assert "Slow water rises" not in text, "the words are in S3, never on the row"


@then('the Delivery of "{key}" was written for its counts once')
def written_once(context, key):
    row_id = email_delivery(context, key)["id"]
    noted = [line for line in records.json_list(context.deliveries.get(row_id)["history"]) if line["note"].startswith("counts from Caducus")]
    assert len(noted) == 1, noted


@then('"{address}" has been mailed {number:d} message in all')
@then('"{address}" has been mailed {number:d} messages in all')
def mailed(context, address, number):
    found = [call for call in context.site.mailer.calls if call["to"] == address and "Confirm" not in call["subject"]]
    assert len(found) == number, f"{address} was mailed {len(found)}"


@then('"{address}" is suppressed because of a complaint')
def suppressed_complaint(context, address):
    audience = context.site.runtime.audience
    assert audience.suppression(audience._keys.recipient(address)) == "complaint"


@then("Today lists {number:d} email send")
@then("Today lists {number:d} email sends")
def lists_sends(context, number):
    assert len(context.today["sends"]) == number, context.today["sends"]


@then('the send is for the lists "{lists}" with {items:d} item and the counts "{text}"')
def send_is(context, lists, items, text):
    (send,) = context.today["sends"]
    assert send["lists"] == [name.strip() for name in lists.split(",")] and send["items"] == items and send["countsText"] == text, send


@then('the send says "{state}" and "{cost}"')
def send_says(context, state, cost):
    (send,) = context.today["sends"]
    assert send["stateShown"] == state, send["stateShown"]
    assert today.send_text(send).endswith(cost), today.send_text(send)


@then('Today prints the line "{line}"')
def prints_line(context, line):
    assert f"  {line}" in today.render(context.today), today.render(context.today)


@then("Today made only index reads of the announcement records")
def only_indexes(context):
    reads = {index for index, _key in context.backend.reads}
    assert reads == {"announcementDecisionsByState", "deliveriesByAnnouncement", "deliveriesByDue", "reviewRequestsByState", "semanticRelationsBySubjectState"}   # deliveriesByDue and reviewRequestsByState (the open partition): the overdue check, reads
    assert not context.backend.gets, context.backend.gets
