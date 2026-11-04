"""Site selection, the site's tenant and the upgrade hint, through the real code. No network, login, keychain or real site."""
import json
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from behave import given, when, then

from papyrus.cli import _consume_site_flag
from papyrus_content import env, site_document, site_selection
from papyrus_content.cli_user_auth import AuthError, SiteSession, command, save_selection
from papyrus_content.graphql_authoring import PapyrusGraphQLAuthoringClient, create_authoring_client
from procedures.newsroom.tests.test_cli_multisite_auth import site

OTHER_BACKEND = 'https://file.appsync-api.us-east-1.amazonaws.com/graphql'
VARIABLES = ('PAPYRUS_GRAPHQL_AUTH', 'PAPYRUS_CLI_AUTH_CONFIG', 'PAPYRUS_SITE', 'PAPYRUS_SITE_ROOT', 'PAPYRUS_GRAPHQL_ENDPOINT',
             'PAPYRUS_TENANT_ID', 'PAPYRUS_IDENTITY_POOL_ID')


def _world(context):
    if getattr(context, 'selection', None) is not None:
        return context.selection
    temporary = tempfile.TemporaryDirectory()
    context.add_cleanup(temporary.cleanup)
    root = Path(temporary.name)
    (root/'work').mkdir()
    environment = patch.dict(os.environ, {'PAPYRUS_CLI_STATE_DIR': str(root/'state')})
    environment.start(); context.add_cleanup(environment.stop)
    for name in VARIABLES:
        os.environ.pop(name, None)
    here = os.getcwd()
    os.chdir(root/'work'); context.add_cleanup(lambda: os.chdir(here))
    engine = patch.object(env, 'PAPYRUS_ROOT', root/'engine')
    engine.start(); context.add_cleanup(engine.stop)
    context.add_cleanup(site_selection.uninstall)
    site_selection.install()
    site_document._not_served.clear()
    context.selection = type('World', (), {})()
    context.selection.root = root/'work'
    context.selection.documents = {}      # host -> the site file it serves (absent: none)
    context.selection.fetched = []
    context.selection.error = None
    context.selection.endpoint = None
    context.selection.client = None
    context.selection.stderr = ''
    context.selection.stdout = ''

    def fetch(origin, **options):
        context.selection.fetched.append(origin)
        return context.selection.documents.get(origin[len('https://'):])
    patcher = patch.object(site_document, 'fetch', fetch)
    patcher.start(); context.add_cleanup(patcher.stop)
    return context.selection


def _try(world, action):
    world.error = None
    try:
        return action()
    except Exception as error:
        world.error = str(error)
        return None


@given('the person is signed in to "{host}" only')
def signed_in_to_one(context, host):
    _world(context)
    save_selection(site(host))


@given('the person is signed in to "{first}" and "{second}"')
def signed_in_to_two(context, first, second):
    _world(context)
    save_selection(site(first)); save_selection(site(second))


@given('the person is signed in to no site')
def signed_in_to_none(context):
    _world(context)


@given('the working directory has no Amplify outputs file')
def no_outputs_file(context):
    _world(context)


@given('the working directory has an Amplify outputs file for another backend')
def outputs_for_another_backend(context):
    world = _world(context)
    (world.root/'amplify_outputs.json').write_text(json.dumps({
        'data': {'url': OTHER_BACKEND}, 'storage': {'bucket_name': 'bucket-of-the-file'}, 'auth': {'identity_pool_id': 'pool-of-the-file'}}))


@given('the working directory is the checkout of "{host}"')
def checkout_of(context, host):
    world = _world(context)
    (world.root/'infra').mkdir()
    (world.root/'infra'/'site.json').write_text(json.dumps({'cms': {'consoleOrigin': f'https://{host}'}}))


@given('the endpoint variable names the backend of "{host}"')
def endpoint_variable(context, host):
    _world(context)
    os.environ['PAPYRUS_GRAPHQL_ENDPOINT'] = site(host).graphql_endpoint


@given('the operator chose the IAM lane')
def iam_lane(context):
    _world(context)
    os.environ['PAPYRUS_GRAPHQL_AUTH'] = 'iam'


@given('the process is a Lambda, which never installs the site selection')
def lambda_process(context):
    _world(context)
    site_selection.uninstall()


@given('the person set the tenant variable to "{tenant}"')
def tenant_variable(context, tenant):
    _world(context)
    os.environ['PAPYRUS_TENANT_ID'] = tenant


@given('"{host}" publishes the tenant "{tenant}" in its site file')
def publishes_tenant(context, host, tenant):
    _world(context).documents[host] = {'tenant_id': tenant}


