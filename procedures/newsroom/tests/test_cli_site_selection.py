"""Which signed-in site a command talks to, the tenant the site publishes, and the upgrade hint. No network, login or keychain."""
import json
import subprocess
import sys
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest
from papyrus_content import env, site_document, site_selection
from papyrus_content.cli_user_auth import AuthError, SiteSession, command, save_selection
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from papyrus_content.tenancy import tenant_id_from_options
from procedures.newsroom.tests.test_cli_multisite_auth import Opener, site
from papyrus.cli import _consume_site_flag

A, B = site('a.anth.us'), site('b.anth.us')


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPYRUS_CLI_STATE_DIR', str(tmp_path/'state'))
    for name in ('PAPYRUS_GRAPHQL_AUTH', 'PAPYRUS_CLI_AUTH_CONFIG', 'PAPYRUS_SITE', 'PAPYRUS_SITE_ROOT', 'PAPYRUS_GRAPHQL_ENDPOINT',
                 'PAPYRUS_TENANT_ID', 'PAPYRUS_IDENTITY_POOL_ID'):
        monkeypatch.delenv(name, raising=False)
    work = tmp_path/'work'
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv('PAPYRUS_SITE', '')   # recorded, so a site set by the flag is undone with the test (delenv of an absent name is not)
    monkeypatch.delenv('PAPYRUS_SITE')
    monkeypatch.setattr(env, 'PAPYRUS_ROOT', tmp_path/'engine')   # no amplify_outputs.json beside the engine either
    monkeypatch.setattr(site_document, '_not_served', set())
    site_selection.install()
    yield
    site_selection.uninstall()


def sign_in(*configs):
    for config in configs:
        save_selection(config)


def write_outputs(directory, endpoint, bucket='bucket-a', pool='pool-a'):
    (Path(directory)/'amplify_outputs.json').write_text(json.dumps({
        'data': {'url': endpoint}, 'storage': {'bucket_name': bucket, 'aws_region': 'us-east-1'}, 'auth': {'identity_pool_id': pool}}))


def write_site_json(directory, **cms):
    (Path(directory)/'infra').mkdir(exist_ok=True)
    (Path(directory)/'infra'/'site.json').write_text(json.dumps({'cms': cms}))


def served(document):
    """A fake network serving this site document (or none) for any site; records what it was asked."""
    return Opener(document) if document is not None else Opener(error=urllib.error.HTTPError('u', 404, 'nf', {}, BytesIO(b'')))


# --- no outputs file ----------------------------------------------------------------------------

def test_the_only_signed_in_site_is_used_without_an_outputs_file():
    sign_in(A)
    assert env.graphql_endpoint() == A.graphql_endpoint


def test_nothing_signed_in_and_no_file_tells_the_person_to_log_in():
    with pytest.raises(ValueError, match=r'papyrus login <site>.*papyrus --site <site>'):
        env.graphql_endpoint()


def test_an_outputs_file_with_no_endpoint_is_not_a_file_that_decides(tmp_path):
    sign_in(A)
    (Path.cwd()/'amplify_outputs.json').write_text('{}')
    assert env.graphql_endpoint() == A.graphql_endpoint


# --- order of choice ----------------------------------------------------------------------------

def test_an_explicit_site_beats_a_present_outputs_file(monkeypatch):
    sign_in(A, B)
    write_outputs(Path.cwd(), 'https://file.appsync-api.us-east-1.amazonaws.com/graphql')
    monkeypatch.setenv('PAPYRUS_SITE', 'b.anth.us')
    assert env.graphql_endpoint() == B.graphql_endpoint


def test_a_present_outputs_file_beats_the_only_signed_in_site():
    sign_in(A)
    write_outputs(Path.cwd(), 'https://file.appsync-api.us-east-1.amazonaws.com/graphql')
    assert env.graphql_endpoint() == 'https://file.appsync-api.us-east-1.amazonaws.com/graphql'


