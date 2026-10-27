"""Credential-free multi-site CLI behaviour through the real dispatcher and session code."""
import json
import os
import stat
import tempfile
import urllib.error
import urllib.parse
from contextlib import redirect_stdout
from dataclasses import asdict
from io import BytesIO, StringIO
from unittest.mock import patch

from behave import given, when, then

from papyrus_content import cli_doctor
from papyrus_content.cli_user_auth import (
    AuthConfig, AuthError, Session, command, load_registry, selected_headers, selection_path,
)
from procedures.newsroom.tests.test_cli_multisite_auth import Opener, World, site


def _setup(context):
    if getattr(context, 'multisite', None) is not None:
        return
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    environment = patch.dict(os.environ, {'PAPYRUS_CLI_STATE_DIR': temporary.name, 'PAPYRUS_GRAPHQL_AUTH': 'user'})
    environment.start(); context.add_cleanup(environment.stop)
    context.multisite = World()
    context.published = {}
    context.session_requests = []
    context.fetched = []
    context.output = ''
    context.error = None
    context.exit_code = None
    context.iam_used = False
    context.latest = '9.9.9'
    context.kind = 'pipx tool install'
    discovery = patch('urllib.request.build_opener', lambda *handlers: _Site(context))
    sessions = patch('papyrus_content.cli_user_auth.session_for', lambda config: _session(context, config))
    for p in (discovery, sessions):
        p.start(); context.add_cleanup(p.stop)


def _session(context, config):
    context.session_requests.append(config.publication)
    sessions = context.multisite.sessions
    if config.publication not in sessions:
        host = config.publication[len('https://'):]
        context.multisite.stores[host] = _legacy_store(context, host)
        sessions[config.publication] = Session(config, store=context.multisite.stores[host], provider=sessions[next(iter(sessions))].provider,
                                              clock=lambda: context.multisite.clock[0], receive=lambda *a: 'code')
    return sessions[config.publication]


def _legacy_store(context, host):
    return getattr(context, 'legacy_stores', {}).get(host) or __import__('procedures.newsroom.tests.test_cli_user_auth', fromlist=['MemoryStore']).MemoryStore()


class _Site:
    """Stands in for the network: serves whatever the scenario's sites publish."""
    def __init__(self, context):
        self.context = context

    def open(self, request, timeout=None):
        self.context.fetched.append(request.full_url)
        host = urllib.parse.urlsplit(request.full_url).hostname
        published = self.context.published.get(host)
        opener = Opener(**published) if published else Opener(error=urllib.error.HTTPError('u', 404, 'nf', {}, BytesIO(b'')))
        return opener.open(request, timeout)


def _run(context, *arguments):
    stream = StringIO()
    context.error = None
    with redirect_stdout(stream):
        try:
            context.exit_code = command(list(arguments))
        except AuthError as error:
            context.error = str(error)
    context.output = stream.getvalue()


def _hosts(text):
    return [part for part in text.replace('"', ' ').replace(' and ', ' ').split() if part]


def _signed_in(context, hosts):
    context.published.update({h: {'body': asdict(context.multisite.sessions['https://'+h].config)} for h in hosts})
    _run(context, 'login', *hosts)
    context.multisite.logins.clear()


@given('the sites "{first}" and "{second}" each publish CLI login metadata')
def two_sites_publish(context, first, second):
    _setup(context)
    for host in (first, second):
        context.published[host] = {'body': asdict(context.multisite.sessions['https://'+host].config)}


@given('the site "{host}" publishes no CLI login file')
def site_without_file(context, host):
    _setup(context)


@given('the site "{host}" publishes login metadata that {problem}')
def site_with_bad_metadata(context, host, problem):
    _setup(context)
    good = asdict(context.multisite.sessions['https://'+host].config)
    good.pop('refresh_lifetime_seconds')
    published = {
        'names a different publication': {'body': {**good, 'publication': 'https://other.anth.us'}},
        'contains an unknown extra field': {'body': {**good, 'extra': 'x'}},
        'omits the client id': {'body': {k: v for k, v in good.items() if k != 'client_id'}},
        'uses a non-HTTPS OAuth domain': {'body': {**good, 'oauth_domain': 'http://x.test'}},
        'uses a non-loopback callback': {'body': {**good, 'callback_uri': 'https://evil.test/cb'}},
        'is larger than the size cap': {'body': {**good, 'client_id': 'x'*(20*1024)}},
        'answers with a redirect': {'error': urllib.error.HTTPError('u', 302, 'moved', {}, BytesIO(b''))},
    }[problem]
    context.published[host] = published


