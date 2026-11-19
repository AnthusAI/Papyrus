"""What a person changed in a Delivery and how far it reaches (features_backend/delivery-edit-capture.feature, PPY-627bbc).

The catalog, the Deliveries and the one door are built by announcement_records_steps.py and delivery_editing_steps.py; this file only records an edit and reads what was recorded.
No network, no AWS.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import step, then

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from announcement_records_steps import attempt  # noqa: E402
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
