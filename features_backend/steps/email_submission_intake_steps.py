from copy import deepcopy
from hashlib import sha256

from behave import given, then, when

from papyrus_content.email_submission_intake import EmailStore, _resume_pending
from procedures.newsroom.tests.email_submission_fixture import (
    collect_email,
    email_fixture,
    route_email,
)


@given("an email with failed authentication is available to an editor for private review")
def email_pending_reference_fixture(context):
    from procedures.newsroom.tests.test_reference_intake import (
        EmailReceiptStore,
        IntakeClient,
    )

    context.email_reference_client = IntakeClient()
    context.email_reference_env = {
        "PAPYRUS_GRAPHQL_ENDPOINT": "https://publication.appsync-api.us-east-1.amazonaws.com/graphql",
        "PAPYRUS_USER_POOL_ISSUER": "https://cognito-idp.us-east-1.amazonaws.com/publication-pool",
        "PAPYRUS_TENANT_ID": "",
        "PAPYRUS_PUBLICATION_CORPUS_KEY": "email-publication",
    }
    context.email_reference_client.tables["KnowledgeCorpus"]["knowledge-corpus-email-publication"] = {
        "id": "knowledge-corpus-email-publication"}
    context.email_reference_identity = {
        "sub": "editor-sub", "issuer": context.email_reference_env["PAPYRUS_USER_POOL_ISSUER"],
        "claims": {"sub": "editor-sub", "iss": context.email_reference_env["PAPYRUS_USER_POOL_ISSUER"],
                   "cognito:groups": ["editor"]},
    }
    context.email_reference_payload = {
        "receiptId": "EMAIL#" + "c" * 64,
        "items": [{"candidateIndex": 0, "source_uri": "https://example.org/email-story"}],
    }
    context.email_reference_store = EmailReceiptStore(
        context.email_reference_payload["receiptId"],
        [{"url": "https://example.org/email-story", "title": "Email story"}],
        corpus_id="knowledge-corpus-email-publication",
    )


@when("the editor explicitly adds its selected article links to References")
def email_editor_imports_pending_references(context):
    from unittest.mock import patch

    from papyrus_content.reference_intake import intake_email_submission_references

    client = context.email_reference_client
    with patch.dict("os.environ", context.email_reference_env), patch(
        "papyrus_content.reference_intake.upload_attachment_body", client.upload
    ):
        context.email_reference_first = intake_email_submission_references(
            client, context.email_reference_payload, context.email_reference_identity,
            env=context.email_reference_env, receipt_store=context.email_reference_store,
        )
        context.email_reference_retry = intake_email_submission_references(
            client, context.email_reference_payload, context.email_reference_identity,
            env=context.email_reference_env, receipt_store=context.email_reference_store,
        )


@then("each selected URL is registered or matched as a pending Reference with editor provenance")
def email_reference_is_pending(context):
    client = context.email_reference_client
    references = context.email_reference_first["references"]
    assert len(references) == 1
    stored = client.tables["Reference"][references[0]["id"]]
    assert stored["sourceUri"] == "https://example.org/email-story"
    assert stored["curationStatus"] == "pending"
    assert stored["versionCreatedBy"] == "user:editor-sub"
    assert "EMAIL#" in stored["curationStatusReason"]


@then("repeating the import is idempotent and makes no vote, classifier request, or publication")
def email_reference_import_is_inert(context):
    client = context.email_reference_client
    assert context.email_reference_retry["references"] == context.email_reference_first["references"]
    assert len(client.tables["Reference"]) == 1
    assert len(client.tables["KnowledgeImportRun"]) == 1
    assert not client.tables.get("Message")
    assert not client.tables.get("PublishedItem")
    assert not client.tables.get("Decision")


@given("an isolated publication email destination and a newsletter email")
def email_destination(context):
    context.email_fixture = email_fixture()


@given("an isolated 41-link newsletter email destination")
def email_destination_with_many_links(context):
    context.email_fixture = email_fixture()
    links = "\n".join(f"https://example.org/article/{i}" for i in range(41))
    context.email_fixture.s3.raw = context.email_fixture.s3.raw.replace(
        b"https://example.org/alpha\r\nhttps://example.org/beta", links.encode())


