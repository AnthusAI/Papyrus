import json
from pathlib import Path

import pytest

from papyrus_content.announcements import actions
from papyrus_content.appsync_event import NO_OPERATION_MESSAGE, amplify_function_event, user_pool_identity

OPERATIONS = sorted(actions.READS | actions.CHANGES)
# What the page's nine calls become on the way to the Lambda; scripts/test-announcements.ts checks the page sends exactly these.
PAGE_REQUESTS = json.loads((Path(__file__).resolve().parents[3] / "features_backend" / "fixtures" / "announcements-page-requests.json").read_text())


@pytest.fixture
def ran(monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "handle", lambda operation, payload, groups, actor, accounts, settings, **_: calls.append((operation, payload, groups, actor)) or {"ok": True})
    return calls


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("encoded", [True, False], ids=["input as JSON text", "input as a JSON object"])
def test_every_operation_reaches_handle_from_the_event_amplify_sends(ran, operation, encoded):
    payload = {"paused": True}
    type_name = "Query" if operation in actions.READS else "Mutation"
    event = amplify_function_event(type_name, operation, {"input": json.dumps(payload) if encoded else payload}, user_pool_identity("ryan", ["admin"], "ryan@example.test"))
    assert actions.handle_event(event, accounts=None, settings=None) == {"ok": True}
    assert ran == [(operation, payload, ["admin"], "ryan@example.test")]


def test_a_request_with_no_field_says_it_carried_no_operation(ran):
    event = amplify_function_event("Query", "announcementsSettings", {"input": "{}"}, user_pool_identity("ryan", ["admin"]))
    del event["fieldName"]
    assert actions.handle_event(event, accounts=None, settings=None) == {"ok": False, "error": "no_operation", "message": NO_OPERATION_MESSAGE}
    assert ran == []


@pytest.mark.parametrize("raw", ["[1]", "not json", 7])
def test_an_input_that_is_not_a_json_object_is_refused(ran, raw):
    event = amplify_function_event("Mutation", "announcementsPause", {"input": raw}, user_pool_identity("ryan", ["admin"]))
    assert actions.handle_event(event, accounts=None, settings=None)["error"] == "invalid_input"
    assert ran == []


def test_the_requests_the_page_sends_each_run_the_operation_they_name(ran):
    answers = [actions.handle_event(event, accounts=None, settings=None) for event in PAGE_REQUESTS]
    assert answers == [{"ok": True}] * len(PAGE_REQUESTS)
    assert [operation for operation, *_ in ran] == [event["fieldName"] for event in PAGE_REQUESTS]
    assert sorted(operation for operation, *_ in ran) == OPERATIONS
    assert [payload for _, payload, *_ in ran] == [json.loads(event["arguments"]["input"]) for event in PAGE_REQUESTS]


class SettingsInMode:
    def __init__(self, mode):
        self.mode, self.saved = mode, []

    def read(self):
        return {"mode": self.mode}

    def save(self, proposed, connection_status):
        self.saved.append(proposed)
        return proposed


class ConnectedAccounts:
    def status(self):
        return {"connection": "connected"}


def save_event(mode, claims):
    event = amplify_function_event("Mutation", "announcementsSaveSettings", {"input": json.dumps({"settings": {"mode": mode}})}, user_pool_identity("ryan", ["admin"], "ryan@example.test"))
    event["identity"]["claims"].update(claims)
    return event


def test_a_credential_issued_to_no_person_client_cannot_turn_announcements_on(monkeypatch):
    monkeypatch.setenv(actions.PERSON_CLIENT_IDS_VARIABLE, "console-client")
    settings = SettingsInMode("dry_run")
    answer = actions.handle_event(save_event("on", {"aud": "cli-client"}), ConnectedAccounts(), settings)
    assert answer["error"] == "person_only" and settings.saved == []


def test_a_credential_issued_to_the_console_client_can_turn_announcements_on(monkeypatch):
    monkeypatch.setenv(actions.PERSON_CLIENT_IDS_VARIABLE, "console-client")
    settings = SettingsInMode("dry_run")
    for claims in ({"aud": "console-client"}, {"client_id": "console-client"}):
        assert actions.handle_event(save_event("on", claims), ConnectedAccounts(), settings)["ok"] is True
    assert len(settings.saved) == 2


def test_with_no_person_client_configured_no_credential_is_a_person(monkeypatch):
    monkeypatch.delenv(actions.PERSON_CLIENT_IDS_VARIABLE, raising=False)
    answer = actions.handle_event(save_event("on", {"aud": "console-client"}), ConnectedAccounts(), SettingsInMode("off"))
    assert answer["error"] == "person_only"


def test_any_credential_may_still_save_other_modes_and_leave_on_alone(monkeypatch):
    monkeypatch.setenv(actions.PERSON_CLIENT_IDS_VARIABLE, "console-client")
    agent_claims = {"aud": "cli-client"}
    assert actions.handle_event(save_event("dry_run", agent_claims), ConnectedAccounts(), SettingsInMode("off"))["ok"] is True
    assert actions.handle_event(save_event("off", agent_claims), ConnectedAccounts(), SettingsInMode("on"))["ok"] is True
    assert actions.handle_event(save_event("on", agent_claims), ConnectedAccounts(), SettingsInMode("on"))["ok"] is True
