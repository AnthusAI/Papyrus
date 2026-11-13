"""Keys and rules for the tenancy records: Tenant, TenantMembership and TenantDomain (PPY-31c45c).

The three models live in the optional ``tenancy`` model group. Nothing reads or writes them yet; provisioning, the token Lambda
and the edge host table will. The key shapes and the two lookups they must support are fixed here so those callers share one
definition:

* a tenant's id is its site id (``validate_tenant_id``);
* a membership id is ``<tenant>#<userSub>``, and the token Lambda finds a person's memberships with ONE query on the ``userSub``
  index (``list_memberships_for_user``), never a scan;
* a tenant selection (the site a person's session acts for, read by the token Lambda) has the person's sub as its id;
* a domain id is the lowercase hostname, so a hostname can belong to one tenant only (``claim_domain``).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Mapping

from .tenancy import TENANT_KEY_SEPARATOR, TenantError, validate_tenant_id

TENANT_STATES = ("active", "past_due", "suspended", "deleted_pending", "deleted")
MEMBERSHIP_ROLES = ("admin", "editor", "curator", "member")
DOMAIN_KINDS = ("subdomain", "custom")
DOMAIN_STATUSES = ("pending_dns", "pending_certificate", "active", "failed", "removed")

#: Index query fields, as declared in amplify/data/schema.ts and resource.ts.
MEMBERSHIPS_BY_USER_SUB_QUERY = "listTenantMembershipsByUserSub"
MEMBERSHIPS_BY_TENANT_QUERY = "listTenantMembershipsByTenant"
DOMAINS_BY_TENANT_QUERY = "listTenantDomainsByTenant"
TENANTS_BY_ACCOUNT_QUERY = "listTenantsByAccount"
TENANTS_BY_STATE_QUERY = "listTenantsByStateKey"

_HOSTNAME_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


class TenantRecordError(TenantError):
    pass


class DomainAlreadyClaimed(TenantRecordError):
    """The hostname already belongs to a tenant (this one or another)."""


def _choice(value: str, allowed: tuple[str, ...], what: str) -> str:
    if value not in allowed:
        raise TenantRecordError(f"{what} {value!r} must be one of: {', '.join(allowed)}.")
    return value


def tenant_state_key(state: str) -> str:
    """``state#<state>``: the partition of the operator's list of tenants in one state."""
    return f"state{TENANT_KEY_SEPARATOR}{_choice(state, TENANT_STATES, 'Tenant state')}"


def membership_id(tenant_id: str, user_sub: str) -> str:
    sub = (user_sub or "").strip()
    if not sub or TENANT_KEY_SEPARATOR in sub:
        raise TenantRecordError("A membership needs a user sub without '#'.")
    return f"{validate_tenant_id(tenant_id)}{TENANT_KEY_SEPARATOR}{sub}"


def domain_id(hostname: str) -> str:
    """The lowercase hostname, which is the TenantDomain id."""
    host = (hostname or "").strip().lower().rstrip(".")
    labels = host.split(".")
    if len(host) > 253 or not all(_HOSTNAME_LABEL.match(label) for label in labels):
        raise TenantRecordError(f"{hostname!r} is not a valid hostname.")
    return host


def tenant_record(tenant_id: str, account_id: str, display_name: str, created_at: str, *, state: str = "active", plan: str | None = None,
                  entitlements: Mapping[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": validate_tenant_id(tenant_id), "accountId": account_id, "displayName": display_name, "state": state,
        "stateKey": tenant_state_key(state), "createdAt": created_at, "stateChangedAt": created_at,
    }
    if plan is not None:
        row["plan"] = plan
    if entitlements is not None:
        row["entitlements"] = dict(entitlements)
    return row


def membership_record(tenant_id: str, user_sub: str, role: str, granted_by: str, granted_at: str, *, user_profile_id: str | None = None,
                      status: str = "active") -> dict[str, Any]:
    row = {
        "id": membership_id(tenant_id, user_sub), "tenantId": tenant_id, "userSub": user_sub,
        "role": _choice(role, MEMBERSHIP_ROLES, "Membership role"), "status": status, "grantedBy": granted_by, "grantedAt": granted_at,
    }
    if user_profile_id:
        row["userProfileId"] = user_profile_id
    return row


def tenant_selection_record(user_sub: str, tenant_id: str, selected_at: str) -> dict[str, Any]:
    """The site a person's session acts for (PPY-0bb0fd). The id is the person's Cognito sub, so there is one row per person and
    the token trigger reads it with one GetItem. Writing it is the first half of switching site; the second is a new token."""
    sub = (user_sub or "").strip()
    if not sub:
        raise TenantRecordError("A tenant selection needs a user sub.")
    return {"id": sub, "selectedTenantId": validate_tenant_id(tenant_id), "selectedAt": selected_at}


def domain_record(tenant_id: str, hostname: str, kind: str, *, status: str = "pending_dns") -> dict[str, Any]:
    return {
        "id": domain_id(hostname), "tenantId": validate_tenant_id(tenant_id), "kind": _choice(kind, DOMAIN_KINDS, "Domain kind"),
        "status": _choice(status, DOMAIN_STATUSES, "Domain status"),
    }


def list_memberships_for_user(query_index: Callable[[str, dict[str, Any]], list[dict[str, Any]]], user_sub: str) -> list[dict[str, Any]]:
    """The token Lambda's lookup: one query on the ``userSub`` index; the index partition holds only this person's rows."""
    if not (user_sub or "").strip():
        raise TenantRecordError("A membership lookup needs a user sub.")
    return query_index(MEMBERSHIPS_BY_USER_SUB_QUERY, {"userSub": user_sub})


def claim_domain(create: Callable[[str, dict[str, Any]], None], tenant_id: str, hostname: str, kind: str) -> dict[str, Any]:
    """Add a hostname to a tenant. ``create(model, row)`` must fail when the id exists (a create is conditional on the key being
    absent, which both AppSync's create and a DynamoDB put with ``attribute_not_exists`` are); it raises ``KeyError`` then, and the
    claim is refused. The id is the hostname, so no second tenant can hold it."""
    row = domain_record(tenant_id, hostname, kind)
    try:
        create("TenantDomain", row)
    except KeyError as error:
        raise DomainAlreadyClaimed(f"{row['id']} already belongs to a tenant.") from error
    return row
