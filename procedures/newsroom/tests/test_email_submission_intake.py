"""Offline trust boundary, durable queue and shared-router integration tests."""
import json
from copy import deepcopy
from decimal import Decimal
from email.message import EmailMessage
from hashlib import sha256

import pytest

from papyrus_content.email_submission_intake import (
    ConfigurationError,
    EmailStore,
    IntakeBusy,
    _resume_pending,
    validate_email_config,
)
from papyrus_content.monitoring_router import (
    CyclotronClient,
    validate_router_config,
)
from procedures.newsroom.tests.email_submission_fixture import (
    RAW,
    collect_email,
    email_fixture,
    route_email,
)
from procedures.newsroom.tests.test_monitoring_router import FakeCyclotron


def update_config(fixture, **changes):
    fixture.config.update(changes)
    fixture.table.put_item(Item=fixture.config)


def next_delivery(fixture, suffix="2"):
    fixture.event["Records"][0]["ses"]["mail"]["messageId"] = "ses-delivery-" + suffix


def shared_fixture():
    fixture = email_fixture()
    update_config(fixture, kind="shared", publicationIds=["publication", "second"])
    fixture.router.update(decisions="cyclotron", feedback=False, cyclotron={
        "endpoint": "https://fixture.execute-api.us-east-1.amazonaws.com", "accountId": "account-fixture",
        "runId": "shared-fixture", "bindingRevision": "1",
        "roleArn": "arn:aws:iam::111111111111:role/email-relevance-invoker", "pollSeconds": 10})
    fixture.router["publications"].append({"publicationId": "second", "site": "second.example",
        "userPoolId": "us-east-1_second",
        "appsyncEndpoint": "https://second.appsync-api.us-east-1.amazonaws.com/graphql"})
    fixture.cognito.editors["us-east-1_second"] = {"editor@example.org"}
    fixture.cognito.groups["us-east-1_second"] = {"editor"}
    fixture.table.put_item(Item=fixture.router)
    return fixture


class AccountCyclotron(FakeCyclotron):
    def __init__(self):
        super().__init__()
        self.account = "account-fixture"

    def http(self, method, url, headers, body, timeout):
        status, result = super().http(method, url, headers, body, timeout)
        if result.get("decision"):
            result["accountId"] = self.account
        return status, result


@pytest.mark.parametrize("verdict", ["spfVerdict", "dkimVerdict", "dmarcVerdict"])
def test_sender_authentication_verdicts_require_private_review_without_router_discoveries(verdict):
    fixture = email_fixture()
    receipt = fixture.event["Records"][0]["ses"]["receipt"]
    receipt[verdict]["status"] = "FAIL"
    receipt[verdict]["reason"] = "signature=must-not-be-retained"
    fixture.s3.raw = b"Authentication-Results: amazonses.com; dmarc=pass; spf=pass\r\n" + RAW
    result = collect_email(fixture)
    assert result["status"] == "pending_review"
    assert fixture.table.by_prefix("DISC#") == []
    stored = fixture.table.by_prefix("EMAIL#")[0]
    diagnostics = stored["sesDiagnostics"]
    assert diagnostics["provenance"] == "ses-invocation-receipt-untrusted-auth-signals"
    assert diagnostics["verdicts"][verdict.removesuffix("Verdict")] == "FAIL"
    assert diagnostics["warnings"]
    assert diagnostics["blockedGateCodes"] == []
    assert stored["processingStage"] == "pending_review"
    assert stored["emailTrustMode"] == "data-only"
    assert stored["reviewRequired"] is True and stored["pendingReviewLinkCount"] == 2
    assert "gsi1pk" not in stored
    stored_details = fixture.table.by_prefix("EMAILDETAIL#")
    assert any("#BODY#" in row["sk"] and "https://example.org/alpha" in row.get("text", "")
               for row in stored_details)
    assert any("#LINKS#" in row["sk"] for row in stored_details)
    assert len(fixture.table.by_prefix("EMAILINDEX#")) == 1
    assert "must-not-be-retained" not in repr(diagnostics)
    assert "Authentication-Results" not in repr(diagnostics)