def test_the_graphql_endpoint_variable_is_used_as_it_always_was(monkeypatch):
    sign_in(A, B)
    monkeypatch.setenv('PAPYRUS_GRAPHQL_ENDPOINT', 'https://other.appsync-api.us-east-1.amazonaws.com/graphql')
    assert env.graphql_endpoint() == 'https://other.appsync-api.us-east-1.amazonaws.com/graphql'


def test_an_explicit_site_that_disagrees_with_the_endpoint_variable_is_an_error(monkeypatch):
    sign_in(A, B)
    monkeypatch.setenv('PAPYRUS_SITE', 'a.anth.us')
    monkeypatch.setenv('PAPYRUS_GRAPHQL_ENDPOINT', B.graphql_endpoint)
    with pytest.raises(AuthError, match='names a different backend than a.anth.us'):
        env.graphql_endpoint()


def test_an_explicit_site_that_agrees_with_the_endpoint_variable_is_fine(monkeypatch):
    sign_in(A)
    monkeypatch.setenv('PAPYRUS_SITE', 'a.anth.us')
    monkeypatch.setenv('PAPYRUS_GRAPHQL_ENDPOINT', A.graphql_endpoint)
    assert env.graphql_endpoint() == A.graphql_endpoint


def test_an_explicit_site_that_is_not_signed_in_names_the_login_command(monkeypatch):
    sign_in(A)
    monkeypatch.setenv('PAPYRUS_SITE', 'c.anth.us')
    with pytest.raises(AuthError, match='Not signed in to c.anth.us; run `papyrus login c.anth.us`'):
        env.graphql_endpoint()


def test_several_signed_in_sites_and_no_choice_lists_them_and_never_guesses():
    sign_in(A, B)
    with pytest.raises(AuthError, match=r'Several sites are signed in \(a.anth.us, b.anth.us\).*--site a.anth.us'):
        env.graphql_endpoint()


def test_the_site_the_working_directory_declares_is_used_when_signed_in():
    sign_in(A, B)
    write_site_json(Path.cwd(), consoleOrigin='https://b.anth.us', siteOrigin='https://www.b.anth.us')
    assert env.graphql_endpoint() == B.graphql_endpoint


def test_the_declared_site_falls_back_to_the_site_origin_and_is_found_from_a_subdirectory():
    sign_in(A, B)
    write_site_json(Path.cwd(), siteOrigin='https://a.anth.us')
    (Path.cwd()/'web').mkdir()
    import os
    os.chdir(Path.cwd()/'web')
    assert env.graphql_endpoint() == A.graphql_endpoint


def test_a_declared_site_beats_a_present_outputs_file():
    sign_in(A, B)
    write_site_json(Path.cwd(), consoleOrigin='https://b.anth.us')
    write_outputs(Path.cwd(), 'https://file.appsync-api.us-east-1.amazonaws.com/graphql')
    assert env.graphql_endpoint() == B.graphql_endpoint


def test_a_declared_site_you_are_not_signed_in_to_is_never_replaced_by_another_one():
    sign_in(A)
    write_site_json(Path.cwd(), consoleOrigin='https://b.anth.us')
    with pytest.raises(AuthError, match='This directory belongs to b.anth.us.*papyrus login b.anth.us'):
        env.graphql_endpoint()


def test_a_declared_site_you_are_not_signed_in_to_still_uses_its_outputs_file():
    sign_in(A)
    write_site_json(Path.cwd(), consoleOrigin='https://b.anth.us')
    write_outputs(Path.cwd(), 'https://file.appsync-api.us-east-1.amazonaws.com/graphql')
    assert env.graphql_endpoint() == 'https://file.appsync-api.us-east-1.amazonaws.com/graphql'


# --- the IAM lane -------------------------------------------------------------------------------

def test_an_iam_operator_is_never_sent_to_a_signed_in_site(monkeypatch):
    sign_in(A)
    monkeypatch.setenv('PAPYRUS_GRAPHQL_AUTH', 'iam')
    with pytest.raises(ValueError, match='No site is selected'):
        env.graphql_endpoint()


