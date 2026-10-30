"""Credential-free OAuth behavior through the real CLI dispatcher/session code."""
import json
import os
from dataclasses import replace
from contextlib import redirect_stdout
from io import StringIO
import tempfile
from pathlib import Path
from unittest.mock import patch
from behave import given, when, then
from papyrus_content.cli_user_auth import AuthConfig, SiteSession, AuthError, OAuthError
from procedures.newsroom.tests.test_cli_user_auth import MemoryStore, Provider


@given('a configured newsroom login with an isolated OAuth provider and secure store')
def configured_login(context):
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    environment = patch.dict(os.environ, {'PAPYRUS_CLI_STATE_DIR':temporary.name, 'PAPYRUS_GRAPHQL_AUTH':'user'})
    environment.start(); context.add_cleanup(environment.stop)
    context.auth_config = AuthConfig(publication='https://news.example.test',issuer='https://cognito-idp.us-east-1.amazonaws.com/pool',client_id='native-client',oauth_domain='https://news.auth.us-east-1.amazoncognito.com',graphql_endpoint='https://abc.appsync-api.us-east-1.amazonaws.com/graphql',callback_uri='http://127.0.0.1:5182/oauth/callback',refresh_lifetime_seconds=172800)
    context.clock = [1000.0]
    context.store = MemoryStore()
    context.provider = Provider(context.clock)
    context.interactions = []
    def receive(*args):
        context.interactions.append('browser sign-in')
        return 'fixture-code'
    context.session = SiteSession(context.auth_config,store=context.store,provider=context.provider,clock=lambda:context.clock[0],receive=receive)


@given('its registered callback uses literal localhost')
def registered_localhost(context):
    context.auth_config = replace(context.auth_config, callback_uri='http://localhost:3001/')
    context.session.config = context.auth_config


@when('the user completes the CLI Google sign-in')
def complete_login(context):
    from papyrus import cli
    with patch('papyrus_content.cli_user_auth.resolve_config',return_value=context.auth_config), patch('papyrus_content.cli_user_auth.session_for',return_value=context.session), redirect_stdout(StringIO()) as output:
        result = cli.main(['login','--publication',context.auth_config.publication])
    assert result == 0
    context.identity = json.loads(output.getvalue())


@then('the CLI identifies the user and publication without exposing tokens')
def identified(context):
    assert context.identity['subject'] == 'person-1'
    assert context.identity['publication'] == context.auth_config.publication
    assert 'refresh-1' not in json.dumps(context.identity)


@when('a restarted CLI session is used after 25 simulated hours')
def restarted_session(context):
    context.clock[0] += 25*3600
    context.session = SiteSession(context.auth_config,store=context.store,provider=context.provider,clock=lambda:context.clock[0],receive=lambda *a:context.interactions.append('unexpected browser'))
    context.session.headers(context.auth_config.graphql_endpoint)


@then('it renews without interactive sign-in')
def renewed(context):
    assert context.provider.calls[-1][1]['grant_type'] == 'refresh_token'
    assert context.interactions == ['browser sign-in']


@then('this evidence is labelled simulated rather than elapsed live testing')
def simulation(context):
    assert context.session.status()['elapsed_24h_live_verified'] is False


@when('the provider confirms the renewable session was revoked')
def revoked(context):
    context.clock[0] += 4000
    context.provider.failure = OAuthError('invalid_grant')


@then('the CLI requires login without falling back to IAM')
def no_escalation(context):
    from papyrus_content import graphql_http
    with patch('papyrus_content.cli_user_auth.session_for',return_value=context.session), patch.object(graphql_http,'iam_signed_graphql_headers',side_effect=AssertionError('IAM escalation')):
        try:
            graphql_http.graphql_request_headers(endpoint=context.auth_config.graphql_endpoint,body=b'{}')
        except AuthError as error:
            assert 'papyrus login' in str(error)
        else:
            raise AssertionError('Revoked session was accepted')


@when('logout cannot reach the provider')
def offline_logout(context):
    context.provider.revocation_failure = True
    context.logout = context.session.logout()


@then('local secrets are removed and remote revocation is unconfirmed')
def logout_result(context):
    assert context.store.get(context.auth_config.key) is None
    assert context.logout['remote_revocation'] == 'unconfirmed'


