"""The same email received several times is one submission with one decision."""
from unittest.mock import patch

import pytest

from papyrus_content import monitoring_view as mv
from papyrus_content.email_fingerprint import content_fingerprint, normalize_subject
from papyrus_content.email_submission_intake import EmailStore, backfill_fingerprints, process_ses_record
from papyrus_content.monitoring_view import TableViewStore
from papyrus_content.email_reference_handoff import queue_email_reference
from procedures.newsroom.tests.email_submission_fixture import RAW, apply_email_decisions, email_fixture
from procedures.newsroom.tests.test_email_quarantine import (
    ENDPOINT, FAR_FUTURE, ISSUER, MONITOR, drain, identity, view_decide,
)
from procedures.newsroom.tests.test_email_submission_intake import shared_fixture
from procedures.newsroom.tests.test_reference_intake import ENV, IDENTITY

FORWARDED = RAW.replace(b"Subject: Sources", b"Subject: Fwd:  Re: SOURCES ")
LINKS = [{"url": "https://example.org/alpha"}, {"url": "https://example.org/beta"}]


def receive(fixture, number, *, raw=RAW, fail_auth=True, now=1000):
    """Deliver one more SES message carrying `raw` (each delivery has its own message id)."""
    record = fixture.event["Records"][0]
    record["ses"]["mail"]["messageId"] = f"ses-delivery-{number}"
    record["ses"]["receipt"]["dmarcVerdict"]["status"] = "FAIL" if fail_auth else "PASS"
    fixture.s3.raw = raw
    result = process_ses_record(record, EmailStore(fixture.table), monitor_id=MONITOR, bucket="mail-fixture",
                                prefix="email-submissions/", s3=fixture.s3, cognito=fixture.cognito, now=now)
    for row in fixture.table.items.values():
        if "ttl" in row:
            row["ttl"] = FAR_FUTURE
    return result


def three_held_copies(fixture=None):
    fixture = fixture or email_fixture()
    for number, raw in ((1, RAW), (2, FORWARDED), (3, RAW)):
        assert receive(fixture, number, raw=raw, now=1000 + number)["status"] == "pending_review"
    return fixture


def listed(fixture):
    return mv.monitoring_list_page({MONITOR: TableViewStore(fixture.table, MONITOR)}, list_name="emailSubmissions",
                                   cursor=None, groups=["editor"], site_endpoint=ENDPOINT, scope="publication",
                                   now=2000)["rows"]


def receipts(fixture):
    return sorted(fixture.table.by_prefix("EMAIL#"), key=lambda row: row["observedAt"])


# --- fingerprint --------------------------------------------------------------------------------

def test_fingerprint_ignores_forward_prefixes_whitespace_and_link_order():
    base = content_fingerprint("The Internet Is Under Attack", LINKS)
    assert content_fingerprint("Fwd: RE:  the internet   is under attack ", list(reversed(LINKS)) + LINKS) == base
    assert normalize_subject("FW: Fwd: Re: Hello") == "hello"


def test_fingerprint_ignores_forward_header_blocks_when_there_are_no_links():
    plain = content_fingerprint("Note", [], "The report is due Friday.")
    forwarded = content_fingerprint("Fwd: Note", [], "---------- Forwarded message ---------\nFrom: A <a@x.test>\n"
                                    "Date: Mon\nSubject: Note\n\n> The report   is due Friday.")
    assert plain == forwarded
    assert plain != content_fingerprint("Note", [], "The report is due Monday.")


def test_different_subject_or_links_give_different_fingerprints():
    base = content_fingerprint("Sources", LINKS)
    assert content_fingerprint("Other sources", LINKS) != base
    assert content_fingerprint("Sources", LINKS[:1]) != base


def test_intake_stores_the_fingerprint_and_group_membership():
    fixture = three_held_copies()
    stored = receipts(fixture)
    assert len({row["contentFingerprint"] for row in stored}) == 1
    assert stored[0]["contentFingerprint"] == content_fingerprint("Sources", LINKS)
    assert len(fixture.table.by_prefix("EMAILFP#")) == 3


# --- the list -----------------------------------------------------------------------------------

def test_three_copies_are_one_list_item_received_three_times():
    fixture = three_held_copies()
    rows = listed(fixture)
    assert len(rows) == 1
    group = rows[0]["group"]
    assert group["count"] == 3
    assert [copy["observedAt"] for copy in group["copies"]] == sorted(
        (row["observedAt"] for row in receipts(fixture)), reverse=True)


