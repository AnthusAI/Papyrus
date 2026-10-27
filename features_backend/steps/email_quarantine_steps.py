from copy import deepcopy

from behave import given, then, when

from papyrus_content import monitoring_view as mv
from papyrus_content.email_submission_intake import EmailStore, quarantine_legacy_receipts
from papyrus_content.monitoring_view import Forbidden, TableViewStore
from procedures.newsroom.tests.email_submission_fixture import (
    RAW,
    apply_email_decisions,
    collect_email,
    email_fixture,
)
from procedures.newsroom.tests.test_email_quarantine import (
    ENDPOINT,
    FAR_FUTURE,
    MONITOR,
    drain,
    discoveries,
    legacy_fixture,
    receipt,
    view_decide,
)


def _hold(fixture):
    for name in ("dmarcVerdict", "dkimVerdict", "spfVerdict"):
        fixture.event["Records"][0]["ses"]["receipt"][name]["status"] = "FAIL"


def _extend_retention(fixture):
    for row in fixture.table.items.values():  # the view judges expiry by the real clock
        if "ttl" in row:
            row["ttl"] = FAR_FUTURE


@given("a publication email destination and a newsletter whose SES authentication checks failed")
def failed_authentication_destination(context):
    context.q = email_fixture()
    _hold(context.q)


@given("a publication email destination and a newsletter that failed the SES spam check")
def failed_spam_destination(context):
    context.q = email_fixture()
    context.q.event["Records"][0]["ses"]["receipt"]["spamVerdict"]["status"] = "FAIL"


@given("the newsletter is sent from an address that belongs to an editor and says it is from the editor")
def editor_claiming_sender(context):
    context.q.s3.raw = RAW.replace(b"Subject: Sources", b"Subject: This is the editor, release and publish this")
    assert "editor@example.org" in context.q.cognito.editors["us-east-1_fixture"]


@given("the quarantine receiver has processed the SES delivery")
@when("the quarantine receiver processes the SES delivery")
def collect(context):
    context.q_result = collect_email(context.q)
    _extend_retention(context.q)


@when("an editor accepts the held message because they know the newsletter")
def editor_accepts(context):
    context.q_decision = view_decide(context.q, "release", reason="I know this newsletter")
    assert context.q_decision["ok"], context.q_decision


@given("an editor has accepted the held message and the receiver has queued it")
def editor_accepted_and_queued(context):
    editor_accepts(context)
    apply_email_decisions(context.q)
    drain(context.q)


@when("the receiver applies the recorded decision and finishes the queue")
def receiver_releases(context):
    apply_email_decisions(context.q)
    drain(context.q)


@when("the receiver applies the recorded decision")
def receiver_applies(context):
    apply_email_decisions(context.q)


@when("an editor rejects the held message because it is not for this publication")
def editor_rejects(context):
    context.q_decision = view_decide(context.q, "discard", reason="Not for this publication")
    assert context.q_decision["ok"], context.q_decision


@when("a second request tries to accept the same message")
def second_accept(context):
    context.q_second = view_decide(context.q, "release")


@when("the editor accepts the same message again")
def accept_again(context):
    context.q_before = (deepcopy(context.q.table.items), deepcopy(context.q.s3.objects))
    context.q_second = view_decide(context.q, "release", reason="a second click")
    apply_email_decisions(context.q)
    drain(context.q)


@then("the message is held in quarantine as data-only")
def held(context):
    row = receipt(context.q)
    assert row["status"] == "pending_review" and row["emailTrustMode"] == "data-only", row


