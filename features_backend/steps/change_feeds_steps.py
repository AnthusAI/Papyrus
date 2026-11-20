"""The change feeds of the other tables (features_backend/agents/change-feeds.feature). A fake stream per table, the Item feed's fake FIFO queue and site store, and no network."""
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

from papyrus_content import agent_wakes, change_feed_relay, change_feeds, item_change_feed  # noqa: E402
from papyrus_content.change_feed_fakes import BUCKET, ENDPOINT, TENANT, FakeSqs, deploy, open_index, stream_record  # noqa: E402
from papyrus_content.localize.dispatch import decode_image  # noqa: E402

STREAMS = {table: f"arn:aws:dynamodb:us-east-1:000000000000:table/{table}-sample/stream/2026-01-01T00:00:00.000" for table in change_feeds.FEED_TABLES}
AT = "2026-11-18T09:00:00Z"


def _definition(row: dict):
    change = {"kind": row["kind"], "change": row["change"]}
    selector = dict(pair.split("=", 1) for pair in row["filter"].split(",")) if row.get("filter") else {}
    if selector:
        change["filter"] = selector
    return SimpleNamespace(id=row["agent"], responsibility="r-" + row["agent"], data={"procedure": row["procedure"], "paid": row["paid"] == "true", "serialBy": "subject", "wakes": {"changes": [change]}})


# --- rows ------------------------------------------------------------------------------------------------------------------------------------------


def _reference(version=1, **fields):
    return {"id": f"ref-1-v{version}", "lineageId": "ref-1", "versionNumber": version, "versionCreatedBy": "ada", "versionCreatedAt": AT, "corpusId": "corpus", "curationStatus": "pending", **fields}


def _review(state="answered", asker="copy-edit", subject="story-1", rid="rr-1", **fields):
    return {"id": rid, "subject": json.dumps({"type": "story", "id": subject}), "mode": "soft_review", "reason": "check", "raisedBy": f"agent:{asker}", "state": state,
            "answer": json.dumps({"decision": "approve", "by": "ada", "at": "2026-11-18T10:00:00Z"}) if state == "answered" else None, **fields}


def _message(number=1, thread="thread-story", **fields):
    return {"id": f"message-{number}", "threadId": thread, "messageKind": "comment", "status": "active", "authorLabel": "ada", "role": "human", "createdAt": "2026-11-18T11:00:00Z", **fields}


def _request(language, at=AT, **fields):
    return {"id": f"story-1#{language}", "languageGroupId": "story-1", "language": language, "sourceVersionId": "story-1-v4", "sourceVersionNumber": 4, "state": "wanted",
            "requestedBy": "ada", "requestedAt": at, **fields}


def _delivery(state, revision, **fields):
    return {"id": "delivery-1", "announcementId": "announcement-1", "channel": "email", "accountId": "account-1", "state": state, "revision": revision, "mode": "automatic", "approval": "soft",
            "history": json.dumps([{"at": AT, "by": "ada", "state": state, "note": "changed"}]), **fields}


# --- delivering a batch ----------------------------------------------------------------------------------------------------------------------------


def _site(context):
    return item_change_feed.Site(publication_id=context.site_id, appsync_endpoint=ENDPOINT, tenant_id=TENANT, site_bucket=BUCKET)


def _feed(context, batch):
    """The feed's own handler over a batch, as amplify/functions/change-feed/handler.py builds it."""
    sqs = FakeSqs({agent_wakes.queue_name(context.site_id): context.queue})
    reads = context.index_reads = getattr(context, "index_reads", [])

    def thread_of(thread_id):
        context.thread_reads.append(thread_id)
        return context.threads.get(thread_id)

    return change_feeds.handle(batch, streams=change_feeds.Streams(tables={arn: table for table, arn in STREAMS.items()}), decode=decode_image,
                               listeners=lambda: (reads.append(1), context.index.document())[1], send=agent_wakes.wake_sender(sqs), site=_site(context), thread_of=thread_of)


