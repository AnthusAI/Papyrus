"""Names, the cron translation and the wake an entry sends (the behaviour is features_backend/agents/schedule-trigger.feature)."""
import json

import pytest

from papyrus_content import agent_wakes, wake_keys
from papyrus_content.agent_definitions import schedules
from papyrus_content.agent_definitions.cron import CronError, scheduler_expression


def test_the_names_are_the_ones_the_agents_stack_builds():
    names = schedules.names_for("Machines.On Machines")
    assert (names.group, names.role, names.queue) == ("papyrus-machines-on-machines-agent-schedules", "papyrus-machines-on-machines-agent-scheduler",
                                                      "papyrus-machines-on-machines-agent-wakes.fifo")
    longest = schedules.names_for("x" * 80)
    assert len(longest.group) <= 64 and len(longest.role) <= 64 and len(longest.queue) <= 80


def test_an_entry_is_named_from_the_agent_and_a_long_id_keeps_a_digest_of_all_of_it():
    assert schedules.entry_name("rate-daily") == "agent-rate-daily"
    first, second = schedules.entry_name("a" * 100), schedules.entry_name("a" * 99 + "b")
    assert len(first) == len(second) == 64 and first != second and first.startswith("agent-aaaa")


@pytest.mark.parametrize("cron", ["0 6 15 * 1", "0 9 * * 5-7", "0 25 * * *", "0 6 * *", "0 6 * * 9", "0 6 * * 1#9", "* * ? * ?"])
def test_a_schedule_the_scheduler_cannot_express_is_refused(cron):
    with pytest.raises(CronError):
        scheduler_expression(cron)


def test_the_entrys_message_is_a_wake_the_runner_accepts_once_the_scheduler_fills_in_the_time():
    record = {"id": "rate-daily", "procedureKey": "rate_items", "limits": {"timeoutSeconds": 840}, "inputTemplate": {"mode": "daily"},
              "trigger": {"kind": "schedule", "config": {"monitorId": "hn", "publicationId": "distinctive"}}}
    publication = {"publicationId": "distinctive", "appsyncEndpoint": "https://abcdefghijklmnopqrstuvwxyz.appsync-api.us-east-1.amazonaws.com/graphql",
                   "tenantId": "distinctive", "siteBucket": "distinctive-bucket", "openaiKeyParameter": "/amplify/shared/app/OPENAI_API_KEY"}
    names = schedules.names_for("distinctive")
    entry = schedules.entry_for(record, {"cron": "0 6 * * *", "timeZone": "America/New_York"}, publication, names,
                                queue_arn="arn:aws:sqs:us-east-1:123456789012:" + names.queue, role_arn="arn:aws:iam::123456789012:role/" + names.role)
    body = entry["Target"]["Input"].replace(schedules.SCHEDULED_TIME, "2026-11-17T11:00:00Z")
    request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": body}]})
    assert request["wakeKey"] == wake_keys.schedule_key("rate-daily", "2026-11-17T11:00:00Z")
    assert (request["tenantId"], request["siteBucket"], request["timeoutSeconds"], request["input"]) == ("distinctive", "distinctive-bucket", 840, {"mode": "daily"})
    assert request["trigger"]["automationId"] == "rate-daily" and request["trigger"]["kind"] == "schedule"
    assert entry["Target"]["SqsParameters"]["MessageGroupId"] == agent_wakes.group_id(agent_wakes.wake_of(request))
    assert json.loads(entry["Target"]["Input"])["wake"]["key"] == "rate-daily|schedule|" + schedules.SCHEDULED_TIME


def test_the_queue_facts_come_from_the_queues_own_address():
    class Sqs:
        def get_queue_url(self, QueueName):
            return {"QueueUrl": f"https://sqs.eu-west-1.amazonaws.com/123456789012/{QueueName}"}

    names = schedules.names_for("distinctive")
    assert schedules.queue_facts(Sqs(), names) == (f"arn:aws:sqs:eu-west-1:123456789012:{names.queue}", f"arn:aws:iam::123456789012:role/{names.role}")