def test_shared_auth_warning_receipt_never_reaches_cyclotron_or_reference_intake():
    fixture, model = shared_fixture(), AccountCyclotron()
    for name in ("spfVerdict", "dkimVerdict", "dmarcVerdict"):
        fixture.event["Records"][0]["ses"]["receipt"][name]["status"] = "FAIL"
    assert collect_email(fixture)["status"] == "pending_review"
    result, delivered = route_email(fixture, cyclotron=CyclotronClient(
        validate_router_config(fixture.router), sign=lambda *_: {}, http=model.http,
        sleep=lambda _: None, clock=lambda: 0))
    assert delivered == []
    assert result["counts"]["decided"] == result["counts"]["delivered"] == 0
    assert model.posts() == []
    assert fixture.table.by_prefix("DISC#") == []


@pytest.mark.parametrize("verdict,reason", [
    ("spamVerdict", "spam_verdict_not_passed"), ("virusVerdict", "virus_verdict_not_passed"),
])
def test_spam_and_virus_verdicts_remain_hard_safety_gates(verdict, reason):
    fixture = email_fixture()
    receipt = fixture.event["Records"][0]["ses"]["receipt"]
    receipt[verdict]["status"] = "FAIL"
    receipt[verdict]["reason"] = "signature=must-not-be-retained"
    fixture.s3.raw = b"Authentication-Results: amazonses.com; dmarc=pass; spf=pass\r\n" + RAW
    result = collect_email(fixture)
    stored = fixture.table.by_prefix("EMAIL#")[0]
    assert result["reason"] == reason
    assert fixture.s3.calls == [] and fixture.table.by_prefix("DISC#") == []
    assert stored["sesDiagnostics"]["blockedGateCodes"] == [reason]
    assert stored["processingStage"] == "ses_safety_checks"
    assert "must-not-be-retained" not in repr(stored["sesDiagnostics"])


def test_all_ses_authentication_signals_remain_visible_as_warnings():
    fixture = email_fixture()
    receipt = fixture.event["Records"][0]["ses"]["receipt"]
    receipt["spfVerdict"]["status"] = "NONE"
    receipt["dkimVerdict"]["status"] = "PERMERROR"
    receipt["dmarcVerdict"]["status"] = "NONE"
    result = collect_email(fixture)
    diagnostics = fixture.table.by_prefix("EMAIL#")[0]["sesDiagnostics"]
    assert result["status"] == "pending_review"
    assert diagnostics["warnings"] == ["spf_not_passed", "dkim_not_passed", "dmarc_not_passed"]
    assert diagnostics["blockedGateCodes"] == []


def test_unresolved_subscriber_tracking_url_is_private_and_never_routed():
    from procedures.newsroom.tests.test_email_submission_redirects import TRACKER
    fixture = email_fixture()
    fixture.s3.raw = fixture.s3.raw.replace(b"https://example.org/alpha", TRACKER.encode())
    assert collect_email(fixture)["status"] == "queued"
    receipt = fixture.table.by_prefix("EMAIL#")[0]
    details = fixture.table.by_prefix("EMAILDETAIL#")
    stored_links = [json.loads(row["json"]) for row in details if "#LINKS#" in row["sk"]]
    links = [link for batch in stored_links for link in batch]
    unresolved = next(link for link in links if link.get("resolutionStatus") == "unresolved")
    assert unresolved["url"] == TRACKER
    assert receipt["unresolvedLinkCount"] == 1
    assert all(row["canonicalUrl"] != TRACKER for row in fixture.table.by_prefix("DISC#"))
    _, delivered = route_email(fixture)
    assert all(row[1]["canonicalUrl"] != TRACKER for row in delivered)


def explored_fixture(monkeypatch, explorer):
    from procedures.newsroom.tests.test_email_submission_redirects import TRACKER
    from papyrus_content import email_submission_intake as intake
    monkeypatch.setattr(intake, "link_explorer", explorer)
    fixture = email_fixture()
    fixture.s3.raw = fixture.s3.raw.replace(b"https://example.org/alpha", TRACKER.encode())
    return fixture, TRACKER


def test_an_explored_tracker_is_routed_as_its_canonical_destination_only(monkeypatch):
    from papyrus_content.link_exploration import Exploration, SearchMatch

    def explorer(link, row):
        return Exploration(True, "https://news.example.org/story", None, "direct", readable=False)

    fixture, tracker = explored_fixture(monkeypatch, explorer)
    assert collect_email(fixture)["status"] == "queued"
    discoveries = fixture.table.by_prefix("DISC#")
    assert any(row["canonicalUrl"] == "https://news.example.org/story" for row in discoveries)
    assert all(tracker not in json.dumps(row, default=str) for row in discoveries)
    receipt = fixture.table.by_prefix("EMAIL#")[0]
    assert receipt["exploredLinkCount"] == 1 and "unresolvedReasons" not in receipt


