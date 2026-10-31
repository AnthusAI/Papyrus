"""Prospectus authorize: the Lambda helper through ``require_authorized``, the CLI's error mapping, and the synth tests."""
import io
import json
import subprocess
from pathlib import Path

from behave import given, then, when

from papyrus_content import graphql_http
from papyrus_content.operator_errors import GraphQLRequestError, exit_code_for_error
from papyrus_content.prospectus_authorize import AccountRequired, AuthorizationDenied, ReenrollmentRequired, require_authorized

ROOT = Path(__file__).resolve().parents[2]
ENDPOINT = 'https://abc123defg.execute-api.us-east-1.amazonaws.com/api/'
ENVIRONMENT = {'PAPYRUS_PROSPECTUS_AUTHORIZE': 'true', 'PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT': ENDPOINT}
SITE_FUNCTION = {'userArn': 'arn:aws:sts::123456789012:assumed-role/site-function/session', 'accountId': '123456789012'}


class Prospectus:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error, self.calls = status, body, error, []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body)))
        if self.error:
            raise self.error
        return self.status, self.body


def _allowed(account):
    return {'allowed': True, 'accountId': account, 'personId': 'person-0001', 'product': 'papyrus-example', 'role': 'owner', 'operation': 'console:write', 'revision': 1}


def _event(account):
    headers = {'X-Prospectus-Human-Token': 'token-0001'}
    if account:
        headers['X-Prospectus-Account'] = account
    return {'identity': {'sub': 'sub-0001', 'claims': {'sub': 'sub-0001'}}, 'request': {'headers': headers}}


def _run(context, event, prospectus):
    context.prospectus = prospectus
    context.authorize_outcome = None
    try:
        context.authorize_result = require_authorized(event, 'publishItem', environment=ENVIRONMENT, transport=prospectus)
        context.authorize_outcome = 'proceeds'
    except ReenrollmentRequired as error:
        context.authorize_outcome, context.authorize_error = 'reenrollment', error
    except AccountRequired as error:
        context.authorize_outcome, context.authorize_error = 'account', error
    except AuthorizationDenied as error:
        context.authorize_outcome, context.authorize_error = 'denied', error


def _cli_message(context, error_type):
    reply = json.dumps({'errors': [{'errorType': error_type, 'message': 'raw'}]}).encode()
    originals = (graphql_http.load_dotenv, graphql_http.graphql_endpoint, graphql_http.graphql_request_headers, graphql_http.urllib.request.urlopen)
    graphql_http.load_dotenv = lambda: None
    graphql_http.graphql_endpoint = lambda: 'https://example.test/graphql'
    graphql_http.graphql_request_headers = lambda **_: {}
    graphql_http.urllib.request.urlopen = lambda *_, **__: io.BytesIO(reply)
    try:
        graphql_http.execute_graphql('query { x }')
    except GraphQLRequestError as error:
        return error
    finally:
        (graphql_http.load_dotenv, graphql_http.graphql_endpoint, graphql_http.graphql_request_headers, graphql_http.urllib.request.urlopen) = originals
    raise AssertionError('the CLI did not fail')


@given('a site that has switched on Prospectus authorization')
def switched_on(context):
    context.account = None


@given('a signed-in person who chose the account "{account}"')
def chose_account(context, account):
    context.account = account


@when('Prospectus allows "{account}" to write')
def prospectus_allows(context, account):
    _run(context, _event(context.account), Prospectus(200, _allowed(account)))


@when('Prospectus answers allowed, but for the account "{account}"')
def prospectus_answers_other(context, account):
    _run(context, _event(context.account), Prospectus(200, _allowed(account)))


@when('Prospectus says this login is no longer enrolled')
def prospectus_reenrollment(context):
    _run(context, _event(context.account), Prospectus(403, {'error': 'reenrollment_required'}))


@when('Prospectus cannot be reached')
def prospectus_unreachable(context):
    _run(context, _event(context.account), Prospectus(error=OSError('unreachable')))


@when('the person sends a request that names no account')
def no_account(context):
    _run(context, _event(None), Prospectus(200, _allowed(context.account)))


@when("the site's own function calls the operation with its role")
def site_function_calls(context):
    _run(context, {'identity': SITE_FUNCTION, 'request': {'headers': {}}}, Prospectus(403, {}))


@then('the operation proceeds')
def operation_proceeds(context):
    assert context.authorize_outcome == 'proceeds', context.authorize_outcome


@then('Prospectus was asked once, for "{operation}" on "{account}", with the person\'s own token')
def asked_once(context, operation, account):
    assert len(context.prospectus.calls) == 1
    url, headers, body = context.prospectus.calls[0]
    assert url.endswith(f'/v1/accounts/{account}/authorize') and body == {'operation': operation}
    assert headers['x-prospectus-human-token'] == 'token-0001'


@then('the operation is refused as not authorized')
def refused_not_authorized(context):
    assert context.authorize_outcome == 'denied', context.authorize_outcome


@then('the operation is refused as needing re-enrollment')
def refused_reenrollment(context):
    assert context.authorize_outcome == 'reenrollment', context.authorize_outcome


@then('the operation is refused as needing an account')
def refused_account(context):
    assert context.authorize_outcome == 'account', context.authorize_outcome
    assert context.prospectus.calls == []


@then('the CLI tells the person to run `papyrus login` again and exits with a failure')
def cli_reenrollment(context):
    error = _cli_message(context, 'ReenrollmentRequired')
    assert 'Run `papyrus login` again.' in str(error) and exit_code_for_error(error) != 0


@then('the CLI tells the person to choose an account and exits with a failure')
def cli_account(context):
    error = _cli_message(context, 'AccountRequired')
    assert 'papyrus account use <name>' in str(error) and exit_code_for_error(error) != 0


@then('the operation proceeds without asking Prospectus')
def proceeds_unasked(context):
    assert context.authorize_outcome == 'proceeds' and context.authorize_result is None
    assert context.prospectus.calls == []


@when('the backend is synthesized with Prospectus authorization off and then on')
def synthesized(context):
    context.synth = subprocess.run(['node', '--import', 'tsx', 'scripts/test-prospectus-authorize-synth.ts'], cwd=ROOT, capture_output=True, text=True, timeout=600)


@then('the backend with it off has no Prospectus data source, pipeline function, environment or permission')
def off_is_unchanged(context):
    assert context.synth.returncode == 0, context.synth.stdout + context.synth.stderr


@then('the backend with it on has all four')
def on_has_all(context):
    assert 'prospectus authorize synth: ok' in context.synth.stdout
