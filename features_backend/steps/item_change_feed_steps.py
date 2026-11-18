"""The Item change feed (features_backend/item-change-feed.feature). A fake stream, a fake FIFO queue that follows SQS's rules and the real site store over fakes; no network."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from boto3.dynamodb.types import TypeSerializer  # noqa: E402

from papyrus_content import agent_listeners, agent_wakes, item_change_feed  # noqa: E402
from papyrus_content.localize.dispatch import decode_image  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

TENANT, BUCKET = "alpha", "bucket"
ENDPOINT = "https://example123456789012345678.appsync-api.us-east-1.amazonaws.com/graphql"
SERIALIZER = TypeSerializer()


class CountingS3(FakeS3):
    def __init__(self):
        super().__init__()
        self.gets = 0

    def get_object(self, Bucket, Key):
        self.gets += 1
        return super().get_object(Bucket, Key)


class CountingTable(FakeTable):
    """The site's catalogue as the feed may use it: point reads of SiteDocument. Anything else is recorded, so a list or a scan would show."""

    def __init__(self):
        super().__init__()
        self.reads = []

    def get(self, model, row_id):
        self.reads.append(model)
        return super().get(model, row_id)


class Message:
    def __init__(self, body, group, dedupe):
        self.body, self.group, self.dedupe = body, group, dedupe


class FakeQueue:
    """What Papyrus relies on of an SQS FIFO queue: a repeated deduplication id inside the window is dropped."""

    def __init__(self):
        self.messages, self.window, self.refuse_from = [], set(), None
        self.attempts = 0

    def send(self, body, group, dedupe):
        self.attempts += 1
        if self.refuse_from is not None and self.attempts >= self.refuse_from:
            raise OSError("the queue is unavailable")
        if dedupe in self.window:
            return
        self.window.add(dedupe)
        self.messages.append(Message(body, group, dedupe))


class FakeSqs:
    def __init__(self, queues):
        self.queues = queues

    def get_queue_url(self, QueueName):
        return {"QueueUrl": f"https://sqs.example.test/000000000000/{QueueName}"}

    def send_message(self, QueueUrl, MessageBody, MessageGroupId, MessageDeduplicationId):
        self.queues[QueueUrl.rsplit("/", 1)[1]].send(MessageBody, MessageGroupId, MessageDeduplicationId)


def _definition(row: dict):
    change = {"kind": "Item", "change": row["change"]}
    filter_ = dict(pair.split("=", 1) for pair in row["filter"].split(",")) if row.get("filter") else {}
    if filter_:
        change["filter"] = filter_
    return SimpleNamespace(id=row["agent"], data={"procedure": row["procedure"], "paid": row["paid"] == "true", "serialBy": "subject", "wakes": {"changes": [change]}})


def _open_index(context):
    context.s3, context.catalogue = CountingS3(), CountingTable()
    context.deploy_gets = 0
    context.store = SiteStore(context.s3, BUCKET, context.catalogue, now=lambda: "2026-11-18T00:00:00Z")
    context.index = agent_listeners.ListenerIndex(context.store, TENANT)


def _deploy(context, definitions):
    """The deploy's write of the index. Its own reads of the object are not the feed's, so they are counted apart."""
    before = context.s3.gets
    result = agent_listeners.publish(context.store, TENANT, definitions, actor="release", apply=True)
    context.deploy_gets += context.s3.gets - before
    return result


def _record(name, old, new, sequence):
    image = lambda row: {key: SERIALIZER.serialize(value) for key, value in row.items()} if row else None   # noqa: E731
    stream = {"SequenceNumber": f"{sequence:08d}", "Keys": {"id": SERIALIZER.serialize((new or old)["id"])}}
    if old:
        stream["OldImage"] = image(old)
    if new:
        stream["NewImage"] = image(new)
    return {"eventName": name, "dynamodb": stream}


def _story(version, stage="idea", **fields):
    return {"id": f"story-1-v{version}", "lineageId": "story-1", "versionNumber": version, "versionState": "current", "versionCreatedAt": f"2026-11-1{version}T09:00:00Z",
            "versionCreatedBy": "ada", "type": "story", "stage": stage, "section": "world", "language": "en", "updatedAt": "2026-11-17T09:00:00Z",
            "metadata": json.dumps({}), **fields}


