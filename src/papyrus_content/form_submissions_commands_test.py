from __future__ import annotations

import json

import pytest

from papyrus_content import form_submissions_commands as commands


class FakeClient:
    def __init__(self, messages):
        self.messages = messages
        self.created = []

    def graphql(self, query, variables):
        rows = [m for m in self.messages if m["messageKind"] == variables["messageKind"]]
        return {"listMessagesByKindAndCreatedAt": {"items": rows, "nextToken": None}}

    def get_record(self, model, record_id):
        return next((m for m in self.messages if m["id"] == record_id), None)

    def create_record(self, model, payload):
        assert model == "Message"
        self.created.append(payload)
        self.messages.append(payload)


def submission(message_id, form="contact", created="2026-10-21T12:00:00Z"):
    return {
        "id": message_id,
        "messageKind": "form_submission",
        "messageType": "newsletter_signup" if form == "newsletter" else "form_submission",
        "summary": f"{form} from Ada",
        "authorLabel": "Ada <ada@example.org>",
        "metadata": json.dumps({"formId": form, "page": "/contact/"}),
        "createdAt": created,
    }


@pytest.fixture()
def client(monkeypatch):
    fake = FakeClient([submission("form-1"), submission("form-2", "newsletter"), submission("form-3")])
    monkeypatch.setattr(commands, "create_authoring_client", lambda: (fake, None))
    return fake


def test_list_shows_open_submissions_for_a_kind(client, capsys):
    commands.messages_list(["--kind", "form_submission", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in payload["messages"]] == ["form-1", "form-2", "form-3"]
    assert {row["status"] for row in payload["messages"]} == {"open"}


def test_list_requires_a_kind(client):
    with pytest.raises(ValueError, match="--kind"):
        commands.messages_list([])


def test_handle_appends_an_event_and_hides_the_submission_from_open(client, capsys):
    commands.messages_handle(["--message-id", "form-1", "--note", "answered by email"])
    assert len(client.created) == 1
    event = client.created[0]
    assert event["messageKind"] == "form_submission_handled"
    assert event["parentMessageId"] == "form-1"
    assert event["searchVisibility"] == "private"
    capsys.readouterr()
    commands.messages_list(["--kind", "form_submission", "--json"])
    open_ids = [row["id"] for row in json.loads(capsys.readouterr().out)["messages"]]
    assert open_ids == ["form-2", "form-3"]
    commands.messages_list(["--kind", "form_submission", "--status", "handled", "--json"])
    assert [row["id"] for row in json.loads(capsys.readouterr().out)["messages"]] == ["form-1"]


def test_handle_is_idempotent_and_dry_run_writes_nothing(client):
    commands.messages_handle(["--message-id", "form-1", "--dry-run"])
    assert client.created == []
    commands.messages_handle(["--message-id", "form-1"])
    commands.messages_handle(["--message-id", "form-1"])
    assert len(client.created) == 1


def test_handle_rejects_unknown_ids_and_other_kinds(client):
    with pytest.raises(ValueError, match="not found"):
        commands.messages_handle(["--message-id", "nope"])


def test_list_filters_by_form(client, capsys):
    commands.messages_list(["--kind", "form_submission", "--form", "newsletter", "--json"])
    assert [row["id"] for row in json.loads(capsys.readouterr().out)["messages"]] == ["form-2"]
