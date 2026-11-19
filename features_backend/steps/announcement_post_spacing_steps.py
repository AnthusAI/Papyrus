"""Post spacing on one channel account (features_backend/announcement-post-spacing.feature, PPY-97c0f2).

The catalog, the Stories, the decisions and the fake channel are the ones of the records and attempt specs. A Delivery is named by the decision that made it and its
account, because spacing is about two Deliveries on one account.
"""
from __future__ import annotations

import sys
from pathlib import Path

from behave import step, then

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.announcements import records  # noqa: E402
from papyrus_content.announcements.attempts import AccountWorker  # noqa: E402
from papyrus_content.announcements.records import attempt_log  # noqa: E402

from delivery_attempts_steps import attempt, channel_of  # noqa: E402,F401  (the same parsers and fake channel as the attempt specs)


def row_for(context, key, channel, account):
    announcement = records.announcement_id(key)
    rows = [row for row in context.backend.rows("Delivery") if row["announcementId"] == announcement and row["channel"] == channel and row["accountId"] == account]
    assert rows, f"no Delivery of {key} for {channel} {account}"
    return dict(context.deliveries.get(rows[0]["id"]))


@step('one worker serves the channel "{channel:Q}" account "{account:Q}" with post spacing of {minutes:d} minutes')
def worker_with_spacing(context, channel, account, minutes):
    transport = channel_of(context)
    context.workers[(channel, account)] = AccountWorker(context.deliveries, transport, channel, account, spacing_minutes=minutes)
    context.worker = context.workers[(channel, account)]


@step('the worker sends the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}"')
def worker_sends_decision(context, key, channel, account):
    attempt(context, lambda: context.worker.send(row_for(context, key, channel, account)["id"], by="worker", now=context.now))


@then('the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}" is "{state:Q}"')
def decision_delivery_is(context, key, channel, account, state):
    assert row_for(context, key, channel, account)["state"] == state


@then('the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}" has {count:d} attempt')
@then('the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}" has {count:d} attempts')
def decision_delivery_attempts(context, key, channel, account, count):
    assert len(attempt_log(row_for(context, key, channel, account))) == count


@then('the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}" is waiting for "{waiting:Q}" until "{until:Q}"')
def decision_delivery_waits(context, key, channel, account, waiting, until):
    row = row_for(context, key, channel, account)
    assert (row.get("waitingFor"), row.get("nextAttemptAt"), row.get("dueAt")) == (waiting, until, until), row


@then('the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}" waits for nothing')
def decision_delivery_free(context, key, channel, account):
    row = row_for(context, key, channel, account)
    assert not row.get("waitingFor") and not row.get("nextAttemptAt"), row


@step('an attempt is opened for the Delivery of "{key:Q}" for "{channel:Q}" "{account:Q}" and the worker dies before the call')
def open_for_decision_and_die(context, key, channel, account):
    from papyrus_content.announcements.attempts import Attempts

    attempt(context, lambda: Attempts(context.deliveries).open(row_for(context, key, channel, account)["id"], by="worker", now=context.now))
    assert context.error is None, context.error
