"""Observable HTTP boundaries for the optional Papyrus curation BFF."""
import asyncio
from dataclasses import replace

import httpx
import pytest

from papyrus_content.curation_host import CurationContext, create_curation_host
from papyrus_content.publication_bff import PublicationSelection
from decision_flywheel.publication_lab import PublicationError


def test_host_refuses_spoofed_scope_and_missing_original_session():
    async def scenario():
        scope = PublicationSelection('account-a', 'person-a', 'publication-a', 'binding-1')
        calls = []

        async def authorize(capability):
            calls.append(capability)
            return scope

        context = CurationContext(scope, 'embedded', authorize, None, None, 'examples-a', ({'id': 'editorial', 'revision': 1},))
        app = create_curation_host(lambda request: context if request.headers.get('x-test-session') == 'original' else None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://review.test') as client:
            assert (await client.get('/api/newsroom/curation/context')).status_code == 401
            headers = {'x-test-session': 'original'}
            result = await client.get('/api/newsroom/curation/context', headers=headers)
            assert result.status_code == 200
            assert result.json()['scope'] == {'accountId': 'account-a', 'publicationId': 'publication-a', 'bindingRevision': 'binding-1'}
            assert 'person-a' not in result.text
            calls.clear()
            body = {'operation': 'status', 'payload': {}}
            for extra, status in [({}, 400), ({'x-cyclotron-account': 'account-b', 'x-papyrus-publication': 'publication-a', 'x-papyrus-binding': 'binding-1'}, 409)]:
                assert (await client.post('/api/newsroom/curation/publication', headers={**headers, **extra}, json=body)).status_code == status
            assert calls == []
            assert (await client.post('/api/newsroom/curation/publication', headers={**headers, 'origin': 'http://evil.test'}, json=body)).status_code == 403
    asyncio.run(scenario())


@pytest.mark.parametrize('mode', ['embedded', 'remote'])
def test_host_uses_fresh_authority_and_rejects_stale_response(mode):
    async def scenario():
        scope = PublicationSelection('account-a', 'person-a', 'publication-a', 'binding-1')
        state = {'scope': scope, 'allowed': True}

        async def authorize(capability):
            if not state['allowed']:
                raise PublicationError('explicit publication access refused', 403)
            return state['scope']

        class Transport:
            calls = 0
            async def command(self, selection, operation, payload, guard):
                await guard()
                self.calls += 1
                state['scope'] = replace(scope, person_id='different-person')
                return {'contractVersion': 'cyclotron-publication/v1', 'accountId': scope.account_id, 'publicationId': scope.publication_id, 'bindingRevision': scope.binding_revision}

        transport = Transport()
        context = CurationContext(scope, mode, authorize, transport, None, 'examples-a', ({'id': 'editorial', 'revision': 1},))
        app = create_curation_host(lambda _: context)
        headers = {'x-cyclotron-account': scope.account_id, 'x-papyrus-publication': scope.publication_id, 'x-papyrus-binding': scope.binding_revision}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://review.test') as client:
            state['allowed'] = False
            denied = await client.post('/api/newsroom/curation/publication', headers=headers, json={'operation': 'status', 'payload': {}})
            assert denied.status_code == 403 and transport.calls == 0
            state['allowed'] = True
            stale = await client.post('/api/newsroom/curation/publication', headers=headers, json={'operation': 'status', 'payload': {}})
            assert stale.status_code == 409 and transport.calls == 1
    asyncio.run(scenario())