# --- the shared login library: secure stores, compatibility with sessions saved by earlier CLIs ---------

EARLIER_SERVICE = 'papyrus-newsroom-oauth'


def earlier_key(config) -> str:
    """The key the earlier CLI used: sha256 of the site's public binding, computed here by its original formula."""
    import hashlib
    public = {name: getattr(config, name) for name in
              ('publication', 'issuer', 'client_id', 'oauth_domain', 'graphql_endpoint', 'callback_uri')}
    return hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()


def _keychain_double(items=None):
    from cli_login.stores.macos import MacOSKeychain

    class Keychain(MacOSKeychain):
        """A Keychain keyed by (service, account), exactly as the real one is; no native framework."""
        def __init__(self):
            self.items = dict(items or {})
            self.reads = []
            self.writes = []

        def get_password(self, service, account):
            self.reads.append((service, account))
            return self.items.get((service, account))

        def set_password(self, service, account, value):
            self.writes.append((service, account))
            self.items[(service, account)] = value

        def delete_password(self, service, account):
            self.items.pop((service, account), None)

    return Keychain()


def _use_keychain(context, keychain):
    """Make the library's own store selection pick the Keychain, as it does on a Mac."""
    from unittest.mock import patch as _patch
    from cli_login import stores
    from cli_login.stores.macos import MacOSKeychainStore
    backends = dict(stores.BACKENDS)
    backends['keychain'] = (lambda target, state_dir, environ: MacOSKeychainStore(target.namespace, keychain), 'darwin')
    for patcher in (_patch.object(stores, 'BACKENDS', backends), _patch.object(stores.sys, 'platform', 'darwin')):
        patcher.start()
        context.add_cleanup(patcher.stop)


def _earlier_record(refresh):
    return json.dumps({'subject': 'person-1', 'label': 'person@example.test', 'refresh_token': refresh, 'created_at': 1000.0})


@given('a macOS Keychain that already holds an earlier CLI session under service "{service}" and the site\'s key')
def earlier_keychain_session(context, service):
    configured_login(context)
    context.earlier_key = earlier_key(context.auth_config)
    assert context.auth_config.key == context.earlier_key
    context.keychain = _keychain_double({(service, context.earlier_key): _earlier_record('earlier-refresh')})
    _use_keychain(context, context.keychain)


@when('a CLI session for that site is used 25 simulated hours later')
def use_earlier_session(context):
    from papyrus_content.cli_user_auth import SiteSession
    context.clock[0] += 25*3600
    context.session = SiteSession(context.auth_config, provider=context.provider, clock=lambda: context.clock[0],
                                  receive=lambda *a: context.interactions.append('unexpected browser'))
    context.session.headers(context.auth_config.graphql_endpoint)


@then('the shared login library read it from that same service and key')
def read_from_same_key(context):
    assert (EARLIER_SERVICE, context.earlier_key) in context.keychain.reads
    assert set(context.keychain.reads) == {(EARLIER_SERVICE, context.earlier_key)}


@then('it renewed with the stored refresh token without interactive sign-in')
def renewed_with_stored_token(context):
    assert context.provider.calls[-1][1]['grant_type'] == 'refresh_token'
    assert context.provider.calls[-1][1]['refresh_token'] == 'earlier-refresh'
    assert context.interactions == []


@then('the renewed session is saved back under that same service and key')
def saved_back(context):
    assert context.keychain.writes == [(EARLIER_SERVICE, context.earlier_key)]
    assert json.loads(context.keychain.items[(EARLIER_SERVICE, context.earlier_key)])['created_at'] == 1000.0