def test_a_story_found_by_search_is_marked_in_the_discovery_provenance(monkeypatch):
    from papyrus_content.link_exploration import Exploration, SearchMatch

    def explorer(link, row):
        return Exploration(True, "https://news.example.org/story", None, "search", search=SearchMatch("A headline of words", 0.85, "fake", "A headline"))

    fixture, tracker = explored_fixture(monkeypatch, explorer)
    collect_email(fixture)
    row = next(row for row in fixture.table.by_prefix("DISC#") if row["canonicalUrl"] == "https://news.example.org/story")
    found = row["emailProvenance"]["linkExploration"]
    assert found["foundVia"] == "search" and found["query"] == "A headline of words" and found["matchScore"] == Decimal("0.85")
    assert tracker not in json.dumps(row, default=str)


def test_an_unexplorable_tracker_records_a_typed_reason_and_stays_unrouted(monkeypatch):
    from papyrus_content.link_exploration import Exploration

    fixture, tracker = explored_fixture(monkeypatch, lambda link, row: Exploration(False, failure="http_4xx", direct_failure="http_4xx"))
    collect_email(fixture)
    receipt = fixture.table.by_prefix("EMAIL#")[0]
    assert receipt["unresolvedReasons"] == {"http_4xx": 1}
    assert all(row["canonicalUrl"] != tracker for row in fixture.table.by_prefix("DISC#"))


def test_exploration_is_off_unless_the_deployed_handler_installs_it():
    from papyrus_content import email_submission_intake as intake
    assert intake.link_explorer is None
    intake.install_link_explorer({"EMAIL_LINK_EXPLORATION": "off"})
    assert intake.link_explorer is None
    intake.install_link_explorer({})
    assert intake.link_explorer is intake.explore_email_link
    intake.link_explorer = None


def test_editor_membership_is_never_inferred_and_email_without_links_remains_readable():
    fixture = email_fixture()
    fixture.cognito.editors["us-east-1_fixture"].clear()
    assert collect_email(fixture)["status"] == "queued"
    stored = fixture.table.by_prefix("EMAIL#")[0]
    assert stored["emailTrustMode"] == "data-only"
    assert fixture.cognito.calls == []

    fixture = email_fixture()
    fixture.s3.raw = RAW.replace(b"https://example.org/alpha\r\nhttps://example.org/beta", b"No editorial links")
    result = collect_email(fixture)
    assert result["status"] == "queued" and result["linkCount"] == 0
    stored = fixture.table.by_prefix("EMAIL#")[0]
    assert stored["processingStage"] == "queued" and stored["errorCode"] is None
    body = "".join(row.get("text", "") for row in fixture.table.by_prefix("EMAILDETAIL#") if "#BODY#" in row["sk"])
    assert "No editorial links" in body


def test_non_ses_event_cannot_claim_ses_verdict_provenance():
    fixture = email_fixture()
    fixture.event["Records"][0]["eventSource"] = "untrusted"
    result = collect_email(fixture)
    stored = fixture.table.by_prefix("EMAIL#")[0]
    assert result["reason"] == "ses_event_required"
    assert stored["sesDiagnostics"] == {
        "provenance": "unverified-event",
        "verdicts": {"spam": "UNAVAILABLE", "virus": "UNAVAILABLE", "spf": "UNAVAILABLE",
                     "dkim": "UNAVAILABLE", "dmarc": "UNAVAILABLE"},
        "warnings": [], "blockedGateCodes": ["ses_event_source_untrusted"],
    }


def test_sender_identity_claims_are_untrusted_and_cannot_change_destination_scope():
    fixture = email_fixture()
    fixture.event["Records"][0]["ses"]["mail"]["commonHeaders"]["from"] = ["attacker@example.org"]
    result = collect_email(fixture)
    assert result["status"] == "queued"
    discovery = fixture.table.by_prefix("DISC#")[0]
    assert discovery["emailDestinationPublicationIds"] == ["publication"]
    assert "emailAuthorizedPublicationIds" not in discovery
    assert fixture.cognito.calls == []
    fixture = email_fixture()
    fixture.s3.raw = RAW.replace(b"editor@example.org", b"different@example.org")
    assert collect_email(fixture)["status"] == "queued"
    assert fixture.table.by_prefix("DISC#")


