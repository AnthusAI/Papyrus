from __future__ import annotations

import json

import pytest

from papyrus_content import agent_wakes, follow_up_timers as fu


class Api:
    class exceptions:  # noqa: N801
        ConflictException = type("ConflictException", (Exception,), {})
        ResourceNotFoundException = type("ResourceNotFoundException", (Exception,), {})

    def __init__(self) -> None:
        self.entries: dict[str, dict] = {}
        self.calls: list[str] = []

    def create_schedule(self, **entry) -> None:
        self.calls.append("create")
        if entry["Name"] in self.entries:
            raise self.exceptions.ConflictException()
        self.entries[entry["Name"]] = entry

    def update_schedule(self, **entry) -> None:
        self.calls.append("update")
        self.entries[entry["Name"]] = entry

    def delete_schedule(self, **entry) -> None:
        self.calls.append("delete")
        self.last_delete = entry
        if entry["Name"] not in self.entries:
            raise self.exceptions.ResourceNotFoundException()
        del self.entries[entry["Name"]]


BASE = {"appsyncEndpoint": "https://abcdefghijklmnopqrstuvwxyz.appsync-api.us-east-1.amazonaws.com/graphql", "procedureKey": "newsroom.deliver", "publicationId": "site", "input": {}}


def timers(api: Api) -> fu.FollowUpTimers:
    return fu.FollowUpTimers.for_site("Site", account="123456789012", region="us-east-1", client=api)


def test_a_due_time_makes_one_entry_in_the_site_group_that_sends_one_wake() -> None:
    api = Api()
    key = timers(api).sync("Delivery", "d-1", "2026-11-17T09:00:00Z", owner="deliver", base=BASE, waiting_for="budget")
    assert key == "deliver|d-1|2026-11-17T09:00:00Z|due"
    (name, entry), = api.entries.items()
    assert name == fu.entry_name("Delivery", "d-1") and name.startswith("follow-up-") and len(name) <= 64
    assert entry["GroupName"] == "papyrus-site-agent-schedules" and entry["ActionAfterCompletion"] == "DELETE"
    assert entry["ScheduleExpression"] == "at(2026-11-17T09:00:00)" and entry["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert entry["Target"]["Arn"].endswith(":sqs:us-east-1:123456789012:papyrus-site-agent-wakes.fifo")
    assert entry["Target"]["RoleArn"].endswith(":iam::123456789012:role/papyrus-site-agent-scheduler")
    body = json.loads(entry["Target"]["Input"])
    assert body["wake"]["key"] == key and "budget" in body["wake"]["why"]
    assert entry["Target"]["SqsParameters"] == {"MessageGroupId": agent_wakes.group_id(body["wake"])}


def test_a_new_time_replaces_the_entry_and_no_time_deletes_it() -> None:
    api = Api()
    follow_up = timers(api)
    follow_up.sync("Delivery", "d-1", "2026-11-17T09:00:00Z", owner="deliver", base=BASE)
    follow_up.sync("Delivery", "d-1", "2026-11-17T12:00:00Z", owner="deliver", base=BASE)
    assert api.calls == ["create", "create", "update"] and len(api.entries) == 1
    assert next(iter(api.entries.values()))["ScheduleExpression"] == "at(2026-11-17T12:00:00)"
    assert follow_up.sync("Delivery", "d-1", None, owner="deliver", base=BASE) is None
    assert api.entries == {}
    follow_up.sync("Delivery", "d-1", None, owner="deliver", base=BASE)   # an entry that already fired and deleted itself is not an error


def test_the_name_and_the_key_name_the_record_and_the_time() -> None:
    assert fu.entry_name("Delivery", "a") != fu.entry_name("Delivery", "b") != fu.entry_name("ReviewRequest", "b")
    assert fu.follow_up_key("x", "r", "2026-01-01T00:00:00Z") != fu.follow_up_key("x", "r", "2026-01-01T00:00:01Z")
    assert not fu.entry_name("Delivery", "agent-1").startswith("agent-")


def test_a_time_that_is_not_a_utc_instant_writes_nothing() -> None:
    api = Api()
    with pytest.raises(fu.FollowUpError, match="UTC instant"):
        timers(api).sync("Delivery", "d-1", "2026-11-17 09:00", owner="deliver", base=BASE)
    with pytest.raises(fu.FollowUpError):
        timers(api).sync("Delivery", "a|b", "2026-11-17T09:00:00Z", owner="deliver", base=BASE)
    assert api.calls == []


def test_the_default_group_sends_no_group_name() -> None:
    api = Api()
    fu.OneShotSchedules(api).set("n", "2026-11-17T09:00:00Z", {"Arn": "a", "RoleArn": "r", "Input": "{}"})
    assert "GroupName" not in api.entries["n"]
    fu.OneShotSchedules(api).clear("n")
    assert api.last_delete == {"Name": "n"}


def test_check_wake_goes_on_only_for_the_time_the_record_still_waits_for() -> None:
    key = fu.follow_up_key("deliver", "d-1", "2026-11-17T09:00:00Z")
    assert fu.due_time_of(key) == "2026-11-17T09:00:00Z" and fu.record_id_of(key) == "d-1"
    assert fu.check_wake(key, {"dueAt": "2026-11-17T09:00:00Z", "waitingFor": "budget"}) == {"waiting": True, "dueAt": "2026-11-17T09:00:00Z", "waitingFor": "budget"}
    assert fu.check_wake(key, {"dueAt": "2026-11-17T12:00:00Z"})["waiting"] is False
    assert fu.check_wake(key, {})["waiting"] is False and fu.check_wake(key, None)["waiting"] is False
    with pytest.raises(fu.FollowUpError):
        fu.due_time_of("deliver|schedule|2026-11-17T09:00:00Z")