@when("the email collector processes the first batch and resumes the receipt")
def email_process_and_resume(context):
    context.first_email_result = collect_email(context.email_fixture)
    context.first_email_receipt = context.email_fixture.table.by_prefix("EMAIL#")[0]
    context.resume_email_result = _resume_pending(
        EmailStore(context.email_fixture.table), "email-publication", "mail-fixture",
        context.email_fixture.s3, context.email_fixture.cognito, now=1001)


@then("the receipt remains processing after 25 links and finishes after 16 more")
def email_progress_receipt(context):
    assert context.first_email_result["status"] == "processing"
    assert context.first_email_receipt["processedCount"] == 25
    assert context.resume_email_result["receipts"][0]["status"] == "queued"
    row = context.email_fixture.table.by_prefix("EMAIL#")[0]
    assert row["processedCount"] == row["linkCount"] == 41


@then("all 41 unique links have one durable discovery")
def email_all_links_durable(context):
    rows = context.email_fixture.table.by_prefix("DISC#")
    assert len(rows) == 41
    assert len({row["sourceId"] for row in rows}) == 41


@given("the SES receipt reports failed SPF, DKIM and DMARC checks")
def email_authentication_failure(context):
    receipt = context.email_fixture.event["Records"][0]["ses"]["receipt"]
    for name in ("spfVerdict", "dkimVerdict", "dmarcVerdict"):
        receipt[name]["status"] = "FAIL"


@given("another publication is present in the SES envelope recipients")
def email_mixed_destinations(context):
    context.email_fixture.event["Records"][0]["ses"]["mail"]["destination"].append("submissions@other.example")


@when("the email collector receives the same SES delivery twice")
def email_repeated(context):
    context.email_results = [collect_email(context.email_fixture) for _ in range(2)]


@when("the email collector receives the SES delivery")
def email_once(context):
    try:
        context.email_results = [collect_email(context.email_fixture)]
    except RuntimeError as error:
        context.email_results = [error]


@then("each newsletter source has one queued discovery with private email provenance")
def email_discoveries(context):
    rows = context.email_fixture.table.by_prefix("DISC#")
    assert len(rows) == 2
    assert all(row["routing"] == "collected" and row["emailProvenance"]["sesMessageId"] == "ses-delivery-1" for row in rows)
    assert context.email_results[1]["status"] == "duplicate"


@then("the email collector has not fetched sources or called an agent")
def email_only_mime(context):
    calls = context.email_fixture.s3.calls
    assert calls[0] == ("mail-fixture", "email-submissions/ses-delivery-1")
    assert sum(key == "email-submissions/ses-delivery-1" for _, key in calls) == 1
    assert all(key.startswith("email-submissions/") for _, key in calls)


@then("the email is rejected before reading the MIME object")
def email_rejected(context):
    assert context.email_results[0]["status"] == "rejected"
    assert context.email_fixture.s3.calls == []
    assert context.email_fixture.table.by_prefix("DISC#") == []


@then("the private receipt records untrusted authentication signals as warnings")
def email_receipt_verdict_diagnostics(context):
    receipt = context.email_fixture.table.by_prefix("EMAIL#")[0]
    diagnostics = receipt["sesDiagnostics"]
    assert receipt["status"] == "pending_review" and receipt["emailTrustMode"] == "data-only"
    assert receipt["reviewRequired"] is True
    assert context.email_fixture.table.by_prefix("DISC#") == []
    assert diagnostics["provenance"] == "ses-invocation-receipt-untrusted-auth-signals"
    assert diagnostics["verdicts"]["dmarc"] == "FAIL"
    assert diagnostics["warnings"] == ["spf_not_passed", "dkim_not_passed", "dmarc_not_passed"]
    assert diagnostics["blockedGateCodes"] == []
    assert set(diagnostics) == {"provenance", "verdicts", "warnings", "blockedGateCodes"}


