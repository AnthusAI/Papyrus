"""Several Papyrus sites signed in at once; discovery by site name; doctor. No real login, network or keychain."""
import json
import os
import stat
import urllib.error
import urllib.request
from dataclasses import asdict, replace
from io import BytesIO
from unittest.mock import patch

import pytest
from papyrus_content import cli_doctor
from papyrus_content.cli_user_auth import (
    AuthConfig, AuthError, OAuthError, Session, command, config_for_endpoint, discover, load_registry,
    normalize_site, registered_site, save_selection, selected_headers, selection_path,
)
from procedures.newsroom.tests.test_cli_user_auth import MemoryStore, Provider, token


def site(host, **changes):
    values = dict(publication=f'https://{host}', issuer='https://cognito-idp.us-east-1.amazonaws.com/pool',
                  client_id='native-client', oauth_domain=f'https://{host.split(".")[0]}.auth.us-east-1.amazoncognito.com',
                  graphql_endpoint=f'https://{host.split(".")[0]}.appsync-api.us-east-1.amazonaws.com/graphql',
                  callback_uri='http://127.0.0.1:5182/oauth/callback')
    values.update(changes)
    return AuthConfig(**values)


@pytest.fixture(autouse=True)
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('PAPYRUS_CLI_STATE_DIR', str(tmp_path/'state'))
    monkeypatch.delenv('PAPYRUS_GRAPHQL_AUTH', raising=False)
    monkeypatch.delenv('PAPYRUS_CLI_AUTH_CONFIG', raising=False)
    monkeypatch.chdir(tmp_path)


