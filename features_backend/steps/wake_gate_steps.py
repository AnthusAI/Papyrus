"""Steps for coalescing-window.feature and agent-loop-guard.feature: the real feed, wake gate, follow-up timers, agent policy and counter over in-memory fakes."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content import agent_wakes, follow_up_timers as fu, item_change_feed, wake_gate  # noqa: E402
from papyrus_content.agent_definitions import schedules  # noqa: E402
from papyrus_content.agent_policy import AgentPolicyStore, PolicyError  # noqa: E402
from papyrus_content.change_feed_fakes import BUCKET, ENDPOINT, TENANT, FakeQueue, FakeSqs, deploy, open_index, stream_record  # noqa: E402
from papyrus_content.images.handlers import Caller  # noqa: E402
from papyrus_content.localize.dispatch import decode_image  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402
from schedule_fakes import ACCOUNT, REGION, TimerScheduler, utc  # noqa: E402

ADMIN = Caller(kind="person", subject="ada", is_admin=True)
STORY_FIELDS = {"type": "story", "stage": "draft", "section": "world", "language": "en"}


class Records:
    """The site's API as the gate uses it: Story versions by lineage, ReviewRequests, nothing else."""

    def __init__(self):
        self.rows = {"Item": {}, "ReviewRequest": {}}

    def get_record(self, model, record_id):
        return self.rows[model].get(record_id)

    def create_record(self, model, payload):
        self.rows[model][payload["id"]] = dict(payload)

    def update_record(self, model, payload):
        self.rows[model][payload["id"]].update(payload)

    def list_by_index(self, name, key):
        assert name == "itemsByLineageAndVersion"
        return [dict(row) for row in self.rows["Item"].values() if row["lineageId"] == key]


def _definition(row):
    change = {"kind": "Item", "change": row["change"], "filter": dict(pair.split("=", 1) for pair in row["filter"].split(","))}
    return SimpleNamespace(id=row["agent"], responsibility=row["responsibility"],
                           data={"procedure": row["procedure"], "paid": row["paid"] == "true", "serialBy": "subject", "safeToRepeat": False, "wakes": {"changes": [change]}})


def _open(context, site):
    names = schedules.names_for(site)
    context.site_id, context.queue, context.records, context.listening = site, FakeQueue(), Records(), []
    context.fake_scheduler = TimerScheduler(names.group, _TimerQueue(context.queue))
    context.timers = fu.FollowUpTimers.for_site(site, account=ACCOUNT, region=REGION, client=context.fake_scheduler)
    context.policy = AgentPolicyStore(SiteStore(FakeS3(), "bucket", FakeTable(), now=lambda: "2026-11-18T00:00:00Z"))
    context.refusal = None
    open_index(context)


class _TimerQueue:
    """The scheduler delivers a timer's message to the same FIFO queue the feed uses, deduplicated by the wake key."""

    def __init__(self, queue):
        self.queue = queue

    def send(self, body, group):
        wake = json.loads(body)["wake"]
        self.queue.send(body, group, agent_wakes.digest(wake["key"]))


@given('the site "{site}" with its wake gate')
def site_with_gate(context, site):
    _open(context, site)


def _listen(context, rows):
    context.listening += [dict(row) for row in rows]
    deploy(context, [_definition(row) for row in context.listening])


@given("these agents listen through the gate")
def agents_listen(context):
    _listen(context, [dict(zip(context.table.headings, row.cells)) for row in context.table])


@given('the paid agent "{agent}" also listens')
def paid_agent_listens(context, agent):
    _listen(context, [{"agent": agent, "responsibility": "fact_check", "procedure": "story.fact_check", "paid": "true", "change": "version_created", "filter": "type=story"}])


def _edit(context, edit):
    context.policy.change("alpha", ADMIN, "the owner's setting", edit)


@given("the owner has set the quiet window to {window:d} minutes after an agent and {person:d} minutes after a person")
@when("the owner has set the quiet window to {window:d} minutes after an agent and {person:d} minutes after a person")
def set_window(context, window, person):
    _edit(context, lambda document: document["site"].update(coalescing={"windowSeconds": window * 60, "afterPersonSeconds": person * 60}))


@given("the owner has set no quiet window")
def no_window(context):
    _edit(context, lambda document: document["site"].pop("coalescing", None))


