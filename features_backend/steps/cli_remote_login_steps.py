"""`papyrus login --remote` through the real dispatcher, session, cli-login client, broker and approval pages.

Only the seams are faked: the network (the site's public login file, the broker's function URL, the token endpoint),
the browser, the secure store and the clock. The broker is cli-login's `Broker` with its in-memory transaction table;
the pages are cli-login's `ApprovalPages` behind the site's own pages function (amplify/functions/cli-login-pages).
"""
import base64
import functools
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
import urllib.parse
from contextlib import redirect_stdout
from dataclasses import asdict
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when
from cli_login.broker.handler import Broker, BrokerConfig
from cli_login.broker.pages import CSRF_COOKIE, NONCE_COOKIE
from cli_login.broker.transactions import MemoryTransactions
from cli_login.remote import remote_login

from papyrus_content import cli_user_auth
from papyrus_content.cli_user_auth import AuthError, SiteSession, command, load_registry, selection_path
from procedures.newsroom.tests.test_cli_multisite_auth import Opener, site
from procedures.newsroom.tests.test_cli_user_auth import MemoryStore

HANDLER = Path(__file__).resolve().parents[2] / 'amplify/functions/cli-login-pages/handler.py'
BROKER_URL = 'https://broker.example.test'


def _pages_handler():
    spec = importlib.util.spec_from_file_location('cli_login_pages_handler', HANDLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LambdaClient:
    """boto3's Lambda client, as the pages function uses it: invokes the in-memory broker directly."""
    def __init__(self, broker):
        self.broker, self.reachable = broker, True

    def invoke(self, FunctionName, InvocationType, Payload):
        if not self.reachable:
            raise OSError('unreachable')
        return {'Payload': BytesIO(json.dumps(self.broker.handle(json.loads(Payload))).encode())}


class Product:
    """One site's broker, pages function and sign-in provider, in memory."""
    def __init__(self, config):
        self.config, self.now, self.broker_calls = config, 1_000_000.0, 0
        self.approver_email, self.issued, self.fired = 'person@example.com', {}, False
        self.broker = Broker(MemoryTransactions(), BrokerConfig(config.client_id, (config.graphql_endpoint,),
                                                                f'{config.publication}/cli/approve', f'{config.publication}/cli/callback'),
                             clock=lambda: self.now)
        self.lambda_client = LambdaClient(self.broker)
        self.handler = _pages_handler()
        self.pages = self.handler.pages_from_environment({
            'BROKER_FUNCTION_ARN': 'arn:aws:lambda:us-east-1:111111111111:function:broker', 'AUTHORIZE_ENDPOINT': config.oauth_domain + '/oauth2/authorize',
            'PRODUCT': 'Papyrus (' + config.publication[len('https://'):] + ')', 'PRIVILEGES': 'Act as you.', 'IDENTITY_PROVIDER': 'Google'},
            client=self.lambda_client)

    # the person's browser, going through the site's pages function --------------------------------------------

    def browse(self, method, url, cookies=None, form=None):
        parts = urllib.parse.urlsplit(url)
        request = {'method': method, 'path': parts.path, 'query': dict(urllib.parse.parse_qsl(parts.query)),
                   'headers': {'cookie': '; '.join(f'{k}={v}' for k, v in (cookies or {}).items())},
                   'body': urllib.parse.urlencode(form) if form else ''}
        response = self.handler.respond(self.pages, request)
        jar = {}
        for name, value in response['headers']:
            if name == 'Set-Cookie':
                cookie, _, rest = value.partition(';')
                key, _, content = cookie.partition('=')
                jar[key] = content
        return response, jar

    def open(self, url):
        response, jar = self.browse('GET', url)
        return response, jar.get(CSRF_COOKIE)

    def approve(self, url):
        transaction = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['t'][0]
        response, csrf = self.open(url)
        if response['status'] != 200:
            return response
        response, jar = self.browse('POST', '/cli/approve', {CSRF_COOKIE: csrf},
                                    {'t': transaction, 'csrf': csrf, 'action': 'approve', 'confirm': 'yes'})
        location = dict(map(tuple, response['headers']))['Location']
        authorize = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(location).query).items()}
        assert urllib.parse.urlsplit(location).path == '/oauth2/authorize' and authorize['identity_provider'] == 'Google'
        code = f'code-{len(self.issued)}'
        self.issued[code] = (authorize['code_challenge'], authorize['nonce'])
        callback, _ = self.browse('GET', f'/cli/callback?state={urllib.parse.quote(authorize["state"])}&code={code}', {NONCE_COOKIE: jar[NONCE_COOKIE]})
        return callback

    def deny(self, url):
        transaction = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['t'][0]
        _, csrf = self.open(url)
        return self.browse('POST', '/cli/approve', {CSRF_COOKIE: csrf}, {'t': transaction, 'csrf': csrf, 'action': 'deny'})[0]

    # the CLI's network ---------------------------------------------------------------------------------------

    def http(self, method, url, *, json_body=None, form=None, timeout=30):
        token_endpoint = self.config.oauth_domain + '/oauth2/token'
        if url in (BROKER_URL + '/start', BROKER_URL + '/poll'):
            self.broker_calls += 1
            if not self.fired and url.endswith('/poll'):
                self.fired = True
                self.on_first_poll(self)
            call = self.broker.start if url.endswith('/start') else self.broker.poll
            status, answer = call(json_body, '198.51.100.1')
            return status, answer, {}
        if url == token_endpoint:
            challenge, nonce = self.issued.pop(form['code'], (None, None))
            proof = base64.urlsafe_b64encode(__import__('hashlib').sha256(form['code_verifier'].encode()).digest()).decode().rstrip('=')
            if challenge is None or proof != challenge:
                return 400, {'error': 'invalid_grant'}, {}
            claims = {'iss': self.config.issuer, 'aud': self.config.client_id, 'sub': 'person-1', 'token_use': 'id',
                      'exp': self.now + 3600, 'email': self.approver_email, 'nonce': nonce}
            encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
            return 200, {'id_token': encode({'alg': 'RS256'}) + '.' + encode(claims) + '.fixture-signature',
                         'access_token': 'access-token-1', 'refresh_token': 'refresh-token-1', 'expires_in': 3600}, {}
        raise AssertionError(f'unexpected request {url}')