def test_an_iam_operator_keeps_the_outputs_file(monkeypatch):
    sign_in(A)
    monkeypatch.setenv('PAPYRUS_GRAPHQL_AUTH', 'iam')
    write_outputs(Path.cwd(), 'https://file.appsync-api.us-east-1.amazonaws.com/graphql')
    assert env.graphql_endpoint() == 'https://file.appsync-api.us-east-1.amazonaws.com/graphql'


def test_an_iam_operator_who_names_a_site_gets_that_sites_endpoint(monkeypatch):
    sign_in(A)
    monkeypatch.setenv('PAPYRUS_GRAPHQL_AUTH', 'iam')
    monkeypatch.setenv('PAPYRUS_SITE', 'a.anth.us')
    assert env.graphql_endpoint() == A.graphql_endpoint


# --- Lambdas ------------------------------------------------------------------------------------

def test_a_process_that_never_installs_the_selection_ignores_the_registry():
    sign_in(A)
    site_selection.uninstall()
    with pytest.raises(ValueError, match='No site is selected'):
        env.graphql_endpoint()


def test_importing_env_loads_neither_the_sign_in_library_nor_the_selection():
    code = ('import sys; import papyrus_content.env, papyrus_content.tenancy; '
            'print(sorted(m for m in ("cli_login", "papyrus_content.site_selection", "papyrus_content.cli_user_auth") if m in sys.modules))')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True,
                         cwd=Path(__file__).resolve().parents[3], env={**__import__('os').environ, 'PYTHONPATH': 'src'}).stdout
    assert out.strip() == '[]'


# --- the other readers of an outputs file -------------------------------------------------------

def test_a_file_for_another_backend_does_not_supply_the_bucket_or_pool_of_the_chosen_site(monkeypatch):
    sign_in(A, B)
    write_outputs(Path.cwd(), 'https://file.appsync-api.us-east-1.amazonaws.com/graphql')
    assert env.storage_bucket_from_amplify_outputs() == 'bucket-a'   # nothing chosen: the file as before
    monkeypatch.setenv('PAPYRUS_SITE', 'b.anth.us')
    assert env.storage_bucket_from_amplify_outputs() is None
    assert env.identity_pool_id_from_amplify_outputs() is None
    from papyrus_content.media_store import storage_region_from_amplify_outputs
    assert storage_region_from_amplify_outputs() is None
    monkeypatch.setenv('PAPYRUS_IDENTITY_POOL_ID', 'pool-given')
    assert env.identity_pool_id_from_amplify_outputs() == 'pool-given'


def test_a_file_for_the_chosen_site_still_supplies_its_bucket_and_pool(monkeypatch):
    sign_in(A)
    write_outputs(Path.cwd(), A.graphql_endpoint)
    monkeypatch.setenv('PAPYRUS_SITE', 'a.anth.us')
    assert env.storage_bucket_from_amplify_outputs() == 'bucket-a'
    assert env.identity_pool_id_from_amplify_outputs() == 'pool-a'


# --- the flag -----------------------------------------------------------------------------------

def test_the_leading_site_flag_sets_the_site_and_is_removed(monkeypatch):
    assert _consume_site_flag(['--site', 'a.anth.us', 'editorial', 'context']) == ['editorial', 'context']
    assert __import__('os').environ['PAPYRUS_SITE'] == 'a.anth.us'
    assert _consume_site_flag(['--site=b.anth.us', 'references', 'list']) == ['references', 'list']
    assert __import__('os').environ['PAPYRUS_SITE'] == 'b.anth.us'
    monkeypatch.delenv('PAPYRUS_SITE')


def test_a_site_option_after_the_command_is_left_for_the_command(monkeypatch):
    arguments = ['items', 'link-references', '--site', 'some-key']
    assert _consume_site_flag(arguments) == arguments
    assert 'PAPYRUS_SITE' not in __import__('os').environ