@given('"{host}" publishes no site file')
def publishes_no_site_file(context, host):
    _world(context).documents.pop(host, None)


@given('"{host}" publishes that it runs Papyrus {version}')
def publishes_version(context, host, version):
    _world(context).documents[host] = {'papyrus_version': version}


@given('the CLI kept no site file for "{host}"')
def kept_no_site_file(context, host):
    assert f'https://{host}' not in site_document.cached()


@when("a command asks for the site's GraphQL endpoint")
def ask_endpoint(context):
    world = _world(context)
    world.endpoint = _try(world, env.graphql_endpoint)


@when('a command asks for the site\'s GraphQL endpoint after the person names "{host}" with the leading site flag')
def ask_endpoint_with_flag(context, host):
    world = _world(context)
    assert _consume_site_flag(['--site', host, 'editorial', 'context']) == ['editorial', 'context']
    world.endpoint = _try(world, env.graphql_endpoint)


@when('a command asks for the site\'s GraphQL endpoint after the person sets the site variable to "{host}"')
def ask_endpoint_with_variable(context, host):
    world = _world(context)
    os.environ['PAPYRUS_SITE'] = host
    world.endpoint = _try(world, env.graphql_endpoint)


@when('the bucket and identity pool are read after the person names "{host}" with the leading site flag')
def read_bucket_and_pool(context, host):
    world = _world(context)
    _consume_site_flag(['--site', host, 'x', 'y'])
    world.bucket, world.pool = env.storage_bucket_from_amplify_outputs(), env.identity_pool_id_from_amplify_outputs()


@when('the person opens an authoring client')
def open_client(context):
    world = _world(context)
    world.client = _try(world, PapyrusGraphQLAuthoringClient)


@when('the person opens an authoring client with the tenant option "{tenant}"')
def open_client_with_tenant(context, tenant):
    world = _world(context)
    world.client = _try(world, lambda: create_authoring_client(tenant)[0])


@when('the person opens an authoring client for a command that reads every row')
def open_client_for_every_row(context):
    world = _world(context)
    world.client = _try(world, lambda: create_authoring_client(None, site_tenant=False)[0])


@when('the person asks which public files the CLI reads from "{host}"')
def public_files(context, host):
    _world(context)


@when('the person runs a command this CLI does not know')
def unknown_command(context):
    world = _world(context)
    from papyrus_content import cli
    world.error = None
    try:
        cli.dispatch('stories', 'no-such-command', [])
    except ValueError as error:
        world.error = str(error)


@given('"{host}" publishes login metadata and a site file saying it runs Papyrus {version}')
def publishes_login_and_site_file(context, host, version):
    world = _world(context)
    world.documents[host] = {'papyrus_version': version}
    world.login = site(host)


@when('the person runs "papyrus login {host}"')
def run_login(context, host):
    world = _world(context)
    session = type('Session', (), {'login': lambda self: {'subject': 's', 'label': 'l', 'publication': f'https://{host}'}, 'person_id': None})()
    out, err = StringIO(), StringIO()
    with patch('papyrus_content.cli_user_auth.discover', lambda value: world.login), \
            patch('papyrus_content.cli_user_auth.session_for', lambda config: session), \
            patch('papyrus_content.cli_doctor.installed_version', lambda: '5.72.0'), \
            redirect_stdout(out), redirect_stderr(err):
        world.exit_code = command(['login', host])
    world.stdout, world.stderr = out.getvalue(), err.getvalue()


@when('a remote login prints its approval URL')
def remote_login_prints(context):
    world = _world(context)

    class Redirected:
        line_buffering = False

        def reconfigure(self, line_buffering):
            self.line_buffering = line_buffering
    stream = Redirected()
    with patch('sys.stdout', stream), patch('papyrus_content.cli_user_auth.remote_login', lambda target, store, **options: {'subject': 's', 'label': 'l'}):
        SiteSession(site('a.anth.us'), store=object(), provider=object()).login_remote(expected_email=None)
    world.stream = stream


@then('the endpoint is the one "{host}" published')
def endpoint_is_sites(context, host):
    world = context.selection
    assert world.error is None, world.error
    assert world.endpoint == site(host).graphql_endpoint, world.endpoint


@then('the endpoint is the one in the outputs file')
def endpoint_is_files(context):
    assert context.selection.error is None, context.selection.error
    assert context.selection.endpoint == OTHER_BACKEND


@then('the command fails with a message that names "{text}"')
def fails_naming(context, text):
    assert context.selection.error and text in context.selection.error, context.selection.error


@then("the message does not tell a deployed site's editor to run a sandbox first")
def no_sandbox_first(context):
    message = context.selection.error
    assert message.index('papyrus login') < message.index('sandbox'), message
    assert 'for a sandbox' in message, message