def deliver(context, table, *records):
    context.sequence = getattr(context, "sequence", 0)
    batch = []
    for name, old, new in records:
        context.sequence += 1
        batch.append(stream_record(name, old, new, context.sequence, STREAMS[table]))
    context.last_batch = batch
    context.thread_reads = getattr(context, "thread_reads", [])
    if getattr(context, "relayed", False):
        # The word index stays on the stream, hands the batch to the feed and reports what the feed reports.
        context.relay_calls = getattr(context, "relay_calls", 0)

        def invoke(name, payload):
            context.relay_calls += 1
            return _feed(context, json.loads(payload)["Records"])

        environment = {change_feed_relay.FUNCTION_ENVIRONMENT: "papyrus-sample-change-feed", change_feed_relay.STREAMS_ENVIRONMENT: json.dumps([STREAMS["Reference"]])}
        context.reader_failures = change_feed_relay.relay({"Records": batch}, environment=environment, invoke=invoke)
        context.answer = {"batchItemFailures": context.reader_failures}
    else:
        context.answer = _feed(context, batch)
    return context.answer


def _redeliver(context):
    context.sequence -= len(context.last_batch)
    table = next(name for name, arn in STREAMS.items() if arn == context.last_batch[0]["eventSourceARN"])
    deliver(context, table, *[(r["eventName"], decode_image(r["dynamodb"].get("OldImage")), decode_image(r["dynamodb"].get("NewImage"))) for r in context.last_batch])


def _wakes(context):
    return [json.loads(message.body) for message in context.queue.messages]


def _wake_of(context, agent):
    return next(wake for wake in _wakes(context) if wake["wake"]["agent"] == agent)


# --- the site --------------------------------------------------------------------------------------------------------------------------------------


@given("these agents listen for changes")
def agents_listen(context):
    context.agent_rows = [dict(zip(context.table.headings, row.cells)) for row in context.table]
    context.definitions = [_definition(row) for row in context.agent_rows]
    context.thread_reads, context.threads = [], {}
    deploy(context, context.definitions)


@given('the Story "{story}" has the comment thread "{story_thread}" and the Reference "{reference}" has the comment thread "{reference_thread}"')
def threads(context, story, story_thread, reference, reference_thread):
    context.threads = {
        story_thread: {"id": story_thread, "threadKind": "story", "primaryAnchorKind": "item", "primaryAnchorId": f"{story}-v3", "primaryAnchorLineageId": story},
        reference_thread: {"id": reference_thread, "threadKind": "reference", "primaryAnchorKind": "reference", "primaryAnchorId": f"{reference}-v1", "primaryAnchorLineageId": reference},
    }


@given("the deploy writes the listener index without any agent that listens for a posted Message")
def without_message_listeners(context):
    open_index(context)
    deploy(context, [_definition(row) for row in context.agent_rows if row["kind"] != "Message"])


@given("the Reference stream has two other readers and the word index relays its batches to the feed")
def relayed(context):
    context.relayed = True


@given('the definitions "{first}" and "{second}" in Git for changes of other tables')
def definitions_in_git(context, first, second):
    rows = {row["agent"]: row for row in context.agent_rows}
    context.in_git = [_definition(rows[first]), _definition(rows[second])]
    open_index(context)


@when("the deploy writes the listener index for these definitions")
def deploy_writes(context):
    context.published = deploy(context, context.in_git)


@then('the site\'s listener index lists "{first}" under {first_change} and "{second}" under {second_change}')
def index_lists(context, first, first_change, second, second_change):
    document = context.store.read_current(TENANT, "listeners")
    assert [entry["agent"] for entry in document["changes"][first_change]] == [first], document
    assert [entry["agent"] for entry in document["changes"][second_change]] == [second], document


# --- Reference -------------------------------------------------------------------------------------------------------------------------------------


@when('a person accepts the Reference "{reference}"')
def accepts(context, reference):
    deliver(context, "Reference", ("MODIFY", _reference(), _reference(curationStatus="accepted", curationStatusUpdatedBy="ada", curationActorKind="human", curationStatusUpdatedAt=AT)))


