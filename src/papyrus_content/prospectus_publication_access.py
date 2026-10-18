"""Publication access for people signed in through Prospectus.

Prospectus owns account membership and role; Papyrus owns what a role may do on
the account's publications, and never more than the role allows. For now every
member of an account gets the capabilities of their role on all of that
account's bound publications (Ryan, 2026-10-17: role now, per-person grants
later). The rule is one injectable function, so per-person narrowing replaces
it without touching the resolver or the publication BFF.
"""
from dataclasses import dataclass
import inspect

from decision_flywheel.publication_lab import PublicationAccess, PublicationActor, PublicationError

PROSPECTUS_ROLE_PUBLICATION_CAPABILITIES = {
    'viewer': ('read',),
    'member': ('read', 'review', 'decide'),
    'admin': ('read', 'review', 'decide', 'steer'),
    'owner': ('read', 'review', 'decide', 'steer'),
}

PROSPECTUS_OPERATION_FOR_PUBLICATION_CAPABILITY = {
    'read': 'console:read',
    'review': 'console:write',
    'decide': 'console:write',
    'steer': 'console:write',
}


@dataclass(frozen=True)
class ProspectusAccountAuthorization:
    """Prospectus's answer to POST /v1/accounts/{id}/authorize for the signed-in person."""
    account_id: str
    person_id: str
    role: str
    operation: str


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


def publication_capabilities_for_prospectus_role(role):
    return PROSPECTUS_ROLE_PUBLICATION_CAPABILITIES.get(role, ())


def role_based_publication_grants(authorization, publication_ids):
    capabilities = publication_capabilities_for_prospectus_role(authorization.role)
    return frozenset((publication_id, capability) for publication_id in publication_ids for capability in capabilities)


class ProspectusPublicationAccess:
    """resolve_access for PublicationBFF, backed by a fresh Prospectus authorization.

    authorize_account_operation(connection, operation) asks Prospectus whether the
    connection's signed-in person may perform operation on the connection's
    selected account, returning ProspectusAccountAuthorization or raising.
    lab_for_account(connection, account_id) returns that account's open lab.
    grants_for(authorization, publication_ids) is the access rule, capped here by
    the role's capabilities whatever it returns.
    """
    def __init__(self, *, authorize_account_operation, lab_for_account, grants_for=role_based_publication_grants, execution_guard_for=None):
        self.authorize_account_operation = authorize_account_operation
        self.lab_for_account = lab_for_account
        self.grants_for = grants_for
        self.execution_guard_for = execution_guard_for

    async def __call__(self, connection, publication, capability):
        operation = PROSPECTUS_OPERATION_FOR_PUBLICATION_CAPABILITY.get(capability)
        if operation is None:
            raise PublicationError('publication capability refused', 403)
        authorization = await resolved(self.authorize_account_operation(connection, operation))
        if not isinstance(authorization, ProspectusAccountAuthorization) or authorization.operation != operation:
            raise PublicationError('account access refused', 403)
        lab = await resolved(self.lab_for_account(connection, authorization.account_id))
        if lab is None or lab.account_id != authorization.account_id:
            raise PublicationError('account access refused', 403)
        role_ceiling = set(publication_capabilities_for_prospectus_role(authorization.role))
        grants = frozenset(
            (publication_id, granted_capability)
            for publication_id, granted_capability in self.grants_for(authorization, tuple(lab.bindings))
            if granted_capability in role_ceiling and publication_id in lab.bindings
        )
        if (publication, capability) not in grants:
            raise PublicationError('publication capability refused', 403)
        actor = PublicationActor(authorization.account_id, authorization.person_id, grants)
        execution_guard = self.execution_guard_for(connection) if self.execution_guard_for else None
        return PublicationAccess(lab, actor, execution_guard)


def create_prospectus_publication_host(
    *,
    resolve_selection,
    authorize_account_operation,
    lab_for_account,
    grants_for=role_based_publication_grants,
    execution_guard_for=None,
):
    from decision_flywheel.publication_lab import create_publication_host
    from .publication_bff import PublicationBFF

    publication_access = ProspectusPublicationAccess(
        authorize_account_operation=authorize_account_operation,
        lab_for_account=lab_for_account,
        grants_for=grants_for,
        execution_guard_for=execution_guard_for,
    )
    return create_publication_host(
        PublicationBFF(resolve_selection=resolve_selection, resolve_access=publication_access),
        require_execution_guard=False,
    )