@given('the user is signed in to "{first}" and "{second}"')
def signed_in_to_two(context, first, second):
    _setup(context)
    _signed_in(context, [first, second])


@given('the browser sign-in for "{host}" will be declined')
def declined(context, host):
    def decline(*args):
        raise AuthError('Google sign-in was declined. No session was saved.')
    context.multisite.sessions['https://'+host].receive = decline


@given('"{host}" has an expired session')
def expired(context, host):
    from papyrus_content.cli_user_auth import OAuthError
    context.multisite.clock[0] += 4000
    context.multisite.sessions['https://'+host].provider.failure = OAuthError('invalid_grant')
    for other, session in context.multisite.sessions.items():
        if not other.endswith(host):
            session.provider.failure = None


@given('a single-site selection file and keychain secret written by the previous CLI for "{host}"')
def legacy(context, host):
    _setup(context)
    config = site(host)
    selection_path().write_text(json.dumps(asdict(config)))
    legacy_store = _legacy_store(context, host)
    seeding = Session(config, store=legacy_store, provider=context.multisite.sessions['https://a.anth.us'].provider,
                      clock=lambda: context.multisite.clock[0], receive=lambda *a: 'code')
    seeding.login()
    context.legacy_stores = {host: legacy_store}
    context.multisite.stores[host] = legacy_store
    context.multisite.sessions[config.publication] = Session(config, store=legacy_store, provider=seeding.provider,
                                                            clock=lambda: context.multisite.clock[0], receive=lambda *a: context.multisite.logins.append(host))
    context.multisite.logins.clear()
    context.published['b.anth.us'] = {'body': asdict(context.multisite.sessions['https://b.anth.us'].config)}


@given('PyPI cannot be reached')
def pypi_down(context):
    _setup(context)
    context.latest = None


@given('the CLI is running from a virtualenv that is not on the PATH')
def venv(context):
    _setup(context)
    context.kind = 'virtualenv'
    context.on_path = None


@when('the user runs "papyrus {arguments}"')
def run_papyrus(context, arguments):
    _setup(context)
    parts = arguments.split()
    if parts[0] == 'doctor':
        stream = StringIO()
        with patch.object(cli_doctor, 'install_kind', lambda: context.kind), \
                patch.object(cli_doctor.shutil, 'which', lambda name: getattr(context, 'on_path', '/usr/local/bin/papyrus')), \
                redirect_stdout(stream):
            context.exit_code = cli_doctor.run([], latest=lambda: context.latest)
        context.output = stream.getvalue()
        return
    _run(context, *parts)


@when('the user runs "papyrus logout" without a site')
def logout_bare(context):
    _run(context, 'logout')


@when('the user tries to sign in to "{host}"')
def try_sign_in(context, host):
    _setup(context)
    _run(context, 'login', host)


@when('a request is made to the GraphQL endpoint of "{host}"')
def request_to(context, host):
    endpoint = site(host).graphql_endpoint
    context.error = None
    context.credentials = None
    context.session_requests.clear()
    try:
        context.credentials = selected_headers(endpoint)
    except AuthError as error:
        context.error = str(error)


@when('a request is made to an unknown GraphQL endpoint')
def request_unknown(context):
    context.error = None
    try:
        selected_headers('https://zzz.appsync-api.us-east-1.amazonaws.com/graphql')
    except AuthError as error:
        context.error = str(error)


@when('the site "{host}" publishes the GraphQL endpoint of "{victim}" and the user signs in to it')
def hijack(context, host, victim):
    config = site(host, graphql_endpoint=site(victim).graphql_endpoint)
    context.multisite.sessions[config.publication] = Session(config, store=context.multisite.stores['a.anth.us'].__class__(),
                                                            provider=context.multisite.sessions['https://a.anth.us'].provider,
                                                            clock=lambda: context.multisite.clock[0], receive=lambda *a: 'code')
    context.published[host] = {'body': asdict(config)}
    _run(context, 'login', host)


@then('the CLI fetched "{url}" over HTTPS')
def fetched(context, url):
    assert context.fetched == [url], context.fetched


@then('the user is signed in to "{host}" only')
def only(context, host):
    assert [c.publication for c in load_registry()] == ['https://'+host]
    assert context.multisite.stores[host].data


@then('the user is signed in to "{first}" and "{second}"')
def both(context, first, second):
    assert sorted(c.publication for c in load_registry()) == sorted(['https://'+first, 'https://'+second])
    assert context.multisite.stores[first].data and context.multisite.stores[second].data


@then('the registry file is private and holds no tokens')
def private(context):
    path = selection_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'refresh_token' not in path.read_text() and 'id_token' not in path.read_text()


