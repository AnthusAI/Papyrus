"""Quarantine, Accept (release) and Reject (discard) for held email submissions."""
from copy import deepcopy
from unittest.mock import patch

import pytest

from papyrus_content import monitoring_view as mv
from papyrus_content.email_quarantine import clean_reason, quarantine_state
from papyrus_content.email_submission_intake import (
    ConfigurationError,
    EmailStore,
    _resume_pending,
    apply_pending_decisions,
    handler,
    quarantine_legacy_receipts,
)
from papyrus_content.monitoring_view import Forbidden, TableViewStore
from papyrus_content.email_reference_handoff import queue_email_reference
from papyrus_content.reference_intake_validation import IntakeError
from procedures.newsroom.tests.email_submission_fixture import (
    RAW,
    accept_held_email,
    apply_email_decisions,
    collect_email,
    decide_email,
    email_fixture,
)

MONITOR = "email-publication"
FAR_FUTURE = 4_000_000_000
ENDPOINT = "https://fixture.appsync-api.us-east-1.amazonaws.com/graphql"
ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_fixture"


@pytest.fixture(autouse=True)
def link_exploration_stays_off():
    """The deployed handler installs link exploration globally; keep that out of other tests."""
    yield
    from papyrus_content import email_submission_intake
    email_submission_intake.link_explorer = None


def held_fixture():
    fixture = email_fixture()
    for name in ("dmarcVerdict", "dkimVerdict", "spfVerdict"):
        fixture.event["Records"][0]["ses"]["receipt"][name]["status"] = "FAIL"
    assert collect_email(fixture)["status"] == "pending_review"
    for row in fixture.table.items.values():  # the view judges expiry by the real clock
        if "ttl" in row:
            row["ttl"] = FAR_FUTURE
    return fixture


def receipt(fixture):
    return fixture.table.by_prefix("EMAIL#")[0]


def identity(**claims):
    base = {"sub": "editor-sub", "iss": ISSUER, "cognito:groups": ["editor"], **claims}
    return {"sub": "editor-sub", "issuer": ISSUER, "claims": base}


def view_decide(fixture, decision, *, groups=("editor",), endpoint=ENDPOINT, who=None, reason=None, receipt_id=None):
    store = TableViewStore(fixture.table, MONITOR)
    arguments = {"receiptId": receipt_id or receipt(fixture)["sk"], "decision": decision}
    if reason is not None:
        arguments["reason"] = reason
    with patch.dict("os.environ", {"PAPYRUS_USER_POOL_ISSUER": ISSUER}):
        return mv.monitoring_decide_email_submission(store, arguments, who or identity(),
                                                     groups=list(groups), site_endpoint=endpoint)


def drain(fixture, rounds=5):
    for _ in range(rounds):
        _resume_pending(EmailStore(fixture.table), MONITOR, "mail-fixture", fixture.s3, fixture.cognito, now=1700, limit=1)


def discoveries(fixture):
    return fixture.table.by_prefix("DISC#")


# --- the reason, in any order ---------------------------------------------------------------------

def test_the_reason_can_be_added_after_the_decision_until_the_receiver_applies_it():
    fixture = held_fixture()
    assert view_decide(fixture, "discard")["ok"]
    key = receipt(fixture)["sk"]
    action = fixture.table.by_prefix("EMAILACTION#")[0]
    assert action["reason"] == ""
    again = view_decide(fixture, "discard", reason="  Not   for\nthis publication ")
    assert again["already"] is True and again["quarantine"]["decision"]["reason"] == "Not for this publication"
    action = fixture.table.by_prefix("EMAILACTION#")[0]
    assert (action["decision"], action["reason"], action["actor"]) == ("discard", "Not for this publication", "editor-sub")
    # A repeat without a reason (or with the same one) changes nothing.
    before = deepcopy(fixture.table.items)
    assert view_decide(fixture, "discard")["already"] is True and view_decide(fixture, "discard", reason="Not for this publication")["already"] is True
    assert fixture.table.items == before
    # The opposite decision is still refused, and does not touch the reason.
    assert view_decide(fixture, "release", reason="changed my mind")["error"] == "already_decided"
    assert fixture.table.by_prefix("EMAILACTION#")[0]["reason"] == "Not for this publication"
    # The reason can be cleared.
    assert view_decide(fixture, "discard", reason="")["quarantine"]["decision"]["reason"] == ""
    # Once the receiver has applied the decision, the receipt's own record stands.
    assert view_decide(fixture, "discard", reason="Final words")["quarantine"]["decision"]["reason"] == "Final words"
    apply_email_decisions(fixture)
    applied = view_decide(fixture, "discard", reason="Too late")
    assert applied["quarantine"]["decision"]["reason"] == "Final words"
    assert fixture.table.get_item(Key={"pk": "MONITOR#" + MONITOR, "sk": key})["Item"]["decision"]["reason"] == "Final words"