@when("the owner tries to set the quiet window to {seconds:d} seconds after an agent")
def try_window(context, seconds):
    try:
        _edit(context, lambda document: document["site"].update(coalescing={"windowSeconds": seconds}))
    except PolicyError as refusal:
        context.refusal = refusal


@then("the policy refuses it, saying the window is from {low:d} to {high:d} seconds")
def refused(context, low, high):
    assert context.refusal is not None and context.refusal.code == "invalid_input", context.refusal
    assert f"from {low} to {high}" in context.refusal.message, context.refusal.message


@given('the owner has set the loop limit of "{first}" and "{second}" to {limit:d}')
def set_limits_two(context, first, second, limit):
    for responsibility in (first, second):
        _edit(context, lambda document, name=responsibility: document["agents"].setdefault(name, {"rung": "propose"}).update(loopLimit=limit))


@given('the owner has set the loop limit of "{responsibility}" to {limit:d}')
def set_limit(context, responsibility, limit):
    _edit(context, lambda document: document["agents"].setdefault(responsibility, {"rung": "propose"}).update(loopLimit=limit))


# --- saves -----------------------------------------------------------------------------------------------------------------------------


def _story_row(context, story, number, at, by):
    versions = [row for row in context.records.rows["Item"].values() if row["lineageId"] == story]
    previous = max(versions, key=lambda row: row["versionNumber"], default=None)
    if previous is None and number > 1:   # the Story's first version, which the scenario does not deliver
        seed = _make_row(story, 1, "2026-11-18T08:00:00Z", "ada", "{}")
        context.records.create_record("Item", seed)
        previous = seed
    metadata = previous["metadata"] if previous else "{}"
    if previous:
        previous["versionState"] = "superseded"
    return _make_row(story, number, at, by, metadata)


def _make_row(story, number, at, by, metadata):
    return {"id": f"{story}-v{number}", "lineageId": story, "versionNumber": number, "versionState": "current", "versionCreatedAt": at, "versionCreatedBy": by,
            "updatedAt": at, "metadata": metadata, **STORY_FIELDS}


def _gate(context):
    return wake_gate.WakeGate(policy=lambda: context.policy.read("alpha").document, timers=context.timers, chain=wake_gate.StoryChain(context.records),
                              review=lambda **found: wake_gate.raise_loop_review(context.records, **found), clock=lambda: utc("2026-11-18T08:00:00Z"))


def _deliver(context, row):
    context.records.rows["Item"][row["id"]] = row
    context.sequence = getattr(context, "sequence", 0) + 1
    site = item_change_feed.Site(publication_id=context.site_id, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.queue})
    context.answer = item_change_feed.handle([stream_record("INSERT", None, row, context.sequence)], decode=decode_image, listeners=lambda: context.index.document(),
                                             send=agent_wakes.wake_sender(sqs), site=site, gate=_gate(context))


def _save(context, by, story, number, at):
    _deliver(context, _story_row(context, story, number, at, by))


@given('a person wrote version {number:d} of the Story "{story}" at "{at}"')
@when('a person writes version {number:d} of the Story "{story}" at "{at}"')
def person_saves(context, number, story, at):
    _save(context, "ada", story, number, at)


@when('the agent "{agent}" writes version {number:d} of the Story "{story}" at "{at}"')
def agent_saves(context, agent, number, story, at):
    _save(context, f"automation:{agent}", story, number, at)


@when('a person writes versions {first:d} to {last:d} of the Story "{story}", {seconds:d} seconds apart from "{start}"')
def person_saves_many(context, first, last, story, seconds, start):
    for position, number in enumerate(range(first, last + 1)):
        at = (utc(start) + timedelta(seconds=seconds * position)).strftime(fu.TIME_FORMAT)
        _save(context, "ada", story, number, at)


@given('the agents "{first}" and "{second}" pass the Story "{story}" back and forth, starting with "{starter}", for {saves:d} saves')
@when('the agents "{first}" and "{second}" pass the Story "{story}" back and forth, starting with "{starter}", for {saves:d} saves')
def ping_pong(context, first, second, story, starter, saves):
    agents = [starter, second if starter == first else first]
    moment = utc("2026-11-18T11:00:00Z") + timedelta(minutes=getattr(context, "rounds", 0) * 60)
    context.rounds = getattr(context, "rounds", 0) + 1
    versions = [row for row in context.records.rows["Item"].values() if row["lineageId"] == story]
    number = max((row["versionNumber"] for row in versions), default=1)
    for position in range(saves):
        number += 1
        _save(context, f"automation:{agents[position % 2]}", story, number, (moment + timedelta(minutes=position)).strftime(fu.TIME_FORMAT))


