"""Remote CLI login enrollment in the pages function, against the real cli-login broker in memory (no AWS, no network)."""
import hashlib
import importlib.util
import json
import sys
import urllib.error
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from cli_login.broker import handler as broker_handler
from cli_login.broker import transactions

from papyrus_content import cli_user_auth
from papyrus_content.cli_user_auth import AuthError, enroll_with_site

PAGES = Path(__file__).resolve().parents[3] / "amplify/functions/cli-login-pages"
sys.path.insert(0, str(PAGES))
from login_challenges import LoginChallenges, Unavailable  # noqa: E402

_spec = importlib.util.spec_from_file_location("cli_login_pages_handler_enrollment", PAGES / "handler.py")
handler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(handler)

ORIGIN = "https://site.example.test"
API = "https://abc123.execute-api.us-east-1.amazonaws.com/api"
AUTH = "https://synthetic.auth.us-east-1.amazoncognito.com"
CHALLENGE_TOKEN = "v1.k1." + "p" * 40 + "." + "m" * 43
NONCE = "N" * 43
CHALLENGE_ID = str(uuid.uuid4())
NOW = 2_000_000_000


class FakeProspectus:
    def __init__(self, status=200, answer=None):
        self.calls = []
        self.status = status
        self.answer = answer if answer is not None else {
            "challengeId": CHALLENGE_ID, "nonce": NONCE, "expiresAt": NOW + 300, "challengeToken": CHALLENGE_TOKEN}

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body)))
        return self.status, self.answer


@pytest.fixture
def broker():
    return broker_handler.Broker(
        transactions.MemoryTransactions(),
        broker_handler.BrokerConfig("site-client", (ORIGIN,), ORIGIN + "/cli/approve", ORIGIN + "/cli/callback"))


def pages_for(broker, prospectus):
    pages = handler.pages_from_environment(
        {"BROKER_FUNCTION_ARN": "arn", "AUTHORIZE_ENDPOINT": AUTH + "/oauth2/authorize", "PRODUCT": "Papyrus", "PRIVILEGES": "x",
         "PROSPECTUS_ACCOUNTS_API": API},
        post=prospectus)
    pages.broker = broker.handle
    return pages


def challenge_pages(broker, prospectus):
    challenges = LoginChallenges(API, prospectus, clock=lambda: NOW)
    from cli_login.broker.pages import ApprovalPages
    return ApprovalPages(broker.handle, authorize_endpoint=AUTH + "/oauth2/authorize", product="Papyrus", privileges="x",
                         identity_provider="Google", prepare=challenges.prepare)


def start(broker):
    _, answer = broker.start({
        "protocol": 1, "client_id": "site-client", "target": ORIGIN, "code_challenge": "c" * 43, "code_challenge_method": "S256",
        "poll_secret_hash": broker_handler.sha256_hex("p"), "nonce": "n" * 16,
        "requester": {"host": "cloud-box", "version": "0.3.0", "note": "nightly"}}, "198.51.100.1")
    return answer["transaction"]


def approve(pages, transaction):
    from http.cookies import SimpleCookie
    shown = pages.approve("GET", {"t": transaction}, {}, {})
    jar = SimpleCookie()
    for name, value in shown.headers:
        if name.lower() == "set-cookie":
            jar.load(value)
    csrf = jar["__Secure-cli_login_csrf"].value
    return pages.approve("POST", {}, {"t": transaction, "csrf": csrf, "action": "approve", "confirm": "yes"}, {"__Secure-cli_login_csrf": csrf})


def test_approving_binds_a_challenge_to_the_transaction_digest_and_returns_its_nonce(broker):
    prospectus = FakeProspectus()
    pages = challenge_pages(broker, prospectus)
    transaction = start(broker)
    answer = approve(pages, transaction)
    assert answer.status == 303
    [(url, headers, body)] = prospectus.calls
    assert url == API + "/v1/identities/google/challenge"
    assert body == {"loginStateDigest": hashlib.sha256(transaction.encode()).hexdigest()}
    location = dict(answer.headers)["Location"]
    assert parse_qs(urlsplit(location).query)["nonce"] == [NONCE]
    assert broker.describe({"transaction": transaction})["ok"] is False


