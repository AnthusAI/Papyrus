import json

import pytest

from papyrus_content.graphql_http import PROSPECTUS_ERROR_GUIDANCE
from papyrus_content.prospectus_authorize import (
    AccountRequired,
    AuthorizationDenied,
    ReenrollmentRequired,
    authorization_enabled,
    authorize,
    is_site_function_caller,
    operation_for,
    require_authorized,
)

ACCOUNT = "acct-0001"
OTHER_ACCOUNT = "acct-0002"
ENDPOINT = "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/"
ENABLED = {"PAPYRUS_PROSPECTUS_AUTHORIZE": "true", "PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT": ENDPOINT}
PERSON_EVENT = {
    "identity": {"sub": "sub-0001", "claims": {"sub": "sub-0001"}},
    "request": {"headers": {"X-Prospectus-Account": ACCOUNT, "X-Prospectus-Human-Token": "token-0001"}},
}
ALLOWED = {"allowed": True, "accountId": ACCOUNT, "personId": "person-0001", "product": "papyrus-example", "role": "owner", "operation": "console:write", "revision": 3}


class Recorder:
    def __init__(self, status=200, body=None, error=None):
        self.status, self.body, self.error, self.calls = status, body, error, []

    def __call__(self, url, headers, body):
        self.calls.append((url, headers, json.loads(body)))
        if self.error:
            raise self.error
        return self.status, self.body


def test_allowed_decision_for_the_requested_account_proceeds():
    transport = Recorder(200, ALLOWED)
    decision = authorize(ACCOUNT, "console:write", "token-0001", endpoint=ENDPOINT, transport=transport)
    assert decision.allowed and decision.role == "owner"
    url, headers, body = transport.calls[0]
    assert url == f"{ENDPOINT}v1/accounts/{ACCOUNT}/authorize"
    assert headers["x-prospectus-human-token"] == "token-0001"
    assert body == {"operation": "console:write"}


def test_a_decision_for_another_account_is_denied():
    decision = authorize(ACCOUNT, "console:write", "token-0001", endpoint=ENDPOINT, transport=Recorder(200, {**ALLOWED, "accountId": OTHER_ACCOUNT}))
    assert not decision.allowed and decision.reason == "account_mismatch"


def test_allowed_false_and_forbidden_are_denied():
    assert not authorize(ACCOUNT, "console:write", "t", endpoint=ENDPOINT, transport=Recorder(200, {**ALLOWED, "allowed": False})).allowed
    assert authorize(ACCOUNT, "console:write", "t", endpoint=ENDPOINT, transport=Recorder(403, {"error": "forbidden"})).reason == "forbidden"


@pytest.mark.parametrize("status", [401, 403])
def test_reenrollment_required_is_raised(status):
    with pytest.raises(ReenrollmentRequired):
        authorize(ACCOUNT, "console:read", "t", endpoint=ENDPOINT, transport=Recorder(status, {"error": "reenrollment_required"}))


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_deny(status):
    assert authorize(ACCOUNT, "console:read", "t", endpoint=ENDPOINT, transport=Recorder(status, {})).reason == "prospectus_unavailable"


def test_network_failure_denies_fail_closed():
    decision = authorize(ACCOUNT, "console:read", "t", endpoint=ENDPOINT, transport=Recorder(error=OSError("unreachable")))
    assert not decision.allowed and decision.reason == "prospectus_unavailable"


def test_missing_endpoint_token_or_a_bad_account_deny_without_a_call():
    transport = Recorder(200, ALLOWED)
    assert authorize(ACCOUNT, "console:read", "t", endpoint="", transport=transport).reason == "prospectus_unavailable"
    assert authorize(ACCOUNT, "console:read", None, endpoint=ENDPOINT, transport=transport).reason == "human_token_required"
    assert authorize("../other", "console:read", "t", endpoint=ENDPOINT, transport=transport).reason == "account_invalid"
    assert transport.calls == []


def test_operations_follow_the_field_name():
    assert operation_for("saveItemDraft") == "console:write"
    assert operation_for("publishItem") == "console:write"
    assert operation_for("listProposals") == "console:read"
    assert operation_for("getAccountMembers") == "members:read"


def test_the_flag_defaults_to_off():
    assert not authorization_enabled({})
    assert not authorization_enabled({"PAPYRUS_PROSPECTUS_AUTHORIZE": "false"})
    assert authorization_enabled(ENABLED)


def test_with_the_flag_off_nothing_is_asked():
    transport = Recorder(200, ALLOWED)
    assert require_authorized(PERSON_EVENT, "publishItem", environment={}, transport=transport) is None
    assert transport.calls == []


def test_a_request_without_the_account_header_is_refused():
    event = {**PERSON_EVENT, "request": {"headers": {"X-Prospectus-Human-Token": "token-0001"}}}
    with pytest.raises(AccountRequired):
        require_authorized(event, "publishItem", environment=ENABLED, transport=Recorder(200, ALLOWED))


def test_an_allowed_person_proceeds_and_a_denied_one_is_refused():
    assert require_authorized(PERSON_EVENT, "publishItem", environment=ENABLED, transport=Recorder(200, ALLOWED)).allowed
    with pytest.raises(AuthorizationDenied):
        require_authorized(PERSON_EVENT, "publishItem", environment=ENABLED, transport=Recorder(403, {}))


def test_the_sites_own_iam_functions_are_not_checked():
    machine = {"userArn": "arn:aws:sts::123456789012:assumed-role/site-function/session", "accountId": "123456789012"}
    transport = Recorder(403, {})
    assert is_site_function_caller(machine)
    assert require_authorized({"identity": machine, "request": {"headers": {}}}, "publishItem", environment=ENABLED, transport=transport) is None
    assert transport.calls == []
    assert not is_site_function_caller({**machine, "cognitoIdentityId": "identity-0001"})
    assert not is_site_function_caller({**machine, "sub": "sub-0001"})
    assert not is_site_function_caller({**machine, "accountId": "999999999999"})


def test_the_cli_names_the_next_step_for_each_error_type():
    assert "papyrus login" in PROSPECTUS_ERROR_GUIDANCE["ReenrollmentRequired"]
    assert "papyrus account use" in PROSPECTUS_ERROR_GUIDANCE["AccountRequired"]


@pytest.mark.parametrize("error_type,fragment", [("ReenrollmentRequired", "Run `papyrus login` again."), ("AccountRequired", "papyrus account use <name>")])
def test_execute_graphql_turns_the_error_type_into_the_next_step(monkeypatch, error_type, fragment):
    import io

    from papyrus_content import graphql_http
    from papyrus_content.operator_errors import GraphQLRequestError, exit_code_for_error

    reply = json.dumps({"errors": [{"errorType": error_type, "message": "raw"}]}).encode()
    monkeypatch.setattr(graphql_http, "load_dotenv", lambda: None)
    monkeypatch.setattr(graphql_http, "graphql_endpoint", lambda: "https://example.test/graphql")
    monkeypatch.setattr(graphql_http, "graphql_request_headers", lambda **_: {})
    monkeypatch.setattr(graphql_http.urllib.request, "urlopen", lambda *_, **__: io.BytesIO(reply))
    with pytest.raises(GraphQLRequestError) as raised:
        graphql_http.execute_graphql("query { x }")
    assert fragment in str(raised.value)
    assert exit_code_for_error(raised.value) != 0