@when('the clock reaches "{moment}"')
def time_arrives(context, moment):
    context.fake_scheduler.fire_until(utc(moment))


# --- what the queue and the timers hold -------------------------------------------------------------------------------------------------------


def _wakes_for(context, agent):
    return [json.loads(message.body) for message in context.queue.messages if json.loads(message.body)["wake"]["agent"] == agent]


@then('the gate queue holds {count:d} wake for the agent "{agent}"')
@then('the gate queue holds {count:d} wakes for the agent "{agent}"')
@then('the agent "{agent}" was woken {count:d} time')
@then('the agent "{agent}" was woken {count:d} times')
def queue_holds(context, count, agent):
    assert len(_wakes_for(context, agent)) == count, [m["wake"]["key"] for m in _wakes_for(context, agent)]


@then("the site's wait timers hold exactly {count:d} entry")
@then("the site's wait timers hold exactly {count:d} entries")
def timers_hold(context, count):
    assert len(context.fake_scheduler.entries) == count, sorted(context.fake_scheduler.entries)


def _entry(context, agent, story):
    return context.fake_scheduler.entries.get(fu.entry_name(wake_gate.COALESCE_RECORD_PREFIX + agent, story))


@then('the pending wait for "{agent}" on "{story}" is due at "{moment}"')
def pending_due(context, agent, story, moment):
    entry = _entry(context, agent, story)
    assert entry is not None, sorted(context.fake_scheduler.entries)
    assert context.fake_scheduler.at_of(entry) == utc(moment), context.fake_scheduler.at_of(entry)


@then('the site\'s wait timers hold a wait for "{agent}" on "{story}"')
def has_wait(context, agent, story):
    assert _entry(context, agent, story) is not None


@then('the site\'s wait timers hold no wait for "{agent}" on "{story}"')
def no_wait(context, agent, story):
    assert _entry(context, agent, story) is None


@then('the wake for "{agent}" names the Story "{story}" and no version')
def wake_without_version(context, agent, story):
    [body] = _wakes_for(context, agent)
    assert body["request"]["input"]["story"] == story and "version" not in body["request"]["input"] and "version" not in body["request"]["trigger"], body
    assert body["wake"]["key"].count("|") == 3 and body["wake"]["key"].startswith(f"{agent}|{story}|") and body["wake"]["key"].endswith("|due"), body["wake"]["key"]


@then('the wake for "{agent}" says in words that it waited for the quiet window')
def wake_says(context, agent):
    [body] = _wakes_for(context, agent)
    assert "quiet window" in body["wake"]["why"], body["wake"]["why"]


@then("the run that takes it reads the current version, which is version {number:d}")
def run_reads_current(context, number):
    from papyrus_content.story_reporting import current_story_version

    assert current_story_version(context.records, "story-1")["versionNumber"] == number


# --- the loop guard ---------------------------------------------------------------------------------------------------------------------------


@then('the Story "{story}" has been run by agents {count:d} time since a person acted')
@then('the Story "{story}" has been run by agents {count:d} times since a person acted')
def run_count(context, story, count):
    assert wake_gate.StoryChain(context.records).read(story)["hops"] == count


def _hard_gates(context, story):
    return [row for row in context.records.rows["ReviewRequest"].values() if row["mode"] == "hard_gate" and json.loads(row["subject"])["id"] == story]


@then('{count:d} hard-gate review request is open for the Story "{story}"')
@then('{count:d} hard-gate review requests are open for the Story "{story}"')
def gates_open(context, count, story):
    assert len(_hard_gates(context, story)) == count, _hard_gates(context, story)


@then("the hard-gate request says the loop limit of {limit:d} was reached")
def gate_says(context, limit):
    [request] = context.records.rows["ReviewRequest"].values()
    assert "agent loop limit reached" in request["reason"] and f"(limit {limit})" in request["reason"], request["reason"]