@then('the sign-in is refused saying the site does not publish CLI login')
def no_client(context):
    assert 'does not publish CLI login' in context.error, context.error


@then('the sign-in is refused with a message about invalid or mismatched metadata')
def invalid(context):
    assert any(text in context.error for text in ('invalid CLI login metadata', 'different publication', 'redirects are refused')), context.error


@then('no site is registered')
def none_registered(context):
    assert load_registry() == []


@then('the session of "{host}" supplied the credentials')
def supplied(context, host):
    assert context.error is None and context.credentials and context.credentials['Authorization']
    assert context.session_requests == ['https://'+host], context.session_requests


@then('the request is refused naming the signed-in sites and the login command')
def named(context):
    assert 'a.anth.us' in context.error and 'b.anth.us' in context.error and 'papyrus login <site>' in context.error


@then('the operator AWS credentials were not used')
def no_iam(context):
    from papyrus_content import graphql_http
    with patch.object(graphql_http, 'iam_signed_graphql_headers', side_effect=AssertionError('IAM escalation')):
        try:
            graphql_http.graphql_request_headers(endpoint='https://zzz.appsync-api.us-east-1.amazonaws.com/graphql', body=b'{}')
        except AuthError:
            return
    raise AssertionError('request was allowed')


@then('the request is refused with "{text}"')
def refused_with(context, text):
    assert text in (context.error or ''), context.error


@then('the session of "{host}" is still signed in')
def still(context, host):
    assert context.multisite.stores[host].data


@then('both sites went through browser sign-in again')
def relogin(context):
    assert sorted(context.multisite.logins) == ['a.anth.us', 'b.anth.us']


@then('"{host}" was signed in again')
def signed_again(context, host):
    assert host in context.multisite.logins


@then('the command reports "{host}" as failed and exits with an error')
def reports_failure(context, host):
    assert context.exit_code == 1
    lines = [json.loads(line) for line in context.output.splitlines()]
    assert any(line.get('publication') == 'https://'+host and 'declined' in line['error'] for line in lines)


@then('one status line is printed for each of "{first}" and "{second}"')
def status_lines(context, first, second):
    lines = [json.loads(line) for line in context.output.splitlines()]
    assert [line['publication'] for line in lines] == ['https://'+first, 'https://'+second]
    assert all(line['signed_in'] for line in lines)


@then('no token appears in the output')
def no_token(context):
    assert 'refresh-' not in context.output and 'fixture-signature' not in context.output


@then('only "{host}" lost its stored session')
def only_lost(context, host):
    assert not context.multisite.stores[host].data
    assert all(store.data for name, store in context.multisite.stores.items() if name != host)


@then('no site has a stored session')
def none_stored(context):
    assert all(not store.data for store in context.multisite.stores.values())


@then('the command asks the user to name a site')
def name_one(context):
    assert 'name one' in context.error, context.error


@then('both sites keep their stored sessions')
def both_kept(context):
    assert all(store.data for store in context.multisite.stores.values())


@then('the existing session is used without signing in again')
def legacy_used(context):
    assert context.error is None and context.credentials and context.multisite.logins == []


@then('a later login to "{host}" keeps "{old}" registered')
def keeps(context, host, old):
    _run(context, 'login', host)
    assert sorted(c.publication for c in load_registry()) == sorted(['https://'+old, 'https://'+host])
    assert json.loads(selection_path().read_text())['version'] == 2


@then('the sign-in is refused saying the endpoint is already registered for "{host}"')
def hijack_refused(context, host):
    assert f'already registered for {host}' in context.error, context.error
    assert 'https://evil.anth.us' not in [c.publication for c in load_registry()]


@then('it reports the installed version and a newer release on PyPI')
def version(context):
    assert 'version\t' in context.output and 'newer release 9.9.9 available' in context.output


@then('it reports whether the CLI runs from a tool install or a virtualenv')
def kind(context):
    assert 'install\tpipx tool install' in context.output


@then('it reports "{good}" as valid and "{bad}" as needing "{command_text}"')
def health(context, good, bad, command_text):
    assert f'site\t{good}\tsigned in, session valid' in context.output
    assert f'site\t{bad}\texpired or revoked; run `{command_text}`' in context.output


@then('the report contains no tokens and no email addresses')
def no_secrets(context):
    assert 'refresh-' not in context.output and '@' not in context.output


@then('it says the latest version is unknown and still reports the install kind')
def offline(context):
    assert 'latest version unknown' in context.output and 'install\t' in context.output


@then('it recommends installing with pipx or uv tool')
def recommends(context):
    assert 'pipx install papyrus-newsroom' in context.output and 'uv tool install papyrus-newsroom' in context.output