@then("the message is queued only within its configured destination")
def email_is_queued_in_explicit_destination(context):
    receipt = context.email_fixture.table.by_prefix("EMAIL#")[0]
    expected_status = "pending_review" if receipt.get("reviewRequired") else "queued"
    assert context.email_results[0]["status"] == expected_status
    rows = context.email_fixture.table.by_prefix("DISC#")
    expected = context.email_fixture.config["publicationIds"]
    if receipt.get("reviewRequired"):
        assert rows == []
    else:
        assert rows and all(row["emailTrustMode"] == "data-only"
                            and row["emailDestinationPublicationIds"] == expected for row in rows)


@then("the message is held for private review within its configured destination")
def email_held_for_review(context):
    result = context.email_results[0]
    receipt = context.email_fixture.table.by_prefix("EMAIL#")[0]
    assert result["status"] == "pending_review"
    assert receipt["reviewRequired"] is True
    assert receipt["emailDestinationPublicationIds"] == context.email_fixture.config["publicationIds"]
    assert context.email_fixture.table.by_prefix("DISC#") == []


@then("no discoveries are created for the classifier or router")
def email_has_no_discoveries(context):
    assert context.email_fixture.table.by_prefix("DISC#") == []
    assert context.email_fixture.table.by_prefix("ROUTE#") == []


@then("no Cognito editor membership lookup is made")
def email_does_not_lookup_editor_membership(context):
    assert context.email_fixture.cognito.calls == []


@then("the original body is available only as inert text to that publication's editors")
def email_body_is_inert_private_text(context):
    row = context.email_fixture.table.by_prefix("EMAIL#")[0]
    details = context.email_fixture.table.by_prefix("EMAILDETAIL#")
    body = "".join(item.get("text", "") for item in details if "#BODY#" in item["sk"])
    assert row["emailTrustMode"] == "data-only" and row["safeBodyChunks"] >= 1
    assert "https://example.org/alpha" in body and "<script" not in body
    assert all(item["ttl"] == row["ttl"] for item in details)


@then("only that publication is added to the configured destination set")
def only_publication_authorized(context):
    rows = context.email_fixture.table.by_prefix("DISC#")
    assert rows and all(row["emailDestinationPublicationIds"] == ["publication"] for row in rows)
    assert all("emailAuthorizedPublicationIds" not in row for row in rows)


@given("the MIME sender and SES sender headers disagree")
def sender_headers_disagree(context):
    context.email_fixture.event["Records"][0]["ses"]["mail"]["commonHeaders"]["from"] = ["attacker@example.net"]
    context.email_fixture.s3.raw = context.email_fixture.s3.raw.replace(
        b"Editor <editor@example.org>", b"Editor <other@example.net>")


@given("a shared destination grants two publications")
def shared_membership_destination(context):
    from procedures.newsroom.tests.test_email_submission_intake import shared_fixture

    context.email_fixture = shared_fixture()


@given("an isolated shared email destination and a newsletter email")
def email_shared_destination(context):
    from procedures.newsroom.tests.test_email_submission_intake import shared_fixture
    context.email_fixture = shared_fixture()


@then("the discovery carries only the two configured destination publications")
def discovery_has_exact_destination_scope(context):
    rows = context.email_fixture.table.by_prefix("DISC#")
    assert rows and all(row["emailDestinationPublicationIds"] == ["publication", "second"] for row in rows)
    assert all("emailAuthorizedPublicationIds" not in row for row in rows)


@then("the Cyclotron can choose only among those publications")
def cyclotron_selection_stays_in_destination(context):
    from papyrus_content.monitoring_router import (
        CyclotronClient,
        validate_router_config,
    )
    from procedures.newsroom.tests.test_email_submission_intake import AccountCyclotron

    model = AccountCyclotron()
    client = CyclotronClient(validate_router_config(context.email_fixture.router), sign=lambda *_: {}, http=model.http,
                             sleep=lambda _: None, clock=lambda: 0)
    result, delivered = route_email(context.email_fixture, cyclotron=client)
    allowed = {"publication", "second"}
    assert result["counts"]["delivered"] == 4
    assert delivered and {entry[0]["publicationId"] for entry in delivered} <= allowed
    assert model.posts() and all(any(f"/bindings/{pub}/" in row[1] for pub in allowed)
                                 for row in model.posts())


