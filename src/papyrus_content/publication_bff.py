"""Trusted Papyrus account composition over Cyclotron's shared publication host.

No route, token issuer, membership store or persistence backend is installed here.
The deployment supplies verified selection and fresh account/publication access.
"""
from dataclasses import dataclass
import inspect

from decision_flywheel.publication_lab import PublicationAccess, PublicationError


@dataclass(frozen=True)
class PublicationSelection:
    account_id: str
    person_id: str
    publication_id: str
    binding_revision: str


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


class PublicationBFF:
    """Resolver for create_publication_host, with fresh post-ownership authority.

    resolve_selection(connection) returns a server-verified PublicationSelection.
    resolve_access(connection, publication, capability) returns PublicationAccess
    only after current account AND explicit publication authorization. Console
    read/write roles must never be converted implicitly into publication grants.
    Neither callback may enter an engine async operation while reauthorizing.
    """
    def __init__(self, *, resolve_selection, resolve_access):
        self.resolve_selection=resolve_selection
        self.resolve_access=resolve_access

    async def __call__(self, connection, publication, capability):
        selection=await resolved(self.resolve_selection(connection))
        if not isinstance(selection,PublicationSelection) or selection.publication_id!=publication:
            raise PublicationError('verified publication selection required',403)

        async def fresh():
            try:
                current=await resolved(self.resolve_selection(connection))
                if current!=selection:raise PublicationError('publication account selection changed',409,code='account_changed')
                access=await resolved(self.resolve_access(connection,publication,capability))
            except PublicationError:raise
            except Exception:
                raise PublicationError('publication authorization unavailable',503) from None
            if not isinstance(access,PublicationAccess):raise PublicationError('publication access refused',403)
            lab,actor=access.lab,access.actor
            binding=lab.authorize(actor,publication,capability)
            if capability=='steer':lab.authorize(actor,publication,'read')
            if (actor.account_id,actor.actor_id,lab.account_id,binding.revision)!=(selection.account_id,selection.person_id,selection.account_id,selection.binding_revision):
                raise PublicationError('verified publication identity or binding changed',409,code='account_changed')
            return access

        access=await fresh()
        if not callable(getattr(access.lab.engine,'execution',None)):
            raise PublicationError('supported guarded execution owner required',503)

        async def guard():
            current=await fresh()
            if current.lab is not access.lab:
                raise PublicationError('publication execution owner changed',409,code='account_changed')
            if current.execution_guard is not None:
                result=await resolved(current.execution_guard())
                if result is not None:raise TypeError('trusted host guard must return None or raise')

        return PublicationAccess(access.lab,access.actor,guard)
