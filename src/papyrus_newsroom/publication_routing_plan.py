"""Prepare inactive two-stage routing artifacts without infrastructure or model calls.

This module is not an authorization service. A host must authenticate the central
receipt and check its current grant before supplying it through ``verify_match``.
The returned handoff is preparation metadata, never an execution capability.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
import math
import re
from typing import Any
from uuid import UUID


class PlanValidationError(ValueError):
    """An incomplete or inconsistent artifact cannot prepare a routing handoff."""


@dataclass(frozen=True)
class PublicationConsumer:
    account_id: str | None
    perspective_system: str | None
    perspective_id: str | None
    publication_id: str | None
    domain: str | None


@dataclass(frozen=True)
class CentralRouter:
    service_id: str | None
    owner_account_id: str | None
    instance_id: str | None
    output_id: str | None
    grant_id: str | None
    grant_revision: int | None
    binding_revision: str | None
    match_label: str | None
    billing_account_id: str | None
    billing_policy: str | None


@dataclass(frozen=True)
class InternalRouter:
    account_id: str | None
    instance_id: str | None
    publication_id: str | None
    section_taxonomy_ref: str | None


@dataclass(frozen=True)
class PreparedPublicationRoutingPlan:
    publication_name: str
    consumer: PublicationConsumer
    central_router: CentralRouter
    internal_router: InternalRouter
    editorial_policy_ref: str | None
    unresolved_fields: tuple[str, ...]
    status: str = "inactive"

    @property
    def ready_for_review(self) -> bool:
        """All artifact fields are supplied; this grants no operational authority."""
        return not self.unresolved_fields


@dataclass(frozen=True)
class SourceProvenance:
    account_id: str
    publication_id: str | None
    list_id: str
    source_id: str
    revision: int
    content_hash: str


@dataclass(frozen=True)
class SectionHandoff:
    """Immutable preparation for the consumer's internal section classification."""

    consumer_account_id: str
    publication_id: str
    central_service_id: str
    central_owner_account_id: str
    central_instance_id: str
    central_binding_revision: str
    central_output_id: str
    central_output_version: int
    central_match_label: str
    central_confidence: float | None
    central_decision_id: str
    central_request_id: str
    central_receipt_id: str
    grant_id: str
    grant_revision: int
    source: SourceProvenance
    internal_router: InternalRouter
    editorial_policy_ref: str
    billing_account_id: str
    billing_policy: str
    reserved_requests: int
    provider_requests: int
    delivery_id: str | None
    origin_receipt_id: str | None
    origin_provider_requests: int | None
    status: str = "prepared"


