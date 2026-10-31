import json
import tempfile
import urllib.error
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

from behave import given, then, when

from papyrus_content import cli_user_auth
from papyrus_content.cli_user_auth import AuthError, SiteSession
from procedures.newsroom.tests import test_cli_login_challenges as support


@given('a site with enrollment switched on and a started remote login')
def started(context):
    context.prospectus = support.FakeProspectus()
    context.broker = support.broker_handler.Broker(
        support.transactions.MemoryTransactions(),
        support.broker_handler.BrokerConfig('site-client', (support.ORIGIN,), support.ORIGIN + '/cli/approve', support.ORIGIN + '/cli/callback'))
    context.pages = support.challenge_pages(context.broker, context.prospectus)
    context.transaction = support.start(context.broker)


@when('the person approves it')
def approve(context):
    context.answer = support.approve(context.pages, context.transaction)


@when('the person approves it but Prospectus answers no usable challenge')
def approve_unusable(context):
    context.prospectus.status = 503
    context.answer = support.approve(context.pages, context.transaction)


@then('Prospectus was asked for a challenge bound to the digest of the transaction, never the transaction itself')
def digest(context):
    [(url, _, body)] = context.prospectus.calls
    assert url.endswith('/v1/identities/google/challenge')
    assert list(body) == ['loginStateDigest'] and body['loginStateDigest'] != context.transaction and len(body['loginStateDigest']) == 64


@then("the Google sign-in uses the challenge's nonce")
def nonce(context):
    assert parse_qs(urlsplit(dict(context.answer.headers)['Location']).query)['nonce'] == [support.NONCE]


@then('the waiting CLI receives the signed challenge as its enrollment')
def enrollment(context):
    from http.cookies import SimpleCookie
    jar = SimpleCookie()
    for name, value in context.answer.headers:
        if name.lower() == 'set-cookie':
            jar.load(value)
    state = parse_qs(urlsplit(dict(context.answer.headers)['Location']).query)['state'][0]
    context.pages.callback({'state': state, 'code': 'c'}, {'__Secure-cli_login_nonce': jar['__Secure-cli_login_nonce'].value})
    status, collected = context.broker.poll({'transaction': context.transaction, 'poll_secret': 'p'}, '198.51.100.1')
    assert collected['enrollment'] == support.CHALLENGE_TOKEN


@then('the approval page says the service is unavailable')
def unavailable(context):
    assert context.answer.status == 503 and 'unavailable' in context.answer.body


@then('the transaction is still unbound')
def unbound(context):
    assert context.broker.describe({'transaction': context.transaction})['ok'] is True


def _refusal(status, code):
    return urllib.error.HTTPError(support.ORIGIN + '/cli/enroll', status, 'x', {}, BytesIO(json.dumps({'error': code, 'message': 'internal detail'}).encode()))


def _remote(context, opener):
    context.state_dir = tempfile.TemporaryDirectory()
    context.old_state = cli_user_auth.os.environ.get('PAPYRUS_CLI_STATE_DIR')
    cli_user_auth.os.environ['PAPYRUS_CLI_STATE_DIR'] = context.state_dir.name
    context.stored = []
    context.session = SiteSession(support.config(), enroll_opener=opener)
    context.error = None


@given('a remote login whose enrollment the site refuses as login_not_enrollable')
def refuses_main(context):
    _remote(context, support.Opener(error=_refusal(403, 'login_not_enrollable')))


@given('a remote login whose enrollment the site refuses as reenrollment_required')
def refuses_rebound(context):
    _remote(context, support.Opener(error=_refusal(401, 'reenrollment_required')))


@given('a remote login the site enrolls as a Person')
def enrolls(context):
    _remote(context, support.Opener(support.Reply(b'{"person": {"id": "person-1"}}')))


@given('a remote login whose enrollment fails with an internal error')
def internal(context):
    _remote(context, support.Opener(error=_refusal(500, 'internal detail code')))