@when('the agent "{agent}" accepts the Reference "{reference}"')
def agent_accepts(context, agent, reference):
    deliver(context, "Reference", ("MODIFY", _reference(), _reference(curationStatus="accepted", curationStatusUpdatedBy=f"automation:{agent}", curationActorKind="agent", curationStatusUpdatedAt=AT)))


@when('a person accepts a Reference that belongs to the tenant "{tenant}"')
def foreign(context, tenant):
    deliver(context, "Reference", ("MODIFY", _reference(tenantId=tenant), _reference(tenantId=tenant, curationStatus="accepted", curationStatusUpdatedBy="ada")))


@when('a person adds the Reference "{reference}"')
def adds(context, reference):
    deliver(context, "Reference", ("INSERT", None, _reference()))


@when('a person gives the Reference "{reference}" {stars:d} stars')
def stars(context, reference, stars):
    deliver(context, "Reference", ("MODIFY", _reference(), _reference(starRating=stars, starRatedBy="ada", starRatedAt=AT)))


@when('the Reference "{reference}" is captured again')
def recaptured(context, reference):
    deliver(context, "Reference", ("MODIFY", _reference(retrievedAt="2026-11-17T08:00:00Z"), _reference(retrievedAt="2026-11-18T08:00:00Z")))


@when('the Reference "{reference}" is captured for the first time')
def captured(context, reference):
    deliver(context, "Reference", ("MODIFY", _reference(), _reference(retrievedAt="2026-11-18T08:00:00Z")))


@when('a person edits the title of the Reference "{reference}"')
def edits_title(context, reference):
    deliver(context, "Reference", ("MODIFY", _reference(), _reference(title="A better title")))


@when('the table removes the Reference "{reference}"')
def removes(context, reference):
    deliver(context, "Reference", ("REMOVE", _reference(), None))


# --- ReviewRequest ---------------------------------------------------------------------------------------------------------------------------------


@when('a person answers the review request "{request}" that "{asker}" raised about the Story "{story}"')
def answers(context, request, asker, story):
    deliver(context, "ReviewRequest", ("MODIFY", _review("open", asker, story, request), _review("answered", asker, story, request)))


@when('a person edits the open review request "{request}" that "{asker}" raised about the Story "{story}"')
def edits_request(context, request, asker, story):
    deliver(context, "ReviewRequest", ("MODIFY", _review("open", asker, story, request), _review("open", asker, story, request, ask="a new question")))


# --- Message ---------------------------------------------------------------------------------------------------------------------------------------


@when('a person comments on the Story "{story}"')
def comments_story(context, story):
    deliver(context, "Message", ("INSERT", None, _message()))


@when('a person comments on the Reference "{reference}"')
def comments_reference(context, reference):
    deliver(context, "Message", ("INSERT", None, _message(thread="thread-reference")))


@when('the agent "{agent}" comments on the Story "{story}"')
def agent_comments(context, agent, story):
    deliver(context, "Message", ("INSERT", None, _message(authorLabel=f"automation:{agent}", role="assistant")))


@when("a person edits a comment")
def edits_comment(context):
    deliver(context, "Message", ("MODIFY", _message(), _message(content="edited", editedAt=AT)))


@when("a person posts a console chat turn")
def chat_turn(context):
    deliver(context, "Message", ("INSERT", None, _message(2, messageKind="console_chat_turn")))


# --- LocalizationRequest and Delivery --------------------------------------------------------------------------------------------------------------


@when('a person asks for the translation of the Story "{story}" into "{language}"')
def asks(context, story, language):
    deliver(context, "LocalizationRequest", ("INSERT", None, _request(language)))


@when('a person asks for the translation of the Story "{story}" into "{language}" again later')
def asks_again(context, story, language):
    deliver(context, "LocalizationRequest", ("MODIFY", _request(language), _request(language, at="2026-11-18T12:00:00Z")))


@when('the Delivery "{delivery}" is sent')
def sent(context, delivery):
    deliver(context, "Delivery", ("MODIFY", _delivery("ready", 2), _delivery("sent", 3)))


@when('the Delivery "{delivery}" is drafted')
def drafted(context, delivery):
    deliver(context, "Delivery", ("INSERT", None, _delivery("drafted", 1)))