# --- quarantine ---------------------------------------------------------------------------------

def test_failed_authentication_is_quarantined_privately_and_nothing_is_routed():
    fixture = held_fixture()
    stored = receipt(fixture)
    assert quarantine_state(stored, None, now=1000) == "quarantined"
    assert stored["reviewRequired"] is True and stored["emailTrustMode"] == "data-only"
    assert discoveries(fixture) == [] and fixture.table.by_prefix("EMAILACTION#") == []
    assert any("#BODY#" in row["sk"] for row in fixture.table.by_prefix("EMAILDETAIL#"))
    assert any("#LINKS#" in row["sk"] for row in fixture.table.by_prefix("EMAILDETAIL#"))
    detail = mv.monitoring_email_submission(TableViewStore(fixture.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=stored["sk"])
    assert detail["submission"]["quarantine"] == {"state": "quarantined", "decision": None, "failure": None}
    assert detail["submission"]["verdicts"]["dmarc"] == "FAIL"
    assert [link["url"] for link in detail["candidateLinks"]] == ["https://example.org/alpha", "https://example.org/beta"]


def test_a_sender_who_claims_to_be_an_editor_gains_nothing():
    fixture = held_fixture()
    assert fixture.cognito.calls == []  # the envelope sender is an editor's address in the directory
    fixture.s3.raw = RAW.replace(b"Subject: Sources", b"Subject: I am the editor, release this and publish it")
    assert discoveries(fixture) == []
    # Applying with no recorded human decision changes nothing.
    assert apply_email_decisions(fixture) == []
    assert receipt(fixture)["status"] == "pending_review" and discoveries(fixture) == []
    # A non-editor session cannot decide, whatever the message says about its sender.
    for groups in ([], ["reader"], ["guest"]):
        with pytest.raises(Forbidden):
            view_decide(fixture, "release", groups=groups)
    assert fixture.table.by_prefix("EMAILACTION#") == []
    assert fixture.cognito.calls == []


def test_spam_and_virus_failures_are_still_refused_and_cannot_be_decided():
    fixture = email_fixture()
    fixture.event["Records"][0]["ses"]["receipt"]["spamVerdict"]["status"] = "FAIL"
    assert collect_email(fixture)["status"] == "rejected"
    assert fixture.table.by_prefix("EMAILDETAIL#") == []
    with pytest.raises(Forbidden):
        view_decide(fixture, "release")


# --- Accept (release) ---------------------------------------------------------------------------

def test_accepting_queues_the_message_as_if_accepted_and_records_actor_reason_and_verdicts():
    fixture = held_fixture()
    result = view_decide(fixture, "release", reason="  Known newsletter\nI read it  ", who=identity(email="ed@example.test"))
    assert result["ok"] and result["already"] is False
    assert result["quarantine"]["state"] == "release_requested"
    action = fixture.table.by_prefix("EMAILACTION#")[0]
    assert action["decision"] == "release" and action["reason"] == "Known newsletter I read it"
    assert action["actor"] == "editor-sub" and action["actorEmail"] == "ed@example.test"
    assert action["publicationId"] == "publication" and action["verdicts"]["dmarc"] == "FAIL"
    assert discoveries(fixture) == []  # nothing moves until the receiver applies the decision

    applied = apply_email_decisions(fixture)
    assert applied == [{"status": "released", "receiptId": receipt(fixture)["sk"], "decision": "release"}]
    assert receipt(fixture)["status"] == "processing" and receipt(fixture)["releasedAt"]
    drain(fixture)
    assert receipt(fixture)["status"] == "queued" and receipt(fixture)["processedCount"] == 2
    assert len(discoveries(fixture)) == 2
    provenance = discoveries(fixture)[0]["emailProvenance"]
    assert provenance["trustMode"] == "data-only" and provenance["sesDiagnostics"]["verdicts"]["dmarc"] == "FAIL"
    assert discoveries(fixture)[0]["emailDestinationPublicationIds"] == ["publication"]
    stored = receipt(fixture)
    assert stored["decision"]["actor"] == "editor-sub" and stored["decision"]["reason"] == "Known newsletter I read it"
    assert fixture.table.by_prefix("EMAILACTION#")[0]["outcome"] == "released"
    assert "gsi1pk" not in fixture.table.by_prefix("EMAILACTION#")[0]
    assert fixture.cognito.calls == []

    detail = mv.monitoring_email_submission(TableViewStore(fixture.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=stored["sk"])
    assert detail["submission"]["quarantine"]["state"] == "released"
    assert detail["submission"]["quarantine"]["decision"]["action"] == "accept"


def test_releasing_twice_does_nothing_new():
    fixture = held_fixture()
    assert view_decide(fixture, "release")["already"] is False
    apply_email_decisions(fixture)
    drain(fixture)
    before = (deepcopy(fixture.table.items), deepcopy(fixture.s3.objects))
    again = view_decide(fixture, "release", reason="a second click")
    assert again["ok"] and again["already"] is True and again["quarantine"]["state"] == "released"
    assert apply_email_decisions(fixture) == []
    drain(fixture)
    assert (fixture.table.items, fixture.s3.objects) == before
    assert len(discoveries(fixture)) == 2


def test_crash_after_the_receipt_is_queued_but_before_the_decision_is_marked_applied_converges():
    fixture = held_fixture()
    view_decide(fixture, "release")
    store = EmailStore(fixture.table)
    original = store.put
    calls = []

    def crash_on_action_row(monitor_id, record):
        if str(record.get("sk", "")).startswith("EMAILACTION#"):
            calls.append(record)
            raise RuntimeError("table unavailable")
        return original(monitor_id, record)

    store.put = crash_on_action_row
    assert apply_pending_decisions(store, fixture.s3, monitor_id=MONITOR, bucket="mail-fixture", now=1600) == [
        {"status": "retry", "receiptId": receipt(fixture)["sk"]}]
    assert receipt(fixture)["releasedAt"] and calls
    assert "gsi1pk" in fixture.table.by_prefix("EMAILACTION#")[0]  # still pending
    assert [r["status"] for r in apply_email_decisions(fixture)] == ["released"]
    drain(fixture)
    assert len(discoveries(fixture)) == 2 and receipt(fixture)["status"] == "queued"


def test_a_message_with_no_eligible_links_is_queued_immediately():
    fixture = email_fixture()
    fixture.s3.raw = RAW.split(b"\r\n\r\n")[0] + b"\r\n\r\nNothing to link here\r\n"
    fixture.event["Records"][0]["ses"]["receipt"]["dmarcVerdict"]["status"] = "FAIL"
    assert collect_email(fixture)["status"] == "pending_review"
    accept_held_email(fixture)
    assert receipt(fixture)["status"] == "queued" and discoveries(fixture) == []


def test_redelivery_of_the_same_ses_message_never_reverts_a_decision():
    fixture = held_fixture()
    accept_held_email(fixture)
    assert collect_email(fixture)["status"] == "duplicate"
    assert receipt(fixture)["releasedAt"] and receipt(fixture)["status"] != "pending_review"
    other = held_fixture()
    decide_email(other, "discard")
    apply_email_decisions(other)
    assert collect_email(other)["status"] == "duplicate"
    assert receipt(other)["status"] == "discarded"


def test_release_waits_while_the_destination_is_disabled_and_is_never_dropped():
    fixture = held_fixture()
    view_decide(fixture, "release")
    fixture.config["enabled"] = False
    fixture.table.put_item(Item=fixture.config)
    assert apply_email_decisions(fixture)[0]["status"] == "retry"
    assert "gsi1pk" in fixture.table.by_prefix("EMAILACTION#")[0] and receipt(fixture)["status"] == "pending_review"
    fixture.config["enabled"] = True
    fixture.table.put_item(Item=fixture.config)
    assert apply_email_decisions(fixture)[0]["status"] == "released"


def test_changed_destination_binding_fails_closed_with_a_visible_code():
    fixture = held_fixture()
    view_decide(fixture, "release")
    fixture.config["publicationIds"] = ["publication"]
    fixture.config["addresses"] = ["submissions@publication.example", "other@publication.example"]
    fixture.table.put_item(Item=fixture.config)
    assert apply_email_decisions(fixture)[0]["status"] == "email_retry_binding_changed"
    assert receipt(fixture)["status"] == "pending_review" and discoveries(fixture) == []
    detail = mv.monitoring_email_submission(TableViewStore(fixture.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=receipt(fixture)["sk"])
    assert detail["submission"]["quarantine"]["state"] == "decision_failed"
    assert detail["submission"]["quarantine"]["failure"] == "email_retry_binding_changed"


def test_expired_quarantine_cannot_be_decided():
    fixture = held_fixture()
    row = receipt(fixture)
    row["ttl"] = 1
    fixture.table.put_item(Item=row)
    assert view_decide(fixture, "release") == {"error": "expired"}
    assert fixture.table.by_prefix("EMAILACTION#") == []


# --- Reject (discard) ---------------------------------------------------------------------------

def test_rejecting_discards_the_message_and_keeps_the_record_of_who_and_why():
    fixture = held_fixture()
    result = view_decide(fixture, "discard", reason="Not for this publication")
    assert result["ok"] and result["quarantine"]["state"] == "discard_requested"
    assert [r["status"] for r in apply_email_decisions(fixture)] == ["discarded"]
    stored = receipt(fixture)
    assert stored["status"] == "discarded" and stored["decision"]["decision"] == "discard"
    assert stored["decision"]["reason"] == "Not for this publication" and "releasedAt" not in stored
    assert discoveries(fixture) == [] and "manifestKey" not in stored
    assert fixture.table.by_prefix("EMAILDETAIL#")  # kept for its 30 days, never lost
    assert view_decide(fixture, "discard")["already"] is True
    assert apply_email_decisions(fixture) == []
    detail = mv.monitoring_email_submission(TableViewStore(fixture.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=stored["sk"])
    assert detail["submission"]["quarantine"]["state"] == "discarded"
    assert detail["submission"]["quarantine"]["decision"]["action"] == "reject"


def test_the_first_decision_wins():
    fixture = held_fixture()
    view_decide(fixture, "discard")
    result = view_decide(fixture, "release")
    assert result["error"] == "already_decided" and result["quarantine"]["state"] == "discard_requested"
    apply_email_decisions(fixture)
    assert receipt(fixture)["status"] == "discarded" and discoveries(fixture) == []
    other = held_fixture()
    view_decide(other, "release")
    assert view_decide(other, "discard")["error"] == "already_decided"


def test_concurrent_requests_record_exactly_one_decision():
    fixture = held_fixture()
    store = TableViewStore(fixture.table, MONITOR)
    real_put = store.put_email_decision
    results = []

    def racing(item):
        # Another click lands between this request's read and its write of the group decision.
        if not item["sk"].startswith("EMAILGROUP#"):
            return real_put(item)
        results.append(real_put({**item, "decision": "release", "actor": "other-click"}))
        return real_put(item)

    with patch.object(TableViewStore, "put_email_decision", lambda self, item: racing(item)), \
            patch.dict("os.environ", {"PAPYRUS_USER_POOL_ISSUER": ISSUER}):
        outcome = mv.monitoring_decide_email_submission(
            store, {"receiptId": receipt(fixture)["sk"], "decision": "release"}, identity(),
            groups=["editor"], site_endpoint=ENDPOINT)
    assert results == [True] and outcome["ok"] and outcome["already"] is True
    assert len(fixture.table.by_prefix("EMAILACTION#")) == 1
    assert fixture.table.by_prefix("EMAILACTION#")[0]["actor"] == "other-click"


# --- authorization ------------------------------------------------------------------------------

def test_only_a_validated_editor_of_a_routed_publication_may_decide():
    fixture = held_fixture()
    other = "https://other.appsync-api.us-east-1.amazonaws.com/graphql"
    with pytest.raises(Forbidden):
        view_decide(fixture, "release", endpoint=other)
    with pytest.raises(Forbidden):
        view_decide(fixture, "release", endpoint=None)
    wrong_issuer = identity()
    wrong_issuer["issuer"] = "https://cognito-idp.us-east-1.amazonaws.com/other-pool"
    with pytest.raises(Forbidden):
        view_decide(fixture, "release", who=wrong_issuer)
    no_groups = identity()
    no_groups["claims"]["cognito:groups"] = []
    with pytest.raises(Forbidden):
        view_decide(fixture, "release", who=no_groups)
    routed_elsewhere = receipt(fixture)
    routed_elsewhere["emailDestinationPublicationIds"] = ["another-publication"]
    fixture.table.put_item(Item=routed_elsewhere)
    with pytest.raises(Forbidden):
        view_decide(fixture, "release")
    assert fixture.table.by_prefix("EMAILACTION#") == []


@pytest.mark.parametrize("arguments", [
    {"decision": "release"}, {"receiptId": "EMAIL#nope", "decision": "release"},
    {"receiptId": "EMAIL#" + "a" * 64, "decision": "release", "extra": 1},
])
def test_malformed_requests_are_refused_before_any_read(arguments):
    store = TableViewStore(email_fixture().table, MONITOR)
    with patch.dict("os.environ", {"PAPYRUS_USER_POOL_ISSUER": ISSUER}):
        assert mv.monitoring_decide_email_submission(store, arguments, identity(), groups=["editor"],
                                                     site_endpoint=ENDPOINT) == {"error": "bad_request"}


def test_unknown_decisions_and_accepted_messages_are_refused():
    fixture = held_fixture()
    assert view_decide(fixture, "publish") == {"error": "bad_request"}
    assert view_decide(fixture, "release", reason=7) == {"error": "bad_request"}
    queued = email_fixture()
    assert collect_email(queued)["status"] == "queued"
    assert view_decide(queued, "release") == {"error": "not_quarantined"}


def test_reason_is_plain_bounded_text():
    assert clean_reason(None) == "" and clean_reason("a\x00b\tc\n d") == "a b c d"
    assert len(clean_reason("x" * 5000)) == 500


def test_the_appsync_resolver_dispatches_decisions_with_the_signed_in_editor():
    fixture = held_fixture()
    event = {"info": {"fieldName": "monitoringDecideEmailSubmission"}, "identity": {**identity(), "groups": ["editor"]},
             "arguments": {"receiptId": receipt(fixture)["sk"], "decision": "discard", "reason": "spam to me"}}
    env = {"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT, "PAPYRUS_USER_POOL_ISSUER": ISSUER, "PAPYRUS_EMAIL_MONITOR_ID": MONITOR}
    with patch.dict("os.environ", {"PAPYRUS_USER_POOL_ISSUER": ISSUER}):
        result = mv.handle(event, env=env, email_store_factory=lambda: TableViewStore(fixture.table, MONITOR),
                           store_factory=lambda monitor_id=MONITOR: TableViewStore(fixture.table, MONITOR))
        assert result["ok"] and fixture.table.by_prefix("EMAILACTION#")[0]["decision"] == "discard"
        event["identity"]["groups"] = ["reader"]
        assert mv.handle(event, env=env, email_store_factory=lambda: TableViewStore(fixture.table, MONITOR),
                         store_factory=lambda monitor_id=MONITOR: TableViewStore(fixture.table, MONITOR)) == {"error": "forbidden"}


# --- a held message is read-only until accepted -----------------------------------------------

def test_nothing_is_resolved_or_imported_from_a_held_discarded_or_expired_message():
    fixture = held_fixture()
    store = TableViewStore(fixture.table, MONITOR)
    row_id = receipt(fixture)["sk"]
    calls = []
    assert mv.monitoring_email_resolve_article_link(
        store, groups=["editor"], site_endpoint=ENDPOINT, receipt_id=row_id, candidate_index=0,
        resolver=lambda url: calls.append(url)) == {"error": "quarantined"}
    request = {"receiptId": row_id, "candidateIndex": 0, "source_uri": "https://example.org/alpha", "referenceId": "ref-1"}
    with patch.dict("os.environ", {"PAPYRUS_USER_POOL_ISSUER": ISSUER}), pytest.raises(IntakeError, match="Accept this held email"):
        queue_email_reference(store, request, identity(), endpoint=ENDPOINT)
    view_decide(fixture, "discard")
    apply_email_decisions(fixture)
    with patch.dict("os.environ", {"PAPYRUS_USER_POOL_ISSUER": ISSUER}), pytest.raises(IntakeError, match="Accept this held email"):
        queue_email_reference(store, request, identity(), endpoint=ENDPOINT)
    assert calls == []


# --- the two messages the earlier authentication gate refused ---------------------------------

def legacy_fixture(*, error_code="sender_authentication_failed", with_snapshot=False, message_id="ses-delivery-1"):
    """A receipt as the earlier gate left it: refused before the MIME was read."""
    fixture = email_fixture()
    from hashlib import sha256
    key = "EMAIL#" + sha256(message_id.encode()).hexdigest()
    row = {"pk": "MONITOR#" + MONITOR, "sk": key, "sesMessageId": message_id, "status": "rejected",
           "processingStage": "ses_safety_checks", "errorCode": error_code, "ttl": FAR_FUTURE,
           "firstSeen": 900, "updatedAt": "1970-01-01T00:15:00Z"}
    if with_snapshot:
        row["sesDiagnostics"] = {"provenance": "ses-invocation-receipt-untrusted-auth-signals",
                                 "verdicts": {"spam": "PASS", "virus": "PASS", "spf": "FAIL", "dkim": "NONE", "dmarc": "FAIL"},
                                 "warnings": ["spf_not_passed"], "blockedGateCodes": []}
    fixture.table.put_item(Item=row)
    return fixture, key


@pytest.mark.parametrize("error_code", ["sender_authentication_failed", "sender_not_active_editor"])
@pytest.mark.parametrize("with_snapshot", [False, True])
def test_a_receipt_refused_by_the_earlier_gate_can_be_quarantined_then_accepted(error_code, with_snapshot):
    fixture, key = legacy_fixture(error_code=error_code, with_snapshot=with_snapshot)
    before = deepcopy(receipt(fixture))
    results = quarantine_legacy_receipts(EmailStore(fixture.table), fixture.s3, monitor_id=MONITOR,
                                         bucket="mail-fixture", now=1000)
    assert results == [{"status": "pending_review", "receiptId": key, "linkCount": 2, "processedCount": 0}]
    held = receipt(fixture)
    assert held["status"] == "pending_review" and held["emailTrustMode"] == "data-only"
    assert held["legacyErrorCode"] == error_code and held["errorCode"] is None
    for field in ("sesMessageId", "firstSeen", "ttl"):  # data-preserving
        assert held[field] == before[field]
    verdicts = held["sesDiagnostics"]["verdicts"]
    assert verdicts == (before["sesDiagnostics"]["verdicts"] if with_snapshot
                        else {name: "UNAVAILABLE" for name in ("spam", "virus", "spf", "dkim", "dmarc")})
    assert "legacy_authentication_rejection" in held["warnings"]
    assert len(fixture.table.by_prefix("EMAILINDEX#")) == 1 and discoveries(fixture) == []
    detail = mv.monitoring_email_submission(TableViewStore(fixture.table, MONITOR), groups=["editor"],
                                            site_endpoint=ENDPOINT, receipt_id=key)
    assert len(detail["candidateLinks"]) == 2 and "alpha" in detail["safeBodyText"]
    assert detail["submission"]["quarantine"]["state"] == "quarantined"

    accept_held_email(fixture, receipt_key=key)
    drain(fixture)
    assert receipt(fixture)["status"] == "queued" and len(discoveries(fixture)) == 2

    # Running the migration again changes nothing.
    snapshot = deepcopy(fixture.table.items)
    again = quarantine_legacy_receipts(EmailStore(fixture.table), fixture.s3, monitor_id=MONITOR,
                                       bucket="mail-fixture", now=1100)
    assert again == []
    assert fixture.table.items == snapshot


def test_the_migration_finds_every_refused_receipt_and_leaves_other_receipts_alone():
    fixture, first = legacy_fixture()
    second_fixture, second = legacy_fixture(message_id="ses-delivery-2", error_code="sender_not_active_editor")
    fixture.table.items.update(second_fixture.table.items)
    other = {"pk": "MONITOR#" + MONITOR, "sk": "EMAIL#" + "e" * 64, "status": "rejected", "errorCode": "spam_verdict_not_passed",
             "ttl": FAR_FUTURE, "sesMessageId": "ses-spam"}
    fixture.table.put_item(Item=other)
    results = quarantine_legacy_receipts(EmailStore(fixture.table), fixture.s3, monitor_id=MONITOR,
                                         bucket="mail-fixture", now=1000)
    assert {r["receiptId"] for r in results} == {first, second}
    assert fixture.table.get_item(Key={"pk": other["pk"], "sk": other["sk"]})["Item"]["status"] == "rejected"


def test_the_migration_never_quarantines_known_spam_or_virus_unparseable_or_expired_mail():
    fixture, key = legacy_fixture(with_snapshot=True)
    row = receipt(fixture)
    row["sesDiagnostics"]["verdicts"]["virus"] = "FAIL"
    fixture.table.put_item(Item=row)
    def run():
        return quarantine_legacy_receipts(EmailStore(fixture.table), fixture.s3, monitor_id=MONITOR,
                                          bucket="mail-fixture", receipt_keys=[key], now=1000)[0]

    assert run() == {"status": "unchanged", "reason": "safety_verdict_not_passed", "receiptId": key}
    row["sesDiagnostics"]["verdicts"]["virus"] = "PASS"
    row["ttl"] = 10
    fixture.table.put_item(Item=row)
    assert run()["status"] == "expired"
    row["ttl"] = FAR_FUTURE
    fixture.table.put_item(Item=row)
    fixture.s3.raw = b"x" * (2 * 1024 * 1024)
    assert run() == {"status": "unchanged", "reason": "message_too_large", "receiptId": key}
    assert receipt(fixture)["status"] == "rejected" and fixture.table.by_prefix("EMAILDETAIL#") == []


def test_the_operator_task_quarantines_the_named_receipts_only():
    fixture, key = legacy_fixture()
    env = {"TABLE_NAME": "t", "EMAIL_MONITOR_ID": MONITOR, "EMAIL_RAW_BUCKET": "mail-fixture"}
    with patch.dict("os.environ", env), patch("boto3.resource") as resource, patch("boto3.client", return_value=fixture.s3):
        resource.return_value.Table.return_value = fixture.table
        with pytest.raises(ConfigurationError):
            handler({"task": "quarantine-legacy", "monitorId": "someone-else"}, None)
        result = handler({"task": "quarantine-legacy", "monitorId": MONITOR, "receiptIds": [key]}, None)
    assert result["receipts"][0]["status"] == "pending_review"


def test_the_resume_schedule_applies_decisions_before_draining_the_queue():
    fixture = held_fixture()
    view_decide(fixture, "release")
    env = {"TABLE_NAME": "t", "EMAIL_MONITOR_ID": MONITOR, "EMAIL_RAW_BUCKET": "mail-fixture"}
    with patch.dict("os.environ", env), patch("boto3.resource") as resource, patch("boto3.client", return_value=fixture.s3):
        resource.return_value.Table.return_value = fixture.table
        result = handler({"task": "resume", "monitorId": MONITOR}, None)
    assert result["decisions"][0]["status"] == "released"
    assert receipt(fixture)["status"] == "queued" and len(discoveries(fixture)) == 2