@when('the CLI finishes the code exchange')
def finish(context):
    tokens = {'access_token': 'a.b.c', 'id_token': 'd.e.f'}

    def fake_remote_login(target, store_token_set, *, enroll=None, **options):
        enroll(tokens, 'T1', support.CHALLENGE_TOKEN)
        context.stored.append(tokens)
        return {'subject': 's', 'label': 'l'}

    original = cli_user_auth.remote_login
    cli_user_auth.remote_login = fake_remote_login
    try:
        context.session.login_remote()
        cli_user_auth.save_selection(support.config())
        cli_user_auth.record_person(support.ORIGIN, context.session.person_id)
    except AuthError as error:
        context.error = str(error)
    finally:
        cli_user_auth.remote_login = original


@then('it stores no session and records no person')
def nothing_stored(context):
    assert context.stored == [] and cli_user_auth.enrolled_person(support.ORIGIN) is None
    _restore(context)


@then('it stores no session')
def no_session(context):
    assert context.stored == []
    _restore(context)


@then("it says plainly that the site's sign-in client is not registered for enrollment")
def plain(context):
    assert 'login_not_enrollable' in context.error and 'not registered' in context.error


@then('it says to run `papyrus login` again')
def again(context):
    assert 'Run `papyrus login` again.' in context.error


@then("the Person's id is recorded for the site in the CLI's registry file")
def recorded(context):
    assert cli_user_auth.enrolled_person(support.ORIGIN) == 'person-1'


@then('the registry file holds no token')
def no_token(context):
    assert 'a.b.c' not in cli_user_auth.selection_path().read_text()
    _restore(context)


@then('the message names only the code and a short reason')
def only_code(context):
    assert 'internal detail' not in context.error
    _restore(context)


def _restore(context):
    if context.old_state is None:
        cli_user_auth.os.environ.pop('PAPYRUS_CLI_STATE_DIR', None)
    else:
        cli_user_auth.os.environ['PAPYRUS_CLI_STATE_DIR'] = context.old_state
    context.state_dir.cleanup()


@given('a site that has switched enrollment on and a local login')
def local_enrolling(context):
    _remote(context, support.Opener(support.Reply(b'{"person": {"id": "person-1"}}')))
    context.enrolls = True


@given('a site that has not switched enrollment on and a local login')
def local_not_enrolling(context):
    _remote(context, support.Opener(support.Reply(b'{"person": {"id": "person-1"}}')))
    context.enrolls = False


@when('the CLI signs in locally')
def sign_in_locally(context):
    context.hooks = []

    def fake_login(*, prepare=None, enroll=None):
        context.hooks.append(prepare is not None and enroll is not None)
        if prepare:
            enroll({'access_token': 'a.b.c', 'id_token': 'd.e.f'}, 'state-1', support.CHALLENGE_TOKEN)
        return {'subject': 's', 'label': 'l'}

    context.session._session.login = fake_login
    cli_user_auth.site_enrolls = lambda *arguments, **keywords: context.enrolls
    context.session.login()
    cli_user_auth.record_person(support.ORIGIN, context.session.person_id)


@then("it asked the site for a challenge bound to its own state and used the challenge's nonce")
def local_challenge(context):
    opener = support.Opener(support.Reply(json.dumps({'nonce': support.NONCE, 'challengeToken': support.CHALLENGE_TOKEN}).encode()))
    assert cli_user_auth.challenge_from_site is not None
    assert support.REAL_CHALLENGE_FROM_SITE(support.config(), 'state-1', opener=opener) == (support.NONCE, support.CHALLENGE_TOKEN)
    assert opener.requests[0].full_url.endswith('/cli/challenge?state=state-1')


@then('it enrolled the finished login with that state and recorded the Person')
def local_enrolled(context):
    assert json.loads(context.session.enroll_opener.requests[0].data)['loginState'] == 'state-1'
    assert cli_user_auth.enrolled_person(support.ORIGIN) == 'person-1'
    _restore(context)


@then('it passed no enrollment hooks and recorded no Person')
def local_unchanged(context):
    assert context.hooks == [False] and cli_user_auth.enrolled_person(support.ORIGIN) is None
    _restore(context)
