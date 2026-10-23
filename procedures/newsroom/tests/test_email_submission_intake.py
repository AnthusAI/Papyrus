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


@pytest.mark.parametrize("verdict", ["spfVerdict", "dkimVerdict", "dmarcVerdict", "spamVerdict", "virusVerdict"])
def test_trusted_verdicts_required_and_mime_header_cannot_authorize(verdict):
    fixture = email_fixture()
    receipt = fixture.event["Records"][0]["ses"]["receipt"]
    receipt[verdict]["status"] = "FAIL"
    if verdict in {"spfVerdict", "dkimVerdict"}:
        receipt["spfVerdict"]["status"] = receipt["dkimVerdict"]["status"] = "FAIL"
    fixture.s3.raw = b"Authentication-Results: amazonses.com; dmarc=pass; spf=pass\r\n" + RAW
    result = collect_email(fixture)
    assert result["reason"] == "sender_authentication_failed"
    assert fixture.s3.calls == []
    assert fixture.table.by_prefix("DISC#") == []


def test_editor_membership_and_from_mime_must_match_authenticated_envelope():
    fixture = email_fixture()
    fixture.event["Records"][0]["ses"]["mail"]["commonHeaders"]["from"] = ["attacker@example.org"]
    assert collect_email(fixture)["reason"] == "sender_not_active_editor"
    assert fixture.s3.calls == []
    fixture = email_fixture()
    fixture.s3.raw = RAW.replace(b"editor@example.org", b"different@example.org")
    assert collect_email(fixture)["reason"] == "mime_sender_mismatch"
    assert fixture.table.by_prefix("DISC#") == []


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
    {"maxLinks": 26}, {"maxMessageBytes": 1048577}, {"maxMessagesPerSenderHour": 0},
    {"maxMessagesPerSenderHour": True}, {"enabled": "true"}, {"unexpected": True},
])
def test_bad_or_mismatched_operator_config_fails_before_reading_mail(mutation):
    fixture = email_fixture()
    update_config(fixture, **mutation)
    with pytest.raises(ConfigurationError):
        collect_email(fixture)
    assert fixture.s3.calls == [] and fixture.table.by_prefix("DISC#") == []


def test_email_cannot_start_procedures_or_generate_feedback():
    fixture = shared_fixture()
    fixture.router["feedback"] = True
    with pytest.raises(ConfigurationError, match="feedback"):
        validate_email_config(fixture.config, fixture.router)


def test_dynamodb_decimal_sender_rate_limit_validates():
    fixture = email_fixture()
    fixture.config["maxMessagesPerSenderHour"] = Decimal(10)
    assert validate_email_config(fixture.config, fixture.router)["maxMessagesPerSenderHour"] == 10


@pytest.mark.parametrize("change", ["group", "unverified", "disabled", "lookup"])
def test_only_enabled_verified_editor_is_eligible_and_lookup_fails_closed(change):
    fixture = email_fixture()
    if change == "group":
        fixture.cognito.groups["us-east-1_fixture"].clear()
    elif change == "unverified":
        fixture.cognito.verified = False
    elif change == "disabled":
        fixture.cognito.enabled = False
    else:
        fixture.cognito.fail = True
    if change == "lookup":
        with pytest.raises(RuntimeError, match="editor_membership_lookup_unavailable"):
            collect_email(fixture)
    else:
        assert collect_email(fixture)["reason"] == "sender_not_active_editor"
    assert fixture.s3.calls == []
    assert fixture.table.by_prefix("DISC#") == []


def test_active_admin_is_eligible_because_application_allows_admin_content_writes():
    fixture = email_fixture()
    fixture.cognito.groups["us-east-1_fixture"] = {"admin"}
    assert collect_email(fixture)["status"] == "queued"
    assert fixture.table.by_prefix("DISC#")


def test_shared_route_is_limited_to_editor_publications_and_revocation_rechecked():
    fixture, model = shared_fixture(), AccountCyclotron()
    fixture.cognito.editors["us-east-1_second"].clear()
    assert collect_email(fixture)["status"] == "queued"
    discovery = fixture.table.by_prefix("DISC#")[0]
    assert discovery["emailAuthorizedPublicationIds"] == ["publication"]
    result, delivered = route_email(fixture, cyclotron=CyclotronClient(
        validate_router_config(fixture.router), sign=lambda *_: {}, http=model.http,
        sleep=lambda _: None, clock=lambda: 0))
    assert result["counts"]["delivered"] == 2  # one authorized publication for each of two links
    assert {entry[0]["publicationId"] for entry in delivered} == {"publication"}

    # Another queued discovery cannot survive membership revocation.
    next_delivery(fixture, "new")
    assert collect_email(fixture)["status"] == "queued"
    fixture.cognito.editors["us-east-1_fixture"].clear()
    result, delivered = route_email(fixture)
    assert delivered == [] and result["counts"]["refused"] == 2


def test_router_membership_lookup_failure_fails_closed():
    fixture = email_fixture()
    collect_email(fixture)
    fixture.cognito.fail = True
    result, delivered = route_email(fixture)
    assert delivered == [] and result["counts"]["error"] == 2


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
    assert len(fixture.s3.calls) == 1
    assert len(fixture.table.by_prefix("RATE#")[0]["messages"]) == 1
    fixture = email_fixture()
    update_config(fixture, maxMessageBytes=50)
    assert collect_email(fixture)["reason"] == "message_too_large"
    fixture = email_fixture()
    update_config(fixture, maxLinks=1)
    assert collect_email(fixture)["reason"] == "email_link_count_invalid"
    assert fixture.table.by_prefix("DISC#") == []


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
