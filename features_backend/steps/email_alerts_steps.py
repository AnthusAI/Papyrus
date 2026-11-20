"""An email alert is the email Delivery of a Story's Announcement (features_backend/announcements/email-alerts-on-the-new-records.feature).

The announce agent's decision (``list_cadence.announce.announce_story``) runs over the real Announcement and Delivery records on their in-memory backend with the real alert
drafter; Caducus runs in memory with its mailer replaced by a recorder (``notifications_test.Site``), reached through the email channel. The kept alert rows are served by a
tiny stand-in for the newsletter table. Nothing is sent and nothing touches AWS; every address is a placeholder."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT, Path(__file__).resolve().parent):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.announcements import alert_conversion, records  # noqa: E402
from papyrus_content.announcements.attempts import AccountWorker  # noqa: E402
from papyrus_content.announcements.email_channel import CaducusEmail  # noqa: E402
from papyrus_content.announcements.email_delivery import send_due_email  # noqa: E402
from papyrus_content.announcements.link_reads import StoryRef  # noqa: E402
from papyrus_content.list_cadence import announce  # noqa: E402
from papyrus_content.list_cadence.alert_text import alert_drafter, alert_facts  # noqa: E402
from papyrus_content.newsletter.store import _ser  # noqa: E402

ACCOUNT, BY, ORIGIN = "alpha-send", "announce", "https://alpha.example.test"
TITLES = {"slow-water": "Slow water rises", "old-news": "An older story"}


def _story(lineage, section):
    return SimpleNamespace(title=TITLES.get(lineage, lineage), dek="A river is slower than it was.", body="The river keeps its pace.\n", path=f"/{section}/{lineage}.html")


def email_delivery(context, key):
    announcement = records.announcement_id(key)
    (row,) = [row for row in context.backend.rows("Delivery") if row["announcementId"] == announcement and row["channel"] == "email"]
    return dict(row)


@given('the every-item lists "stories" and "security" are carried by the announce agent')
def lists(context):
    base = {"cadence": "each", "emptyPeriod": None}
    context.alert_lists = {"stories": {**base, "name": "New stories", "rule": {"minStars": 3}}, "security": {**base, "name": "Security", "rule": {"minStars": 3, "sections": ["security"]}}}
    context.alert_section = {}
    context.channel_ready = False


@when('the announce agent decides for the Story "{lineage}" in the "{section}" section rated {stars:d} stars')
def decide(context, lineage, section, stars):
    context.alert_section[lineage] = section
    candidate = announce.Candidate(StoryRef(lineage, f"{lineage}-v3", 3), section, "article", [], stars)
    draft = alert_drafter(lambda name: _story(name, context.alert_section[name]), lambda: ORIGIN)
    context.alert_result = announce.announce_story(context.announcements, context.alert_lists, candidate, draft=draft, policy_rung=lambda _list: "publish_auto",
                                                   account_id=ACCOUNT, by=BY, now=context.now)


@then('the announce agent\'s last decision was "{reason}"')
def last_decision(context, reason):
    assert context.alert_result.reason == reason, context.alert_result.reason


def _alert_worker(context):
    """The worker for the email account, whose channel reads an alert's title and link back from its words."""
    if getattr(context, "email_worker", None) is None:
        site = context.site
        context.email_channel = CaducusEmail(site.runtime.router, site.runtime.log, site.settings.site_id, alert_facts, clock=site.clock)
        context.email_worker = AccountWorker(context.deliveries, context.email_channel, "email", ACCOUNT)
    return context.email_worker


@when('the worker sends the alert of "{key}" and Caducus works through its queue')
def send(context, key):
    delivery = email_delivery(context, key)
    context.announcements.release(context.announcements.by_dedupe_key(key), context.now)
    worker = _alert_worker(context)
    worker.send(delivery["id"], by="worker", now=context.now)
    context.site.play_queue()
    worker.settle(delivery["id"], by="worker", now=context.now)


@when('the deliver step runs for a site without an email channel')
def deliver_without_channel(context):
    context.delivered = send_due_email(context.deliveries, None, context.now)
    assert context.delivered == []


@when('the Announcement "{key}" is released')
def released(context, key):
    context.announcements.release(context.announcements.by_dedupe_key(key), context.now)


@when("the deliver step runs with Caducus's email channel and Caducus works through its queue")
def deliver_with_channel(context):
    worker = _alert_worker(context)
    context.delivered = send_due_email(context.deliveries, worker.transport, context.now)
    assert len(context.delivered) == 1, context.delivered
    context.site.play_queue()
    worker.settle(context.delivered[0]["id"], by="worker", now=context.now)


@then('the email Delivery of "{key}" is for the lists "{names}"')
def audience(context, key, names):
    assert sorted(email_delivery(context, key)["audience"]) == sorted(names.split(", ")), email_delivery(context, key)["audience"]


def _words(context, key):
    row = email_delivery(context, key)
    return context.deliveries.get(row["id"]) and context.files.get(row["id"], "v1")