def test_forwarded_attached_message_links_use_outer_editor_authentication_only():
    fixture = email_fixture()
    outer = EmailMessage()
    outer["From"] = "editor@example.org"
    outer["To"] = "submissions@publication.example"
    outer.set_content("Forwarding a newsletter")
    attached = EmailMessage()
    attached["From"] = "newsletter@example.net"
    attached.set_content("https://example.net/article")
    outer.add_attachment(attached)
    fixture.s3.raw = outer.as_bytes()
    result = collect_email(fixture)
    assert result["status"] == "queued"
    discoveries = fixture.table.by_prefix("DISC#")
    assert len(discoveries) == 1
    assert discoveries[0]["canonicalUrl"] == "https://example.net/article"
    assert discoveries[0]["emailProvenance"]["sender"] == "editor@example.org"


def test_mime_to_headers_are_provenance_and_cannot_choose_destination():
    fixture = email_fixture()
    fixture.s3.raw = RAW.replace(b"submissions@publication.example", b"submissions@other.example")
    assert collect_email(fixture)["status"] == "queued"
    assert all(row["emailProvenance"]["recipients"] == ["submissions@publication.example"]
               for row in fixture.table.by_prefix("DISC#"))
    fixture = email_fixture()
    fixture.event["Records"][0]["ses"]["mail"]["destination"] = ["submissions@other.example"]
    assert collect_email(fixture)["reason"] == "destination_scope_mismatch"
    assert fixture.s3.calls == []


def test_publication_destination_delivers_through_existing_router_once():
    fixture = email_fixture()
    assert collect_email(fixture)["status"] == "queued"
    receipt = fixture.table.by_prefix("EMAIL#")[0]
    assert receipt["processingStage"] == "queued"
    assert receipt["sesDiagnostics"] == {
        "provenance": "ses-invocation-receipt-untrusted-auth-signals",
        "verdicts": {"spam": "PASS", "virus": "PASS", "spf": "PASS", "dkim": "PASS", "dmarc": "PASS"},
        "warnings": [], "blockedGateCodes": [],
    }
    result, delivered = route_email(fixture)
    assert result["counts"]["delivered"] == 2
    assert {row[0]["publicationId"] for row in delivered} == {"publication"}
    assert all(row[1]["emailProvenance"]["inputTrust"] == "untrusted-source-material" for row in delivered)
    assert route_email(fixture)[1] == []


def test_shared_destination_uses_one_shared_decision_per_source_and_only_positive_publication():
    fixture, model = shared_fixture(), AccountCyclotron()
    collect_email(fixture)
    for row in fixture.table.by_prefix("DISC#"):
        model.labels[("email-publication-" + row["sourceId"], "second")] = "exclude"
    config = validate_router_config(fixture.router)
    cyclotron = CyclotronClient(config, sign=lambda *_: {}, http=model.http, sleep=lambda _: None, clock=lambda: 0)
    result, delivered = route_email(fixture, cyclotron=cyclotron)
    assert result["counts"]["delivered"] == 2
    assert {row[0]["publicationId"] for row in delivered} == {"publication"}
    assert len(model.posts()) == 4  # two bound projections of each native multi-output decision
    for _, _, request in model.posts():
        values = request["payload"]["item"]["values"]
        assert values["source"] == "email"
        assert values["text"] == values["title"] + "\n" + values["url"]
        assert "sender" not in values and "body" not in values
    assert route_email(fixture, cyclotron=cyclotron)[1] == []
    assert len(model.posts()) == 4


def test_shared_account_mismatch_response_is_not_delivered():
    fixture, model = shared_fixture(), AccountCyclotron()
    collect_email(fixture)
    model.account = "other-account"
    client = CyclotronClient(validate_router_config(fixture.router), sign=lambda *_: {}, http=model.http,
                             sleep=lambda _: None, clock=lambda: 0)
    result, delivered = route_email(fixture, cyclotron=client)
    assert result["counts"]["error"] == 2 and delivered == []