@pytest.mark.parametrize("status,answer", [
    (503, {"error": "unavailable"}),
    (429, {"message": "Too Many Requests"}),
    (200, {"challengeId": CHALLENGE_ID, "nonce": NONCE, "expiresAt": NOW + 300}),
    (200, {"challengeId": "not-a-uuid", "nonce": NONCE, "expiresAt": NOW + 300, "challengeToken": CHALLENGE_TOKEN}),
    (200, {"challengeId": CHALLENGE_ID, "nonce": "short", "expiresAt": NOW + 300, "challengeToken": CHALLENGE_TOKEN}),
    (200, {"challengeId": CHALLENGE_ID, "nonce": NONCE, "expiresAt": NOW - 1, "challengeToken": CHALLENGE_TOKEN}),
    (200, {"challengeId": CHALLENGE_ID, "nonce": NONCE, "expiresAt": NOW + 301, "challengeToken": CHALLENGE_TOKEN}),
    (200, {"challengeId": CHALLENGE_ID, "nonce": NONCE, "expiresAt": NOW + 300, "challengeToken": "forged"}),
    (200, {"challengeId": CHALLENGE_ID, "nonce": NONCE, "expiresAt": NOW + 300, "challengeToken": "v1.K1.x.y"}),
])
def test_an_unusable_challenge_binds_nothing(broker, status, answer):
    pages = challenge_pages(broker, FakeProspectus(status, answer))
    transaction = start(broker)
    response = approve(pages, transaction)
    assert response.status == 503
    assert broker.describe({"transaction": transaction})["ok"] is True


def test_a_transport_failure_binds_nothing_and_names_no_detail(broker):
    def failing(url, headers, body):
        raise OSError("secret internal detail")
    with pytest.raises(Unavailable) as raised:
        LoginChallenges(API, failing, clock=lambda: NOW).prepare("T" * 22, {})
    assert "secret" not in str(raised.value)


def test_the_enrollment_reaches_the_polling_cli(broker):
    pages = challenge_pages(broker, FakeProspectus())
    transaction = start(broker)
    redirect = approve(pages, transaction)
    from http.cookies import SimpleCookie
    jar = SimpleCookie()
    for name, value in redirect.headers:
        if name.lower() == "set-cookie":
            jar.load(value)
    state = parse_qs(urlsplit(dict(redirect.headers)["Location"]).query)["state"][0]
    pages.callback({"state": state, "code": "auth-code"}, {"__Secure-cli_login_nonce": jar["__Secure-cli_login_nonce"].value})
    status, collected = broker.poll({"transaction": transaction, "poll_secret": "p"}, "198.51.100.1")
    assert (status, collected["nonce"], collected["enrollment"]) == (200, NONCE, CHALLENGE_TOKEN)


def test_a_site_without_the_prospectus_endpoint_has_no_enrollment_hook():
    assert handler.prepare_from_environment({}) is None
    assert handler.prepare_from_environment({"PROSPECTUS_ACCOUNTS_API": " "}) is None


def test_the_endpoint_must_be_an_execute_api_https_origin():
    with pytest.raises(ValueError):
        LoginChallenges("http://abc123.execute-api.us-east-1.amazonaws.com/api")
    with pytest.raises(ValueError):
        LoginChallenges("https://example.test/api")


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *arguments):
        return False

    def read(self, limit=-1):
        return self.body


class Opener:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.requests = reply, error, []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.reply


def config():
    return cli_user_auth.AuthConfig(
        publication=ORIGIN, issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_x", client_id="c",
        oauth_domain=AUTH, graphql_endpoint="https://g.example.test/graphql", callback_uri="http://127.0.0.1:38947/cli/callback")


def refusal(status, code):
    return urllib.error.HTTPError(ORIGIN + "/cli/enroll", status, "x", {}, BytesIO(json.dumps({"error": code, "message": "m"}).encode()))


def test_the_cli_enrolls_with_the_site_and_returns_the_person():
    opener = Opener(Reply(b'{"person": {"id": "person-1"}}'))
    person = enroll_with_site(config(), {"access_token": "a.b.c", "id_token": "d.e.f"}, "T1", CHALLENGE_TOKEN, opener=opener)
    assert person == "person-1"
    [request] = opener.requests
    assert request.full_url == ORIGIN + "/cli/enroll"
    assert request.get_header("Authorization") == "Bearer a.b.c"
    assert json.loads(request.data) == {"challengeToken": CHALLENGE_TOKEN, "idToken": "d.e.f", "loginState": "T1"}


def test_a_site_without_a_challenge_is_not_enrolled_and_not_asked():
    opener = Opener()
    assert enroll_with_site(config(), {"access_token": "a", "id_token": "b"}, "T1", None, opener=opener) is None
    assert opener.requests == []


def test_reenrollment_required_tells_the_person_to_log_in_again():
    with pytest.raises(AuthError) as raised:
        enroll_with_site(config(), {"access_token": "a", "id_token": "b"}, "T1", CHALLENGE_TOKEN, opener=Opener(error=refusal(401, "reenrollment_required")))
    assert str(raised.value) == "This login could not be enrolled with Prospectus (reenrollment_required). Run `papyrus login` again."