def test_different_emails_are_never_grouped():
    fixture = three_held_copies()
    receive(fixture, 4, raw=RAW.replace(b"https://example.org/beta", b"https://example.org/gamma"), now=1010)
    receive(fixture, 5, raw=RAW.replace(b"Subject: Sources", b"Subject: Other"), now=1011)
    rows = listed(fixture)
    assert len(rows) == 3
    assert sorted(row.get("group", {}).get("count", 1) for row in rows) == [1, 1, 3]


# --- one decision for the group -----------------------------------------------------------------

def test_one_accept_covers_every_copy_and_each_copy_references_the_group_decision():
    fixture = three_held_copies()
    result = view_decide(fixture, "release", reason="Known newsletter", receipt_id=receipts(fixture)[0]["sk"],
                         who=identity(email="ed@example.test"))
    assert result["ok"] and result["decidedCopies"] == 3
    actions = fixture.table.by_prefix("EMAILACTION#")
    assert len(actions) == 3
    group = fixture.table.by_prefix("EMAILGROUP#")[0]
    for action in actions:
        assert action["decision"] == "release" and action["actor"] == "editor-sub"
        assert action["actorEmail"] == "ed@example.test" and action["reason"] == "Known newsletter"
        assert action["requestedAt"] == group["requestedAt"] and action["groupFingerprint"] == group["fingerprint"]
    assert len(apply_email_decisions(fixture)) == 3
    drain(fixture, 8)
    assert {row["status"] for row in receipts(fixture)} == {"queued"}
    assert all(row["decision"]["groupFingerprint"] == group["fingerprint"] for row in receipts(fixture))
    assert len(fixture.table.by_prefix("DISC#")) == 6  # two links in each of three copies


def test_one_reject_closes_every_copy():
    fixture = three_held_copies()
    assert view_decide(fixture, "discard", receipt_id=receipts(fixture)[2]["sk"])["ok"]
    apply_email_decisions(fixture)
    assert {row["status"] for row in receipts(fixture)} == {"discarded"}
    assert fixture.table.by_prefix("DISC#") == []


def test_a_second_opposite_decision_on_the_group_is_refused_from_any_copy():
    fixture = three_held_copies()
    view_decide(fixture, "discard", receipt_id=receipts(fixture)[0]["sk"])
    assert view_decide(fixture, "release", receipt_id=receipts(fixture)[1]["sk"])["error"] == "already_decided"
    again = view_decide(fixture, "discard", receipt_id=receipts(fixture)[1]["sk"])
    assert again["ok"] and again["already"] is True
    assert len(fixture.table.by_prefix("EMAILACTION#")) == 3


def test_a_copy_decided_earlier_keeps_its_own_decision():
    fixture = three_held_copies()
    first = receipts(fixture)[0]
    from procedures.newsroom.tests.email_submission_fixture import decide_email
    assert decide_email(fixture, "discard", receipt_key=first["sk"])["ok"]
    result = view_decide(fixture, "release", receipt_id=receipts(fixture)[1]["sk"])
    assert result["ok"] and result["decidedCopies"] == 2
    apply_email_decisions(fixture)
    statuses = {row["sk"]: row["status"] for row in receipts(fixture)}
    assert statuses[first["sk"]] == "discarded"
    assert sorted(statuses.values()) == ["discarded", "processing", "processing"]


# --- a copy that arrives after the group was decided --------------------------------------------

def test_a_late_copy_of_an_accepted_email_inherits_accept_and_queues_its_links():
    fixture = three_held_copies()
    view_decide(fixture, "release", reason="ok", receipt_id=receipts(fixture)[0]["sk"])
    apply_email_decisions(fixture)
    assert receive(fixture, 4, now=1100)["status"] == "pending_review"
    late = receipts(fixture)[-1]
    action = next(a for a in fixture.table.by_prefix("EMAILACTION#") if a["receiptId"] == late["sk"])
    assert action["receiptId"] == late["sk"] and action["decision"] == "release" and action["reason"] == "ok"
    assert action["groupFingerprint"] == late["contentFingerprint"]
    assert len(fixture.table.by_prefix("EMAILGROUP#")) == 1  # never asks again
    apply_email_decisions(fixture, now=1700)
    drain(fixture, 8)
    assert fixture.table.get_item(Key={"pk": late["pk"], "sk": late["sk"]})["Item"]["status"] == "queued"
    assert len(fixture.table.by_prefix("DISC#")) == 8