def _step(version, state, *, actor_kind="person", label="ada", at=None, key="illustration", note=False):
    at = at or f"2026-11-18T10:0{version}:00Z"
    entry = {"at": at, "state": state, "actorKind": actor_kind, "actorLabel": label}
    previous = {"at": f"2026-11-18T10:0{version - 1}:00Z", "state": "done", "actorKind": "person", "actorLabel": "ada"}
    return {"id": f"step-story-1-{key}-v{version}", "lineageId": f"step-story-1-{key}", "versionNumber": version, "type": "sub-task", "status": state,
            "parentLineageId": "story-1", "versionCreatedAt": at, "versionCreatedBy": label,
            "metadata": json.dumps({"checklist": {"stepKey": key, "entry": previous if note else entry, "notes": [{"text": "a note"}] if note else []}})}


def deliver(context, *records):
    """One stream batch through the feed, as the handler builds it. Returns the feed's answer."""
    context.sequence = getattr(context, "sequence", 0)
    batch = []
    for name, old, new in records:
        context.sequence += 1
        batch.append(_record(name, old, new, context.sequence))
    context.last_batch = batch
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.queue})
    site = item_change_feed.Site(publication_id=context.site_id, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)
    reads = context.index_reads = getattr(context, "index_reads", [])
    context.answer = item_change_feed.handle(batch, decode=decode_image, listeners=lambda: (reads.append(1), context.index.document())[1],
                                             send=agent_wakes.wake_sender(sqs), site=site)
    return context.answer


@given('the site "{site}" with its wake queue and its listener index')
def open_site(context, site):
    context.site_id, context.queue = site, FakeQueue()
    context.ran, context.run_records, context.agent_rows = [], {}, []
    _open_index(context)


@given("these agents listen")
def agents_listen(context):
    context.agent_rows = [dict(zip(context.table.headings, row.cells)) for row in context.table]
    context.definitions = [_definition(row) for row in context.agent_rows]
    _deploy(context, context.definitions)


@given("the site has no listener index")
def no_index(context):
    _open_index(context)


@given("the queue refuses the second wake it is given")
def refuses(context):
    context.queue.refuse_from = 2


@when('a person moves the Story "{story}" to "{stage}" in the console board')
def board_move(context, story, stage):
    deliver(context, ("MODIFY", _story(3), _story(3, stage, updatedAt="2026-11-18T09:00:00Z")))   # the console writes the stage field only: no record of the move


def _agent_moves(context, agent, stage):
    old = _story(3)
    move = {"at": "2026-11-18T09:00:00Z", "from": "idea", "to": stage, "by": f"automation:{agent}", "reason": "moved"}
    deliver(context, ("MODIFY", old, _story(3, stage, metadata=json.dumps({"stageMoves": [move]}))))


@when('the agent "{agent}" moves the Story "{story}" to "{stage}"')
def agent_moves(context, agent, story, stage):
    _agent_moves(context, agent, stage)


@when('a person saves version {number:d} of the Story "{story}" with the type "{kind}"')
def person_saves_type(context, number, story, kind):
    deliver(context, ("INSERT", None, _story(number, type=kind)))


@when('a person saves version {number:d} of the Story "{story}"')
def person_saves(context, number, story):
    deliver(context, ("INSERT", None, _story(number)))


@when('a person saves version {number:d} of a Story that belongs to the tenant "{tenant}"')
def foreign_tenant(context, number, tenant):
    deliver(context, ("INSERT", None, _story(number, tenantId=tenant)))


@when('the command line saves version {number:d} of the Story "{story}" as a person')
def cli_saves(context, number, story):
    deliver(context, ("INSERT", None, _story(number, versionCreatedBy="papyrus-cli")))


@when('the agent "{agent}" saves version {number:d} of the Story "{story}"')
def agent_saves(context, agent, number, story):
    deliver(context, ("INSERT", None, _story(number, versionCreatedBy=f"automation:{agent}")))


@when('a person reopens the step "{key}" of the Story "{story}"')
def reopens(context, key, story):
    deliver(context, ("INSERT", None, _step(4, "open", key=key)))


@when('a person adds a note to the step "{key}" of the Story "{story}"')
def adds_note(context, key, story):
    deliver(context, ("INSERT", None, _step(5, "open", key=key, note=True)))


@when('the table marks the previous version of the Story "{story}" superseded')
def superseded(context, story):
    context.pending = getattr(context, "pending", [])
    context.pending.append(("MODIFY", _story(3), _story(3, versionState="superseded")))