def test_parked_publication_backfill_rechecks_email_destination_scope():
    fixture, model = shared_fixture(), AccountCyclotron()
    collect_email(fixture)
    model.post_override["second"] = (409, {"detail": "publication criteria are pending"})
    config = validate_router_config(fixture.router)
    client = CyclotronClient(config, sign=lambda *_: {}, http=model.http, sleep=lambda _: None, clock=lambda: 0)
    result, delivered = route_email(fixture, cyclotron=client)
    assert result["counts"]["delivered"] == 2
    calls = len(model.calls)
    park = fixture.table.by_prefix("PARK#")[0]
    park["ready"] = True
    fixture.table.put_item(Item=park)
    fixture.router["publications"][1]["appsyncEndpoint"] = "https://changed.appsync-api.us-east-1.amazonaws.com/graphql"
    fixture.table.put_item(Item=fixture.router)
    model.post_override.clear()
    result, delivered = route_email(fixture, cyclotron=client)
    assert result["counts"]["backfilled"] == 0 and delivered == [] and len(model.calls) == calls
    assert any("binding changed" in row.get("notReady", {}).get("second", {}).get("reason", "")
               for row in fixture.table.by_prefix("ROUTE#"))


@pytest.mark.parametrize("mutation", [
    {"accountId": "other"}, {"publicationIds": ["other"]}, {"kind": "shared"},
    {"allowedSenders": ["*@example.org"]}, {"addresses": []},
    {"maxMessageBytes": 1048577}, {"maxMessagesPerSenderHour": 0},
    {"maxMessagesPerSenderHour": True}, {"enabled": "true"}, {"unexpected": True},
])
def test_bad_or_mismatched_operator_config_fails_before_reading_mail(mutation):
    fixture = email_fixture()
    update_config(fixture, **mutation)
    with pytest.raises(ConfigurationError):
        collect_email(fixture)
    assert fixture.s3.calls == [] and fixture.table.by_prefix("DISC#") == []


def test_a_stored_feedback_switch_on_an_email_router_is_ignored():
    fixture = shared_fixture()
    fixture.router["feedback"] = True
    validate_email_config(fixture.config, fixture.router)   # feedback is never configured: it is always on for Cyclotron decisions


def test_dynamodb_decimal_sender_rate_limit_validates():
    fixture = email_fixture()
    fixture.config["maxMessagesPerSenderHour"] = Decimal(10)
    assert validate_email_config(fixture.config, fixture.router)["maxMessagesPerSenderHour"] == 10


def test_private_email_details_are_replayable_and_idempotent():
    fixture = email_fixture()
    for name in ("spfVerdict", "dkimVerdict", "dmarcVerdict"):
        fixture.event["Records"][0]["ses"]["receipt"][name]["status"] = "FAIL"
    message_id = fixture.event["Records"][0]["ses"]["mail"]["messageId"]
    receipt_id = "EMAIL#" + sha256(message_id.encode()).hexdigest()
    config = validate_email_config(fixture.config, fixture.router)
    fixture.table.put_item(Item={
        "pk": "MONITOR#email-publication", "sk": receipt_id,
        "status": "rejected", "errorCode": "sender_authentication_failed",
        "sesMessageId": message_id, "firstSeen": 1000, "observedAt": "1970-01-01T00:16:40Z",
        "s3Bucket": "mail-fixture", "s3Key": "email-submissions/" + message_id,
        "accountId": config["accountId"], "routingFingerprint": config["routingFingerprint"],
        "destinationFingerprint": config["destinationFingerprint"], "ttl": 999999,
        "sesDiagnostics": {"provenance": "ses-invocation-receipt", "verdicts": {"spam": "PASS", "virus": "PASS",
                            "spf": "FAIL", "dkim": "FAIL", "dmarc": "FAIL"},
                            "failedGateCodes": ["sender_authentication_failed"]},
    })
    first, second = collect_email(fixture), collect_email(fixture)
    assert first["status"] == "pending_review" and second["status"] == "duplicate"
    row = fixture.table.get_item(Key={"pk": "MONITOR#email-publication", "sk": receipt_id})["Item"]
    assert row["sesDiagnostics"]["warnings"] == ["spf_not_passed", "dkim_not_passed", "dmarc_not_passed"]
    assert fixture.table.by_prefix("DISC#") == []
    assert len(fixture.table.by_prefix("EMAILINDEX#")) == 1


def test_private_readable_body_and_candidate_links_survive_bounded_storage_chunks():
    fixture = email_fixture()
    body = "é🙂" * 100_000
    links = [{"url": f"https://example.org/article/{index}", "title": f"Story {index}"} for index in range(5000)]
    digest = "b" * 64
    EmailStore(fixture.table).put_email_detail_chunks("email-publication", "EMAIL#" + digest, body, links, 1234)
    rows = fixture.table.by_prefix("EMAILDETAIL#" + digest + "#")
    body_rows = sorted((row for row in rows if "#BODY#" in row["sk"]), key=lambda row: row["sk"])
    link_rows = sorted((row for row in rows if "#LINKS#" in row["sk"]), key=lambda row: row["sk"])
    stored_body = "".join(row["text"] for row in body_rows)
    stored_links = [link for row in link_rows for link in json.loads(row["json"])]
    assert stored_body == body and len(body_rows) > 1
    assert all(len(row["text"].encode("utf-8")) <= 180 * 1024 for row in body_rows)
    assert stored_links == links and len(link_rows) > 1
    assert all(row["ttl"] == 1234 for row in rows)