class SiteNetwork:
    """The sites' public login files; anything else is a 404."""
    def __init__(self, context):
        self.context = context

    def open(self, request, timeout=None):
        host = urllib.parse.urlsplit(request.full_url).hostname
        return Opener(**self.context.published[host]).open(request, timeout)


def _setup(context):
    if getattr(context, 'remote_world', False):
        return
    context.remote_world = True
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    environment = patch.dict(os.environ, {'PAPYRUS_CLI_STATE_DIR': temporary.name, 'PAPYRUS_GRAPHQL_AUTH': 'user'})
    environment.start(); context.add_cleanup(environment.stop)
    context.published, context.products, context.stores, context.actions = {}, {}, {}, []
    context.argv, context.ran, context.error, context.output, context.page = None, False, None, '', None
    context.unreachable_products = []
    patches = [
        patch('urllib.request.build_opener', lambda *handlers: SiteNetwork(context)),
        patch.object(cli_user_auth, 'session_for', lambda config: _session(context, config)),
        patch.object(cli_user_auth, 'remote_login', lambda target, store, **options: _remote_login(context, target, store, **options)),
    ]
    for p in patches:
        p.start(); context.add_cleanup(p.stop)


def _product(context):
    return next(iter(context.products.values()))


def _session(context, config):
    host = config.publication[len('https://'):]
    store = context.stores.setdefault(host, MemoryStore())
    return SiteSession(config, store=store, clock=lambda: _product(context).now)


def _remote_login(context, target, store_token_set, **options):
    product = context.products[urllib.parse.urlsplit(target.api_endpoint).hostname.split('.')[0] + '.anth.us']

    def act(product):
        url = re.search(r'open (\S+)', context.printed_url[0]).group(1)
        for action in context.actions:
            action(product, url)
    product.on_first_poll = act
    context.printed_url = []

    def out(text):
        context.printed_url.append(text)
        print(text)
    return remote_login(target, store_token_set, http=product.http, out=out, clock=lambda: product.now,
                        sleep=lambda seconds: setattr(product, 'now', product.now + seconds), host='cloud-box', **options)


def _run(context):
    if context.ran:
        return
    context.ran = True
    stream = StringIO()
    with redirect_stdout(stream):
        try:
            context.exit_code = command(context.argv)
        except AuthError as error:
            context.error = str(error)
    context.output = stream.getvalue()


def _publish(context, host, broker=True, **overrides):
    config = site(host)
    context.published[host] = {'body': asdict(config) | ({'broker_endpoint': BROKER_URL, 'remote_callback_uri': f'{config.publication}/cli/callback'} if broker else {}) | overrides}
    if broker and not overrides:
        context.products[host] = Product(config)


@given('the site "{host}" has remote CLI login switched on')
def switched_on(context, host):
    _setup(context)
    _publish(context, host)


@given('the site "{host}" publishes CLI login metadata without a broker')
def without_broker(context, host):
    _setup(context)
    _publish(context, host, broker=False)


@given('the site "{host}" publishes remote login metadata that {problem}')
def odd_metadata(context, host, problem):
    _setup(context)
    callback = f'https://{host}/cli/callback'
    context.published[host] = {'body': asdict(site(host)) | {
        'names a broker that is not HTTPS': {'broker_endpoint': 'http://broker.example.test', 'remote_callback_uri': callback},
        'names a broker but no remote callback': {'broker_endpoint': BROKER_URL},
        'names a remote callback but no broker': {'remote_callback_uri': callback},
    }[problem]}


@when('the agent runs "papyrus {arguments}"')
def agent_runs(context, arguments):
    _setup(context)
    context.argv = arguments.split()


@when('the person approves it in their browser after checking the code')
def person_approves(context):
    context.actions.append(lambda product, url: setattr(context, 'page', product.approve(url)))