@given('a Linux machine with no Secret Service, no kernel keyring and no memory agent')
def bare_linux(context):
    from unittest.mock import patch as _patch
    from cli_login import stores
    from cli_login.errors import StoreUnavailable
    configured_login(context)
    home = tempfile.mkdtemp(prefix='pp', dir='/tmp')  # short: the agent socket path has a length limit
    context.add_cleanup(__import__('shutil').rmtree, home, True)
    def unavailable(reason):
        def factory(target, state_dir, environ):
            raise StoreUnavailable(reason)
        return factory
    backends = dict(stores.BACKENDS)
    backends['secret-service'] = (unavailable('No Secret Service is reachable.'), 'linux')
    backends['kernel-keyring'] = (unavailable('The kernel keyring is unavailable.'), 'linux')
    patchers = [_patch.object(stores, 'BACKENDS', backends), _patch.object(stores.sys, 'platform', 'linux'),
                _patch.dict(os.environ, {'HOME': home}),
                _patch('pathlib.Path.home', return_value=Path(home))]
    for patcher in patchers:
        patcher.start()
        context.add_cleanup(patcher.stop)
    os.environ.pop('CLI_LOGIN_STORE', None)
    os.environ.pop('CLI_LOGIN_AGENT_SOCKET', None)
    context.home = Path(home)


@when('the user tries to sign in to a site')
def try_login(context):
    from papyrus_content.cli_user_auth import command
    context.error = None
    with patch('papyrus_content.cli_user_auth.discover', return_value=context.auth_config):
        try:
            command(['login', 'news.example.test'])
        except AuthError as error:
            context.error = str(error)


@then('sign-in fails saying how to start the memory agent for "{namespace}"')
def agent_guidance(context, namespace):
    assert context.error, 'login should have failed'
    assert 'No secure credential store is available' in context.error
    assert f'python -m cli_login.stores.agent serve --namespace {namespace}' in context.error
    assert 'Plaintext storage is never used' in context.error
    assert context.interactions == [] and context.provider.calls == []


@then('no session or token file was written')
def nothing_written(context):
    state = Path(os.environ['PAPYRUS_CLI_STATE_DIR'])
    written = [path for path in list(state.rglob('*')) + list(context.home.rglob('*')) if path.is_file()]
    assert written == [], written


@given('a macOS Keychain shared by two signed-in sites on the same sign-in pool')
def two_sites(context):
    from dataclasses import replace
    from papyrus_content.cli_user_auth import SiteSession
    configured_login(context)
    first = context.auth_config
    second = replace(first, publication='https://other.example.test',
                     graphql_endpoint='https://other.appsync-api.us-east-1.amazonaws.com/graphql')
    assert first.key != second.key
    context.keychain = _keychain_double()
    _use_keychain(context, context.keychain)
    context.sites = {}

    class NamedProvider(Provider):
        """Issues refresh tokens that name their site, so a mix-up is visible."""
        def __init__(self, clock, name):
            super().__init__(clock)
            self.name = name

        def post(self, url, fields):
            response = super().post(url, fields)
            if 'refresh_token' in response:
                response['refresh_token'] = f'{self.name}-' + response['refresh_token']
            return response

    for config in (first, second):
        provider = NamedProvider(context.clock, config.publication.split('//')[1].split('.')[0])
        session = SiteSession(config, provider=provider, clock=lambda: context.clock[0], receive=lambda *a: 'code')
        session.login()
        context.sites[config.publication] = (config, session, provider)
    assert len(context.keychain.items) == 2


@when("the user renews the first site's session")
def renew_first(context):
    context.clock[0] += 4000
    config, session, provider = context.sites[context.auth_config.publication]
    session.headers(config.graphql_endpoint)


@then("only the first site's own refresh token was sent to the provider")
def only_first_token(context):
    config, session, provider = context.sites[context.auth_config.publication]
    other_config, other_session, other_provider = context.sites['https://other.example.test']
    sent = provider.calls[-1][1]['refresh_token']
    assert sent.startswith('news-'), sent
    assert json.loads(context.keychain.items[(EARLIER_SERVICE, other_config.key)])['refresh_token'].startswith('other-')
    assert len(other_provider.calls) == 1  # the second site's provider saw only its own sign-in


@then("signing out of the first site leaves the second site signed in")
def second_stays(context):
    config, session, provider = context.sites[context.auth_config.publication]
    other_config, other_session, _ = context.sites['https://other.example.test']
    session.logout()
    assert (EARLIER_SERVICE, config.key) not in context.keychain.items
    assert other_session.status()['signed_in'] is True
    assert (EARLIER_SERVICE, other_config.key) in context.keychain.items
