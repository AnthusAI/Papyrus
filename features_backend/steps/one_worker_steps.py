from __future__ import annotations

import json
import sys
from pathlib import Path

from behave import given, then, when

sys.path.insert(0, str(Path(__file__).resolve().parent))
from papyrus_content import agent_wakes  # noqa: E402
from wake_queue_steps import FakeQueue, FakeSqs  # noqa: E402


@given('the site "{site}" with a model of its wake queue')
def open_queue(context, site):
    context.sqs, context.queue, context.serial, context.first_of_account = FakeSqs(), FakeQueue(), {}, {}
    context.sqs.queues[agent_wakes.queue_name(site)] = context.queue
    context.url = f"https://sqs.example.test/000000000000/{agent_wakes.queue_name(site)}"
    context.counter, context.refused = 0, None


def _serial(context, agent, serial_by):
    context.serial[agent] = serial_by


@given('the agent "{agent}" runs one at a time by subject')
def by_subject(context, agent):
    _serial(context, agent, "subject")


@given('the agent "{agent}" runs one at a time by agent')
def by_agent(context, agent):
    _serial(context, agent, "agent")


@given('the agent "{agent}" runs one at a time by the key "{name}"')
def by_key(context, agent, name):
    _serial(context, agent, f"key:{name}")


@given('the agent "{agent}" runs one at a time by "{value}"')
def by_value(context, agent, value):
    _serial(context, agent, value)


def request(context, agent, story, **trigger):
    context.counter += 1
    serial = context.serial.get(agent)
    return {"wakeKey": f"distinctive.{agent}|{story}|v{context.counter}|rated", "publicationId": "distinctive", "procedureKey": f"{agent}.run",
            "trigger": {"kind": "event", "summary": f"{agent} woke for {story}", **({"serialBy": serial} if serial else {}), **trigger}}


def put(context, req):
    try:
        agent_wakes.send_wake(context.sqs, context.url, req)
    except agent_wakes.WakeError as refused:
        context.refused = refused


@when('two wakes about the Story "{story}" arrive')
def two_wakes(context, story):
    for _ in range(2):
        put(context, request(context, "announce", story))


@when('wakes about the Stories "{first}" and "{second}" arrive')
def two_stories(context, first, second):
    for story in (first, second):
        put(context, request(context, "announce", story))


@when('wakes about the Stories "{first}" and "{second}" arrive for "{agent}"')
def two_stories_for(context, first, second, agent):
    for story in (first, second):
        put(context, request(context, agent, story))


@when('a wake about the Story "{story}" arrives for "{agent}"')
def one_for(context, story, agent):
    put(context, request(context, agent, story))


@when('a wake about the Story "{story}" arrives')
def one_story(context, story):
    put(context, request(context, "announce", story))


@when('wakes arrive for the account "{first}" and the account "{second}"')
def two_accounts(context, first, second):
    for account in (first, second):
        put(context, request(context, "announce", f"story-{account}", serialKey=account))
        context.first_of_account[account] = context.queue.messages[-1]


@when('wakes arrive for the account "{account}" again')
def account_again(context, account):
    put(context, request(context, "announce", "story-later", serialKey=account))


@when("a wake arrives that names no account")
def no_account(context):
    put(context, request(context, "announce", "story-1"))


@when("two wakes about different Stories arrive from an automation that has no definition")
def no_definition(context):
    for story in ("story-1", "story-2"):
        put(context, request(context, "legacy", story))


@then("the queue gives the runner the copy-edit message while it holds the first")
def copy_edit_runs(context):
    received = context.queue.receive()
    assert received is context.queue.messages[2] and received is not context.running and json.loads(received.body)["wake"]["agent"].endswith("copy-edit")


@then("that message is in the same group as the first account's first message")
def same_account(context):
    assert context.queue.messages[-1].group == context.first_of_account["first-account"].group
    assert context.queue.messages[-1].group != context.first_of_account["second-account"].group


@then("the wake is refused and the queue holds no message")
def refused(context):
    assert context.refused is not None and context.queue.messages == []
