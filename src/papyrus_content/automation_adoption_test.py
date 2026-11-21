"""An agent adopts an automation only on the named instruction of the admin whose session it runs in, recorded as entered by the agent."""
from __future__ import annotations

import pytest

from papyrus_content.automation_adoption import adopt
from papyrus_content.automations import AutomationError
from papyrus_content.images.handlers import Caller


class AutomationTableWithOneUnadoptedAutomation:
    def __init__(self):
        self.updates = []

    def get_record(self, model, record_id):
        return {"id": record_id, "title": "Announce", "enabled": True, "trigger": {"kind": "event", "config": {}}, "procedureKey": "announce_story"} if record_id == "announce" else None

    def update_record(self, model, payload):
        self.updates.append(payload)


def admin_session(kind):
    return Caller(kind=kind, subject="ryan@anth.us", is_admin=True)


def test_an_agent_without_a_named_instruction_is_refused():
    client = AutomationTableWithOneUnadoptedAutomation()
    with pytest.raises(AutomationError):
        adopt(client, admin_session("agent"), "announce", "announce", apply=True)
    assert client.updates == []


def test_an_agent_on_the_session_owners_instruction_adopts_and_is_recorded():
    client = AutomationTableWithOneUnadoptedAutomation()
    result = adopt(client, admin_session("agent"), "announce", "announce", apply=True, on_instruction_of="ryan@anth.us", quote="No you run it.", agent="Claude")
    assert result["applied"] is True
    assert "on the instruction of ryan@anth.us" in result["instruction"]
    assert len(client.updates) == 1
    assert "ryan@anth.us via cli (Claude)" in str(client.updates[0])


def test_an_agent_naming_someone_else_than_the_session_owner_is_refused():
    client = AutomationTableWithOneUnadoptedAutomation()
    with pytest.raises(AutomationError):
        adopt(client, admin_session("agent"), "announce", "announce", apply=True, on_instruction_of="someone@else", quote="go", agent="Claude")
    assert client.updates == []


def test_an_agent_in_a_non_admin_session_is_refused():
    client = AutomationTableWithOneUnadoptedAutomation()
    with pytest.raises(AutomationError):
        adopt(client, Caller(kind="agent", subject="ryan@anth.us", is_admin=False), "announce", "announce", apply=True,
              on_instruction_of="ryan@anth.us", quote="go", agent="Claude")
    assert client.updates == []