def test_the_leading_site_flag_needs_a_value():
    from papyrus_content.operator_errors import OperatorError
    for arguments in (['--site'], ['--site', '--backend'], ['--site=']):
        with pytest.raises(OperatorError, match='--site requires a signed-in site'):
            _consume_site_flag(arguments)


# --- the site document --------------------------------------------------------------------------

def test_a_site_document_keeps_known_valid_fields_and_ignores_new_ones():
    assert site_document.parse(b'{"tenant_id": "machines-on-machines", "papyrus_version": "5.81.0", "later": 1}') == {
        'tenant_id': 'machines-on-machines', 'papyrus_version': '5.81.0'}
    assert site_document.parse(b'{}') == {}
    assert site_document.parse(b'{"papyrus_version": "5.81.0-next.2"}') == {'papyrus_version': '5.81.0-next.2'}


@pytest.mark.parametrize('raw', [b'not json', b'[]', b'{"tenant_id": "Not Valid"}', b'{"tenant_id": 4}', b'{"papyrus_version": "latest"}',
                                 b'{"papyrus_version": 5}', b'{"tenant_id": "' + b'a'*5000 + b'"}'])
def test_an_unusable_site_document_is_not_a_document(raw):
    assert site_document.parse(raw) is None


def test_the_site_document_is_fetched_over_https_from_the_sites_own_origin():
    opener = served({'tenant_id': 'm'})
    assert site_document.fetch('https://a.anth.us', opener=opener) == {'tenant_id': 'm'}
    assert opener.requests[0].full_url == 'https://a.anth.us/.well-known/papyrus-site.json'
    assert site_document.fetch('http://a.anth.us', opener=opener) is None


def test_a_missing_redirecting_or_unreachable_site_document_is_just_absent():
    for error in (urllib.error.HTTPError('u', 404, 'nf', {}, BytesIO(b'')), urllib.error.HTTPError('u', 302, 'moved', {}, BytesIO(b'')),
                  OSError('down'), urllib.error.URLError('down')):
        assert site_document.fetch('https://a.anth.us', opener=Opener(error=error)) is None


# --- the tenant ---------------------------------------------------------------------------------

def test_the_tenant_comes_from_the_site_and_is_kept_for_next_time(monkeypatch):
    sign_in(A)
    monkeypatch.setattr(site_document, 'fetch', lambda origin, **k: {'tenant_id': 'machines-on-machines', 'papyrus_version': '5.81.0'})
    client = PapyrusGraphQLAuthoringClient()
    assert client.endpoint == A.graphql_endpoint and client.tenant_id == 'machines-on-machines'
    monkeypatch.setattr(site_document, 'fetch', lambda *a, **k: pytest.fail('a kept document needs no second fetch'))
    assert PapyrusGraphQLAuthoringClient().tenant_id == 'machines-on-machines'
    assert site_document.cached()['https://a.anth.us']['papyrus_version'] == '5.81.0'


def test_the_tenant_environment_variable_wins_over_the_site(monkeypatch):
    sign_in(A)
    site_document.store('https://a.anth.us', {'tenant_id': 'machines-on-machines'})
    monkeypatch.setenv('PAPYRUS_TENANT_ID', 'other-tenant')
    assert PapyrusGraphQLAuthoringClient().tenant_id == 'other-tenant'


def test_an_explicit_tenant_wins_over_the_site(monkeypatch):
    sign_in(A)
    site_document.store('https://a.anth.us', {'tenant_id': 'machines-on-machines'})
    assert PapyrusGraphQLAuthoringClient(tenant_id='explicit').tenant_id == 'explicit'
    assert create_authoring_client('explicit')[0].tenant_id == 'explicit'
    assert tenant_id_from_options({'tenant': 'from-option'}) == 'from-option'
    assert tenant_id_from_options({}) == 'machines-on-machines'


