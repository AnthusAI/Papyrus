"""The signed-in lane is the CLI's default; the operator lane (IAM) only when named. Real code; no network, keychain or AWS."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from unittest.mock import patch

from behave import given, then, when

from papyrus import cli as papyrus_cli
from papyrus.operator.backends.cloud import CloudBackend
from papyrus.operator.config import OperatorConfig
from papyrus_content import cli_user_auth, graphql_http
from papyrus_content.cli_user_auth import AuthError, save_selection
from papyrus_content.operator_errors import OperatorError
from procedures.newsroom.tests.test_cli_multisite_auth import site

REPO = Path(__file__).resolve().parents[2]
SITE = site('a.anth.us')
SESSION_HEADERS = {'Authorization': 'signed-in-token'}
AWS_HEADERS = {'Authorization': 'AWS4-HMAC-SHA256 signed'}


class _Session:
    def __init__(self, world, expired=False):
        self.world, self.expired = world, expired

    def headers(self, endpoint):
        self.world.session_used = True
        if self.expired:
            raise AuthError('Your session for a.anth.us has expired; run `papyrus login a.anth.us`.')
        return dict(SESSION_HEADERS)


def _world(context):
    world = getattr(context, 'lane_world', None)
    if world is not None:
        return world
    world = context.lane_world = type('World', (), {})()
    world.signed, world.session_used, world.error, world.headers, world.local_runs = [], False, None, None, 0
    world.session = None
    for name, value in {'AWS_ACCESS_KEY_ID': 'AKIAEXAMPLE', 'AWS_SECRET_ACCESS_KEY': 'secret', 'PAPYRUS_GRAPHQL_ENDPOINT': SITE.graphql_endpoint}.items():
        patcher = patch.dict(os.environ, {name: value})
        patcher.start(); context.add_cleanup(patcher.stop)
    lane = patch.dict(os.environ, {})   # restores PAPYRUS_GRAPHQL_AUTH and PAPYRUS_SITE however a scenario sets them
    lane.start(); context.add_cleanup(lane.stop)

    def sign(endpoint, body, session=None):
        graphql_http._aws_credentials()
        world.signed.append(endpoint)
        return dict(AWS_HEADERS)
    for target, replacement in ((graphql_http, 'iam_signed_graphql_headers'),):
        patcher = patch.object(target, replacement, sign)
        patcher.start(); context.add_cleanup(patcher.stop)
    credentials = patch.object(graphql_http, '_aws_credentials', lambda: object())
    credentials.start(); context.add_cleanup(credentials.stop)
    sessions = patch.object(cli_user_auth, 'session_for', lambda config: world.session)
    sessions.start(); context.add_cleanup(sessions.stop)
    return world


def _try(world, action):
    world.error = None
    try:
        return action()
    except (OperatorError, AuthError, ValueError) as error:
        world.error = error
        return None


@given('a machine with AWS credentials in its environment and no Papyrus sign-in')
def step_machine(context):
    _world(context)
    assert not os.environ.get('PAPYRUS_GRAPHQL_AUTH')


@given('a signed-in session for the site')
def step_session(context):
    world = _world(context)
    save_selection(SITE)
    world.session = _Session(world)


@given('a signed-in session for the site whose sign-in has expired')
def step_expired_session(context):
    world = _world(context)
    save_selection(SITE)
    world.session = _Session(world, expired=True)


@given('the process names the operator lane with PAPYRUS_GRAPHQL_AUTH=iam')
def step_iam_variable(context):
    _world(context)
    os.environ['PAPYRUS_GRAPHQL_AUTH'] = 'iam'


@given('the AWS credentials have expired')
def step_no_credentials(context):
    world = _world(context)
    def missing():
        raise ValueError('No AWS credentials found for IAM AppSync signing. Set AWS_PROFILE to an SSO or role profile.')
    patcher = patch.object(graphql_http, '_aws_credentials', missing)
    patcher.start(); context.add_cleanup(patcher.stop)


@when('a command asks for headers to call the site API')
def step_headers(context):
    world = _world(context)
    world.headers = _try(world, lambda: graphql_http.graphql_request_headers(endpoint=SITE.graphql_endpoint, body=b'{}'))


@when('the command line starts with "{flags}"')
def step_flags(context, flags):
    world = _world(context)
    world.rest = _try(world, lambda: papyrus_cli._consume_leading_flags([*flags.split(), 'references', 'list']))


@when('the command line is "{line}"')
def step_line(context, line):
    world = _world(context)
    world.rest = _try(world, lambda: papyrus_cli._consume_leading_flags(line.split()))


@when('a knowledge query runs with execution "{execution}"')
def step_knowledge_query(context, execution):
    world = _world(context)
    os.environ.pop('PAPYRUS_GRAPHQL_ENDPOINT', None)
    from papyrus_knowledge_query import cli as knowledge_cli

    def local(payload, services):
        world.local_runs += 1
        return {'ok': True}
    patcher = patch.object(knowledge_cli, 'run_knowledge_query', local)
    patcher.start(); context.add_cleanup(patcher.stop)
    services = patch.object(knowledge_cli, 'build_environment_services', lambda: None)
    services.start(); context.add_cleanup(services.stop)
    arguments = argparse.Namespace(execution=execution, site='', input='', query='who', text='who')
    loader = patch.object(knowledge_cli, '_input_from_args', lambda args: {'query': 'who'})
    loader.start(); context.add_cleanup(loader.stop)
    _try(world, lambda: knowledge_cli.run_knowledge_query_cli(arguments))


@when('the operator CLI checks that it can reach the site')
def step_operator_backend(context):
    world = _world(context)
    config = OperatorConfig(backend='cloud', default_corpus_key=None, publication_key=None, pod_path=None, default_story=None,
                            graphql_endpoint=SITE.graphql_endpoint, config_path=None, fixture_root=None)
    _try(world, lambda: CloudBackend(config)._ensure_auth())


@then('it refuses with a message that names "{first}" and "{second}"')
def step_refuses_naming_both(context, first, second):
    error = _world(context).error
    assert error is not None, 'expected a refusal'
    assert first in str(error) and second in str(error), str(error)


@then('it refuses with a message that names "{text}"')
def step_refuses_naming(context, text):
    error = _world(context).error
    assert error is not None and text in str(error), str(error)


@then('the refusal exits with status 2')
def step_exit_two(context):
    error = _world(context).error
    assert isinstance(error, OperatorError) and error.exit_code == 2, repr(error)


@then('nothing was signed with the AWS credentials')
def step_not_signed(context):
    assert _world(context).signed == []


@then('the headers come from the signed-in session')
def step_session_headers(context):
    world = _world(context)
    assert world.error is None, world.error
    assert world.headers == SESSION_HEADERS


@then("it refuses with the session's own message to sign in again")
def step_session_refusal(context):
    error = _world(context).error
    assert isinstance(error, AuthError) and 'papyrus login a.anth.us' in str(error), repr(error)


@then('the request is signed with the AWS credentials')
def step_signed(context):
    world = _world(context)
    if world.headers is None and world.error is None:
        world.headers = _try(world, lambda: graphql_http.graphql_request_headers(endpoint=SITE.graphql_endpoint, body=b'{}'))
    assert world.error is None, world.error
    assert world.headers == AWS_HEADERS and world.signed == [SITE.graphql_endpoint]


@then('it refuses with a message about AWS credentials')
def step_aws_refusal(context):
    error = _world(context).error
    assert error is not None and 'AWS credentials' in str(error), repr(error)


@then('the signed-in session was not used')
def step_session_unused(context):
    assert _world(context).session_used is False


@then('it refuses with a message that says only one of them may speak')
def step_conflict(context):
    error = _world(context).error
    assert error is not None and 'only one of them speaks' in str(error), repr(error)


@then('the lane is "{lane}" and the site is "{host}"')
def step_lane_and_site(context, lane, host):
    world = _world(context)
    assert world.error is None, world.error
    assert os.environ.get('PAPYRUS_GRAPHQL_AUTH') == lane and os.environ.get('PAPYRUS_SITE') == host


@then('the command that runs is "{words}"')
def step_rest(context, words):
    assert _world(context).rest == words.split()


@then('the local engine did not run')
def step_local_not_run(context):
    assert _world(context).local_runs == 0


# --- workers name the operator lane in their own definitions ---------------------------------------------------------

_ENDPOINT_SETTERS = re.compile(r'PAPYRUS_GRAPHQL_ENDPOINT')


@then('no function definition sets PAPYRUS_GRAPHQL_ENDPOINT except through the shared site API access')
def step_no_bare_endpoint(context):
    offenders = []
    for path in (REPO/'amplify').rglob('*.ts'):
        if 'node_modules' in path.parts or path.name == 'site-api-access.ts':
            continue
        text = path.read_text(encoding='utf-8')
        if _ENDPOINT_SETTERS.search(text):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f'set the endpoint with connectToSiteApi or siteApiEnvironment instead: {offenders}'


@then('the shared site API access names PAPYRUS_GRAPHQL_AUTH iam with every endpoint')
def step_shared_access(context):
    text = (REPO/'amplify'/'site-api-access.ts').read_text(encoding='utf-8')
    assert 'PAPYRUS_GRAPHQL_AUTH: "iam"' in text
    assert re.search(r'return \{ PAPYRUS_GRAPHQL_ENDPOINT: graphqlEndpoint, \.\.\.OPERATOR_LANE \}', text)


def _monitoring_workers_name_the_lane() -> bool:
    text = (REPO/'infra'/'monitoring'/'papyrus-monitoring.yaml').read_text(encoding='utf-8')
    functions = re.split(r'\n  \w+:\n    Type: AWS::Lambda::Function', text)[1:]
    graphql_workers = [body for body in functions if 'monitoring_router.handler' in body]
    return bool(graphql_workers) and all('PAPYRUS_GRAPHQL_AUTH: iam' in body for body in graphql_workers)


def _child_environment_names_the_lane() -> bool:
    from papyrus_content.procedure_runner import child_environment
    return child_environment({'appsyncEndpoint': SITE.graphql_endpoint}, None)['PAPYRUS_GRAPHQL_AUTH'] == 'iam'


WORKERS = {
    'the knowledge run image': lambda: 'PAPYRUS_GRAPHQL_AUTH=iam' in (REPO/'infra'/'knowledge-run'/'Dockerfile').read_text(encoding='utf-8'),
    'the procedure runner image': lambda: 'PAPYRUS_GRAPHQL_AUTH=iam' in (REPO/'infra'/'procedures'/'Dockerfile').read_text(encoding='utf-8'),
    "the procedure runner's child processes": _child_environment_names_the_lane,
    "the monitoring stack's GraphQL workers": _monitoring_workers_name_the_lane,
    "the staging build's drafts export": lambda: 'PAPYRUS_GRAPHQL_AUTH=iam' in (REPO/'infra'/'amplify-app-shell'/'lib'/'build-specs.ts').read_text(encoding='utf-8')
                                         and '${BUILD_ROLE_LANE} papyrus ops content export-published --drafts' in (REPO/'infra'/'amplify-app-shell'/'lib'/'build-specs.ts').read_text(encoding='utf-8'),
}


@then('the worker "{worker}" names the operator lane')
def step_worker(context, worker):
    assert WORKERS[worker](), f'{worker} does not name PAPYRUS_GRAPHQL_AUTH=iam'
