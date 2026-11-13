"""The tenant a function call acts for, built once from an AppSync resolver event's identity.

A signed-in caller carries one tenant in its token claims (``papyrus_tenant_<role>``, docs/plans/tenant-claims-spike-1.md);
an IAM caller (an operator or another function) names the tenant explicitly. A shared stack refuses any call that
cannot name exactly one tenant; a dedicated stack always acts for its fixed site tenant. The tenant never comes from
the request body and is never guessed. TypeScript twin: amplify/functions/shared/tenant-context.ts; both read
features_backend/fixtures/tenant-context/vectors.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .tenancy import TenantError, is_shared_stack, tenant_id_from_environment, validate_tenant_id

#: Claim name per role, in the order roles are reported.
ROLE_CLAIMS = (
    ("admin", "papyrus_tenant_admin"),
    ("editor", "papyrus_tenant_editor"),
    ("curator", "papyrus_tenant_curator"),
    ("member", "papyrus_tenant_member"),
)


class TenantContextRefusal(TenantError):
    """A call that cannot be given one tenant. ``reason`` is one of the codes below."""

    REASONS = (
        "unsupported_identity",
        "iam_without_tenant",
        "no_tenant_claim",
        "multiple_tenants",
        "foreign_tenant",
        "invalid_tenant",
        "explicit_tenant_for_user",
    )

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str | None
    roles: tuple[str, ...]
    mode: str
    operator: bool


def _checked(tenant_id: Any) -> str:
    if not isinstance(tenant_id, str):
        raise TenantContextRefusal("invalid_tenant", "A tenant id must be a string.")
    try:
        return validate_tenant_id(tenant_id)
    except TenantError as error:
        raise TenantContextRefusal("invalid_tenant", str(error)) from error


def _claimed(claims: Mapping[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    named = {role: claims[claim] for role, claim in ROLE_CLAIMS if claims.get(claim) not in (None, "")}
    tenants = {_checked(value) for value in named.values()}
    if len(tenants) > 1:
        raise TenantContextRefusal("multiple_tenants", "The claims name more than one tenant; a session acts for one tenant at a time.")
    tenant = next(iter(tenants), None)
    return tenant, tuple(role for role, _ in ROLE_CLAIMS if role in named)


def build_tenant_context(identity: Mapping[str, Any] | None, explicit_tenant: str | None = None) -> TenantContext:
    """Build the context for an AppSync event's ``identity``. ``explicit_tenant`` is for IAM callers only."""
    is_user = isinstance(identity, Mapping) and isinstance(identity.get("claims"), Mapping)
    is_iam = isinstance(identity, Mapping) and not is_user and ("userArn" in identity or "accountId" in identity)
    if not (is_user or is_iam):
        raise TenantContextRefusal("unsupported_identity", "The call carries neither a user pool identity nor an IAM identity.")
    shared = is_shared_stack()
    mode = "shared" if shared else "dedicated"
    if is_user and explicit_tenant is not None:
        raise TenantContextRefusal("explicit_tenant_for_user", "A signed-in caller's tenant comes from its claims, never from an argument.")
    if is_iam and shared and not explicit_tenant:
        raise TenantContextRefusal("iam_without_tenant", "An IAM call on a shared stack must name its tenant.")
    claimed, roles = _claimed(identity["claims"]) if is_user else (None, ())
    requested = _checked(explicit_tenant) if is_iam and explicit_tenant else claimed
    if shared:
        if requested is None:
            raise TenantContextRefusal("no_tenant_claim", "The caller's token carries no tenant claim.")
        return TenantContext(requested, roles, mode, is_iam)
    fixed = tenant_id_from_environment()
    if requested is not None and requested != fixed:
        raise TenantContextRefusal("foreign_tenant", "The call names a tenant other than this stack's fixed tenant.")
    return TenantContext(fixed, roles, mode, is_iam)