@pytest.mark.parametrize("change", ["group", "unverified", "disabled", "lookup"])
def test_sender_directory_state_never_controls_data_only_email_intake(change):
    fixture = email_fixture()
    if change == "group":
        fixture.cognito.groups["us-east-1_fixture"].clear()
    elif change == "unverified":
        fixture.cognito.verified = False
    elif change == "disabled":
        fixture.cognito.enabled = False
    else:
        fixture.cognito.fail = True
    assert collect_email(fixture)["status"] == "queued"
    assert fixture.table.by_prefix("EMAIL#")[0]["emailTrustMode"] == "data-only"
    assert fixture.table.by_prefix("DISC#")
    assert fixture.cognito.calls == []


def test_admin_role_does_not_grant_any_email_submission_privilege():
    fixture = email_fixture()
    fixture.cognito.groups["us-east-1_fixture"] = {"admin"}
    assert collect_email(fixture)["status"] == "queued"
    assert fixture.table.by_prefix("DISC#")


def test_shared_route_is_limited_to_recipient_destination_not_sender_membership():
    fixture, model = shared_fixture(), AccountCyclotron()
    fixture.cognito.editors["us-east-1_second"].clear()
    assert collect_email(fixture)["status"] == "queued"
    discovery = fixture.table.by_prefix("DISC#")[0]
    assert discovery["emailDestinationPublicationIds"] == ["publication", "second"]
    assert "emailAuthorizedPublicationIds" not in discovery
    for row in fixture.table.by_prefix("DISC#"):
        model.labels[("email-publication-" + row["sourceId"], "second")] = "exclude"
    result, delivered = route_email(fixture, cyclotron=CyclotronClient(
        validate_router_config(fixture.router), sign=lambda *_: {}, http=model.http,
        sleep=lambda _: None, clock=lambda: 0))
    assert result["counts"]["delivered"] == 2  # the shared classifier selected only the first publication
    assert {entry[0]["publicationId"] for entry in delivered} == {"publication"}


def test_router_does_not_use_untrusted_sender_for_editor_authorization():
    fixture = email_fixture()
    collect_email(fixture)
    fixture.cognito.fail = True
    result, delivered = route_email(fixture)
    assert len(delivered) == 2 and result["counts"]["delivered"] == 2
    assert fixture.cognito.calls == []


def test_router_rejects_auth_warning_discovery_even_if_one_is_injected():
    fixture = email_fixture()
    collect_email(fixture)
    discovery = fixture.table.by_prefix("DISC#")[0]
    discovery["emailProvenance"]["sesDiagnostics"]["warnings"] = ["dmarc_not_passed"]
    from papyrus_content.monitoring_router import validate_email_discovery_scope, ItemInvalid
    with pytest.raises(ItemInvalid, match="require editor review"):
        validate_email_discovery_scope(discovery, validate_router_config(fixture.router))


def test_classifier_backfill_rechecks_membership_before_delivery():
    fixture, model = shared_fixture(), AccountCyclotron()
    collect_email(fixture)
    model.post_override["second"] = (409, {"detail": "publication criteria are pending"})
    client = CyclotronClient(validate_router_config(fixture.router), sign=lambda *_: {}, http=model.http,
                             sleep=lambda _: None, clock=lambda: 0)
    result, delivered = route_email(fixture, cyclotron=client)
    assert {entry[0]["publicationId"] for entry in delivered} == {"publication"}
    assert fixture.table.by_prefix("PARK#")
    fixture.cognito.editors["us-east-1_second"].clear()
    model.post_override.clear()
    calls = len(model.posts())
    result, delivered = route_email(fixture, cyclotron=client)
    assert delivered == [] and result["counts"]["delivered"] == 0
    assert len(model.posts()) == calls
    fixture.router["feedback"] = False
    fixture.router["publications"][0]["procedureTriggers"] = [{"procedureKey": "unsafe.publish", "input": {}}]
    fixture.router["publications"][0]["openaiKeyParameter"] = "/fixture/unused"
    with pytest.raises(ConfigurationError):
        validate_email_config(fixture.config, fixture.router)


