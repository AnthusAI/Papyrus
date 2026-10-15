"""Exercise actual native stores, guarded ASGI transports and priming orchestration."""
import asyncio
import uuid
import httpx
import pytest
from fixtures import ReviewAuthority, ACCOUNTS
from papyrus_content.curation_host import create_curation_host

@pytest.mark.parametrize('mode', ['embedded', 'remote'])
@pytest.mark.parametrize('vote', [{'label': 'publish'}, {'label': 'publish', 'rationale': ''}, {'label': 'publish', 'rationale': None}, {'label': 'publish', 'rationale': '  '}, {'label': 'publish', 'rationale': '  Exact operator explanation.  '}])
def test_real_curation_paths(tmp_path, mode, vote):
    async def run():
        authority = ReviewAuthority(tmp_path)
        authority.mode = mode
        try:
            for workspace in authority.workspaces.values():
                await workspace.seed()
            app = create_curation_host(authority.context)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://review.test') as client:
                bootstrap = (await client.get('/api/newsroom/curation/context')).json()
                scope = bootstrap['scope']
                headers = {'X-Cyclotron-Account': scope['accountId'], 'X-Papyrus-Publication': scope['publicationId'], 'X-Papyrus-Binding': scope['bindingRevision']}
                for operation in ('status', 'history'):
                    response = await client.post('/api/newsroom/curation/publication', headers=headers, json={'operation': operation, 'payload': {}})
                    assert response.status_code == 200, response.text
                    assert response.json()['accountId'] == ACCOUNTS[0]
                async def command(action, payload):
                    response = await client.post('/api/newsroom/curation/priming', headers=headers, json={'query': 'mutation($action:String!,$payload:JSON!){primingCommand(action:$action,payload:$payload)}', 'variables': {'action': action, 'payload': payload}})
                    assert response.status_code == 200, response.text
                    return response.json()
                identity = str(uuid.uuid4())
                result = await command('transform', {'identifier': identity, 'list_id': bootstrap['priming']['listId'], 'refs': bootstrap['priming']['classifiers'], 'transformer_id': 'papyrus', 'inputs': {'url': 'https://example.invalid/paper'}})
                assert 'errors' not in result, result
                draft = result['data']['primingCommand']
                for _ in range(30):
                    if draft['status'] not in ('queued', 'running', 'starting'):
                        break
                    await asyncio.sleep(.01)
                    draft = (await command('poll', {'identifier': identity}))['data']['primingCommand']
                assert draft['status'] == 'preview', draft
                assert draft['rows'][0]['item']['values']['title']
                refused = await command('accept', {'identifier': identity, 'version': draft['version'], 'labels': [{'editorial': {'rationale': 'A note without a label must not imply a label.'}}]})
                assert refused.get('errors')
                assert authority.proof()[ACCOUNTS[0]]['acceptedExamples'] == 0
                accepted = await command('accept', {'identifier': identity, 'version': draft['version'], 'labels': [{'editorial': vote}]})
                assert accepted['data']['primingCommand']['status'] == 'accepted', accepted
                examples = authority.workspaces[ACCOUNTS[0]].priming.examples(bootstrap['priming']['listId'], bootstrap['priming']['classifiers'])
                expected = vote.get('rationale') or ''
                assert examples['editorial'][0].context == ({'human_feedback': expected} if expected.strip() else {})
                replay = await command('accept', {'identifier': identity, 'version': draft['version'], 'labels': [{'editorial': vote}]})
                assert replay == accepted
                proof = authority.proof()
                assert proof[ACCOUNTS[0]]['acceptedExamples'] == 1
                assert proof[ACCOUNTS[1]]['acceptedExamples'] == 0
                assert all(value['operationalLabels'] == 0 for value in proof.values())
                authority.account = ACCOUNTS[1]
                assert (await client.post('/api/newsroom/curation/publication', headers=headers, json={'operation': 'status', 'payload': {}})).status_code == 409
                authority.allowed = False
                assert (await client.get('/api/newsroom/curation/context')).status_code == 401
        finally:
            authority.close()
    asyncio.run(run())

def test_priming_guard_rechecks_after_owner_lock(tmp_path):
    from papyrus_content.curation_host import GuardedPrimingService
    from decision_flywheel.publication_lab import PublicationError
    async def run():
        authority = ReviewAuthority(tmp_path)
        workspace = authority.workspaces[ACCOUNTS[0]]
        calls = []
        class Service:
            def get(self, identifier):
                calls.append(identifier)
                return {}
        async def guard():
            if not authority.allowed:
                raise PublicationError('original session revoked while queued', 401)
        service = GuardedPrimingService(Service(), workspace.engine.execution)
        try:
            async with workspace.engine.execution():
                task = asyncio.create_task(service.call('get', ('draft',), {}, guard))
                await asyncio.sleep(.01)
                assert not task.done()
                authority.allowed = False
            with pytest.raises(PublicationError, match='revoked'):
                await task
            assert calls == []
        finally:
            authority.close()
    asyncio.run(run())

@pytest.mark.parametrize('mode', ['embedded', 'remote'])
def test_explicit_steering_receipt_uses_native_revision(tmp_path, mode):
    async def run():
        authority = ReviewAuthority(tmp_path)
        authority.mode = mode
        try:
            workspace = authority.workspaces[ACCOUNTS[0]]
            await workspace.seed()
            context = authority.context()
            status = await context.publication.command(context.selection, 'status', {}, lambda: context.guard('read'))
            payload = {'bindingRevision': context.selection.binding_revision, 'bindingRef': context.binding_ref,
                'classifier': 'editorial', 'requestId': 'synthetic-evaluation', 'expectedFingerprint': status['classifiers']['editorial']['cyclotron']['fingerprint'],
                'action': 'evaluate', 'explanation': 'Explicit synthetic evaluation.', 'proposal': {'rubric': 'Synthetic scoped rubric.'}}
            result = await context.publication.command(context.selection, 'steer', payload, lambda: context.guard('steer'))
            assert result['steering']['result']['improved'] is False
            assert result['steering']['result']['promoted'] is False
            again = await context.publication.command(context.selection, 'steer', payload, lambda: context.guard('steer'))
            assert again == result and workspace.evaluator.calls == 1
        finally:
            authority.close()
    asyncio.run(run())