@when('the person denies it on the approval page')
def person_denies(context):
    context.actions.append(lambda product, url: setattr(context, 'page', product.deny(url)))


@when('nobody approves it for ten minutes')
def nobody(context):
    pass


@when('"{email}" approves it')
def someone_approves(context, email):
    def approve(product, url):
        product.approver_email = email
        context.page = product.approve(url)
    context.actions.append(approve)


@when('the broker cannot be reached when the person opens the link')
def broker_down(context):
    def open_link(product, url):
        product.lambda_client.reachable = False
        context.page, _ = product.open(url)
    context.actions.append(open_link)


@given('a remote sign-in that was approved and collected')
def approved_and_collected(context):
    _setup(context)
    context.argv = ['login', '--remote', 'shipped.anth.us']
    context.actions.append(lambda product, url: (setattr(context, 'url', url), setattr(context, 'page', product.approve(url))))
    _run(context)
    assert context.error is None and context.stores['shipped.anth.us'].data


@when('someone opens the same approval link')
def reopen(context):
    context.page, _ = _product(context).open(context.url)


@then('the page says the link is no longer valid')
def link_invalid(context):
    _run(context)
    assert context.page['status'] == 410 and 'no longer valid' in context.page['body'], context.page


@then('the CLI printed only the approval URL, the matching code and who it signed in as')
def printed(context):
    _run(context)
    assert context.error is None, context.error
    lines = context.output.splitlines()
    assert re.fullmatch(r'To approve this sign-in, open https://shipped\.anth\.us/cli/approve\?t=[\w-]{22}', lines[0]), lines[0]
    assert re.fullmatch(r'and check that the page shows the code [BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}\.', lines[1]), lines[1]
    assert lines[2] == 'Signed in as person@example.com.'
    assert json.loads(lines[3])['publication'] == 'https://shipped.anth.us' and len(lines) == 4
    for secret in ('refresh-token-1', 'access-token-1', 'id_token', 'fixture-signature'):
        assert secret not in context.output


@then('the user is signed in to "{host}" with the same stored session a normal login makes')
def same_session(context, host):
    _run(context)
    store = context.stores[host]
    assert list(store.data) == [site(host).key]  # the key excludes the broker fields, so a normal login finds it
    record = json.loads(store.data[site(host).key])
    assert set(record) == {'subject', 'label', 'refresh_token', 'created_at'} and record['label'] == 'person@example.com'
    assert [c.publication for c in load_registry()] == ['https://' + host]


@then('the registry file is private and holds no tokens and no broker')
def registry_private(context):
    _run(context)
    path = selection_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    text = path.read_text()
    assert 'token' not in text and 'broker' not in text and 'remote_callback' not in text


@then('the sign-in is refused saying it was denied')
def denied(context):
    _run(context)
    assert 'denied' in context.error, context.error
    assert context.page['status'] == 200 and 'denied' in context.page['body']


@then('the sign-in is refused saying the approval link expired')
def expired(context):
    _run(context)
    assert 'expired' in context.error, context.error


@then('the sign-in is refused saying someone other than the expected person approved')
def stranger(context):
    _run(context)
    assert 'Someone other than the expected person approved' in context.error, context.error


@then('the sign-in is refused saying the site does not publish a remote sign-in broker')
def no_broker(context):
    _run(context)
    assert 'does not publish a remote sign-in broker' in context.error and 'papyrus login plain.anth.us' in context.error, context.error


@then('the sign-in is refused because the published login metadata is invalid')
def invalid_metadata(context):
    _run(context)
    assert 'invalid CLI login metadata' in context.error, context.error


@then('no broker was contacted')
def no_broker_contacted(context):
    _run(context)
    assert sum(product.broker_calls for product in context.products.values()) == 0


@then('the machine has registered no site')
def none_registered(context):
    _run(context)
    assert load_registry() == []
    assert not any(store.data for store in context.stores.values())


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_synth_behaviour(context, behaviour):
    completed = subprocess.run(
        ['node', '--import', 'tsx', 'scripts/test-cli-remote-login.ts', behaviour],
        cwd=REPOSITORY_ROOT, capture_output=True, text=True, timeout=180,
    )
    context.synth_result = completed
    assert completed.returncode == 0, completed.stdout + completed.stderr


@when("a site's broker is synthesized with an alarm topic")
def step_broker_synthesized_with_alarm_topic(context):
    _run_synth_behaviour(context, 'the_broker_alarms_notify_the_sites_alarm_topic_when_one_is_configured')


@then('both broker alarms notify that topic when they fire and when they recover')
def step_alarms_notify_topic(context):
    assert context.synth_result.returncode == 0


@when("a site's broker is synthesized without an alarm topic")
def step_broker_synthesized_without_alarm_topic(context):
    _run_synth_behaviour(context, 'without_an_alarm_topic_the_synth_warns_once_and_names_the_setting')


@then('the alarms carry no notification and synth warns once naming the alarm topic setting')
def step_alarms_silent_with_warning(context):
    assert context.synth_result.returncode == 0
