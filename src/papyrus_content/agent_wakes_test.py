"""The wake message: its ids, its queue name (the same names amplify/agents/wake-queue.ts gives), and what the runner accepts."""
import json

import pytest

from papyrus_content import agent_wakes, wake_keys

REQUEST = {"wakeKey": "distinctive.ttab|reference-1|unversioned|monitor.new_reference", "publicationId": "distinctive",
           "procedureKey": "distinctive.ttab.ruling-analysis", "trigger": {"kind": "monitor", "summary": "Started by monitor ttab for a decision"}}


def event(body):
    return {"Records": [{"eventSource": "aws:sqs", "messageId": "m-1", "body": body}]}


@pytest.mark.parametrize("brand, queue", [
    ("sample-site", "papyrus-sample-site-agent-wakes.fifo"),               # scripts/test-agents-stack.ts asserts the same name
    ("Machines.On Machines", "papyrus-machines-on-machines-agent-wakes.fifo"),
    ("x" * 80, "papyrus-" + "x" * 40 + "-agent-wakes.fifo"),
])
def test_the_queue_is_named_after_the_site_as_the_template_names_it(brand, queue):
    assert agent_wakes.queue_name(brand) == queue and len(queue) <= 80


def test_a_site_with_no_letter_or_digit_has_no_queue():
    with pytest.raises(agent_wakes.WakeError, match="letter or digit"):
        agent_wakes.queue_name("---")


@pytest.mark.parametrize("key, subject", [
    ("agent|story-1|version-3|story.stage_entered", "story-1"),
    ("agent|schedule|2026-11-17T09:00:00Z", "schedule"),
    ("agent|manual|request-9", "request-9"),
])
def test_the_subject_is_what_the_key_is_about(key, subject):
    wake = agent_wakes.wake_of({**REQUEST, "wakeKey": key})
    assert wake["agent"] == "agent" and wake["subject"] == subject and wake["key"] == key


def test_a_wake_needs_a_key_and_a_reason():
    with pytest.raises(agent_wakes.WakeError):
        agent_wakes.wake_of({**REQUEST, "wakeKey": "not a key"})
    with pytest.raises(agent_wakes.WakeError, match="reason"):
        agent_wakes.wake_of({**REQUEST, "trigger": {"kind": "monitor"}})


def test_the_ids_are_the_digests_of_the_key_and_of_the_agent_with_its_subject():
    wake = agent_wakes.wake_of(REQUEST)
    assert agent_wakes.deduplication_id(wake) == agent_wakes.digest(REQUEST["wakeKey"]) and len(agent_wakes.deduplication_id(wake)) == 64
    assert agent_wakes.group_id(wake) == agent_wakes.digest("distinctive.ttab|reference-1")
    long_key = wake_keys.change_key("agent", "s" * 500, "v", "what")
    assert len(agent_wakes.deduplication_id(agent_wakes.wake_of({**REQUEST, "wakeKey": long_key}))) == 64   # SQS allows 128 characters


def _serial(serial_by, **extra):
    return agent_wakes.wake_of({**REQUEST, "trigger": {**REQUEST["trigger"], "serialBy": serial_by, **extra}})


def test_the_group_follows_the_definitions_serial_scope():
    other = {**REQUEST, "wakeKey": "distinctive.ttab|reference-2|unversioned|monitor.new_reference"}
    by_subject = [agent_wakes.group_id(agent_wakes.wake_of({**r, "trigger": {**r["trigger"], "serialBy": "subject"}})) for r in (REQUEST, other)]
    assert by_subject[0] != by_subject[1] and by_subject[0] == agent_wakes.group_id(agent_wakes.wake_of(REQUEST))   # no serialBy is subject
    by_agent = [agent_wakes.group_id(agent_wakes.wake_of({**r, "trigger": {**r["trigger"], "serialBy": "agent"}})) for r in (REQUEST, other)]
    assert by_agent[0] == by_agent[1] != by_subject[0]
    assert agent_wakes.group_id(_serial("key:account", serialKey="acct-1")) != agent_wakes.group_id(_serial("key:account", serialKey="acct-2"))
    assert agent_wakes.group_id(_serial("key:account", serialKey="acct-1")) == agent_wakes.group_id(_serial("key:account", serialKey="acct-1"))


@pytest.mark.parametrize("serial_by, extra", [("key:account", {}), ("everything", {}), ("key:", {"serialKey": "x"})])
def test_a_wake_with_an_unusable_serial_scope_is_not_a_wake(serial_by, extra):
    with pytest.raises(agent_wakes.WakeError, match="serial"):
        _serial(serial_by, **extra)


def test_the_message_round_trips_into_the_runner_request():
    body = agent_wakes.message_body(REQUEST)
    assert "wakeKey" not in json.loads(body)["request"]
    assert agent_wakes.request_from_event(event(body)) == REQUEST


@pytest.mark.parametrize("bad", [
    {}, {"Records": []}, {"Records": [{"eventSource": "aws:sqs", "body": "{}"}, {"eventSource": "aws:sqs", "body": "{}"}]},
    {"Records": [{"eventSource": "aws:sns", "body": "{}"}]}, event("not json"), event("[]"), event('{"wake": {}, "request": {}}'),
    event(json.dumps({"wake": {"key": REQUEST["wakeKey"], "agent": "other", "subject": "reference-1", "why": "x", "scope": "reference-1"}, "request": {}})),
])
def test_the_runner_accepts_only_one_well_formed_wake(bad):
    with pytest.raises(agent_wakes.WakeError):
        agent_wakes.request_from_event(bad)


def test_a_wake_with_an_extra_field_is_not_accepted():
    body = json.loads(agent_wakes.message_body(REQUEST))
    body["wake"]["priority"] = "high"
    with pytest.raises(agent_wakes.WakeError):
        agent_wakes.request_from_event(event(json.dumps(body)))


def test_the_sender_looks_the_queue_up_once_and_sends_with_both_ids():
    class Sqs:
        def __init__(self):
            self.lookups, self.sent = [], []

        def get_queue_url(self, QueueName):
            self.lookups.append(QueueName)
            return {"QueueUrl": "https://sqs.example.test/1/" + QueueName}

        def send_message(self, **arguments):
            self.sent.append(arguments)

    sqs = Sqs()
    send = agent_wakes.wake_sender(sqs)
    send(REQUEST)
    send({**REQUEST, "wakeKey": "distinctive.ttab|reference-2|unversioned|monitor.new_reference"})
    assert sqs.lookups == ["papyrus-distinctive-agent-wakes.fifo"] and len(sqs.sent) == 2
    assert sqs.sent[0]["MessageDeduplicationId"] != sqs.sent[1]["MessageDeduplicationId"]
    assert sqs.sent[0]["MessageGroupId"] != sqs.sent[1]["MessageGroupId"]
