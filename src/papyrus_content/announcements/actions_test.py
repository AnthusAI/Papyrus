import json
from pathlib import Path

import pytest

from papyrus_content.announcements import actions
from papyrus_content.appsync_event import NO_OPERATION_MESSAGE, amplify_function_event, user_pool_identity

OPERATIONS = sorted(actions.READS | actions.CHANGES)
# What the page's nine calls become on the way to the Lambda; scripts/test-announcements.ts checks the page sends exactly these.
PAGE_REQUESTS = json.loads((Path(__file__).resolve().parents[3] / "features_backend" / "fixtures" / "announcements-page-requests.json").read_text())


COMMAND_LINE_ONLY = {"announcementsXSpend"}


@pytest.fixture
def ran(monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "handle", lambda operation, payload, groups, actor, accounts, settings, ledger=None: calls.append((operation, payload, groups, actor)) or {"ok": True})
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
    assert sorted(operation for operation, *_ in ran) == [name for name in OPERATIONS if name not in COMMAND_LINE_ONLY]   # the page never asks the ledger: the command line does
    assert [payload for _, payload, *_ in ran] == [json.loads(event["arguments"]["input"]) for event in PAGE_REQUESTS]


def test_the_spend_query_reads_the_ledger_and_says_when_there_is_none():
    from datetime import date

    class Ledger:
        def spent(self, account_id, start):
            assert (account_id, start) == ("mom", date(2026, 11, 1))
            return "0.4"

    from types import SimpleNamespace

    accounts = SimpleNamespace(status=lambda: {})
    ask = {"accountId": "mom", "cycleStart": "2026-11-01"}
    assert actions.handle("announcementsXSpend", ask, ["editor"], "ed", accounts, None, lambda: Ledger()) == {"ok": True, "spent": "0.4"}
    refused = actions.handle("announcementsXSpend", ask, ["editor"], "ed", accounts, None, None)
    assert refused["ok"] is False and refused["error"] == "not_configured"
    assert actions.handle("announcementsXSpend", ask, [], "nobody", accounts, None, lambda: Ledger())["error"] == "forbidden"