def test_a_site_with_no_tenant_gives_none(monkeypatch):
    sign_in(A)
    site_document.store('https://a.anth.us', {'papyrus_version': '5.81.0'})
    assert PapyrusGraphQLAuthoringClient().tenant_id is None


def test_a_site_that_publishes_no_document_changes_nothing_and_fails_nothing(monkeypatch):
    sign_in(A)
    calls = []
    monkeypatch.setattr(site_document, 'fetch', lambda origin, **k: calls.append(origin))
    assert PapyrusGraphQLAuthoringClient().tenant_id is None
    assert PapyrusGraphQLAuthoringClient().tenant_id is None
    assert calls == ['https://a.anth.us'], 'asked once per process, not on every client'


def test_an_explicit_endpoint_gets_the_tenant_of_the_site_that_owns_it(monkeypatch):
    sign_in(A, B)
    site_document.store('https://a.anth.us', {'tenant_id': 'tenant-a'})
    site_document.store('https://b.anth.us', {})
    assert PapyrusGraphQLAuthoringClient(endpoint=A.graphql_endpoint).tenant_id == 'tenant-a'
    assert PapyrusGraphQLAuthoringClient(endpoint=B.graphql_endpoint).tenant_id is None
    assert PapyrusGraphQLAuthoringClient(endpoint='https://unknown.appsync-api.us-east-1.amazonaws.com/graphql').tenant_id is None


def test_an_iam_operator_gets_no_site_tenant(monkeypatch):
    sign_in(A)
    site_document.store('https://a.anth.us', {'tenant_id': 'machines-on-machines'})
    monkeypatch.setenv('PAPYRUS_GRAPHQL_AUTH', 'iam')
    monkeypatch.setenv('PAPYRUS_SITE', 'a.anth.us')
    assert PapyrusGraphQLAuthoringClient().tenant_id is None


def test_a_command_that_reads_every_row_opts_out_of_the_site_tenant():
    sign_in(A)
    site_document.store('https://a.anth.us', {'tenant_id': 'machines-on-machines'})
    assert create_authoring_client(None, site_tenant=False)[0].tenant_id is None
    from papyrus_content.tenant_adoption_commands import adoption_tenant_from_options
    assert adoption_tenant_from_options({'tenant': 'machines-on-machines'}) == 'machines-on-machines'


def test_a_lambda_without_the_selection_gets_only_the_environment_tenant(monkeypatch):
    sign_in(A)
    site_document.store('https://a.anth.us', {'tenant_id': 'machines-on-machines'})
    site_selection.uninstall()
    assert PapyrusGraphQLAuthoringClient(endpoint=A.graphql_endpoint).tenant_id is None
    monkeypatch.setenv('PAPYRUS_TENANT_ID', 'from-build')
    assert PapyrusGraphQLAuthoringClient(endpoint=A.graphql_endpoint).tenant_id == 'from-build'


# --- the upgrade hint ---------------------------------------------------------------------------

def test_an_unknown_command_names_a_newer_site_and_the_upgrade_command():
    hint = site_selection.newer_site_hint(installed='5.72.0', sites=[A], opener=served({'papyrus_version': '5.81.0'}))
    assert hint == ('This papyrus is 5.72.0, and a.anth.us runs 5.81.0, so the command may exist there. '
                    'Upgrade with `pipx upgrade papyrus-newsroom` (or `uv tool upgrade papyrus-newsroom`).')


def test_no_hint_when_the_cli_is_current_or_the_site_says_nothing():
    for document in ({'papyrus_version': '5.72.0'}, {'papyrus_version': '5.60.0'}, {}, None):
        assert site_selection.newer_site_hint(installed='5.72.0', sites=[A], opener=served(document)) is None
    assert site_selection.newer_site_hint(installed='5.72.0', sites=[]) is None


def test_the_hint_compares_the_release_not_the_prerelease_tag():
    assert site_selection.newer_site_hint(installed='5.81.0', sites=[A], opener=served({'papyrus_version': '5.81.0-next.4'})) is None
    assert site_selection.newer_site_hint(installed='5.81.0.dev3', sites=[A], opener=served({'papyrus_version': '5.82.0'}))