@then('the command fails with a message saying the endpoint variable names a different backend')
def fails_conflict(context):
    assert 'PAPYRUS_GRAPHQL_ENDPOINT names a different backend' in (context.selection.error or ''), context.selection.error


@then('the command fails with a message listing "{first}" and "{second}"')
def fails_listing(context, first, second):
    assert context.selection.error and first in context.selection.error and second in context.selection.error, context.selection.error


@then('the message tells the person to name one with the leading site flag')
def message_names_flag(context):
    assert 'papyrus --site' in context.selection.error and 'PAPYRUS_SITE' in context.selection.error


@then('no site was chosen')
def no_site_chosen(context):
    assert context.selection.endpoint is None


@then('no signed-in site was used')
def no_signed_in_site_used(context):
    assert context.selection.endpoint is None
    assert 'a.anth.us' not in (context.selection.error or '')
    assert site('a.anth.us').graphql_endpoint != context.selection.endpoint


@then('neither is taken from that file')
def neither_from_file(context):
    assert context.selection.bucket is None and context.selection.pool is None


@then('the client is scoped to the tenant "{tenant}"')
def client_scoped(context, tenant):
    assert context.selection.error is None, context.selection.error
    assert context.selection.client.tenant_id == tenant


@then('the person set no tenant variable and passed no tenant option')
def no_explicit_tenant(context):
    assert 'PAPYRUS_TENANT_ID' not in os.environ


@then('the CLI kept the site file for next time')
def kept_site_file(context):
    assert site_document.cached()['https://a.anth.us']['tenant_id'] == 'machines-on-machines'


@then('the client has no tenant')
def client_has_no_tenant(context):
    assert context.selection.client.tenant_id is None


@then('nothing failed')
def nothing_failed(context):
    assert context.selection.error is None, context.selection.error


@then('the sign-in file is "{login_path}" and the site file is "{site_path}"')
def two_files(context, login_path, site_path):
    from papyrus_content.cli_user_auth import DISCOVERY_PATH, _OPTIONAL_FIELDS, _PUBLIC_FIELDS
    assert (DISCOVERY_PATH, site_document.SITE_DOCUMENT_PATH) == (login_path, site_path)
    assert not {'tenant_id', 'papyrus_version'} & (_PUBLIC_FIELDS | _OPTIONAL_FIELDS), 'the strict sign-in file gained a field'


@then('the failure still says the command is unsupported')
def still_unsupported(context):
    assert context.selection.error.startswith('Unsupported papyrus command: stories no-such-command'), context.selection.error


@then('it names "{host}" and version {version} and the upgrade command')
def names_upgrade(context, host, version):
    message = context.selection.error
    assert f'{host} runs {version}' in message and 'pipx upgrade papyrus-newsroom' in message, message


@then('the failure says only that the command is unsupported')
def only_unsupported(context):
    assert context.selection.error == 'Unsupported papyrus command: stories no-such-command', context.selection.error


@then('the login succeeds')
def login_succeeds(context):
    assert context.selection.exit_code == 0
    assert json.loads(context.selection.stdout)['publication'] == 'https://a.anth.us'


@then('a warning on standard error says this CLI is older than "{host}" and how to upgrade')
def warns_older(context, host):
    err = context.selection.stderr
    assert f'older than {host}' in err and 'pipx upgrade papyrus-newsroom' in err, err


@then('the line was flushed immediately')
def flushed(context):
    assert context.selection.stream.line_buffering is True


@given('a local pod is configured for the operator commands')
def local_pod(context):
    world = _world(context)
    pod = world.root/'pod'
    pod.mkdir()
    (world.root/'operator.yaml').write_text(f'local:\n  podPath: {pod}\n')
    patcher = patch.dict(os.environ, {'PAPYRUS_OPERATOR_CONFIG': str(world.root/'operator.yaml')})
    patcher.start(); context.add_cleanup(patcher.stop)
    os.environ.pop('PAPYRUS_BACKEND', None)


@when('an operator reference command picks its backend with no backend flag')
def operator_backend_default(context):
    from papyrus.operator.config import load_operator_config
    _world(context).backend = load_operator_config(corpus_key_override='some-corpus').backend


@when('an operator reference command picks its backend with the backend flag "{name}"')
def operator_backend_flag(context, name):
    from papyrus.operator.config import load_operator_config
    _world(context).backend = load_operator_config(backend_override=name, corpus_key_override='some-corpus').backend


@then('the backend is "{name}"')
def backend_is(context, name):
    assert _world(context).backend == name
