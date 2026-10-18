"""Role-based publication access over a real guarded lab and the Papyrus publication BFF."""
import asyncio

import pytest
from decision_flywheel import Cyclotron
from decision_flywheel.publication_lab import PublicationError, PublicationLab
from decision_flywheel.publication_lab_test import BINDINGS, DEFINITION, ITEM, OfflineModel

from papyrus_content.prospectus_publication_access import (
    ProspectusAccountAuthorization,
    ProspectusPublicationAccess,
    publication_capabilities_for_prospectus_role,
)
from papyrus_content.publication_bff import PublicationBFF, PublicationSelection

SELECTION = PublicationSelection('account-a', 'person-a', 'threat-intelligence', 'binding-1')


def prospectus_answering(role, *, account_id='account-a', person_id='person-a', refusal=None):
    asked = []

    def authorize_account_operation(connection, operation):
        asked.append(operation)
        if refusal is not None:
            raise refusal
        return ProspectusAccountAuthorization(account_id, person_id, role, operation)

    return authorize_account_operation, asked


async def run_command(lab, access_resolver, operation, payload):
    bff = PublicationBFF(resolve_selection=lambda _connection: SELECTION, resolve_access=access_resolver)
    capability = {'status': 'read', 'history': 'read', 'events': 'read'}.get(operation, operation)
    owned = await bff(None, SELECTION.publication_id, capability)
    return await owned.lab.command(owned.actor, SELECTION.publication_id, operation, payload, execution_guard=owned.execution_guard)


def test_role_capabilities_never_grow_past_the_role():
    assert publication_capabilities_for_prospectus_role('viewer') == ('read',)
    assert publication_capabilities_for_prospectus_role('member') == ('read', 'review', 'decide')
    assert 'steer' in publication_capabilities_for_prospectus_role('admin')
    assert publication_capabilities_for_prospectus_role('owner') == publication_capabilities_for_prospectus_role('admin')
    assert publication_capabilities_for_prospectus_role('guest') == ()


@pytest.mark.parametrize('role,operation,allowed', [
    ('viewer', 'status', True), ('viewer', 'decide', False),
    ('member', 'decide', True), ('member', 'steer', False),
    ('admin', 'decide', True), ('owner', 'status', True),
    ('unknown-role', 'status', False),
])
def test_prospectus_role_decides_publication_capability(tmp_path, role, operation, allowed):
    async def scenario():
        model = OfflineModel()
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, model) as engine:
            lab = PublicationLab(engine, account_id='account-a', bindings=BINDINGS)
            authorize, asked = prospectus_answering(role)
            access = ProspectusPublicationAccess(authorize_account_operation=authorize, lab_for_account=lambda _connection, _account: lab)
            payload = {'bindingRevision': 'binding-1', 'item': ITEM} if operation == 'decide' else {}
            if operation == 'steer':
                with pytest.raises(PublicationError) as refused:
                    await PublicationBFF(resolve_selection=lambda _connection: SELECTION, resolve_access=access)(None, SELECTION.publication_id, 'steer')
                assert refused.value.status == 403
                assert asked == ['console:write']
                return
            if allowed:
                result = await run_command(lab, access, operation, payload)
                assert result
            else:
                with pytest.raises(PublicationError) as refused:
                    await run_command(lab, access, operation, payload)
                assert refused.value.status == 403
                assert model.calls == 0, 'a refused person never reaches the classifier'
            assert asked[0] == ('console:write' if operation == 'decide' else 'console:read')
    asyncio.run(scenario())


def test_a_custom_rule_cannot_grant_more_than_the_role(tmp_path):
    async def scenario():
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, OfflineModel()) as engine:
            lab = PublicationLab(engine, account_id='account-a', bindings=BINDINGS)
            authorize, _asked = prospectus_answering('viewer')
            def everything(_authorization, publication_ids):
                return frozenset((publication_id, capability) for publication_id in publication_ids + ('elsewhere',) for capability in ('read', 'review', 'decide', 'steer'))
            access = ProspectusPublicationAccess(authorize_account_operation=authorize, lab_for_account=lambda _c, _a: lab, grants_for=everything)
            with pytest.raises(PublicationError) as refused:
                await access(None, 'threat-intelligence', 'decide')
            assert refused.value.status == 403
            granted = await access(None, 'threat-intelligence', 'read')
            assert granted.actor.grants == frozenset({('threat-intelligence', 'read'), ('pilobolus', 'read')})
    asyncio.run(scenario())


