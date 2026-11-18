"""The fakes the change feeds' specs share (features_backend/item-change-feed.feature, features_backend/change-feeds.feature): a fake stream record, a fake FIFO
queue that follows SQS's rules, and the real site store over fakes, counting what the feed reads. No network."""
from __future__ import annotations

from boto3.dynamodb.types import TypeSerializer

from . import agent_listeners
from .site_store import SiteStore
from .site_store_test import FakeS3, FakeTable

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


def open_index(context):
    """A fresh site store and listener index on the scenario's context."""
    context.s3, context.catalogue = CountingS3(), CountingTable()
    context.deploy_gets = 0
    context.store = SiteStore(context.s3, BUCKET, context.catalogue, now=lambda: "2026-11-18T00:00:00Z")
    context.index = agent_listeners.ListenerIndex(context.store, TENANT)


def deploy(context, definitions):
    """The deploy's write of the index. Its own reads of the object are not the feed's, so they are counted apart."""
    before = context.s3.gets
    result = agent_listeners.publish(context.store, TENANT, definitions, actor="release", apply=True)
    context.deploy_gets += context.s3.gets - before
    return result


def stream_record(name, old, new, sequence, source_arn=None):
    image = lambda row: {key: SERIALIZER.serialize(value) for key, value in row.items()} if row else None   # noqa: E731
    stream = {"SequenceNumber": f"{sequence:08d}", "Keys": {"id": SERIALIZER.serialize((new or old)["id"])}}
    if old:
        stream["OldImage"] = image(old)
    if new:
        stream["NewImage"] = image(new)
    record = {"eventName": name, "dynamodb": stream}
    if source_arn:
        record["eventSourceARN"] = source_arn
    return record