@when('the table refreshes the checklist counts on the Story "{story}"')
def counts(context, story):
    context.pending.append(("MODIFY", _story(3), _story(3, metadata=json.dumps({"checklist": {"total": 9, "done": 4}}), updatedAt="2026-11-18T11:00:00Z")))


@when('a person rates the Story "{story}"')
def rates(context, story):
    context.pending.append(("MODIFY", _story(3), _story(3, starRating=3)))
    deliver(context, *context.pending)


@when('the table removes a version of the Story "{story}"')
def removes(context, story):
    deliver(context, ("REMOVE", _story(3), None))


@when("the same stream record is delivered again inside the queue's window")
def again_inside(context):
    context.sequence -= len(context.last_batch)
    deliver(context, *[(r["eventName"], decode_image(r["dynamodb"].get("OldImage")), decode_image(r["dynamodb"].get("NewImage"))) for r in context.last_batch])


@when("the same stream record is delivered again after the queue's window")
def again_after(context):
    context.queue.window.clear()
    again_inside(context)


@when("the runner takes every wake on the queue")
def runner(context):
    for message in list(context.queue.messages):
        request = agent_wakes.request_from_event({"Records": [{"eventSource": "aws:sqs", "body": message.body}]})
        run_id = "run-for-" + request["wakeKey"]
        if run_id in context.run_records:   # the once-only create: a second start finds the record and runs nothing
            continue
        context.run_records[run_id] = request["wakeKey"]
        context.ran.append(request["procedureKey"])
        context.queue.messages.remove(message)


@when("the queue accepts wakes again and the batch is retried")
def retry(context):
    context.queue.refuse_from = None
    context.sequence -= len(context.last_batch)
    deliver(context, *[(r["eventName"], decode_image(r["dynamodb"].get("OldImage")), decode_image(r["dynamodb"].get("NewImage"))) for r in context.last_batch])


@when("the deploy writes a changed listener index")
def changed_index(context):
    extra = _definition({"agent": "another", "procedure": "story.another", "paid": "false", "change": "version_created", "filter": "type=story"})
    _deploy(context, [*context.definitions, extra])


def _wakes(context):
    return [json.loads(message.body) for message in context.queue.messages]


@then("the queue holds {count:d} wake")
@then("the queue holds {count:d} wakes")
def holds(context, count):
    assert len(context.queue.messages) == count, f"{len(context.queue.messages)} wakes: {[w['wake']['key'] for w in _wakes(context)]}"


def _agents(text):
    return sorted(re.findall(r'"([^"]+)"', text))


@then('the queue holds {count:d} wake, for the agent "{agent}"')
def holds_for(context, count, agent):
    assert [w["wake"]["agent"] for w in _wakes(context)] == [agent] and len(context.queue.messages) == count


@then("the queue holds {count:d} wakes, for the agents {agents}")
def holds_for_agents(context, count, agents):
    assert sorted(w["wake"]["agent"] for w in _wakes(context)) == _agents(agents) and len(context.queue.messages) == count, [w["wake"]["key"] for w in _wakes(context)]


@then('the wake key is "{key}"')
def key_is(context, key):
    assert _wakes(context)[0]["wake"]["key"] == key, _wakes(context)[0]["wake"]["key"]


@then("the wake says the Story entered {stage} and who moved it")
def says_entered(context, stage):
    why = _wakes(context)[0]["wake"]["why"]
    assert f"entered {stage}" in why and "by a person" in why, why


@then('the wake is in the message group of "{agent}" and "{story}"')
def in_group(context, agent, story):
    assert context.queue.messages[0].group == agent_wakes.group_id({"agent": agent, "subject": story})


def _wake_of(context, agent):
    return next(w for w in _wakes(context) if w["wake"]["agent"] == agent)


@then('the wake for "{agent}" says the step is paid')
def paid(context, agent):
    assert _wake_of(context, agent)["request"]["trigger"]["paid"] is True


@then('the wake for "{agent}" says the step is free')
def free(context, agent):
    assert _wake_of(context, agent)["request"]["trigger"]["paid"] is False


@then("each wake names the person who saved the version and when")
def names_person(context):
    for wake in _wakes(context):
        trigger = wake["request"]["trigger"]
        assert (trigger["actorKind"], trigger["actorLabel"], trigger["at"]) == ("person", "ada", "2026-11-14T09:00:00Z"), trigger