def test_a_late_copy_of_a_rejected_email_is_closed_even_when_authentication_passes():
    fixture = three_held_copies()
    view_decide(fixture, "discard", receipt_id=receipts(fixture)[0]["sk"])
    apply_email_decisions(fixture)
    assert receive(fixture, 4, fail_auth=False, now=1100)["status"] == "pending_review"
    apply_email_decisions(fixture, now=1700)
    assert {row["status"] for row in receipts(fixture)} == {"discarded"}
    assert fixture.table.by_prefix("DISC#") == []
    assert len(listed(fixture)[0]["group"]["copies"]) == 4


def test_a_late_copy_of_an_accepted_email_that_passes_authentication_queues_normally():
    fixture = three_held_copies()
    view_decide(fixture, "release", receipt_id=receipts(fixture)[0]["sk"])
    apply_email_decisions(fixture)
    assert receive(fixture, 4, fail_auth=False, now=1100)["status"] in {"queued", "processing"}


def test_a_different_email_after_a_group_decision_is_still_held_for_review():
    fixture = three_held_copies()
    view_decide(fixture, "release", receipt_id=receipts(fixture)[0]["sk"])
    other = RAW.replace(b"Subject: Sources", b"Subject: Something else")
    receive(fixture, 4, raw=other, now=1100)
    assert len(fixture.table.by_prefix("EMAILACTION#")) == 3  # the other email got no inherited decision
    assert receipts(fixture)[-1]["status"] == "pending_review"


# --- references stay idempotent -----------------------------------------------------------------

def test_importing_the_same_link_from_every_copy_creates_one_reference_request():
    fixture = three_held_copies(shared_fixture())
    view_decide(fixture, "release", receipt_id=receipts(fixture)[0]["sk"])
    apply_email_decisions(fixture)
    store = TableViewStore(fixture.table, MONITOR)
    for row in receipts(fixture):
        request = {"receiptId": row["sk"], "candidateIndex": 0, "source_uri": "https://example.org/alpha",
                   "referenceId": "reference-alpha"}
        with patch.dict("os.environ", ENV):
            queue_email_reference(store, request, IDENTITY, endpoint=fixture.router["publications"][0]["appsyncEndpoint"])
    imported = [row for row in fixture.table.by_prefix("DISC#") if row.get("editorSelectedReference")]
    assert len(imported) == 1


# --- backfill -----------------------------------------------------------------------------------

def strip_fingerprints(fixture):
    for key in [k for k in fixture.table.items if k[1].startswith("EMAILFP#")]:
        del fixture.table.items[key]
    for row in fixture.table.by_prefix("EMAIL#"):
        row.pop("contentFingerprint", None)
        fixture.table.put_item(Item=row)


def test_backfill_groups_existing_receipts_and_preserves_their_data():
    fixture = three_held_copies()
    before = {row["sk"]: {k: v for k, v in row.items() if k != "contentFingerprint"} for row in receipts(fixture)}
    strip_fingerprints(fixture)
    assert len(listed(fixture)) == 3
    result = backfill_fingerprints(EmailStore(fixture.table), monitor_id=MONITOR, now=1500)
    assert result["fingerprinted"] == 3
    after = {row["sk"]: {k: v for k, v in row.items() if k != "contentFingerprint"} for row in receipts(fixture)}
    assert after == before
    assert len(listed(fixture)) == 1 and listed(fixture)[0]["group"]["count"] == 3
    assert backfill_fingerprints(EmailStore(fixture.table), monitor_id=MONITOR, now=1500)["fingerprinted"] == 0


def test_backfill_seeds_the_group_decision_from_an_already_decided_copy():
    fixture = three_held_copies()
    from procedures.newsroom.tests.email_submission_fixture import decide_email
    decide_email(fixture, "release", receipt_key=receipts(fixture)[0]["sk"], reason="earlier")
    apply_email_decisions(fixture)
    strip_fingerprints(fixture)
    for row in fixture.table.by_prefix("EMAILGROUP#"):
        del fixture.table.items[(row["pk"], row["sk"])]
    result = backfill_fingerprints(EmailStore(fixture.table), monitor_id=MONITOR, now=1500)
    assert result["groupsSeeded"] == 1
    assert fixture.table.by_prefix("EMAILGROUP#")[0]["decision"] == "release"
