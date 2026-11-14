"""The tenant a function call acts for, built once from an AppSync resolver event's identity.

A signed-in caller carries one tenant in its token claims (``papyrus_tenant_<role>``, docs/plans/tenant-claims-spike-1.md);
an IAM caller (an operator or another function) names the tenant explicitly. A shared stack refuses any call that
cannot name exactly one tenant; a dedicated stack always acts for its fixed site tenant. The tenant never comes from
the request body and is never guessed. TypeScript twin: amplify/functions/shared/tenant-context.ts; both read
features_backend/fixtures/tenant-context/vectors.json.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

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


def _is_user(identity: Any) -> bool:
    return isinstance(identity, Mapping) and isinstance(identity.get("claims"), Mapping)


def _is_iam(identity: Any) -> bool:
    return isinstance(identity, Mapping) and not _is_user(identity) and ("userArn" in identity or "accountId" in identity)


def _context(identity: Mapping[str, Any] | None, explicit_tenant: str | None, *, iam: bool) -> TenantContext:
    user = not iam and _is_user(identity)
    shared = is_shared_stack()
    mode = "shared" if shared else "dedicated"
    if user and explicit_tenant is not None:
        raise TenantContextRefusal("explicit_tenant_for_user", "A signed-in caller's tenant comes from its claims, never from an argument.")
    if iam and shared and not explicit_tenant:
        raise TenantContextRefusal("iam_without_tenant", "An IAM call on a shared stack must name its tenant.")
    claimed, roles = _claimed(identity["claims"]) if user else (None, ())
    requested = _checked(explicit_tenant) if iam and explicit_tenant else claimed
    if shared:
        if requested is None:
            raise TenantContextRefusal("no_tenant_claim", "The caller's token carries no tenant claim.")
        return TenantContext(requested, roles, mode, iam)
    fixed = tenant_id_from_environment()
    if requested is not None and requested != fixed:
        raise TenantContextRefusal("foreign_tenant", "The call names a tenant other than this stack's fixed tenant.")
    return TenantContext(fixed, roles, mode, iam)


def build_tenant_context(identity: Mapping[str, Any] | None, explicit_tenant: str | None = None) -> TenantContext:
    """Build the context for an AppSync event's ``identity``. ``explicit_tenant`` is for IAM callers only."""
    if not (_is_user(identity) or _is_iam(identity)):
        raise TenantContextRefusal("unsupported_identity", "The call carries neither a user pool identity nor an IAM identity.")
    return _context(identity, explicit_tenant, iam=_is_iam(identity))


def build_invocation_tenant_context(tenant_id: str | None) -> TenantContext:
    """The context of a direct invocation by the platform (a scheduled task, a stream trigger, another function): an IAM-signed call that is not an
    AppSync event. A shared stack requires the payload to name its tenant; a dedicated stack acts for its fixed tenant."""
    return _context(None, tenant_id, iam=True)


def _named_tenant(arguments: Any) -> Any:
    """The tenant an IAM caller names: the ``tenantId`` argument, or for a function whose argument is one JSON ``input``, that input's ``tenantId``."""
    if not isinstance(arguments, Mapping):
        return None
    if "tenantId" in arguments:
        return arguments["tenantId"]
    raw = arguments.get("input")
    try:
        parsed = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    except ValueError:
        return None
    return parsed.get("tenantId") if isinstance(parsed, Mapping) else None


def build_event_tenant_context(event: Mapping[str, Any]) -> TenantContext:
    """The one context of an AppSync field event. A signed-in caller's tenant is its role claim and nothing in the arguments is read for it.
    An IAM caller (the platform operator or a worker) names the tenant in the call's arguments (``_named_tenant``)."""
    identity = event.get("identity")
    explicit = _named_tenant(event.get("arguments")) if _is_iam(identity) else None
    return build_tenant_context(identity, explicit)


_ACTING_FOR: ContextVar[TenantContext | None] = ContextVar("papyrus_acting_for_tenant", default=None)


@contextmanager
def acting_for(context: TenantContext) -> Iterator[TenantContext]:
    """Run one call for ``context``: everything below reads the tenant from ``current_tenant_context()``, never from the environment."""
    token = _ACTING_FOR.set(context)
    try:
        yield context
    finally:
        _ACTING_FOR.reset(token)


def current_tenant_context() -> TenantContext:
    context = _ACTING_FOR.get()
    if context is None:
        raise TenantContextRefusal("unsupported_identity", "No tenant context: a handler builds one from the event before it reads or writes anything.")
    return context
