"""The attempt event id reaching the released Caducus (features_backend/announcements/attempt-event-id.feature).

The channel is Caducus's own router, delivery log and ``XChannel`` (the pinned release), wired to in-memory stores and an in-process fake X account. The test
Transport is the small adapter a site would write: hand the event to the router, let the x queue consumer send it, read the delivery log. Nothing leaves the machine.
"""
from __future__ import annotations

import itertools
import json
import re
import sys
from pathlib import Path

from behave import step, then

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from caducus.notify.catalog import catalog_from_mapping  # noqa: E402
from caducus.notify.channels.x import Http, HttpResponse, XChannel  # noqa: E402
from caducus.notify.delivery_log import DeliveryLog  # noqa: E402
from caducus.notify.directory import ChannelAccount, StaticDirectory, account_key  # noqa: E402
from caducus.notify.fakes import X_PRICES, FakeClock, FakeGuard, FakeTokens  # noqa: E402
from caducus.notify.grouping import Dispatcher  # noqa: E402
from caducus.notify.incidents import IncidentTracker  # noqa: E402
from caducus.notify.kinds import Kind, load_registry  # noqa: E402
from caducus.notify.queues import MemoryQueues  # noqa: E402
from caducus.notify.routing import Router  # noqa: E402
from caducus.notify.store import MemoryStore  # noqa: E402
from caducus.notify.triage import TriageSettings  # noqa: E402

from papyrus_content.announcements.attempts import ANSWER_FAILED, ANSWER_SENT, QUEUED, AccountWorker, Answer  # noqa: E402


class FakeXAccount(Http):
    """An in-process X: it posts what it is sent, or refuses with a scripted status."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.refusals: list[str] = []

    def request(self, method, url, headers, body):  # type: ignore[no-untyped-def]
        if self.refusals:
            return HttpResponse(403, {}, json.dumps({"detail": self.refusals.pop(0)}).encode())
        self.posts.append(json.loads(body))
        return HttpResponse(201, {}, json.dumps({"data": {"id": f"post-{len(self.posts)}"}}).encode())


class CaducusTransport:
    """Papyrus's Transport onto the released Caducus: submit the ``story.announce`` event, let the x channel send what was queued, read the delivery log."""

    def __init__(self, handle: str) -> None:
        clock, self.store, ids = FakeClock(), MemoryStore(), itertools.count(1)
        self.account = ChannelAccount(key=account_key("x", handle), address="@example_pub", channel="x", external_id="9001")
        directory = StaticDirectory(["ops@example.invalid"], "test-key-secret", probe_address="probe@example.invalid", accounts=[self.account])
        kinds = load_registry()
        kinds._kinds["story.announce"] = Kind(name="story.announce", klass="broadcast", default_on=True, channels=("x",))
        self.log = DeliveryLog(self.store, clock, make_id=lambda: "d%04d" % next(ids))
        dispatcher = Dispatcher(self.store, self.log, MemoryQueues(), kinds, clock, make_id=lambda: "g%04d" % next(ids))
        self.router = Router(store=self.store, kinds=kinds, log=self.log, directory=directory, dispatcher=dispatcher, incidents=IncidentTracker(self.store, clock),
                             catalog=catalog_from_mapping({"alarms": []}), triage=TriageSettings(portal_url="https://example.invalid", role_name="reader", accounts={}),
                             clock=clock)
        self.x = FakeXAccount()
        self.channel = XChannel(self.store, self.log, directory, tokens=FakeTokens(), prices=X_PRICES, guard=FakeGuard(), clock=clock, http=self.x, recent_count=5,
                                base_url="http://x.invalid")
        self.event_ids: list[str] = []
        self.queued_only = False   # True: like the site, the router only queues the post and the site's X function sends it later

    def submit(self, row, text: str, event_id: str) -> None:  # type: ignore[no-untyped-def]
        self.event_ids.append(event_id)
        result = self.router.handle_detail({"schema": 1, "eventId": event_id, "kind": "story.announce", "product": "papyrus", "site": "example",
                                            "occurredAt": "2026-11-17T09:00:00Z", "severity": "info", "facts": {"title": "A Story", "text": text},
                                            "audience": self.account.key})
        assert result.outcome in ("accepted", "duplicate"), result
        if self.queued_only:
            return
        for queued in self.log.for_event(event_id):
            if queued["status"] == "queued":
                self.channel.send(queued)

    def delivery(self, event_id: str) -> Answer | None:
        rows = self.log.for_event(event_id)
        if not rows:
            return None
        status = rows[0]["status"]
        if status == "sent":
            return Answer(ANSWER_SENT, provider_id=rows[0].get("providerMessageId"), cost=None)
        if status == "failed":
            return Answer(ANSWER_FAILED, code=rows[0].get("reason"))
        assert status == "queued", rows[0]
        return Answer(QUEUED)

    def recorded(self) -> dict[str, str]:
        return {item["eventId"]: item["status"] for (_, sort_key), item in self.store.items.items() if sort_key.startswith("DELIVERY#")}


@step('one worker serves the channel "{channel}" account "{account}" through the released Caducus')
def worker_on_caducus(context, channel, account):
    context.caducus = CaducusTransport(account)
    context.workers = {(channel, account): AccountWorker(context.deliveries, context.caducus, channel, account)}
    context.worker = context.workers[(channel, account)]


@step('the fake X account refuses the next post with "{detail}"')
def x_refuses(context, detail):
    context.caducus.x.refusals.append(detail)


@then('Caducus recorded exactly these events for the Delivery "{channel}" "{account}"')
def recorded_events(context, channel, account):
    delivery = next(row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account)["id"]
    wanted = {row["event id"].replace("<the Delivery id>", delivery): row["status"] for row in context.table}
    assert context.caducus.recorded() == wanted, (context.caducus.recorded(), wanted)


@then("no event id Caducus recorded carries a round suffix")
def no_round_suffix(context):
    for event_id in context.caducus.recorded():
        assert re.fullmatch(r"delivery:[^:]+:a\d+", event_id), event_id


@then('the fake X account received {count:d} post with the text "{text}"')
def x_received(context, count, text):
    assert context.caducus.x.posts == [{"text": text}] * count, context.caducus.x.posts


@step("the channel leaves each post on the X queue for the site's X function")
def queued_only(context):
    context.caducus.queued_only = True


@step("the site's X function takes the queued post")
def x_function_takes(context):
    """The site's X function: one message of the x queue for each queued delivery Caducus logged, posted by the x channel, and then the Delivery settled from Caducus's
    record (announcements/settle_after_post.py)."""
    from papyrus_content.announcements.settle_after_post import settle_after_post
    from papyrus_content.notifications.x_sender import handle_batch

    records = [{"messageId": f"m{index}", "body": json.dumps({"eventId": row["eventId"], "deliveryId": row["deliveryId"]})}
               for index, event_id in enumerate(context.caducus.event_ids) for row in context.caducus.log.for_event(event_id)]
    context.x_function_answer = handle_batch(context.caducus.store, context.caducus.channel, {"Records": records},
                                             posted=lambda event_id: settle_after_post(context.deliveries, context.caducus, event_id, now=context.now))
    assert context.x_function_answer == {"batchItemFailures": []}, context.x_function_answer