def test_per_person_narrowing_replaces_the_rule_without_touching_the_resolver(tmp_path):
    async def scenario():
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, OfflineModel()) as engine:
            lab = PublicationLab(engine, account_id='account-a', bindings=BINDINGS)
            authorize, _asked = prospectus_answering('admin')
            def only_pilobolus(_authorization, _publication_ids):
                return frozenset({('pilobolus', 'read')})
            access = ProspectusPublicationAccess(authorize_account_operation=authorize, lab_for_account=lambda _c, _a: lab, grants_for=only_pilobolus)
            with pytest.raises(PublicationError):
                await access(None, 'threat-intelligence', 'read')
            assert (await access(None, 'pilobolus', 'read')).actor.grants == frozenset({('pilobolus', 'read')})
    asyncio.run(scenario())


@pytest.mark.parametrize('case', ['other-account-lab', 'no-lab', 'prospectus-refuses', 'wrong-operation-answer', 'unknown-capability'])
def test_access_fails_closed(tmp_path, case):
    async def scenario():
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, OfflineModel()) as engine:
            lab = PublicationLab(engine, account_id='account-b' if case == 'other-account-lab' else 'account-a', bindings=BINDINGS)
            authorize, _asked = prospectus_answering('owner', refusal=PublicationError('not authorized', 403) if case == 'prospectus-refuses' else None)
            if case == 'wrong-operation-answer':
                authorize = lambda _connection, _operation: ProspectusAccountAuthorization('account-a', 'person-a', 'owner', 'members:read')
            access = ProspectusPublicationAccess(
                authorize_account_operation=authorize,
                lab_for_account=lambda _c, _a: None if case == 'no-lab' else lab,
            )
            with pytest.raises(PublicationError) as refused:
                await access(None, 'threat-intelligence', 'publish' if case == 'unknown-capability' else 'read')
            assert refused.value.status == 403
    asyncio.run(scenario())


def test_prospectus_publication_host_serves_each_role_over_http(tmp_path):
    import httpx
    from decision_flywheel.publication_lab import HTTPPublicationClient
    from papyrus_content.prospectus_publication_access import create_prospectus_publication_host

    async def scenario():
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, OfflineModel()) as engine:
            lab = PublicationLab(engine, account_id='account-a', bindings=BINDINGS)
            signed_in_role = {'role': 'member'}

            def authorize_account_operation(connection, operation):
                return ProspectusAccountAuthorization('account-a', 'person-a', signed_in_role['role'], operation)

            host = create_prospectus_publication_host(
                resolve_selection=lambda _connection: SELECTION,
                authorize_account_operation=authorize_account_operation,
                lab_for_account=lambda _connection, _account: lab,
            )
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=host), base_url='http://offline.test') as http:
                client = HTTPPublicationClient(http, account_id='account-a')
                decided = await client.command('threat-intelligence', 'decide', {'item': ITEM, 'bindingRevision': 'binding-1'})
                assert decided['accountId'] == 'account-a'
                assert (await client.command('threat-intelligence', 'status', {}))
                signed_in_role['role'] = 'viewer'
                assert (await client.command('threat-intelligence', 'status', {}))
                with pytest.raises(PublicationError) as refused:
                    await client.command('threat-intelligence', 'decide', {'item': ITEM, 'bindingRevision': 'binding-1'})
                assert refused.value.status == 403
                signed_in_role['role'] = 'guest'
                with pytest.raises(PublicationError) as removed:
                    await client.command('threat-intelligence', 'status', {})
                assert removed.value.status == 403
    asyncio.run(scenario())
