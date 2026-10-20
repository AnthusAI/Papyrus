"""Two-layer dispatch through existing authenticated publication transports.

Hosts inject verified bindings, session authorization and deployment-owned engines.
This module provisions nothing, retries nothing, and never reviews, seeds or trains.
"""
from dataclasses import dataclass
from hashlib import sha256
import json

from decision_flywheel.publication_lab import HTTPPublicationClient
from .curation_host import EmbeddedPublicationTransport, RemotePublicationTransport
from .publication_bff import PublicationSelection, resolved


@dataclass(frozen=True)
class PublicationRoute:
    publication: str
    remote_revision: str
    relevance_output: str
    positive_label: str
    section_revision: str
    section_outputs: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, 'section_outputs', tuple(self.section_outputs))
        if any(not isinstance(value, str) or not value.strip() for value in (
                self.publication, self.remote_revision, self.relevance_output,
                self.positive_label, self.section_revision)):
            raise ValueError('Explicit publication/output/binding identities are required')
        if (not self.section_outputs or len(set(self.section_outputs)) != len(self.section_outputs)
                or any(not isinstance(v, str) or not v.strip() for v in self.section_outputs)):
            raise ValueError('Explicit distinct integrated section outputs are required')


class RoutingFailure(ValueError):
    """A completed stage may exist; retain evidence without automatically retrying."""
    def __init__(self, stage, receipt):
        super().__init__(f'Classification failed during {stage}; retained partial receipt requires explicit reconciliation')
        self.stage, self.receipt = stage, receipt


def checked_prediction(response, selection, outputs, item):
    expected = {'contractVersion': 'cyclotron-publication/v1', 'accountId': selection.account_id,
                'publicationId': selection.publication_id, 'bindingRevision': selection.binding_revision}
    if not isinstance(response, dict) or any(response.get(k) != v for k, v in expected.items()):
        raise ValueError('Publication prediction account/publication/binding mismatch')
    decision = response.get('decision') or {}
    declarations = response.get('outputs') or []
    if (not decision.get('decisionId') or decision.get('itemId') != item['id']
            or set(decision.get('classifiers') or {}) != set(outputs)
            or len(declarations) != len(outputs) or {r.get('id') for r in declarations} != set(outputs)):
        raise ValueError('Prediction source or output set does not match its verified binding')
    if any(not isinstance(p.get('fingerprint'), str) or not p['fingerprint'] or type(p.get('version')) is not int
           for p in decision['classifiers'].values()):
        raise ValueError('Prediction version/fingerprint provenance is missing')
    if any(decision['classifiers'][output['id']].get('label') not in output.get('classes', []) for output in declarations):
        raise ValueError('Prediction label is outside its declared output contract')
    return response


async def route_discovery(remote_client, integrated, routes, item, *, account_id, authorize):
    """Evaluate all publication outputs together, then each positive's sections.

    authorize(publication, layer) must freshly resolve a server-verified
    PublicationSelection with decide capability. The existing embedded BFF repeats
    authorization after ownership acquisition; the remote host verifies its own
    actor. Separate HTTP projections must share one native decision, proving that
    independent engines were not substituted. An error is propagated without paid
    retry. The caller retains stage/request provenance for explicit reconciliation.
    """
    if (not isinstance(account_id, str) or not account_id.strip()
            or not isinstance(remote_client, HTTPPublicationClient) or remote_client.account_id != account_id):
        raise ValueError('A pinned remote HTTP publication client is required')
    routes = tuple(routes)
    if (not routes or len({r.publication for r in routes}) != len(routes)
            or len({r.relevance_output for r in routes}) != len(routes)):
        raise ValueError('Distinct publication bindings and relevance outputs are required')
    if any(not isinstance(integrated.get(r.publication), EmbeddedPublicationTransport) for r in routes):
        raise ValueError('Each publication requires its existing guarded integrated transport')
    if not callable(authorize) or not isinstance(item, dict) or not item.get('id') or not isinstance(item.get('values'), dict):
        raise ValueError('Verified authorization and an immutable structured source revision are required')
    frozen = json.dumps(item, sort_keys=True, separators=(',', ':'), allow_nan=False)
    source = json.loads(frozen)
    remote = RemotePublicationTransport(remote_client)
    result = {'inputFingerprint': sha256(frozen.encode()).hexdigest(), 'itemId': source['id'],
              'sharedDecisionId': None, 'publications': {}}
    actor = None

    async def selection_for(route, layer):
        nonlocal actor
        selection = await resolved(authorize(route.publication, layer))
        revision = route.remote_revision if layer == 'remote' else route.section_revision
        if (not isinstance(selection, PublicationSelection) or selection.account_id != account_id
                or selection.publication_id != route.publication or selection.binding_revision != revision):
            raise ValueError('Verified publication selection/binding changed')
        if actor is None:
            actor = selection.person_id
        if not actor or selection.person_id != actor:
            raise ValueError('Original publication actor changed')
        return selection

    async def dispatch(transport, route, layer, outputs):
        selection = await selection_for(route, layer)
        async def guard():
            if await selection_for(route, layer) != selection:
                raise ValueError('Publication selection changed during classification')
        payload = {'bindingRevision': selection.binding_revision, 'item': json.loads(frozen)}
        response = await transport.command(selection, 'decide', payload, guard)
        await guard()
        return checked_prediction(response, selection, outputs, source)

    # All remote projections precede integrated work. Native Cyclotron caches the
    # identical item against the shared multi-output engine: one model request.
    stage = 'remote routing'
    try:
        for route in routes:
            stage = f'remote routing for {route.publication}'
            response = await dispatch(remote, route, 'remote', (route.relevance_output,))
            output = response['outputs'][0]
            if output.get('positiveLabel') != route.positive_label or route.positive_label not in output.get('classes', []):
                raise ValueError('Relevance labels changed from the verified binding')
            decision_id = response['decision']['decisionId']
            if result['sharedDecisionId'] not in (None, decision_id):
                raise ValueError('Remote publications did not share one multi-output decision; no fallback')
            result['sharedDecisionId'] = decision_id
            result['publications'][route.publication] = {'relevance': response, 'sections': None}
        for route in routes:
            stage = f'integrated sections for {route.publication}'
            row = result['publications'][route.publication]
            if row['relevance']['decision']['classifiers'][route.relevance_output]['label'] == route.positive_label:
                row['sections'] = await dispatch(integrated[route.publication], route, 'integrated', route.section_outputs)
    except Exception as error:
        raise RoutingFailure(stage, result) from error
    return result