def test_bounds_reject_before_queue_writes_and_rate_retries_do_not_consume_new_slots():
    fixture = email_fixture()
    update_config(fixture, maxMessagesPerSenderHour=1)
    assert collect_email(fixture)["status"] == "queued"
    assert collect_email(fixture)["status"] == "duplicate"
    next_delivery(fixture)
    assert collect_email(fixture)["reason"] == "sender_rate_limit"
    assert sum(key.startswith("email-submissions/ses-delivery-") for _, key in fixture.s3.calls) == 1
    assert len(fixture.table.by_prefix("RATE#")[0]["messages"]) == 1
    fixture = email_fixture()
    update_config(fixture, maxMessageBytes=50)
    assert collect_email(fixture)["reason"] == "message_too_large"
    fixture = email_fixture()
    update_config(fixture, maxLinks=1)  # old config key is accepted but no longer a content ceiling
    assert collect_email(fixture)["linkCount"] == 2


def test_41_links_are_checkpointed_25_then_16_and_all_reach_existing_router():
    fixture = email_fixture()
    links = "\n".join(f"https://example.org/article/{i}" for i in range(41))
    fixture.s3.raw = fixture.s3.raw.replace(b"https://example.org/alpha\r\nhttps://example.org/beta", links.encode())
    first = collect_email(fixture)
    assert first["status"] == "processing" and first["linkCount"] == 41
    receipt = fixture.table.by_prefix("EMAIL#")[0]
    assert receipt["processedCount"] == 25 and 0 < receipt["cursorBytes"] < receipt["manifestBytes"]
    first_delivered = []
    while len(first_delivered) < 25:
        _, delivered = route_email(fixture)
        first_delivered.extend(delivered)
    assert len(first_delivered) == 25

    resumed = _resume_pending(EmailStore(fixture.table), "email-publication", "mail-fixture",
                              fixture.s3, fixture.cognito, now=1001)
    assert resumed["receipts"][0]["status"] == "queued"
    final = fixture.table.by_prefix("EMAIL#")[0]
    assert final["processedCount"] == final["linkCount"] == 41
    assert "gsi1pk" not in final
    second_delivered = []
    while len(second_delivered) < 16:
        _, delivered = route_email(fixture)
        second_delivered.extend(delivered)
    assert len(second_delivered) == 16
    assert len(fixture.table.by_prefix("DISC#")) == 41


def test_pending_manifest_fails_closed_if_destination_addresses_change():
    fixture = email_fixture()
    links = "\n".join(f"https://example.org/article/{i}" for i in range(41))
    fixture.s3.raw = fixture.s3.raw.replace(b"https://example.org/alpha\r\nhttps://example.org/beta", links.encode())
    assert collect_email(fixture)["status"] == "processing"
    update_config(fixture, addresses=["new-submissions@publication.example"])
    result = _resume_pending(EmailStore(fixture.table), "email-publication", "mail-fixture",
                             fixture.s3, fixture.cognito, now=1001)
    row = fixture.table.by_prefix("EMAIL#")[0]
    assert result["receipts"][0]["reason"] == "email_retry_binding_changed"
    assert row["status"] == "failed" and "gsi1pk" not in row
    assert len(fixture.table.by_prefix("DISC#")) == 25


def test_crashed_batch_resumes_without_overwriting_a_routed_discovery(monkeypatch):
    fixture = email_fixture()
    real_put, calls = fixture.table.put_item, 0
    def fail_second_discovery(*, Item, **kwargs):
        nonlocal calls
        if Item["sk"].startswith("DISC#"):
            calls += 1
            if calls == 2:
                raise RuntimeError("temporary table failure")
        return real_put(Item=Item, **kwargs)
    monkeypatch.setattr(fixture.table, "put_item", fail_second_discovery)
    with pytest.raises(RuntimeError, match="temporary"):
        collect_email(fixture)
    assert fixture.table.by_prefix("EMAIL#")[0]["status"] == "failed"
    assert len(fixture.table.by_prefix("DISC#")) == 1
    route_email(fixture)
    assert collect_email(fixture)["status"] == "queued"
    assert len(fixture.table.by_prefix("DISC#")) == 2
    assert len(fixture.table.by_prefix("RATE#")[0]["messages"]) == 1
    result, delivered = route_email(fixture)
    assert result["counts"]["delivered"] == 1 and len(delivered) == 1