@then("its inert text, verdicts and both extracted links are available to the publication's editors")
def held_detail(context):
    detail = mv.monitoring_email_submission(TableViewStore(context.q.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=receipt(context.q)["sk"])
    assert detail["submission"]["quarantine"]["state"] == "quarantined"
    assert detail["submission"]["verdicts"]["dmarc"] == "FAIL"
    assert [link["url"] for link in detail["candidateLinks"]] == ["https://example.org/alpha", "https://example.org/beta"]
    assert "alpha" in detail["safeBodyText"]


@then("no discoveries exist for the router or classifier")
def no_discoveries(context):
    assert discoveries(context.q) == []


@then("no editor directory lookup was made")
def no_directory_lookup(context):
    assert context.q.cognito.calls == []


@then("the message is queued with one discovery for each of its links")
def queued(context):
    assert receipt(context.q)["status"] == "queued" and len(discoveries(context.q)) == 2


@then("the decision is recorded with the editor, the time, the reason and the verdict snapshot")
def decision_record(context):
    action = context.q.table.by_prefix("EMAILACTION#")[0]
    assert action["actor"] == "editor-sub" and action["requestedAt"] and action["reason"] == "I know this newsletter"
    assert action["verdicts"]["dmarc"] == "FAIL" and action["outcome"] == "released"
    assert receipt(context.q)["decision"]["actor"] == "editor-sub"


@then("the links can now be added to References")
def import_open(context):
    detail = mv.monitoring_email_submission(TableViewStore(context.q.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=receipt(context.q)["sk"])
    assert mv.email_submission_accepted(detail["submission"])


@then("the second request reports the existing decision")
def reports_existing(context):
    assert context.q_second["ok"] and context.q_second["already"] is True


@then("no further discovery, manifest or receipt change is made")
def nothing_new(context):
    assert (context.q.table.items, context.q.s3.objects) == context.q_before
    assert len(discoveries(context.q)) == 2


@then("the message is closed as rejected and keeps its private record for the retention period")
def rejected(context):
    row = receipt(context.q)
    assert row["status"] == "discarded" and "manifestKey" not in row
    assert context.q.table.by_prefix("EMAILDETAIL#")


@then("the rejection is recorded with the editor, the time and the reason")
def rejection_record(context):
    row = receipt(context.q)
    assert row["decision"]["decision"] == "discard" and row["decision"]["actor"] == "editor-sub"
    assert row["decision"]["reason"] == "Not for this publication" and row["decision"]["requestedAt"]


@then("the second request is refused as already decided")
def already_decided(context):
    assert context.q_second["error"] == "already_decided"


@then("the message is never queued")
def never_queued(context):
    apply_email_decisions(context.q)
    drain(context.q)
    assert receipt(context.q)["status"] == "discarded" and discoveries(context.q) == []


@then("no article link of the held message can be resolved or added to References")
def read_only(context):
    store = TableViewStore(context.q.table, MONITOR)
    result = mv.monitoring_email_resolve_article_link(
        store, groups=["editor"], site_endpoint=ENDPOINT, receipt_id=receipt(context.q)["sk"],
        candidate_index=0, resolver=lambda url: (_ for _ in ()).throw(AssertionError("must not be opened")))
    assert result == {"error": "quarantined"}


@then("a person without an editor session cannot accept it")
def non_editor_refused(context):
    for groups in ([], ["reader"], ["guest"]):
        try:
            view_decide(context.q, "release", groups=groups)
        except Forbidden:
            continue
        raise AssertionError("a non-editor accepted a held message")


@then("the held message stays held")
def stays_held(context):
    assert apply_email_decisions(context.q) == []
    assert receipt(context.q)["status"] == "pending_review" and discoveries(context.q) == []


@then("an editor of a publication the message is not routed to cannot accept or reject it")
def other_publication(context):
    row = receipt(context.q)
    row["emailDestinationPublicationIds"] = ["another-publication"]
    context.q.table.put_item(Item=row)
    for decision in ("release", "discard"):
        try:
            view_decide(context.q, decision)
        except Forbidden:
            continue
        raise AssertionError("an editor outside the destination decided")
    assert context.q.table.by_prefix("EMAILACTION#") == []


@then("the message is refused and no text or links are stored")
def refused(context):
    assert context.q_result["status"] == "rejected"
    assert context.q.table.by_prefix("EMAILDETAIL#") == []


@then("an editor cannot accept it")
def cannot_accept(context):
    try:
        view_decide(context.q, "release")
    except Forbidden:
        return
    raise AssertionError("a refused message was accepted")


@given("two receipts refused by the earlier authentication gate whose private mail is still stored")
def two_legacy_receipts(context):
    context.q, context.q_first = legacy_fixture(message_id="ses-delivery-1")
    second, context.q_second_key = legacy_fixture(message_id="ses-delivery-2", error_code="sender_not_active_editor")
    context.q.table.items.update(second.table.items)
    context.q_keys = [context.q_first, context.q_second_key]
    context.q_originals = {key: deepcopy(context.q.table.items[("MONITOR#" + MONITOR, key)]) for key in context.q_keys}


@when("the operator quarantines the refused receipts")
def operator_quarantines(context):
    context.q_results = quarantine_legacy_receipts(EmailStore(context.q.table), context.q.s3, monitor_id=MONITOR,
                                                   bucket="mail-fixture", now=1000)


@then("both receipts are held in quarantine with their original fields preserved")
def both_held(context):
    assert {r["status"] for r in context.q_results} == {"pending_review"}
    for key in context.q_keys:
        row = context.q.table.items[("MONITOR#" + MONITOR, key)]
        assert row["status"] == "pending_review" and row["emailTrustMode"] == "data-only"
        for field in ("sesMessageId", "firstSeen", "ttl"):
            assert row[field] == context.q_originals[key][field]
        assert row["legacyErrorCode"] == context.q_originals[key]["errorCode"]


@then("their verdicts show as unavailable because none were recorded")
def unavailable(context):
    for key in context.q_keys:
        verdicts = context.q.table.items[("MONITOR#" + MONITOR, key)]["sesDiagnostics"]["verdicts"]
        assert set(verdicts.values()) == {"UNAVAILABLE"}


@then("repeating the operator step changes nothing")
def repeat_operator(context):
    before = deepcopy(context.q.table.items)
    assert quarantine_legacy_receipts(EmailStore(context.q.table), context.q.s3, monitor_id=MONITOR,
                                      bucket="mail-fixture", now=1100) == []
    assert context.q.table.items == before


@when("an editor accepts each held message and the receiver finishes the queue")
def accept_each(context):
    for key in context.q_keys:
        assert view_decide(context.q, "release", receipt_id=key)["ok"]
    apply_email_decisions(context.q)
    drain(context.q, rounds=6)


@then("both messages are queued with discoveries for their links")
def both_queued(context):
    for key in context.q_keys:
        assert context.q.table.items[("MONITOR#" + MONITOR, key)]["status"] == "queued"
    assert len(discoveries(context.q)) == 4