@when('the table refreshes the counts of the Delivery "{delivery}"')
def refreshes(context, delivery):
    deliver(context, "Delivery", ("MODIFY", _delivery("sent", 3), _delivery("sent", 4, counts=json.dumps({"opened": 2}))))


# --- the feed itself -------------------------------------------------------------------------------------------------------------------------------


@when("the same change record is delivered again after the queue's window")
def again_after(context):
    context.queue.window.clear()
    _redeliver(context)


@when("the queue accepts wakes again and the change batch is retried")
def retry(context):
    context.queue.refuse_from = None
    _redeliver(context)


@when("a record arrives from a stream the feed does not read")
def foreign_stream(context):
    context.sequence = getattr(context, "sequence", 0) + 1
    batch = [stream_record("INSERT", None, _reference(), context.sequence, "arn:aws:dynamodb:us-east-1:000000000000:table/Other/stream/x")]
    try:
        _feed(context, batch)
        context.refused = None
    except change_feeds.UnknownStream as refusal:
        context.refused = str(refusal)


@then("the feed refuses the batch and names the stream")
def refused(context):
    assert context.refused and "table/Other/stream/x" in context.refused, context.refused


@then('the wake key for "{agent}" is "{key}"')
def key_for(context, agent, key):
    assert _wake_of(context, agent)["wake"]["key"] == key, _wake_of(context, agent)["wake"]["key"]


@then('the wake for "{agent}" names the person "{person}" and when they {did}')
def names_person(context, agent, person, did):
    trigger = _wake_of(context, agent)["request"]["trigger"]
    assert (trigger["actorKind"], trigger["actorLabel"]) == ("person", person) and trigger["at"], trigger


@then('the wake for "{agent}" says the table is "{table}" and the change is "{change}"')
def says_table(context, agent, table, change):
    request = _wake_of(context, agent)["request"]
    assert request["trigger"]["event"] == f"{table.lower()}.{change}" and request["input"]["change"] == change, request


@then('the wake for "{agent}" is in the message group of "{name}" and "{subject}"')
def group_of(context, agent, name, subject):
    message = next(message for message in context.queue.messages if json.loads(message.body)["wake"]["agent"] == agent)
    assert message.group == agent_wakes.group_id({"agent": name, "scope": subject})


@then('the wake for "{agent}" says the subject is the Story "{story}"')
def subject_is(context, agent, story):
    assert _wake_of(context, agent)["request"]["input"]["subject"] == {"kind": "Story", "id": story}


@then('the wake for "{agent}" says the change was made by an agent')
def by_agent(context, agent):
    trigger = _wake_of(context, agent)["request"]["trigger"]
    assert trigger["actorKind"] == "agent" and trigger["actorLabel"].startswith("automation:"), trigger


@then("the comment thread was read once")
def thread_read_once(context):
    assert len(context.thread_reads) == 1, context.thread_reads


@then("the comment thread was not read")
def thread_not_read(context):
    assert context.thread_reads == [], context.thread_reads


@then("the wakes carry {count:d} different wake keys")
def different_keys(context, count):
    assert len({wake["wake"]["key"] for wake in _wakes(context)}) == count, [wake["wake"]["key"] for wake in _wakes(context)]


@then("the change feeds' code has no list of any table")
def code_has_no_list(context):
    pattern = re.compile(r"list_(records|tenant_rows|by_index)\(|\.scan\(|\.query\(|list_[a-z_]*automation")
    for path in (REPO_ROOT / "src/papyrus_content/change_feeds.py", REPO_ROOT / "src/papyrus_content/change_vocabulary.py", REPO_ROOT / "amplify/functions/change-feed/handler.py"):
        code = [line for line in path.read_text().splitlines() if not line.lstrip().startswith(("#", '"""'))]
        assert not [line for line in code if pattern.search(line)], f"{path.name} lists a table"


@then("the relayed batch reached the feed once")
def relayed_once(context):
    assert context.relay_calls == 1, context.relay_calls


@then("the reader reports the record as failed")
def reader_reports(context):
    assert context.reader_failures == [{"itemIdentifier": f"{context.sequence:08d}"}], context.reader_failures