@then('the words of the email Delivery of "{key}" begin "{text}"')
def words_begin(context, key, text):
    assert (_words(context, key) or "").startswith(text), _words(context, key)


@then('the words of the email Delivery of "{key}" say "{text}"')
def words_say(context, key, text):
    assert text in (_words(context, key) or ""), _words(context, key)


@then('the first attempt of the email Delivery of "{key}" is the Caducus event "{kind}" for the Delivery')
def first_attempt(context, key, kind):
    row = email_delivery(context, key)
    (entry, *_) = records.attempt_log(row)
    assert entry["eventId"] == f"delivery:{row['id']}:a1", entry
    rows = context.site.runtime.log.for_event(entry["eventId"])
    assert rows and {item["kind"] for item in rows} == {kind}, rows


@then('"{address}" received {number:d} message')
def received(context, address, number):
    assert len([call for call in context.site.mailer.calls if call["to"] == address]) == number, [call["to"] for call in context.site.mailer.calls]


@then('each message says "{title}" and links to "{url}"')
def messages_say(context, title, url):
    assert context.site.mailer.calls
    for call in context.site.mailer.calls:
        assert title in call["subject"] + call["text"] and url in call["html"], call["subject"]


@then('the Delivery of "{key}" has {number:d} attempt')
def attempts(context, key, number):
    assert len(records.attempt_log(email_delivery(context, key))) == number


@then('the worker sends nothing for "{key}"')
def sends_nothing(context, key):
    delivery = email_delivery(context, key)
    try:
        _alert_worker(context).send(delivery["id"], by="worker", now=context.now)
    except records.RecordError as refused:
        context.refusal = refused
        return
    raise AssertionError("a sent alert was handed over again")


@then("nobody is mailed")
def nobody(context):
    context.site.play_queue()
    assert context.site.mailer.calls == []


# --- the kept rows ----------------------------------------------------------------------------------------------------------------------------------


class KeptTable:
    """The newsletter table as far as the conversion reads it: ``query`` of one list's partition. Rows are serialized as DynamoDB returns them."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query(self, TableName, KeyConditionExpression, ExpressionAttributeValues, **_):
        pk = ExpressionAttributeValues[":p"]["S"]
        self.queries.append(pk)
        return {"Items": [_ser(row) for row in self.rows if row["pk"] == pk]}


@given("the newsletter table kept these alert rows")
def kept(context):
    context.kept = KeptTable([{"pk": f"ALERT#{row['list']}", "sk": f"ITEM#{row['story']}", "issueId": row["issue"], "at": "2026-11-10T09:00:00Z"} for row in context.table])
    context.issues = {row["issue"]: {"issueId": row["issue"], "status": row["issue status"], "sourceItemId": f"{row['story']}-v3", "lineageId": row["story"],
                                     "bodyMarkus": f"## [{TITLES.get(row['story'], row['story'])}](https://alpha.example.test/news/{row['story']}.html)\n\nRead it.\n\n[Read it on alpha.example.test](https://alpha.example.test/news/{row['story']}.html)\n"}
                      for row in context.table}
    context.items = {f"{row['story']}-v3": {"id": f"{row['story']}-v3", "versionNumber": 3} for row in context.table}


def _rows(context):
    return alert_conversion.read_rows(context.kept, "newsletter-table", ["stories", "security"])


@when("the kept alert rows are converted")
def convert(context):
    context.conversion = alert_conversion.convert(alert_conversion.plan(_rows(context)), context.announcements, read_issue=context.issues.get, read_item=context.items.get,
                                                  account_id=ACCOUNT, now=context.now)


@then('the conversion\'s second run made {made:d} Announcements and found {found:d} already converted')
def second_run(context, made, found):
    assert (context.conversion.announcements, context.conversion.unchanged) == (made, found), context.conversion


@then('the conversion plan names "{lineage}" for the lists "{names}"')
def plan_names(context, lineage, names):
    (item,) = [item for item in alert_conversion.plan(_rows(context)) if item.lineage == lineage]
    assert sorted(item.lists) == sorted(names.split(", ")), item
    assert sorted(context.kept.queries) == ["ALERT#security", "ALERT#stories"], "one query on each list's partition, never a scan"


@then("Announcements have once-only keys only for a published Story, a roundup and a correction")
def key_kinds(context):
    names = {name for name in dir(records) if name.endswith("_key") and callable(getattr(records, name))}
    assert {"story_published_key", "roundup_key", "correction_key"} <= names
    assert not [name for name in dir(records) if "alarm" in name.lower() or "operator" in name.lower()]


@then("the operator listener's stack does not name the Announcement or Delivery records")
def operator_stack(context):
    text = (REPO_ROOT / "infra" / "monitoring" / "papyrus-monitoring.yaml").read_text()
    assert "AnnouncementDecision" not in text and "Announcement" not in text and "DeliveryTable" not in text