@then("the site has {count:d} run records, one for each wake key")
def run_records(context, count):
    assert len(context.run_records) == count and len(set(context.run_records.values())) == count


@then("each agent's procedure ran once")
def ran_once(context):
    assert sorted(context.ran) == sorted(set(context.ran)) and len(context.ran) == 2, context.ran


@then('no wake is for the agent "{agent}"')
def no_wake_for(context, agent):
    assert agent not in [w["wake"]["agent"] for w in _wakes(context)]


@then("the wake says the change was made by an agent")
def by_agent(context):
    trigger = _wakes(context)[0]["request"]["trigger"]
    assert trigger["actorKind"] == "agent" and trigger["actorLabel"].startswith("automation:"), trigger


@then("the wake key names the Story and the step's version")
def names_step(context):
    assert _wakes(context)[0]["wake"]["key"] == "illustrate|story-1|step-story-1-illustration-v4|step_changed"


@then("the listener index was not read")
def not_read(context):
    assert context.index_reads == []


@then("the Automation table was not listed")
def automation_not_listed(context):
    assert "Automation" not in context.catalogue.reads


@then("no table was listed or scanned")
def no_lists(context):
    assert set(context.catalogue.reads) <= {"SiteDocument"}, context.catalogue.reads
    assert not [name for name in dir(context.catalogue) if name.startswith(("list", "scan", "query"))], "the catalogue offers the feed no way to list"


@then("the feed's code has no list of the Automation table")
def code_has_no_list(context):
    pattern = re.compile(r"list_(records|tenant_rows|by_index)\(|\.scan\(|\.query\(|list_[a-z_]*automation")
    for path in (REPO_ROOT / "src/papyrus_content/item_change_feed.py", REPO_ROOT / "src/papyrus_content/agent_listeners.py", REPO_ROOT / "amplify/functions/item-change-feed/handler.py"):
        code = [line for line in path.read_text().splitlines() if not line.lstrip().startswith(("#", '"""'))]
        assert not [line for line in code if pattern.search(line)], f"{path.name} lists a table"


@then("the listener index body was fetched {times}")
def fetched(context, times):
    assert context.s3.gets - context.deploy_gets == {"once": 1, "twice": 2}[times], context.s3.gets - context.deploy_gets


@then("the batch reports the record as failed")
def reports_failed(context):
    assert context.answer["batchItemFailures"] == [{"itemIdentifier": f"{context.sequence:08d}"}], context.answer


# --- the deploy's side ----------------------------------------------------------------------------------------------------------------

@given('the definitions "{first}" and "{second}" in Git')
def definitions_in_git(context, first, second):
    rows = {row["agent"]: row for row in context.agent_rows}
    context.in_git = {name: _definition(rows[name]) for name in (first, second)}
    _open_index(context)


@when("the deploy writes the listener index")
def deploy_writes(context):
    context.published = _deploy(context, list(context.in_git.values()))


@when("the deploy writes the listener index again with the same definitions")
def deploy_again(context):
    context.published = _deploy(context, list(context.in_git.values()))


@when('the definition "{name}" is removed from Git and the deploy writes the listener index')
def removed(context, name):
    del context.in_git[name]
    context.published = _deploy(context, list(context.in_git.values()))


@then('the site\'s listener index is version {version:d} and lists "{first}" under {first_change} and "{second}" under {second_change}')
def index_lists(context, version, first, first_change, second, second_change):
    assert context.store.current_version(TENANT, "listeners") == version
    document = context.store.read_current(TENANT, "listeners")
    assert [e["agent"] for e in document["changes"][f"Item/{first_change}"]] == [first]
    assert [e["agent"] for e in document["changes"][f"Item/{second_change}"]] == [second]


@then("no new version is written")
def no_new_version(context):
    assert context.published["action"] == "unchanged" and context.published["applied"] is False
    assert context.store.current_version(TENANT, "listeners") == 1


@then('the site\'s listener index is version {version:d} and no longer lists "{name}"')
def index_without(context, version, name):
    assert context.store.current_version(TENANT, "listeners") == version
    assert name not in json.dumps(context.store.read_current(TENANT, "listeners"))


@then("the listener index holds no rung, pause or budget")
def index_has_no_policy(context):
    text = json.dumps(context.store.read_current(TENANT, "listeners"))
    for word in ("rung", "paused", "budget", "model"):
        assert word not in text, word