@given("a prior authentication-rejected SES delivery with passing spam and virus checks")
def prior_authentication_rejection(context):
    fixture = email_fixture()
    ses_receipt = fixture.event["Records"][0]["ses"]["receipt"]
    for field in ("spfVerdict", "dkimVerdict", "dmarcVerdict"):
        ses_receipt[field]["status"] = "FAIL"
    message_id = fixture.event["Records"][0]["ses"]["mail"]["messageId"]
    receipt_id = "EMAIL#" + sha256(message_id.encode()).hexdigest()
    from papyrus_content.email_submission_intake import validate_email_config

    config = validate_email_config(fixture.config, fixture.router)
    fixture.table.put_item(Item={
        "pk": "MONITOR#email-publication", "sk": receipt_id,
        "status": "rejected", "errorCode": "sender_authentication_failed",
        "sesMessageId": message_id, "firstSeen": 1000, "observedAt": "1970-01-01T00:16:40Z",
        "s3Bucket": "mail-fixture", "s3Key": "email-submissions/" + message_id,
        "accountId": config["accountId"], "routingFingerprint": config["routingFingerprint"],
        "destinationFingerprint": config["destinationFingerprint"], "ttl": 999999,
        "sesDiagnostics": {"provenance": "ses-invocation-receipt",
                            "verdicts": {"spam": "PASS", "virus": "PASS", "spf": "FAIL",
                                         "dkim": "FAIL", "dmarc": "FAIL"},
                            "failedGateCodes": ["sender_authentication_failed"]},
    })
    context.email_fixture = fixture


@when("the operator replays its stored SES message")
def replay_stored_email(context):
    context.email_results = [collect_email(context.email_fixture), collect_email(context.email_fixture)]


@then("the original private receipt is held for review as data-only")
def replay_receipt_queued(context):
    assert context.email_results[0]["status"] == "pending_review", context.email_results
    assert context.email_results[1]["status"] == "duplicate", context.email_results
    receipt = context.email_fixture.table.by_prefix("EMAIL#")[0]
    assert receipt["emailTrustMode"] == "data-only" and receipt["reviewRequired"] is True, receipt


@then("replay does not create duplicate discoveries")
def replay_is_idempotent(context):
    assert context.email_fixture.table.by_prefix("DISC#") == []


@when("the router Account binding changes before delivery")
def email_account_changed(context):
    row = deepcopy(context.email_fixture.router)
    row["accountId"] = "different-account"
    context.email_fixture.table.put_item(Item=row)


@then("the router refuses the discovery without delivering references")
def email_scope_refused(context):
    result, delivered = route_email(context.email_fixture)
    assert result["counts"]["error"] == 2
    assert delivered == []


@given("an explicitly granted shared email destination for two publications")
def shared_email_destination(context):
    from procedures.newsroom.tests.test_email_submission_intake import (
        AccountCyclotron,
        shared_fixture,
    )

    context.email_fixture = shared_fixture()
    context.email_model = AccountCyclotron()


@when("the shared Cyclotron includes the first publication and excludes the second")
def shared_email_route(context):
    from papyrus_content.monitoring_router import (
        CyclotronClient,
        validate_router_config,
    )

    for row in context.email_fixture.table.by_prefix("DISC#"):
        context.email_model.labels[("email-publication-" + row["sourceId"], "second")] = "exclude"
    client = CyclotronClient(validate_router_config(context.email_fixture.router), sign=lambda *_: {},
                             http=context.email_model.http, sleep=lambda _: None, clock=lambda: 0)
    context.email_routing, context.email_deliveries = route_email(context.email_fixture, cyclotron=client)


@then("only the included publication receives the pending reference handoff")
def shared_email_destinations(context):
    assert context.email_routing["counts"]["delivered"] == 2
    assert {entry[0]["publicationId"] for entry in context.email_deliveries} == {"publication"}
    assert all(row["sectionHandoff"] == "pending-reference-site-sweep" for row in context.email_fixture.table.by_prefix("EMAIL#"))


@then("no email feedback or publication procedure is started")
def shared_email_no_actions(context):
    assert context.email_routing["counts"]["proceduresStarted"] == 0
    assert all(call[2]["operation"] == "decide" for call in context.email_model.posts())
