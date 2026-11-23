"""Poke-in: which stopped wakes a resume sends again, and what wake now sends (features_backend/agents/poke-in.feature and kill-switches.feature have the narrative)."""
from __future__ import annotations

import json

import pytest

from papyrus_content import agent_poke_in
from papyrus_content.agent_poke_in import PokeInError, sent_again, stopped_wakes
from papyrus_content.appsync_event import amplify_function_event, user_pool_identity
from papyrus_content.images.handlers import Caller


def change_wake(subject: str, version: str, what: str, agent: str = "announce") -> dict:
    return {"wakeKey": f"{agent}|{subject}|{version}|{what}", "publicationId": "site", "procedureKey": "announce_story", "actorLabel": f"automation:{agent}",
            "input": {"story": subject, "version": version, "change": "rated"},
            "trigger": {"kind": "event", "automationId": agent, "story": subject, "version": version, "summary": f"Agent {agent} woke because Story {subject} was rated"}}


def run(at: str, wake: dict | None, reason: str | None) -> dict:
    return {"id": f"run-{at}", "requestedAt": at, "outcomeReason": reason, "wake": json.dumps(wake) if wake else None}


class Ledger:
    def __init__(self, rows):
        self.rows = rows

    def runs_since(self, automation_id, since):
        return sorted((row for row in self.rows if row["requestedAt"] >= since), key=lambda row: row["requestedAt"])

    def newest_first(self, automation_id):
        return iter(sorted(self.rows, key=lambda row: row["requestedAt"], reverse=True))


def test_each_subject_gets_its_latest_stopped_wake_once():
    first, second, other = change_wake("s1", "v1", "rated:3"), change_wake("s1", "v2", "rated:4"), change_wake("s2", "v1", "rated:5")
    ledger = Ledger([run("2026-11-23T10:00:00Z", first, "paused"), run("2026-11-23T11:00:00Z", other, "paused"), run("2026-11-23T12:00:00Z", second, "paused")])
    assert [wake["wakeKey"] for wake in stopped_wakes(ledger, "announce", "2026-11-23T09:00:00Z")] == [other["wakeKey"], second["wakeKey"]]


def test_a_subject_whose_latest_wake_ran_needs_nothing_and_a_run_that_kept_no_wake_is_left_alone():
    stopped, ran = change_wake("s1", "v1", "rated:3"), change_wake("s1", "v2", "rated:4")
    ledger = Ledger([run("2026-11-23T10:00:00Z", stopped, "paused"), run("2026-11-23T11:00:00Z", ran, "announced"), run("2026-11-23T12:00:00Z", None, "paused")])
    assert stopped_wakes(ledger, "announce", "2026-11-23T09:00:00Z") == []


def test_a_wake_before_the_pause_began_is_not_caught_up():
    ledger = Ledger([run("2026-11-23T08:00:00Z", change_wake("s1", "v1", "rated:3"), "paused")])
    assert stopped_wakes(ledger, "announce", "2026-11-23T09:00:00Z") == []


def test_a_wake_sent_again_keeps_its_subject_and_version_and_says_who_and_why():
    again = sent_again(change_wake("s1", "v2", "rated:4"), marker="resumed-v6", poke="resume", by="Ada", reason="Drafts checked", at="2026-11-23T15:00:00Z")
    assert again["wakeKey"] == "announce|s1|v2|rated:4+resumed-v6"
    assert again["trigger"]["poke"] == {"kind": "resume", "by": "Ada", "reason": "Drafts checked", "at": "2026-11-23T15:00:00Z", "repeats": "announce|s1|v2|rated:4"}
    assert again["trigger"]["summary"].startswith("Ada resumed (Drafts checked)") and again["input"] == {"story": "s1", "version": "v2", "change": "rated"}


