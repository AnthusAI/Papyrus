"""The sign-in client a site names, `papyrus login --print-client`, and the fixed loopback port."""
import json
import socket
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from behave import given, then, when

from papyrus_content.cli_user_auth import AuthError, command, receive_code

LOOPBACK = 'http://127.0.0.1:38947/cli/callback'
SECRET_PREFIX = 'syntheticprefix'
CLIENT_SUFFIX = 'wxyz'


class _Opener:
    def __init__(self, body):
        self.body = body

    def open(self, request, timeout=None):
        body = json.dumps(self.body).encode()
        return type('Response', (), {'read': lambda self, n=-1: body, '__enter__': lambda self: self, '__exit__': lambda self, *a: False})()


def _login_file(callback_uri):
    return {
        'publication': 'https://newsroom.example.test', 'issuer': 'https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Synthetic',
        'client_id': SECRET_PREFIX + CLIENT_SUFFIX, 'oauth_domain': 'https://newsroom.auth.us-east-1.amazoncognito.com',
        'graphql_endpoint': 'https://synthetic.appsync-api.us-east-1.amazonaws.com/graphql', 'callback_uri': callback_uri,
    }


@given('a site whose login file names the main web client and the localhost 3001 callback')
def main_client(context):
    context.login_file = _login_file('http://localhost:3001/')


@given('a site whose login file names the federation client and the fixed loopback callback')
def federation_client(context):
    context.login_file = _login_file(LOOPBACK)


@when('the user runs "papyrus login --print-client" for that site')
def print_client(context):
    stream = StringIO()
    with patch('urllib.request.build_opener', lambda *handlers: _Opener(context.login_file)), redirect_stdout(stream):
        context.exit_code = command(['login', '--print-client', 'newsroom.example.test'])
    context.output = stream.getvalue()


@then('the output ends the client id with its last four characters only')
def suffix_only(context):
    assert json.loads(context.output)['client_id_suffix'] == CLIENT_SUFFIX
    assert SECRET_PREFIX not in context.output


@then('the output shows the localhost 3001 callback and signs in to nothing')
def shows_main_callback(context):
    assert json.loads(context.output)['callback_uri'] == 'http://localhost:3001/'
    assert context.exit_code == 0


@then('the output shows the fixed loopback callback and signs in to nothing')
def shows_loopback(context):
    assert json.loads(context.output)['callback_uri'] == LOOPBACK
    assert context.exit_code == 0


@given('another program is listening on the fixed loopback port')
def port_taken(context):
    holder = socket.socket()
    holder.bind(('127.0.0.1', 38947))
    holder.listen(1)
    context.add_cleanup(holder.close)


@when('the CLI waits for the sign-in callback on the fixed loopback callback')
def wait_for_callback(context):
    context.error = None
    try:
        receive_code(LOOPBACK, 'https://newsroom.auth.example.test/oauth2/authorize', 'state', 1)
    except AuthError as error:
        context.error = str(error)


@then('it stops saying the local port is already in use and to run the login again')
def refused(context):
    assert context.error and '38947' in context.error and 'already in use' in context.error and 'run the login again' in context.error
