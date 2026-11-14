from unittest.mock import patch

from behave import given, then, when

from papyrus_content.email_submission_intake import EmailStore, backfill_fingerprints
from papyrus_content.email_reference_handoff import queue_email_reference
from papyrus_content.monitoring_view import TableViewStore
from procedures.newsroom.tests.email_submission_fixture import (
    RAW, apply_email_decisions, decide_email, email_fixture,
)
from procedures.newsroom.tests.test_email_duplicate_receipts import (
    FORWARDED, MONITOR, listed, receipts, receive, strip_fingerprints, three_held_copies, view_decide,
)
from procedures.newsroom.tests.test_email_quarantine import drain
from procedures.newsroom.tests.test_email_submission_intake import shared_fixture
from procedures.newsroom.tests.test_reference_intake import ENV, IDENTITY


@given('the same newsletter was received three times, once as a "Fwd:" forward')
def three_copies(context):
    context.f = three_held_copies(shared_fixture())


@given("an email with the same subject but a different link was received")
def same_subject(context):
    receive(context.f, 4, raw=RAW.replace(b"https://example.org/beta", b"https://example.org/gamma"), now=1010)


@given("an email with a different subject but the same links was received")
def same_links(context):
    receive(context.f, 5, raw=RAW.replace(b"Subject: Sources", b"Subject: Other"), now=1011)


@given("the oldest copy was rejected on its own before the group was decided")
def oldest_rejected(context):
    assert decide_email(context.f, "discard", receipt_key=receipts(context.f)[0]["sk"])["ok"]


@given("an editor accepted the newsletter and the receiver applied it")
def accepted_and_applied(context):
    view_decide(context.f, "release", reason="ok", receipt_id=receipts(context.f)[0]["sk"])
    apply_email_decisions(context.f)
    drain(context.f, 8)


@given("an editor rejected the newsletter and the receiver applied it")
def rejected_and_applied(context):
    view_decide(context.f, "discard", receipt_id=receipts(context.f)[0]["sk"])
    apply_email_decisions(context.f)


@given("the receipts have no fingerprint, as before this feature")
def no_fingerprints(context):
    context.before = {r["sk"]: {k: v for k, v in r.items() if k != "contentFingerprint"} for r in receipts(context.f)}
    strip_fingerprints(context.f)


@when("an editor opens the Monitoring email list")
def open_list(context):
    context.rows = listed(context.f)


@when("an editor accepts the newsletter once with a reason")
def accept_once(context):
    context.result = view_decide(context.f, "release", reason="Known newsletter", receipt_id=receipts(context.f)[1]["sk"])


@when("the receiver applies the recorded decisions")
def apply_decisions(context):
    apply_email_decisions(context.f)
    drain(context.f, 8)


@when("a fourth copy of the newsletter arrives")
def fourth_copy(context):
    assert receive(context.f, 6, now=1100)["status"] == "pending_review"
    apply_email_decisions(context.f, now=1700)
    drain(context.f, 8)


@when("a fourth copy of the newsletter arrives that passes authentication")
def fourth_copy_passing(context):
    receive(context.f, 6, fail_auth=False, now=1100)
    apply_email_decisions(context.f, now=1700)


@when("the same article link is imported from each copy")
def import_each(context):
    store = TableViewStore(context.f.table, MONITOR)
    endpoint = context.f.router["publications"][0]["appsyncEndpoint"]
    for row in receipts(context.f):
        request = {"receiptId": row["sk"], "candidateIndex": 0, "source_uri": "https://example.org/alpha",
                   "referenceId": "reference-alpha"}
        with patch.dict("os.environ", ENV):
            queue_email_reference(store, request, IDENTITY, endpoint=endpoint)


@when("the receiver runs the fingerprint backfill task")
def run_backfill(context):
    backfill_fingerprints(EmailStore(context.f.table), monitor_id=MONITOR, now=1500)


@then("the list shows one item that was received {count:d} times")
def one_item(context, count):
    assert len(context.rows) == 1 and context.rows[0]["group"]["count"] == count


@then("expanding it shows all {count:d} copies with their dates")
def copies_with_dates(context, count):
    copies = context.rows[0]["group"]["copies"]
    assert len(copies) == count and all(copy["observedAt"] for copy in copies)


@then("the list shows {count:d} items")
def list_items(context, count):
    assert len(context.rows) == count


@then("every copy records the same actor, time and reason, referencing the group decision")
def copies_reference_group(context):
    group = context.f.table.by_prefix("EMAILGROUP#")[0]
    actions = context.f.table.by_prefix("EMAILACTION#")
    assert len(actions) == 3
    for action in actions:
        assert (action["actor"], action["requestedAt"], action["reason"]) == (
            group["actor"], group["requestedAt"], "Known newsletter")
        assert action["groupFingerprint"] == group["fingerprint"]


@then("every copy is released and queued")
def all_queued(context):
    assert {r["status"] for r in receipts(context.f)} == {"queued"}


@then("a second, opposite decision from any copy is refused")
def opposite_refused(context):
    for row in receipts(context.f):
        assert view_decide(context.f, "discard", receipt_id=row["sk"])["error"] in {"already_decided", "not_quarantined"}


@then("the oldest copy stays rejected and the other copies are released")
def oldest_stays(context):
    statuses = [r["status"] for r in receipts(context.f)]
    assert statuses[0] == "discarded" and statuses[1:] == ["queued", "queued"]


@then("the fourth copy takes the accept without any new question")
def inherits_accept(context):
    assert len(context.f.table.by_prefix("EMAILGROUP#")) == 1
    late = receipts(context.f)[-1]
    action = next(a for a in context.f.table.by_prefix("EMAILACTION#") if a["receiptId"] == late["sk"])
    assert action["decision"] == "release" and action["groupFingerprint"] == late["contentFingerprint"]


@then("its links are queued")
def late_queued(context):
    assert receipts(context.f)[-1]["status"] == "queued"
    assert len(context.f.table.by_prefix("DISC#")) == 8


@then("the fourth copy is closed and nothing is routed")
def late_closed(context):
    assert {r["status"] for r in receipts(context.f)} == {"discarded"}
    assert context.f.table.by_prefix("DISC#") == []


@then("only one Reference request exists for that canonical URL")
def one_reference(context):
    assert len([r for r in context.f.table.by_prefix("DISC#") if r.get("editorSelectedReference")]) == 1


@then("the three receipts are grouped and no other receipt field changed")
def regrouped(context):
    after = {r["sk"]: {k: v for k, v in r.items() if k != "contentFingerprint"} for r in receipts(context.f)}
    assert after == context.before
    rows = listed(context.f)
    assert len(rows) == 1 and rows[0]["group"]["count"] == 3