def test_a_timer_tick_is_never_sent_again():
    tick = {**change_wake("s1", "v1", "x"), "wakeKey": "rate|schedule|2026-11-23T08:30:00Z"}
    with pytest.raises(PokeInError) as refused:
        sent_again(tick, marker="m", poke="resume", by="Ada", reason="r", at="t")
    assert refused.value.code == "constraint_conflict"


def test_wake_now_sends_the_subjects_latest_wake_once_under_a_persons_request():
    sent = []
    ledger = Ledger([run("2026-11-23T10:00:00Z", change_wake("s1", "v1", "rated:3"), "announced"), run("2026-11-23T11:00:00Z", change_wake("s2", "v1", "rated:4"), "paused")])
    result = agent_poke_in.wake(ledger, sent.append, Caller(kind="person", subject="Edie", request_id="r1"), agent="announce", subject="s1", reason="Draft it today")
    assert [request["wakeKey"] for request in sent] == ["announce|s1|v1|rated:3+woken-r1"]
    assert result["repeats"] == "announce|s1|v1|rated:3" and result["requestedBy"] == "Edie"


def test_wake_now_for_a_subject_the_agent_never_saw_is_not_found_and_an_agent_may_not_ask():
    with pytest.raises(PokeInError) as missing:
        agent_poke_in.wake(Ledger([]), lambda request: None, Caller(kind="person", subject="Edie"), agent="announce", subject="s9", reason="r")
    assert missing.value.code == "not_found" and "never been woken for s9" in missing.value.message
    from papyrus_content.agent_policy.document import PolicyError

    with pytest.raises(PolicyError) as refused:
        agent_poke_in.wake(Ledger([]), lambda request: None, Caller(kind="agent", subject="rate"), agent="announce", subject="s1", reason="r")
    assert refused.value.code == "human_required"


def test_the_automation_page_function_wakes_for_an_editor_and_refuses_anyone_else():
    from papyrus_content.automation_view import handle

    class Client:
        tenant_id = None

        def list_by_index(self, *args, **kwargs):
            return []

        def iterate_newest_first(self, index_name, key):
            assert index_name == "procedureRunWakesByAutomation" and key == "announce"
            yield {"id": "run-1", "requestedAt": "2026-11-23T10:00:00Z", "wake": json.dumps(change_wake("s1", "v1", "rated:3"))}

    sent = []
    wake_input = json.dumps({"op": "agents_wake", "agent": "announce", "subject": "s1", "reason": "Draft it today"})
    editor = user_pool_identity("edie", ["editor"])
    answer = handle(amplify_function_event("Mutation", "agentWake", {"input": wake_input}, editor), env={}, client_factory=Client, invoker=sent.append)
    assert answer["ok"] is True and answer["result"]["subject"] == "s1" and len(sent) == 1 and sent[0]["trigger"]["poke"]["kind"] == "wake"
    reader = user_pool_identity("rita", ["reader"])
    assert handle(amplify_function_event("Mutation", "agentWake", {"input": wake_input}, reader), env={}, client_factory=Client, invoker=sent.append)["error"] == "not_authorized"
    bad = json.dumps({"agent": "announce", "subject": "s1"})
    assert handle(amplify_function_event("Mutation", "agentWake", {"input": bad}, editor), env={}, client_factory=Client, invoker=sent.append)["error"] == "invalid_input"
    assert len(sent) == 1


def test_the_hand_written_usage_names_every_flag_the_generated_spec_has():
    import re

    from papyrus.operator.command_usage import usage_for_path
    from papyrus_content.images.cli_generated import COMMANDS

    entries = [entry for entry in COMMANDS if entry["group"] == "agents"]
    assert sorted(entry["op"] for entry in entries) == ["agents_pause", "agents_pauses", "agents_resume", "agents_wake"]
    for entry in entries:
        usage = usage_for_path(["agents", *entry["words"]])
        assert usage is not None, entry["words"]
        for flag in re.findall(r"--[a-z-]+", entry["usage"]):
            assert flag in usage.usage, (entry["words"], flag)
