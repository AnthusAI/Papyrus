"""Credential-free OAuth behavior through the real CLI dispatcher/session code."""
import json
import os
from contextlib import redirect_stdout
from io import StringIO
import tempfile
from unittest.mock import patch
from behave import given, when, then
from papyrus_content.cli_user_auth import AuthConfig, Session, AuthError, OAuthError
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
    context.session = Session(context.auth_config,store=context.store,provider=context.provider,clock=lambda:context.clock[0],receive=receive)


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
    context.session = Session(context.auth_config,store=context.store,provider=context.provider,clock=lambda:context.clock[0],receive=lambda *a:context.interactions.append('unexpected browser'))
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