def _object(value: Any, keys: set[str], path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise PlanValidationError(f"{path} must contain exactly the documented fields")
    return value


def _text(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 200
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise PlanValidationError(f"{path} must be a nonempty bounded string")
    return value


def _account(value: Any, path: str) -> str:
    value = _text(value, path)
    try:
        valid = str(UUID(value)) == value
    except ValueError:
        valid = False
    if not valid:
        raise PlanValidationError(f"{path} must be a canonical SaaS account UUID")
    return value


def _positive_integer(value: Any, path: str) -> int:
    if type(value) is not int or value < 1:
        raise PlanValidationError(f"{path} must be a positive integer")
    return value


def _domain(value: Any, path: str) -> str:
    value = _text(value, path)
    if not re.fullmatch(
        r"(?=.{1,200}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
        value,
    ):
        raise PlanValidationError(f"{path} must be a lowercase DNS name")
    return value


def prepare_publication_routing_plan(
    raw: Mapping[str, Any],
) -> PreparedPublicationRoutingPlan:
    """Validate supplied facts, retaining nulls and reporting every unresolved field.

    The artifact deliberately has no active mode, credentials, policy bodies,
    labels, feedback, infrastructure target or executable grant configuration.
    """
    raw = _object(
        raw,
        {
            "schemaVersion",
            "status",
            "publicationName",
            "consumer",
            "centralRouter",
            "internalRouter",
            "editorialPolicyRef",
        },
        "plan",
    )
    if type(raw["schemaVersion"]) is not int or raw["schemaVersion"] != 1:
        raise PlanValidationError("plan.schemaVersion must be 1")
    if raw["status"] != "inactive":
        raise PlanValidationError("plan.status must remain inactive")
    consumer = _object(
        raw["consumer"],
        {
            "accountId",
            "perspectiveSystem",
            "perspectiveId",
            "publicationId",
            "domain",
        },
        "consumer",
    )
    central = _object(
        raw["centralRouter"],
        {
            "serviceId",
            "ownerAccountId",
            "instanceId",
            "outputId",
            "grantId",
            "grantRevision",
            "bindingRevision",
            "matchLabel",
            "billingAccountId",
            "billingPolicy",
        },
        "centralRouter",
    )
    internal = _object(
        raw["internalRouter"],
        {
            "accountId",
            "instanceId",
            "publicationId",
            "sectionTaxonomyRef",
        },
        "internalRouter",
    )
    unresolved: list[str] = []

    def field(group, key, prefix, validator=_text):
        path = f"{prefix}.{key}" if prefix else key
        value = group[key]
        if value is None:
            unresolved.append(path)
            return None
        return validator(value, path)

    target = PublicationConsumer(
        field(consumer, "accountId", "consumer", _account),
        field(consumer, "perspectiveSystem", "consumer"),
        field(consumer, "perspectiveId", "consumer"),
        field(consumer, "publicationId", "consumer"),
        field(consumer, "domain", "consumer", _domain),
    )
    shared = CentralRouter(
        field(central, "serviceId", "centralRouter"),
        field(central, "ownerAccountId", "centralRouter", _account),
        field(central, "instanceId", "centralRouter"),
        field(central, "outputId", "centralRouter"),
        field(central, "grantId", "centralRouter"),
        field(central, "grantRevision", "centralRouter", _positive_integer),
        field(central, "bindingRevision", "centralRouter"),
        field(central, "matchLabel", "centralRouter"),
        field(central, "billingAccountId", "centralRouter", _account),
        field(central, "billingPolicy", "centralRouter"),
    )
    sections = InternalRouter(
        field(internal, "accountId", "internalRouter", _account),
        field(internal, "instanceId", "internalRouter"),
        field(internal, "publicationId", "internalRouter"),
        field(internal, "sectionTaxonomyRef", "internalRouter"),
    )
    for actual, expected, path in (
        (sections.account_id, target.account_id, "internalRouter.accountId"),
        (
            sections.publication_id,
            target.publication_id,
            "internalRouter.publicationId",
        ),
        (
            shared.billing_account_id,
            shared.owner_account_id,
            "centralRouter.billingAccountId",
        ),
    ):
        if actual is not None and expected is not None and actual != expected:
            raise PlanValidationError(f"{path} does not match its owning identity")
    if (
        shared.instance_id is not None
        and sections.instance_id is not None
        and shared.instance_id == sections.instance_id
    ):
        raise PlanValidationError(
            "internalRouter.instanceId must differ from the central router"
        )
    if shared.billing_policy is not None and shared.billing_policy != "owner-pays":
        raise PlanValidationError("centralRouter.billingPolicy must be owner-pays")
    if target.account_id is not None and target.account_id == shared.owner_account_id:
        raise PlanValidationError(
            "consumer.accountId must differ from the central owner"
        )
    policy = field(raw, "editorialPolicyRef", "")
    return PreparedPublicationRoutingPlan(
        _text(raw["publicationName"], "publicationName"),
        target,
        shared,
        sections,
        policy,
        tuple(unresolved),
    )


def _plan_document(plan: PreparedPublicationRoutingPlan) -> dict[str, Any]:
    """Reconstruct facts so callers cannot bypass validation with replaced dataclasses."""
    if not isinstance(plan, PreparedPublicationRoutingPlan):
        raise PlanValidationError("plan must be a prepared publication routing plan")

    def fields(value, expected_type):
        if not isinstance(value, expected_type):
            raise PlanValidationError("plan contains an invalid routing identity")
        return {
            key.split("_")[0]
            + "".join(part.title() for part in key.split("_")[1:]): value
            for key, value in asdict(value).items()
        }

    return {
        "schemaVersion": 1,
        "status": plan.status,
        "publicationName": plan.publication_name,
        "consumer": fields(plan.consumer, PublicationConsumer),
        "centralRouter": fields(plan.central_router, CentralRouter),
        "internalRouter": fields(plan.internal_router, InternalRouter),
        "editorialPolicyRef": plan.editorial_policy_ref,
    }


def prepare_section_handoff(
    plan: PreparedPublicationRoutingPlan,
    envelope: object,
    *,
    verify_match: Callable[[object], Mapping[str, Any]],
) -> SectionHandoff:
    """Validate a host-authenticated central match and prepare its next stage.

    ``verify_match`` is required and has no default. It must reject untrusted
    transport/issuer/audience, expired receipts and revoked/stale grants; confirm
    consumer entitlement, current source/output scope and budget; and return only
    the verified ``cyclotron-sharing/v1`` receipt. This function checks structural
    bindings, not cryptographic authenticity or current authorization. A host must
    authorize again immediately before any effect; a prepared handoff is no lease.
    Bind the verifier to ``plan.central_router.service_id``: that identity is not
    asserted by the sharing receipt and must come from authenticated transport.
    """
    plan = prepare_publication_routing_plan(_plan_document(plan))
    if not plan.ready_for_review:
        raise PlanValidationError("plan has unresolved fields")
    candidate = verify_match(envelope)
    is_delivery = isinstance(candidate, Mapping) and "delivery" in candidate
    receipt_keys = {
        "contractVersion",
        "receiptId",
        "grantId",
        "grantRevision",
        "ownerAccountId",
        "consumerAccountId",
        "publicationId",
        "engineId",
        "bindingRevision",
        "requestId",
        "decisionId",
        "source",
        "outputs",
        "billing",
    }
    receipt = _object(
        candidate, receipt_keys | ({"delivery"} if is_delivery else set()), "receipt"
    )
    if receipt["contractVersion"] != "cyclotron-sharing/v1":
        raise PlanValidationError("receipt.contractVersion is unsupported")
    central = plan.central_router
    for key, expected in (
        ("grantId", central.grant_id),
        ("grantRevision", central.grant_revision),
        ("ownerAccountId", central.owner_account_id),
        ("consumerAccountId", plan.consumer.account_id),
        ("publicationId", plan.consumer.publication_id),
        ("engineId", central.instance_id),
        ("bindingRevision", central.binding_revision),
    ):
        if type(receipt[key]) is not type(expected) or receipt[key] != expected:
            raise PlanValidationError(f"receipt.{key} does not match the prepared plan")
    source = _object(
        receipt["source"],
        {
            "accountId",
            "publicationId",
            "listId",
            "id",
            "revision",
            "contentHash",
        },
        "receipt.source",
    )
    content_hash = _text(source["contentHash"], "receipt.source.contentHash")
    if not re.fullmatch("[0-9a-f]{64}", content_hash):
        raise PlanValidationError(
            "receipt.source.contentHash must be a SHA-256 hex digest"
        )
    provenance = SourceProvenance(
        _account(source["accountId"], "receipt.source.accountId"),
        (
            _text(source["publicationId"], "receipt.source.publicationId")
            if source["publicationId"] is not None
            else None
        ),
        _text(source["listId"], "receipt.source.listId"),
        _text(source["id"], "receipt.source.id"),
        _positive_integer(source["revision"], "receipt.source.revision"),
        content_hash,
    )
    outputs = _object(receipt["outputs"], {central.output_id}, "receipt.outputs")
    output = _object(
        outputs[central.output_id],
        {
            "label",
            "confidence",
            "version",
        },
        "receipt.outputs.match",
    )
    if output["label"] != central.match_label:
        raise PlanValidationError(
            "receipt output is not the configured publication match"
        )
    confidence = output["confidence"]
    if confidence is not None and (
        type(confidence) not in (int, float)
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise PlanValidationError("receipt output confidence must be between 0 and 1")
    billing_keys = {"accountId", "policy", "reservedRequests", "providerRequests"}
    billing = _object(
        receipt["billing"],
        billing_keys | ({"origin"} if is_delivery else set()),
        "receipt.billing",
    )
    if (
        billing["accountId"] != central.billing_account_id
        or billing["policy"] != central.billing_policy
    ):
        raise PlanValidationError("receipt.billing does not match the prepared plan")
    if type(billing["reservedRequests"]) is not int or billing["reservedRequests"] != 1:
        raise PlanValidationError("receipt.billing.reservedRequests must be 1")
    if type(billing["providerRequests"]) is not int or billing["providerRequests"] < 0:
        raise PlanValidationError(
            "receipt.billing.providerRequests must be nonnegative"
        )
    delivery_id = origin_receipt_id = origin_provider_requests = None
    if is_delivery:
        delivery = _object(
            receipt["delivery"], {"id", "centralReceiptId"}, "receipt.delivery"
        )
        origin = _object(
            billing["origin"],
            {"receiptId", "providerRequests"},
            "receipt.billing.origin",
        )
        delivery_id = _text(delivery["id"], "receipt.delivery.id")
        origin_receipt_id = _text(
            delivery["centralReceiptId"], "receipt.delivery.centralReceiptId"
        )
        if origin["receiptId"] != origin_receipt_id:
            raise PlanValidationError("receipt delivery and billing origin must agree")
        origin_provider_requests = origin["providerRequests"]
        if type(origin_provider_requests) is not int or origin_provider_requests < 0:
            raise PlanValidationError(
                "receipt.billing.origin.providerRequests must be nonnegative"
            )
        if billing["providerRequests"] != 0:
            raise PlanValidationError(
                "receipt delivery must not repeat provider charges"
            )
    return SectionHandoff(
        plan.consumer.account_id,
        plan.consumer.publication_id,
        central.service_id,
        central.owner_account_id,
        central.instance_id,
        central.binding_revision,
        central.output_id,
        _positive_integer(output["version"], "receipt.outputs.match.version"),
        central.match_label,
        float(confidence) if confidence is not None else None,
        _text(receipt["decisionId"], "receipt.decisionId"),
        _text(receipt["requestId"], "receipt.requestId"),
        _text(receipt["receiptId"], "receipt.receiptId"),
        central.grant_id,
        central.grant_revision,
        provenance,
        plan.internal_router,
        plan.editorial_policy_ref,
        central.billing_account_id,
        central.billing_policy,
        billing["reservedRequests"],
        billing["providerRequests"],
        delivery_id,
        origin_receipt_id,
        origin_provider_requests,
    )
