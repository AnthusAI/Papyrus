"""Role-based publication access over a real guarded lab and the Papyrus publication BFF."""
import asyncio

import pytest
from decision_flywheel import Cyclotron
from decision_flywheel.publication_lab import PublicationError, PublicationLab
from decision_flywheel.publication_lab_test import BINDINGS, DEFINITION, ITEM, OfflineModel

from papyrus_content.prospectus_publication_access import (
    role_based_publication_grants,
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


def test_central_lab_access_serves_roles_through_the_publication_contract(tmp_path):
    import httpx
    from decision_flywheel.publication_lab import PublicationAccess, PublicationActor, create_publication_host
    from papyrus_content.prospectus_publication_access import ProspectusCentralPublicationAccess

    async def scenario():
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, OfflineModel()) as engine:
            central_lab = PublicationLab(engine, account_id='account-a', bindings=BINDINGS)
            central_calls = []

            def central_trusts_the_site(_connection, publication, capability):
                central_calls.append((publication, capability))
                actor = PublicationActor('account-a', 'person-a', frozenset((publication, action) for action in ('read', 'review', 'decide', 'steer')))
                return PublicationAccess(central_lab, actor)

            central_host = create_publication_host(central_trusts_the_site, require_execution_guard=False)
            signed_in_role = {'role': 'member'}

            def authorize_account_operation(_connection, operation):
                return ProspectusAccountAuthorization('account-a', 'person-a', signed_in_role['role'], operation)

            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=central_host), base_url='http://central.test') as central_http:
                access = ProspectusCentralPublicationAccess(
                    authorize_account_operation=authorize_account_operation,
                    central_http_client_for=lambda _account: central_http,
                    publication_ids_for=lambda _account: tuple(central_lab.bindings),
                )
                member_client = await access(None, 'threat-intelligence', 'decide')
                decided = await member_client.command('threat-intelligence', 'decide', {'item': ITEM, 'bindingRevision': 'binding-1'})
                assert decided['accountId'] == 'account-a'
                signed_in_role['role'] = 'viewer'
                await access(None, 'threat-intelligence', 'read')
                calls_before_refusal = len(central_calls)
                with pytest.raises(PublicationError) as refused:
                    await access(None, 'threat-intelligence', 'decide')
                assert refused.value.status == 403
                assert len(central_calls) == calls_before_refusal, 'a refused person never reaches the central lab'
                with pytest.raises(PublicationError):
                    await access(None, 'not-bound-here', 'read')
    asyncio.run(scenario())


def test_central_lab_client_sends_the_account_credential_the_lab_reverifies(tmp_path):
    import httpx
    from decision_flywheel.publication_lab import create_publication_host
    from decision_flywheel.site_credentials import VerifiedSiteCredential, site_credential_access
    from papyrus_content.prospectus_publication_access import ProspectusCentralPublicationAccess, central_lab_http_client_factory

    async def scenario():
        with Cyclotron.open(tmp_path / 'engine', DEFINITION, OfflineModel()) as engine:
            lab = PublicationLab(engine, account_id='account-a', bindings=BINDINGS)
            live_credentials = {'credential-1': VerifiedSiteCredential('account-a', 'person-a', 'member')}
            verifications = []

            def verify_credential(token, pinned_account_id):
                verifications.append((token, pinned_account_id))
                return live_credentials.get(token)

            def lab_grants(credential, publication_ids):
                return role_based_publication_grants(
                    ProspectusAccountAuthorization(credential.account_id, credential.subject_id, credential.role, 'console:write'),
                    publication_ids,
                )

            central_host = create_publication_host(
                site_credential_access(verify_credential, lambda _account: lab, lab_grants),
                require_execution_guard=False,
            )
            issued = {'credential': 'credential-1'}
            http_factory = central_lab_http_client_factory(
                endpoint='http://central.test',
                credential_for=lambda _account: issued['credential'],
                transport=httpx.ASGITransport(app=central_host),
            )
            access = ProspectusCentralPublicationAccess(
                authorize_account_operation=lambda _connection, operation: ProspectusAccountAuthorization('account-a', 'person-a', 'member', operation),
                central_http_client_for=http_factory,
                publication_ids_for=lambda _account: tuple(lab.bindings),
            )
            client = await access(None, 'threat-intelligence', 'decide')
            decided = await client.command('threat-intelligence', 'decide', {'item': ITEM, 'bindingRevision': 'binding-1'})
            assert decided['accountId'] == 'account-a'
            assert verifications[-1] == ('credential-1', 'account-a')

            del live_credentials['credential-1']
            with pytest.raises(PublicationError) as revoked:
                await client.command('threat-intelligence', 'status', {})
            assert revoked.value.status == 403, 'a revoked credential stops working on the next call'

            issued['credential'] = ''
            with pytest.raises(PublicationError) as missing:
                await client.command('threat-intelligence', 'status', {})
            assert missing.value.status == 503
    asyncio.run(scenario())
