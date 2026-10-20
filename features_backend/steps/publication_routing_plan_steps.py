"""Offline steps; importing this file does not require a provider or engine."""

from copy import deepcopy

from behave import given, then, when

from papyrus_newsroom.publication_routing_plan import (
    prepare_publication_routing_plan,
    prepare_section_handoff,
)

OWNER = "11111111-1111-4111-8111-111111111111"
CONSUMER = "22222222-2222-4222-8222-222222222222"


@given("a synthetic publication routing plan with separately owned routing stages")
def synthetic_plan(context):
    context.routing_raw = {
        "schemaVersion": 1,
        "status": "inactive",
        "publicationName": "Synthetic",
        "consumer": {
            "accountId": CONSUMER,
            "perspectiveSystem": "synthetic-view",
            "perspectiveId": "view",
            "publicationId": "publication",
            "domain": "news.example.invalid",
        },
        "centralRouter": {
            "serviceId": "service",
            "ownerAccountId": OWNER,
            "instanceId": "central",
            "outputId": "output",
            "grantId": "grant",
            "grantRevision": 1,
            "bindingRevision": "binding-revision",
            "matchLabel": "match",
            "billingAccountId": OWNER,
            "billingPolicy": "owner-pays",
        },
        "internalRouter": {
            "accountId": CONSUMER,
            "instanceId": "internal",
            "publicationId": "publication",
            "sectionTaxonomyRef": "taxonomy-revision",
        },
        "editorialPolicyRef": "policy-revision",
    }
    context.routing_error = None
    context.section_handoff = None


@given("an inactive publication routing plan with unresolved identities and criteria")
def unresolved_plan(context):
    synthetic_plan(context)
    for group in ("consumer", "centralRouter", "internalRouter"):
        context.routing_raw[group] = dict.fromkeys(context.routing_raw[group])
    context.routing_raw["editorialPolicyRef"] = None
    context.routing_original = deepcopy(context.routing_raw)


@given("the internal router uses the central owner's account")
def owner_router(context):
    context.routing_raw["internalRouter"]["accountId"] = OWNER


@given("the internal router reuses the central router identity")
def reused_router(context):
    context.routing_raw["internalRouter"]["instanceId"] = "central"


@when("the publication routing plan is prepared")
def prepare_plan(context):
    try:
        context.routing_plan = prepare_publication_routing_plan(context.routing_raw)
    except ValueError as error:
        context.routing_error = error


@then("publication routing review remains blocked by unresolved fields")
def unresolved_review(context):
    assert not context.routing_plan.ready_for_review
    assert "consumer.accountId" in context.routing_plan.unresolved_fields
    assert "internalRouter.sectionTaxonomyRef" in context.routing_plan.unresolved_fields


@then("preparation does not fill in an account, policy or section taxonomy")
def unchanged_plan(context):
    assert context.routing_raw == context.routing_original
    assert context.routing_plan.consumer.account_id is None
    assert context.routing_plan.editorial_policy_ref is None


@then("preparation rejects the publication routing plan")
def rejected_plan(context):
    assert context.routing_error is not None


@given("the host rejects the central match receipt")
def rejected_receipt(context):
    def verifier(_):
        raise PermissionError("Synthetic invalid receipt")

    context.match_verifier = verifier


@given("the host verifies a scoped synthetic central match")
def verified_receipt(context):
    context.match_verifier = lambda _: {
        "contractVersion": "cyclotron-sharing/v1",
        "receiptId": "receipt",
        "consumerAccountId": CONSUMER,
        "publicationId": "publication",
        "ownerAccountId": OWNER,
        "engineId": "central",
        "bindingRevision": "binding-revision",
        "grantId": "grant",
        "grantRevision": 1,
        "requestId": "request",
        "decisionId": "decision",
        "source": {
            "accountId": OWNER,
            "publicationId": "source-publication",
            "listId": "source-list",
            "id": "source",
            "revision": 1,
            "contentHash": "a" * 64,
        },
        "outputs": {"output": {"label": "match", "confidence": 0.9, "version": 1}},
        "billing": {
            "accountId": OWNER,
            "policy": "owner-pays",
            "reservedRequests": 1,
            "providerRequests": 1,
        },
    }


@given("the host verifies addressed delivery of an existing central match")
def verified_delivery(context):
    verified_receipt(context)
    receipt = context.match_verifier(None)
    receipt["delivery"] = {"id": "delivery", "centralReceiptId": "original-receipt"}
    receipt["billing"]["providerRequests"] = 0
    receipt["billing"]["origin"] = {
        "receiptId": "original-receipt",
        "providerRequests": 4,
    }
    context.match_verifier = lambda _: receipt


@when("a publication section handoff is prepared")
def prepare_handoff(context):
    context.routing_plan = prepare_publication_routing_plan(context.routing_raw)
    try:
        context.section_handoff = prepare_section_handoff(
            context.routing_plan, object(), verify_match=context.match_verifier
        )
    except PermissionError as error:
        context.routing_error = error


@then("no publication section handoff is returned")
def no_handoff(context):
    assert context.section_handoff is None
    assert isinstance(context.routing_error, PermissionError)


@then("the handoff targets only the consumer's internal router")
def consumer_handoff(context):
    assert context.section_handoff.consumer_account_id == CONSUMER
    assert context.section_handoff.internal_router.account_id == CONSUMER
    assert context.section_handoff.internal_router.instance_id == "internal"


@then("the handoff retains its source revision and central prediction")
def retained_provenance(context):
    assert context.section_handoff.source.list_id == "source-list"
    assert context.section_handoff.source.revision == 1
    assert context.section_handoff.central_decision_id == "decision"
    assert context.section_handoff.central_owner_account_id == OWNER


@then("the publication routing plan is still inactive")
def inactive_plan(context):
    assert context.routing_plan.status == "inactive"


@then(
    "the handoff retains original billing attribution without another provider request"
)
def retained_billing(context):
    assert context.section_handoff.delivery_id == "delivery"
    assert context.section_handoff.origin_receipt_id == "original-receipt"
    assert context.section_handoff.origin_provider_requests == 4
    assert context.section_handoff.provider_requests == 0
    assert context.section_handoff.source.account_id == OWNER