def test_a_login_on_the_main_client_is_refused_with_a_plain_reason():
    with pytest.raises(AuthError) as raised:
        enroll_with_site(config(), {"access_token": "a", "id_token": "b"}, "T1", CHALLENGE_TOKEN, opener=Opener(error=refusal(403, "login_not_enrollable")))
    assert "login_not_enrollable" in str(raised.value) and "not registered" in str(raised.value)


def test_unknown_codes_and_outages_say_no_more_than_the_code():
    with pytest.raises(AuthError) as raised:
        enroll_with_site(config(), {"access_token": "a", "id_token": "b"}, "T1", CHALLENGE_TOKEN, opener=Opener(error=OSError("detail")))
    assert "unavailable" in str(raised.value) and "detail" not in str(raised.value)


def test_a_failed_enrollment_stores_no_session(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path))
    stored = []
    session = cli_user_auth.SiteSession(config(), store=None, enroll_opener=Opener(error=refusal(403, "login_not_enrollable")))
    from cli_login import remote
    tokens = {"access_token": "a", "id_token": "b"}

    def fake_remote_login(target, store_token_set, *, enroll=None, **options):
        enroll(tokens, "T1", CHALLENGE_TOKEN)
        stored.append(store_token_set(tokens))

    monkeypatch.setattr(cli_user_auth, "remote_login", fake_remote_login)
    with pytest.raises(AuthError):
        session.login_remote()
    assert stored == []
    assert cli_user_auth.enrolled_person(ORIGIN) is None


def test_the_person_id_is_recorded_next_to_the_registry_without_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path))
    cli_user_auth.save_selection(config())
    cli_user_auth.record_person(ORIGIN, "person-1")
    assert cli_user_auth.enrolled_person(ORIGIN) == "person-1"
    cli_user_auth.save_selection(config())
    assert cli_user_auth.enrolled_person(ORIGIN) == "person-1"
    assert "token" not in (tmp_path / "user-session.json").read_text()


REAL_SITE_ENROLLS = cli_user_auth.site_enrolls
REAL_CHALLENGE_FROM_SITE = cli_user_auth.challenge_from_site


def test_a_site_enrolls_only_when_its_challenge_route_exists():
    assert REAL_SITE_ENROLLS(config(), opener=Opener(error=refusal(400, "invalid_request"))) is True
    assert REAL_SITE_ENROLLS(config(), opener=Opener(error=refusal(404, "cli_enrollment_not_configured"))) is False
    assert REAL_SITE_ENROLLS(config(), opener=Opener(error=OSError("down"))) is False


def test_a_local_login_asks_for_a_challenge_bound_to_its_own_state():
    opener = Opener(Reply(json.dumps({"nonce": NONCE, "challengeToken": CHALLENGE_TOKEN}).encode()))
    assert REAL_CHALLENGE_FROM_SITE(config(), "state_1-A", opener=opener) == (NONCE, CHALLENGE_TOKEN)
    assert opener.requests[0].full_url == ORIGIN + "/cli/challenge?state=state_1-A"
    with pytest.raises(AuthError):
        REAL_CHALLENGE_FROM_SITE(config(), "s", opener=Opener(Reply(b'{"nonce": "n"}')))
    with pytest.raises(AuthError) as raised:
        REAL_CHALLENGE_FROM_SITE(config(), "s", opener=Opener(error=refusal(503, "unavailable")))
    assert "unavailable" in str(raised.value)


def test_a_local_login_passes_its_hooks_only_for_a_site_that_enrolls(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path))
    calls = []
    opener = Opener(Reply(b'{"person": {"id": "person-9"}}'))
    session = cli_user_auth.SiteSession(config(), enroll_opener=opener)

    def fake_login(*, prepare=None, enroll=None):
        calls.append(prepare is not None and enroll is not None)
        if prepare:
            enroll({"access_token": "a.b.c", "id_token": "d.e.f"}, "state-1", "enrollment-1")
        return {"subject": "s", "label": "l"}

    session._session.login = fake_login
    monkeypatch.setattr(cli_user_auth, "site_enrolls", lambda *arguments, **keywords: False)
    session.login()
    monkeypatch.setattr(cli_user_auth, "site_enrolls", lambda *arguments, **keywords: True)
    session.login()
    assert calls == [False, True]
    assert session.person_id == "person-9"
    assert json.loads(opener.requests[-1].data)["loginState"] == "state-1"
