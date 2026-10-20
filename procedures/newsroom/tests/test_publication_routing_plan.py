"""Offline contracts for preparing a publication with two routing stages."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path

import pytest

from papyrus_newsroom.publication_routing_plan import (
    PlanValidationError,
    prepare_publication_routing_plan,
    prepare_section_handoff,
)

OWNER = "11111111-1111-4111-8111-111111111111"
CONSUMER = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
ROOT = Path(__file__).resolve().parents[3]


def complete_plan():
    """Every value is synthetic; no production tenant, policy or taxonomy."""
    return {
        "schemaVersion": 1,
        "status": "inactive",
        "publicationName": "Synthetic publication",
        "consumer": {
            "accountId": CONSUMER,
            "perspectiveSystem": "synthetic-editorial-view",
            "perspectiveId": "synthetic-view",
            "publicationId": "synthetic-publication",
            "domain": "news.example.invalid",
        },
        "centralRouter": {
            "serviceId": "synthetic-central-service",
            "ownerAccountId": OWNER,
            "instanceId": "synthetic-central-instance",
            "outputId": "synthetic-publication-output",
            "grantId": "synthetic-grant",
            "grantRevision": 1,
            "bindingRevision": "synthetic-binding-revision",
            "matchLabel": "synthetic-match",
            "billingAccountId": OWNER,
            "billingPolicy": "owner-pays",
        },
        "internalRouter": {
            "accountId": CONSUMER,
            "instanceId": "synthetic-internal-instance",
            "publicationId": "synthetic-publication",
            "sectionTaxonomyRef": "synthetic-taxonomy-revision",
        },
        "editorialPolicyRef": "synthetic-editorial-policy-revision",
    }


def verified_receipt():
    """Shape returned by a host verifier, never by an untrusted client."""
    return {
        "contractVersion": "cyclotron-sharing/v1",
        "receiptId": "synthetic-receipt",
        "consumerAccountId": CONSUMER,
        "publicationId": "synthetic-publication",
        "ownerAccountId": OWNER,
        "engineId": "synthetic-central-instance",
        "bindingRevision": "synthetic-binding-revision",
        "grantId": "synthetic-grant",
        "grantRevision": 1,
        "requestId": "synthetic-request",
        "decisionId": "synthetic-central-decision",
        "source": {
            "accountId": OWNER,
            "publicationId": "synthetic-source-publication",
            "listId": "synthetic-source-list",
            "id": "synthetic-source",
            "revision": 1,
            "contentHash": "a" * 64,
        },
        "outputs": {
            "synthetic-publication-output": {
                "label": "synthetic-match",
                "confidence": 0.9,
                "version": 1,
            }
        },
        "billing": {
            "accountId": OWNER,
            "policy": "owner-pays",
            "reservedRequests": 1,
            "providerRequests": 1,
        },
    }


def verified_delivery():
    receipt = verified_receipt()
    receipt["delivery"] = {
        "id": "synthetic-delivery",
        "centralReceiptId": "original-receipt",
    }
    receipt["billing"]["providerRequests"] = 0
    receipt["billing"]["origin"] = {
        "receiptId": "original-receipt",
        "providerRequests": 4,
    }
    return receipt


def test_unknown_fields_remain_null_and_block_readiness():
    raw = complete_plan()
    for group in ("consumer", "centralRouter", "internalRouter"):
        raw[group] = dict.fromkeys(raw[group])
    raw["editorialPolicyRef"] = None
    untouched = deepcopy(raw)
    plan = prepare_publication_routing_plan(raw)
    assert raw == untouched
    assert not plan.ready_for_review
    assert "consumer.accountId" in plan.unresolved_fields
    assert "consumer.perspectiveSystem" in plan.unresolved_fields
    assert "centralRouter.grantId" in plan.unresolved_fields
    assert "internalRouter.sectionTaxonomyRef" in plan.unresolved_fields
    assert plan.consumer.account_id is None
    assert plan.internal_router.instance_id is None


def test_dataparade_example_is_inactive_and_does_not_invent_identity_or_policy():
    raw = json.loads(
        (ROOT / "docs/examples/dataparade-publication-plan.json").read_text()
    )
    assert raw["publicationName"] == "Data Parade"
    assert raw["status"] == "inactive"
    assert raw["editorialPolicyRef"] is None
    for group in ("consumer", "centralRouter", "internalRouter"):
        assert all(value is None for value in raw[group].values())
    assert not prepare_publication_routing_plan(raw).ready_for_review


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("status",), "active"),
        (("consumer", "accountId"), "688128002352"),
        (("consumer", "perspectiveId"), ""),
        (("consumer", "domain"), "https://news.example.invalid"),
        (("consumer", "domain"), "news.example.invalid/path"),
        (("centralRouter", "grantRevision"), True),
        (("centralRouter", "grantRevision"), 0),
        (("centralRouter", "billingAccountId"), CONSUMER),
        (("centralRouter", "billingPolicy"), "consumer-pays"),
        (("internalRouter", "accountId"), OWNER),
        (("internalRouter", "publicationId"), "other-publication"),
        (("internalRouter", "instanceId"), "synthetic-central-instance"),
    ],
)
def test_invalid_or_unsafe_bindings_are_rejected(path, value):
    raw = complete_plan()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(PlanValidationError):
        prepare_publication_routing_plan(raw)


@pytest.mark.parametrize(
    "field", ["apiKey", "policyBody", "labels", "feedback", "trusted"]
)
def test_extra_configuration_is_not_accepted(field):
    raw = complete_plan()
    raw["centralRouter"][field] = "synthetic-private-value"
    with pytest.raises(PlanValidationError) as failure:
        prepare_publication_routing_plan(raw)
    assert "synthetic-private-value" not in str(failure.value)


def test_fully_specified_artifact_is_immutable_and_still_inactive():
    raw = complete_plan()
    plan = prepare_publication_routing_plan(raw)
    raw["consumer"]["accountId"] = OTHER
    assert plan.ready_for_review
    assert plan.status == "inactive"
    assert plan.consumer.account_id == CONSUMER
    with pytest.raises(FrozenInstanceError):
        plan.consumer.account_id = OTHER


def test_consumer_cannot_silently_reuse_the_central_owners_account():
    raw = complete_plan()
    raw["consumer"]["accountId"] = OWNER
    raw["internalRouter"]["accountId"] = OWNER
    with pytest.raises(PlanValidationError, match="differ"):
        prepare_publication_routing_plan(raw)


@pytest.mark.parametrize(
    "change",
    [
        lambda plan: replace(
            plan, internal_router=replace(plan.internal_router, account_id=OWNER)
        ),
        lambda plan: replace(
            plan,
            internal_router=replace(
                plan.internal_router, instance_id="synthetic-central-instance"
            ),
        ),
        lambda plan: replace(
            plan,
            internal_router=replace(
                plan.internal_router, publication_id="other-publication"
            ),
        ),
        lambda plan: replace(plan, status="active"),
        lambda plan: replace(
            plan,
            central_router=replace(plan.central_router, grant_id=None),
            unresolved_fields=(),
        ),
    ],
)
def test_reconstructed_dataclasses_cannot_bypass_handoff_plan_validation(change):
    plan = change(prepare_publication_routing_plan(complete_plan()))
    calls = []
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(plan, object(), verify_match=calls.append)
    assert not calls


def test_pending_plan_does_not_reach_receipt_verifier():
    raw = complete_plan()
    raw["centralRouter"]["grantId"] = None
    calls = []
    with pytest.raises(PlanValidationError, match="unresolved"):
        prepare_section_handoff(
            prepare_publication_routing_plan(raw), object(), verify_match=calls.append
        )
    assert not calls


def test_a_json_trust_flag_does_not_replace_host_verification():
    plan = prepare_publication_routing_plan(complete_plan())
    envelope = {"trusted": True, **verified_receipt()}
    with pytest.raises(TypeError):
        prepare_section_handoff(plan, envelope)

    def reject_unsigned(_):
        raise PermissionError("unsigned receipt")

    with pytest.raises(PermissionError, match="unsigned"):
        prepare_section_handoff(plan, envelope, verify_match=reject_unsigned)
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(plan, envelope, verify_match=lambda _: True)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("consumerAccountId", OTHER),
        ("publicationId", "other-publication"),
        ("ownerAccountId", OTHER),
        ("engineId", "other-instance"),
        ("bindingRevision", "other-binding"),
        ("grantId", "other-grant"),
        ("grantRevision", 2),
        ("decisionId", ""),
    ],
)
def test_verified_receipt_must_match_every_scope_and_provenance_binding(field, value):
    receipt = verified_receipt()
    receipt[field] = value
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(
            prepare_publication_routing_plan(complete_plan()),
            object(),
            verify_match=lambda _: receipt,
        )


@pytest.mark.parametrize("field", ["policyBody", "labels", "feedback", "allOutputs"])
def test_receipt_rejects_unscoped_private_payloads(field):
    receipt = verified_receipt()
    receipt[field] = {"private": "synthetic"}
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(
            prepare_publication_routing_plan(complete_plan()),
            object(),
            verify_match=lambda _: receipt,
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda receipt: receipt["outputs"].update({"another-output": {}}),
        lambda receipt: receipt["outputs"].clear(),
        lambda receipt: receipt["outputs"]["synthetic-publication-output"].update(
            label="synthetic-no-match"
        ),
        lambda receipt: receipt["outputs"]["synthetic-publication-output"].update(
            confidence=float("nan")
        ),
        lambda receipt: receipt["outputs"]["synthetic-publication-output"].update(
            version=""
        ),
        lambda receipt: receipt["outputs"]["synthetic-publication-output"].update(
            version=True
        ),
        lambda receipt: receipt["outputs"]["synthetic-publication-output"].update(
            version=0
        ),
        lambda receipt: receipt["billing"].update(accountId=CONSUMER),
        lambda receipt: receipt["billing"].update(policy="consumer-pays"),
        lambda receipt: receipt["billing"].update(providerRequests=True),
        lambda receipt: receipt["billing"].update(providerRequests=-1),
        lambda receipt: receipt["source"].update(contentHash="not-a-sha256"),
    ],
)
def test_handoff_requires_one_match_and_complete_billing_and_source_provenance(change):
    receipt = verified_receipt()
    change(receipt)
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(
            prepare_publication_routing_plan(complete_plan()),
            object(),
            verify_match=lambda _: receipt,
        )


@pytest.mark.parametrize(
    "field", ["accountId", "publicationId", "listId", "id", "revision", "contentHash"]
)
def test_source_provenance_cannot_be_omitted(field):
    receipt = verified_receipt()
    receipt["source"].pop(field)
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(
            prepare_publication_routing_plan(complete_plan()),
            object(),
            verify_match=lambda _: receipt,
        )


def test_only_a_verified_match_prepares_consumer_owned_section_routing():
    plan = prepare_publication_routing_plan(complete_plan())
    receipt = verified_receipt()
    envelope = object()
    calls = []

    def verify(candidate):
        assert candidate is envelope
        calls.append(candidate)
        return receipt

    handoff = prepare_section_handoff(plan, envelope, verify_match=verify)
    receipt["source"]["id"] = "mutated-after-verification"
    assert calls == [envelope]
    assert handoff.consumer_account_id == CONSUMER
    assert handoff.publication_id == "synthetic-publication"
    assert handoff.central_owner_account_id == OWNER
    assert handoff.central_decision_id == "synthetic-central-decision"
    assert handoff.source.account_id == OWNER
    assert handoff.source.source_id == "synthetic-source"
    assert handoff.source.list_id == "synthetic-source-list"
    assert handoff.source.revision == 1
    assert handoff.source.content_hash == "a" * 64
    assert handoff.internal_router == plan.internal_router
    assert handoff.internal_router.account_id == CONSUMER
    assert handoff.internal_router.instance_id != handoff.central_instance_id
    assert handoff.editorial_policy_ref == plan.editorial_policy_ref
    assert handoff.central_match_label == "synthetic-match"
    assert handoff.central_confidence == 0.9
    assert handoff.status == "prepared"


@pytest.mark.parametrize("requests", [0, 1, 4])
def test_actual_provider_usage_is_preserved_without_reclassifying(requests):
    receipt = verified_receipt()
    receipt["billing"]["providerRequests"] = requests
    handoff = prepare_section_handoff(
        prepare_publication_routing_plan(complete_plan()),
        object(),
        verify_match=lambda _: receipt,
    )
    assert handoff.provider_requests == requests
    assert handoff.reserved_requests == 1


def test_missing_confidence_does_not_invent_an_editorial_threshold():
    receipt = verified_receipt()
    receipt["outputs"]["synthetic-publication-output"]["confidence"] = None
    handoff = prepare_section_handoff(
        prepare_publication_routing_plan(complete_plan()),
        object(),
        verify_match=lambda _: receipt,
    )
    assert handoff.central_confidence is None
    assert handoff.central_match_label == "synthetic-match"


def test_existing_central_decision_delivery_retains_origin_without_reclassification():
    receipt = verified_delivery()
    handoff = prepare_section_handoff(
        prepare_publication_routing_plan(complete_plan()),
        object(),
        verify_match=lambda _: receipt,
    )
    assert handoff.source.account_id == OWNER
    assert handoff.source.publication_id == "synthetic-source-publication"
    assert handoff.source.source_id == "synthetic-source"
    assert handoff.source.list_id == "synthetic-source-list"
    assert handoff.source.revision == 1
    assert handoff.central_decision_id == "synthetic-central-decision"
    assert handoff.delivery_id == "synthetic-delivery"
    assert handoff.origin_receipt_id == "original-receipt"
    assert handoff.origin_provider_requests == 4
    assert handoff.provider_requests == 0
    assert handoff.internal_router.account_id == CONSUMER


def test_shared_pool_source_does_not_invent_an_originating_publication():
    receipt = verified_delivery()
    receipt["source"]["publicationId"] = None
    handoff = prepare_section_handoff(
        prepare_publication_routing_plan(complete_plan()),
        object(),
        verify_match=lambda _: receipt,
    )
    assert handoff.source.publication_id is None
    assert handoff.source.account_id == OWNER
    assert handoff.source.source_id == "synthetic-source"
    assert handoff.source.list_id == "synthetic-source-list"
    assert handoff.source.revision == 1
    assert handoff.source.content_hash == "a" * 64
    assert handoff.publication_id == "synthetic-publication"


def test_source_lists_distinguish_identically_named_owner_pool_items():
    plan = prepare_publication_routing_plan(complete_plan())
    first = verified_delivery()
    second = deepcopy(first)
    second["source"]["listId"] = "another-source-list"
    first_handoff = prepare_section_handoff(
        plan, object(), verify_match=lambda _: first
    )
    second_handoff = prepare_section_handoff(
        plan, object(), verify_match=lambda _: second
    )
    assert first_handoff.source != second_handoff.source
    assert first_handoff.source.list_id == "synthetic-source-list"
    assert second_handoff.source.list_id == "another-source-list"
    assert first_handoff.source.source_id == second_handoff.source.source_id
    assert first_handoff.source.revision == second_handoff.source.revision == 1


@pytest.mark.parametrize("revision", [True, "1", 0, -1, None])
def test_source_revision_keeps_native_positive_integer_semantics(revision):
    receipt = verified_delivery()
    receipt["source"]["revision"] = revision
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(
            prepare_publication_routing_plan(complete_plan()),
            object(),
            verify_match=lambda _: receipt,
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda receipt: receipt["delivery"].update(centralReceiptId="wrong-origin"),
        lambda receipt: receipt["delivery"].update(id=""),
        lambda receipt: receipt["billing"].update(providerRequests=1),
        lambda receipt: receipt["billing"]["origin"].update(providerRequests=True),
        lambda receipt: receipt["billing"]["origin"].update(providerRequests=-1),
    ],
)
def test_delivery_rejects_changed_origin_or_repeated_provider_charges(change):
    receipt = verified_delivery()
    change(receipt)
    with pytest.raises(PlanValidationError):
        prepare_section_handoff(
            prepare_publication_routing_plan(complete_plan()),
            object(),
            verify_match=lambda _: receipt,
        )