def test_concurrent_collector_lease_is_retryable_without_mail_reads():
    fixture = email_fixture()
    store = EmailStore(fixture.table)
    assert store.acquire_email_lock("email-publication", "other-worker", 1000)
    with pytest.raises(IntakeBusy):
        collect_email(fixture)
    assert fixture.s3.calls == []


def test_changed_mime_on_retry_cannot_mix_source_batches(monkeypatch):
    fixture = email_fixture()
    real_put = fixture.table.put_item
    def fail_discovery(*, Item, **kwargs):
        if Item["sk"].startswith("DISC#"):
            raise RuntimeError("table unavailable")
        return real_put(Item=Item, **kwargs)
    monkeypatch.setattr(fixture.table, "put_item", fail_discovery)
    with pytest.raises(RuntimeError):
        collect_email(fixture)
    monkeypatch.setattr(fixture.table, "put_item", real_put)
    fixture.s3.raw = RAW.replace(b"alpha", b"different")
    assert collect_email(fixture)["reason"] == "email_mime_changed"
    assert fixture.table.by_prefix("DISC#") == []


@pytest.mark.parametrize("change", ["account", "endpoint", "corpus", "procedures"])
def test_queued_destination_scope_is_immutable_even_on_delivery_retry(change):
    fixture = email_fixture()
    collect_email(fixture)
    router = deepcopy(fixture.router)
    if change == "account":
        router["accountId"] = "different"
    elif change == "endpoint":
        router["publications"][0]["appsyncEndpoint"] = "https://other.appsync-api.us-east-1.amazonaws.com/graphql"
    elif change == "corpus":
        router["publications"][0]["corpusId"] = "knowledge-corpus-other"
    else:
        router["publications"][0]["procedureTriggers"] = [{"procedureKey": "unsafe.publish", "input": {}}]
        router["publications"][0]["openaiKeyParameter"] = "/fixture/unused"
    fixture.table.put_item(Item=router)
    result, delivered = route_email(fixture)
    assert result["counts"]["error"] == 2 and delivered == []


def test_email_provenance_reaches_existing_reference_intake_without_recuration(monkeypatch):
    from papyrus_content import monitoring_intake
    from papyrus_content.monitoring_router import deliver_reference
    from procedures.newsroom.tests.test_monitoring_intake import Client

    fixture = email_fixture()
    collect_email(fixture)
    disc = fixture.table.by_prefix("DISC#")[0]
    config = validate_router_config(fixture.router)
    publication = config["publications"][0]
    client, saved = Client(), []
    client.endpoint = publication["appsyncEndpoint"]
    real_intake = monitoring_intake.ReferenceIntake
    monkeypatch.setattr(monitoring_intake, "ReferenceIntake", lambda *args, **kwargs:
                        real_intake(*args, **kwargs, persist=lambda rows: saved.extend(rows)))
    decision = {"decisionId": "direct-fixture", "output": "publication", "label": "include"}
    result = deliver_reference(client, publication, disc, decision, config)
    assert client.references[0]["curationStatus"] == "pending"
    message = next(r["expected"] for r in saved if r["modelName"] == "Message")
    body = json.loads(message["body"])
    assert body["emailSubmission"]["mimeSha256"] == sha256(RAW).hexdigest()
    assert body["sectionHandoff"] == "pending-reference-site-sweep"
    # A different SES delivery of the same URL has independent audit provenance,
    # while canonical Reference deduplication reuses the original pending row.
    next_delivery(fixture)
    collect_email(fixture)
    second = next(row for row in fixture.table.by_prefix("DISC#")
                  if row["canonicalUrl"] == disc["canonicalUrl"] and row["sourceId"] != disc["sourceId"])
    again = deliver_reference(client, publication, second, decision, config)
    assert again["referenceId"] == result["referenceId"]
    assert client.references[0]["curationStatus"] == "pending" and len(client.writes) == 1
    messages = [row["expected"] for row in saved if row["modelName"] == "Message"]
    assert len({row["id"] for row in messages}) == 2
    assert {json.loads(row["body"])["emailSubmission"]["sesMessageId"] for row in messages} == {"ses-delivery-1", "ses-delivery-2"}
    client.references[0]["curationStatus"] = "accepted"
    before = deepcopy(client.references[0])
    again = deliver_reference(client, publication, disc, decision, config)
    assert again["referenceId"] == result["referenceId"]
    assert client.references[0] == before and len(client.writes) == 1