class Opener:
    def __init__(self, body=None, error=None):
        self.body, self.error, self.requests = body, error, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        body = self.body if isinstance(self.body, bytes) else json.dumps(self.body).encode()
        class Response(BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return Response(body)


# --- site names ---------------------------------------------------------------------------------

@pytest.mark.parametrize('given,origin', [('shipped.anth.us', 'https://shipped.anth.us'),
                                          ('https://Shipped.Anth.us/', 'https://shipped.anth.us'),
                                          ('  p.apyr.us ', 'https://p.apyr.us')])
def test_site_names_become_https_origins(given, origin):
    assert normalize_site(given) == origin


@pytest.mark.parametrize('given', ['http://shipped.anth.us', 'https://shipped.anth.us/newsroom', 'https://u:p' + chr(64) + 'shipped.anth.us',
                                   'https://shipped.anth.us?x=1', 'ftp://x.test', ''])
def test_unusable_site_names_are_refused(given):
    with pytest.raises(AuthError, match='Site must be'):
        normalize_site(given)


# --- discovery ----------------------------------------------------------------------------------

def test_discovery_reads_the_wellknown_file_over_https_and_returns_the_config():
    config = site('shipped.anth.us', refresh_lifetime_seconds=2592000)
    opener = Opener(asdict(config))
    assert discover('shipped.anth.us', opener=opener) == config
    assert opener.requests[0].full_url == 'https://shipped.anth.us/.well-known/papyrus-cli.json'


def test_discovery_missing_file_says_the_site_has_no_native_cli_client():
    error = urllib.error.HTTPError('u', 404, 'nf', {}, BytesIO(b''))
    with pytest.raises(AuthError, match='does not publish CLI login.*native CLI client'):
        discover('shipped.anth.us', opener=Opener(error=error))


def test_discovery_redirects_are_refused():
    error = urllib.error.HTTPError('u', 302, 'moved', {}, BytesIO(b''))
    with pytest.raises(AuthError, match='redirects are refused'):
        discover('shipped.anth.us', opener=Opener(error=error))
    # The default opener itself never follows a redirect.
    with patch.object(urllib.request.OpenerDirector, 'open', side_effect=error):
        with pytest.raises(AuthError, match='redirects are refused'):
            discover('shipped.anth.us')


def test_discovery_publication_must_equal_the_requested_origin():
    with pytest.raises(AuthError, match='different publication'):
        discover('shipped.anth.us', opener=Opener(asdict(site('other.anth.us'))))


def test_discovery_rejects_unknown_missing_and_oversized_fields_and_non_https_values():
    good = asdict(site('shipped.anth.us'))
    good.pop('refresh_lifetime_seconds')
    for bad in [{**good, 'extra': 'x'}, {k: v for k, v in good.items() if k != 'client_id'}, {**good, 'oauth_domain': 'http://x.test'},
                {**good, 'callback_uri': 'https://evil.test/cb'}, [good], {**good, 'client_id': 'x'*(20*1024)}]:
        with pytest.raises(AuthError, match='invalid CLI login metadata'):
            discover('shipped.anth.us', opener=Opener(bad))
    with pytest.raises(AuthError, match='invalid CLI login metadata'):
        discover('shipped.anth.us', opener=Opener(b'not json'))


def test_discovery_network_failure_is_a_clean_error():
    with pytest.raises(AuthError, match='Could not reach shipped.anth.us'):
        discover('shipped.anth.us', opener=Opener(error=OSError('down')))


# --- registry -----------------------------------------------------------------------------------

def test_registry_is_private_atomic_public_metadata_only():
    save_selection(site('a.anth.us')); save_selection(site('b.anth.us'))
    path = selection_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [c.publication for c in load_registry()] == ['https://a.anth.us', 'https://b.anth.us']
    assert 'token' not in path.read_text().lower()
    assert not list(path.parent.glob('selection-*'))


def test_saving_a_site_again_replaces_its_entry():
    save_selection(site('a.anth.us')); save_selection(site('a.anth.us', client_id='rotated'))
    assert [c.client_id for c in load_registry()] == ['rotated']


def test_a_second_site_cannot_claim_another_sites_graphql_endpoint():
    save_selection(site('a.anth.us'))
    with pytest.raises(AuthError, match='already registered for a.anth.us'):
        save_selection(site('b.anth.us', graphql_endpoint=site('a.anth.us').graphql_endpoint))
    assert [c.publication for c in load_registry()] == ['https://a.anth.us']


def test_legacy_single_selection_file_is_migrated_transparently():
    legacy = site('old.anth.us')
    selection_path().write_text(json.dumps(asdict(legacy)))
    assert load_registry() == [legacy]
    save_selection(site('new.anth.us'))
    assert [c.publication for c in load_registry()] == ['https://old.anth.us', 'https://new.anth.us']
    assert json.loads(selection_path().read_text())['version'] == 2


def test_keychain_keys_are_unchanged_by_the_registry():
    config = site('old.anth.us')
    selection_path().write_text(json.dumps(asdict(config)))
    assert load_registry()[0].key == config.key


def test_symlinked_or_corrupt_registry_is_refused(tmp_path):
    selection_path().write_text('{broken')
    with pytest.raises(AuthError, match='unreadable'):
        load_registry()
    selection_path().unlink()
    target = tmp_path/'elsewhere.json'; target.write_text('{}')
    selection_path().symlink_to(target)
    with pytest.raises(AuthError, match='symlink'):
        load_registry()


def test_registered_site_lookup_names_the_login_command_when_absent():
    save_selection(site('a.anth.us'))
    assert registered_site('https://a.anth.us/').publication == 'https://a.anth.us'
    with pytest.raises(AuthError, match='papyrus login b.anth.us'):
        registered_site('b.anth.us')


# --- choosing the session -----------------------------------------------------------------------

def test_headers_use_the_session_whose_endpoint_matches(monkeypatch):
    a, b = site('a.anth.us'), site('b.anth.us')
    save_selection(a); save_selection(b)
    chosen = []
    class Fake:
        def __init__(self, config): self.config = config
        def headers(self, endpoint): chosen.append(self.config.publication); return {'Authorization': 'x'}
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for', Fake)
    selected_headers(b.graphql_endpoint); selected_headers(a.graphql_endpoint)
    assert chosen == ['https://b.anth.us', 'https://a.anth.us']


def test_unknown_endpoint_error_lists_signed_in_sites_and_never_falls_back_to_iam():
    save_selection(site('a.anth.us'))
    monkey = 'https://zzz.appsync-api.us-east-1.amazonaws.com/graphql'
    with pytest.raises(AuthError) as error:
        config_for_endpoint(monkey)
    assert 'a.anth.us' in str(error.value) and 'papyrus login <site>' in str(error.value) and monkey in str(error.value)


def test_explicit_config_env_still_selects_one_config(tmp_path, monkeypatch):
    config = site('c.anth.us')
    path = tmp_path/'cfg.json'; path.write_text(json.dumps(asdict(config)))
    save_selection(site('a.anth.us'))
    monkeypatch.setenv('PAPYRUS_CLI_AUTH_CONFIG', str(path))
    assert config_for_endpoint(config.graphql_endpoint) == config


def test_signed_out_site_error_names_the_site_to_log_in_to():
    config = site('a.anth.us')
    with pytest.raises(AuthError, match='papyrus login a.anth.us'):
        Session(config, store=MemoryStore(), provider=None).headers(config.graphql_endpoint)


def test_revoked_session_error_names_the_site():
    config = site('a.anth.us'); clock = [1000.0]; store = MemoryStore(); provider = Provider(clock)
    session = Session(config, store=store, provider=provider, clock=lambda: clock[0], receive=lambda *a: 'code')
    session.login(); clock[0] += 4000; provider.failure = OAuthError('invalid_grant')
    with pytest.raises(OAuthError, match='papyrus login a.anth.us'):
        session.headers(config.graphql_endpoint)


# --- commands -----------------------------------------------------------------------------------

class World:
    """Sites a.anth.us and b.anth.us with independent stores/providers."""
    def __init__(self):
        self.clock = [1000.0]; self.sessions = {}; self.stores = {}; self.logins = []
        for host in ('a.anth.us', 'b.anth.us'):
            config = site(host)
            self.stores[host] = MemoryStore()
            self.sessions[config.publication] = Session(config, store=self.stores[host], provider=Provider(self.clock),
                                                       clock=lambda: self.clock[0],
                                                       receive=lambda *a, h=host: self.logins.append(h) or 'code')

    def discover(self, value):
        return self.sessions['https://'+value.replace('https://', '')].config


@pytest.fixture
def world(monkeypatch):
    w = World()
    monkeypatch.setattr('papyrus_content.cli_user_auth.discover', w.discover)
    monkeypatch.setattr('papyrus_content.cli_user_auth.session_for', lambda config: w.sessions[config.publication])
    return w


def out(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_login_by_site_name_signs_in_and_registers(world, capsys):
    assert command(['login', 'a.anth.us']) == 0
    assert world.logins == ['a.anth.us']
    assert [c.publication for c in load_registry()] == ['https://a.anth.us']
    assert out(capsys)[0]['publication'] == 'https://a.anth.us'


def test_login_accepts_several_sites_and_all_uses_the_registry(world, capsys):
    assert command(['login', 'a.anth.us', 'b.anth.us']) == 0
    world.logins.clear()
    assert command(['login', '--all']) == 0
    assert sorted(world.logins) == ['a.anth.us', 'b.anth.us']


def test_login_all_continues_past_a_failed_site_and_exits_nonzero(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    def declined(*a): raise AuthError('Google sign-in was declined. No session was saved.')
    world.sessions['https://a.anth.us'].receive = declined
    world.logins.clear()
    assert command(['login', '--all']) == 1
    lines = out(capsys)
    assert any('declined' in line.get('error', '') for line in lines) and world.logins == ['b.anth.us']


def test_whoami_lists_every_signed_in_site(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    assert command(['whoami']) == 0
    lines = out(capsys)
    assert [l['publication'] for l in lines] == ['https://a.anth.us', 'https://b.anth.us'] and all(l['signed_in'] for l in lines)
    assert 'refresh-' not in json.dumps(lines)


def test_whoami_for_one_site_and_auth_status(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    assert command(['whoami', 'b.anth.us']) == 0
    assert [l['publication'] for l in out(capsys)] == ['https://b.anth.us']
    assert command(['auth', 'status']) == 0
    assert len(out(capsys)) == 2


def test_logout_one_site_leaves_the_others_signed_in(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    assert command(['logout', 'a.anth.us']) == 0
    assert world.stores['a.anth.us'].get(world.sessions['https://a.anth.us'].config.key) is None
    assert world.stores['b.anth.us'].get(world.sessions['https://b.anth.us'].config.key) is not None
    assert len(load_registry()) == 2  # signed-out sites stay listed so a later call cannot fall back to IAM


def test_logout_all_signs_out_everything(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    assert command(['logout', '--all']) == 0
    assert all(store.data == {} for store in world.stores.values())


def test_logout_without_a_name_is_ambiguous_when_several_sites_are_signed_in(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    with pytest.raises(AuthError, match='name one'):
        command(['logout'])
    assert all(store.data for store in world.stores.values())


def test_login_with_no_arguments_relogs_the_only_registered_site(world, capsys):
    command(['login', 'a.anth.us']); world.logins.clear(); capsys.readouterr()
    assert command(['login']) == 0 and world.logins == ['a.anth.us']


def test_login_config_file_still_works(world, tmp_path, capsys):
    path = tmp_path/'cfg.json'; path.write_text(json.dumps(asdict(world.sessions['https://b.anth.us'].config)))
    assert command(['login', '--config', str(path)]) == 0 and world.logins == ['b.anth.us']


def test_unknown_site_for_whoami_is_actionable(world):
    with pytest.raises(AuthError, match='papyrus login c.anth.us'):
        command(['whoami', 'c.anth.us'])


# --- doctor -------------------------------------------------------------------------------------

def run_doctor(capsys, args=(), latest=lambda: '9.9.9'):
    code = cli_doctor.run(list(args), latest=latest)
    return code, capsys.readouterr().out


def test_doctor_reports_version_install_and_sites_without_secrets_or_identity(world, capsys):
    command(['login', 'a.anth.us']); capsys.readouterr()
    code, text = run_doctor(capsys)
    assert code == 0
    assert 'newer release 9.9.9 available' in text and 'install\t' in text and 'on-path\t' in text
    assert 'site\ta.anth.us\tsigned in, session valid' in text
    assert 'refresh' not in text and 'person@example.test' not in text and 'person-1' not in text


def test_doctor_tolerates_an_unreachable_pypi_and_offline_mode(world, capsys):
    code, text = run_doctor(capsys, latest=lambda: None)
    assert 'latest version unknown' in text and code == 0
    called = []
    cli_doctor.run(['--offline'], latest=lambda: called.append(1))
    assert called == []


def test_doctor_flags_signed_out_and_expired_sites(world, capsys):
    command(['login', 'a.anth.us', 'b.anth.us']); capsys.readouterr()
    command(['logout', 'a.anth.us']); capsys.readouterr()
    world.clock[0] += 4000; world.sessions['https://b.anth.us'].provider.failure = OAuthError('invalid_grant')
    code, text = run_doctor(capsys)
    assert code == 1
    assert 'signed out; run `papyrus login a.anth.us`' in text and 'expired or revoked; run `papyrus login b.anth.us`' in text


def test_doctor_keeps_a_session_when_the_provider_is_down(world, capsys):
    command(['login', 'a.anth.us']); capsys.readouterr()
    world.clock[0] += 4000; world.sessions['https://a.anth.us'].provider.failure = OAuthError('temporarily_unavailable', transient=True)
    code, text = run_doctor(capsys)
    assert 'session kept' in text and code == 0


def test_doctor_with_no_sites_says_how_to_log_in(world, capsys):
    code, text = run_doctor(capsys)
    assert 'papyrus login <site>' in text


@pytest.mark.parametrize('prefix,base,kind', [('/opt/x/pipx/venvs/papyrus-newsroom', '/usr', 'pipx tool install'),
                                              ('/opt/x/share/uv/tools/papyrus-newsroom', '/usr', 'uv tool install'),
                                              ('/opt/x/caches/pypoetry/virtualenvs/p-py3.12', '/usr', 'virtualenv'),
                                              ('/usr', '/usr', 'system Python')])
def test_doctor_tells_tool_installs_from_virtualenvs(prefix, base, kind):
    assert cli_doctor.install_kind(prefix, base) == kind


def test_doctor_hints_at_pipx_when_run_from_a_virtualenv(world, capsys, monkeypatch):
    monkeypatch.setattr(cli_doctor, 'install_kind', lambda: 'virtualenv')
    monkeypatch.setattr(cli_doctor.shutil, 'which', lambda name: None)
    code, text = run_doctor(capsys)
    assert 'pipx install papyrus-newsroom' in text and 'on-path\tno' in text


def test_doctor_dispatches_from_the_real_cli(world, capsys, monkeypatch):
    from papyrus import cli
    monkeypatch.setattr(cli_doctor, 'latest_version', lambda: None)
    assert cli.main(['doctor']) == 0
    assert 'version\t' in capsys.readouterr().out