def test_an_unsupported_command_keeps_its_message_and_adds_the_hint_when_a_site_is_newer(monkeypatch):
    sign_in(A)
    monkeypatch.setattr(site_document, 'fetch', lambda origin, **k: {'papyrus_version': '99.0.0'})
    error = site_selection.unsupported_command('command: stories assign-research')
    assert str(error).startswith('Unsupported papyrus command: stories assign-research\nThis papyrus is ')
    assert 'a.anth.us runs 99.0.0' in str(error) and 'pipx upgrade papyrus-newsroom' in str(error)
    assert isinstance(error, ValueError)


def test_an_unsupported_command_is_unchanged_when_no_site_is_newer_or_the_lookup_fails(monkeypatch):
    assert str(site_selection.unsupported_command('command: x y')) == 'Unsupported papyrus command: x y'
    sign_in(A)
    monkeypatch.setattr(site_document, 'fetch', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    assert str(site_selection.unsupported_command('command: x y')) == 'Unsupported papyrus command: x y'


def test_the_real_dispatcher_gives_the_hint(monkeypatch, capsys):
    from papyrus.cli import main
    sign_in(A)
    monkeypatch.setattr(site_document, 'fetch', lambda origin, **k: {'papyrus_version': '99.0.0'})
    assert main(['stories', 'no-such-command']) == 2
    assert 'Upgrade with `pipx upgrade papyrus-newsroom`' in capsys.readouterr().err


def test_logging_in_to_a_newer_site_warns_on_stderr_and_keeps_its_document(monkeypatch, capsys):
    monkeypatch.setattr('papyrus_content.cli_user_auth.discover', lambda value: A)
    session = type('S', (), {'login': lambda self: {'subject': 's', 'label': 'l', 'publication': A.publication}, 'person_id': None})()
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for', lambda config: session)
    monkeypatch.setattr(site_document, 'fetch', lambda origin, **k: {'papyrus_version': '99.0.0', 'tenant_id': 'machines-on-machines'})
    monkeypatch.setattr('papyrus_content.cli_doctor.installed_version', lambda: '5.72.0')
    assert command(['login', 'a.anth.us']) == 0
    captured = capsys.readouterr()
    assert 'older than a.anth.us, which runs 99.0.0' in captured.err and 'pipx upgrade' in captured.err
    assert json.loads(captured.out)['publication'] == A.publication
    assert site_document.cached()['https://a.anth.us']['tenant_id'] == 'machines-on-machines'


def test_logging_in_to_a_site_that_publishes_no_document_works_and_says_nothing_more(monkeypatch, capsys):
    monkeypatch.setattr('papyrus_content.cli_user_auth.discover', lambda value: A)
    session = type('S', (), {'login': lambda self: {'subject': 's', 'label': 'l', 'publication': A.publication}, 'person_id': None})()
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for', lambda config: session)
    monkeypatch.setattr(site_document, 'fetch', lambda origin, **k: None)
    assert command(['login', 'a.anth.us']) == 0
    assert capsys.readouterr().err == ''


# --- the approval URL ---------------------------------------------------------------------------

def test_the_remote_approval_url_is_shown_at_once_when_output_is_redirected(monkeypatch):
    class Redirected:
        line_buffering = False
        def reconfigure(self, line_buffering):
            self.line_buffering = line_buffering
    stream = Redirected()
    monkeypatch.setattr(sys, 'stdout', stream)
    monkeypatch.setattr('papyrus_content.cli_user_auth.remote_login', lambda target, store, **options: {'subject': 's', 'label': 'l'})
    SiteSession(A, store=object(), provider=object()).login_remote(expected_email=None)
    assert stream.line_buffering is True


def test_a_stream_that_cannot_be_reconfigured_is_left_alone():
    from papyrus_content.cli_user_auth import line_buffered
    line_buffered(object())
