from copy import deepcopy

from behave import given, when, then

from procedures.newsroom.tests.email_submission_fixture import email_fixture, collect_email, route_email


@given("an isolated publication email destination and an authenticated newsletter")
def email_destination(context):
    context.email_fixture = email_fixture()


@given("the trusted SES receipt fails DMARC authentication")
def email_authentication_failure(context):
    context.email_fixture.event["Records"][0]["ses"]["receipt"]["dmarcVerdict"]["status"] = "FAIL"


@given("another publication is present in the SES envelope recipients")
def email_mixed_destinations(context):
    context.email_fixture.event["Records"][0]["ses"]["mail"]["destination"].append("submissions@other.example")


@when("the email collector receives the same SES delivery twice")
def email_repeated(context):
    context.email_results = [collect_email(context.email_fixture) for _ in range(2)]


@when("the email collector receives the SES delivery")
def email_once(context):
    context.email_results = [collect_email(context.email_fixture)]


@then("each newsletter source has one queued discovery with private email provenance")
def email_discoveries(context):
    rows = context.email_fixture.table.by_prefix("DISC#")
    assert len(rows) == 2
    assert all(row["routing"] == "collected" and row["emailProvenance"]["sesMessageId"] == "ses-delivery-1" for row in rows)
    assert context.email_results[1]["status"] == "duplicate"


@then("the email collector has not fetched sources or called an agent")
def email_only_mime(context):
    assert context.email_fixture.s3.calls == [("mail-fixture", "email-submissions/ses-delivery-1")]


@then("the email is rejected before reading the MIME object")
def email_rejected(context):
    assert context.email_results[0]["status"] == "rejected"
    assert context.email_fixture.s3.calls == []
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
    from procedures.newsroom.tests.test_email_submission_intake import AccountCyclotron, shared_fixture

    context.email_fixture = shared_fixture()
    context.email_model = AccountCyclotron()


@when("the shared Cyclotron includes the first publication and excludes the second")
def shared_email_route(context):
    from papyrus_content.monitoring_router import CyclotronClient, validate_router_config

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
