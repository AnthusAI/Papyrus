"""The site's X channel as production wires it: Papyrus's ``CaducusBroadcaster`` over Caducus's own router, delivery log and ``XChannel`` (the pinned release), the site's own notification kinds,
``SiteAccounts``, ``SpendGuard`` and the price table of the settings document, and a fake X server answering on localhost (``caducus.notify.fakes.FakeX``). The ``x`` queue is consumed by the
real consumer (``notifications.x_sender``). Nothing leaves the machine and nothing is ever posted to X.

It replaces the in-memory ``context.x`` of ``announcements_steps`` with the Broadcaster, so the announce agent's own steps (the deliver side, the settle, the withdrawal) run over the real path.
"""
from __future__ import annotations

import itertools
import json
import sys
from decimal import Decimal
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from caducus.notify.catalog import catalog_from_mapping  # noqa: E402
from caducus.notify.channels.x import UrllibHttp, XChannel as CaducusXChannel  # noqa: E402
from caducus.notify.delivery_log import DeliveryLog  # noqa: E402
from caducus.notify.directory import StaticDirectory  # noqa: E402
from caducus.notify.fakes import FakeClock, FakeX, X_TOKEN, X_USER_ID  # noqa: E402
from caducus.notify.grouping import Dispatcher  # noqa: E402
from caducus.notify.incidents import IncidentTracker  # noqa: E402
from caducus.notify.kinds import load_registry  # noqa: E402
from caducus.notify.queues import MemoryQueues  # noqa: E402
from caducus.notify.routing import Router  # noqa: E402
from caducus.notify.store import MemoryStore  # noqa: E402
from caducus.notify.triage import TriageSettings  # noqa: E402

from papyrus_content.announcements import channel as channel_module  # noqa: E402
from papyrus_content.announcements.caducus_x import CaducusBroadcaster, SettingsPrices, SiteAccounts  # noqa: E402
from papyrus_content.announcements.channel import CaducusTokens  # noqa: E402
from papyrus_content.announcements.x_delivery import x_runner  # noqa: E402
from papyrus_content.notifications.runtime import CONFIG_DIRECTORY  # noqa: E402
from papyrus_content.notifications.x_sender import handle_batch  # noqa: E402


class Accounts:
    """What ``x_account.XAccounts`` gives the token provider: an access token for the connected account."""

    def access_token(self):
        return X_TOKEN


def wire(context):
    clock, ids = FakeClock(), itertools.count(1)
    context.caducus_store, context.caducus_queues, context.caducus_clock = MemoryStore(), MemoryQueues(), clock
    context.fake_x = FakeX()
    context.add_cleanup(context.fake_x.close)
    # The connected account is the X user the fake server knows: the account id of a connection is X's own user id.
    context.functions.connected = {"connection": "connected", "accountId": X_USER_ID, "handle": "@mom_test"}
    kinds = load_registry(CONFIG_DIRECTORY)
    directory = SiteAccounts(lambda: context.functions.status(), StaticDirectory([], "test-key-secret"))
    log = DeliveryLog(context.caducus_store, clock, make_id=lambda: "d%04d" % next(ids))
    dispatcher = Dispatcher(context.caducus_store, log, context.caducus_queues, kinds, clock, make_id=lambda: "g%04d" % next(ids))
    router = Router(store=context.caducus_store, kinds=kinds, log=log, directory=directory, dispatcher=dispatcher, incidents=IncidentTracker(context.caducus_store, clock),
                    catalog=catalog_from_mapping({"alarms": []}), triage=TriageSettings(portal_url="https://example.invalid", role_name="reader", accounts={}), clock=clock)
    context.caducus_waits = []
    channel = CaducusXChannel(context.caducus_store, log, directory, tokens=CaducusTokens(Accounts()), prices=SettingsPrices(context.functions.read), guard=context.guard, clock=clock,
                              http=UrllibHttp(timeout=0.3), recent_count=5, base_url=context.fake_x.url, sleep=context.caducus_waits.append)
    context.caducus_log, context.caducus_channel, context.caducus_router, context.caducus_kinds = log, channel, router, kinds
    context.x = CaducusBroadcaster(router, log, channel, "mom", clock)


def run_queue(context):
    """The x queue's consumer, once for every message waiting. A message it reports as failed goes back (as SQS would redeliver it); the others are gone."""
    waiting, context.caducus_queues.sent = [body for name, body in context.caducus_queues.sent if name == "x"], []
    returned = []
    for number, body in enumerate(waiting):
        answer = handle_batch(context.caducus_store, context.caducus_channel, {"Records": [{"messageId": f"m{number}", "body": json.dumps(body)}]})
        if answer["batchItemFailures"]:
            returned.append(body)
    context.caducus_queues.sent.extend(("x", body) for body in returned)
    context.returned_to_queue = returned


@given("the site's X channel is the released Caducus, with X itself a fake server on localhost")
def _wire(context):
    wire(context)


@given("X accepts the post but its answer never arrives")
def _hang(context):
    context.fake_x.script.append(("post-then-hang",))


@given("X answers that the rate limit is reached until {seconds:d} seconds from now")
def _rate_limit(context, seconds):
    reset = int(context.caducus_clock.now.timestamp()) + seconds
    context.fake_x.script.append(("status", 429, {"title": "Too Many Requests"}, {"x-rate-limit-reset": str(reset)}))


@when("the x queue runs")
@given("the x queue runs")
def _runs(context):
    run_queue(context)


@when("the x queue runs again")
def _runs_again(context):
    run_queue(context)


@then("the x queue holds {count:d} message")
def _queue_holds(context, count):
    assert len([1 for name, _ in context.caducus_queues.sent if name == "x"]) == count, context.caducus_queues.sent


@then("the fake X server holds {count:d} post")
@then("the fake X server holds {count:d} posts")
def _x_holds(context, count):
    assert len(context.fake_x.posts) == count, context.fake_x.posts


@then("every request to the fake X server carried the account's access token")
def _token(context):
    assert context.fake_x.requests and all(r["authorization"] == "Bearer " + X_TOKEN for r in context.fake_x.requests), context.fake_x.requests


@then("the account's recent posts were read once and none was posted again")
def _read_not_posted(context):
    posts = [r for r in context.fake_x.requests if r["method"] == "POST"]
    reads = [r for r in context.fake_x.requests if r["method"] == "GET"]
    assert len(posts) == 1 and len(reads) == 1, context.fake_x.requests


@then("the kind story.announce is a broadcast to the channel x in the site's own kinds")
def _kind(context):
    context.caducus_kinds = load_registry(CONFIG_DIRECTORY)
    kind = context.caducus_kinds.get("story.announce")
    assert kind is not None and kind.klass == "broadcast" and kind.channels == ("x",), kind


@then("the account key Caducus posts to is CHANNELACCT#x# followed by the connected account's id")
def _audience(context):
    from papyrus_content.announcements.x_channel import CHANNEL

    event = context.caducus_store.get("EVENT#delivery:" + x_id(context) + ":a1", "META")["event"]
    assert CHANNEL == "x" and event["audience"] == channel_module.audience(X_USER_ID), event


def x_id(context):
    from announcements_steps import x_row

    return x_row(context)["id"]


@then("the account's spend this cycle is ${amount}")
def _spend(context, amount):
    from announcements_steps import NOW
    from papyrus_content.announcements import budget

    assert Decimal(context.ledger.spent(X_USER_ID, budget.cycle_start(NOW, 1)) or 0) == Decimal(amount)


@given("the site is On and has no Caducus x channel")
def _no_channel(context):
    context.no_channel = True


@when("the deliver side is built for the site")
def _built(context):
    context.built_error, context.built = None, None
    try:
        context.built = x_runner(context.deliveries, context.announcements, context.control, None)
    except channel_module.ChannelNotAvailable as error:
        context.built_error = error


@then('the site refuses with ChannelNotAvailable saying "{text}"')
def _refused(context, text):
    assert context.built_error is not None and text in str(context.built_error), context.built_error


@then("the site has no deliver side and nothing to send")
def _nothing(context):
    assert context.built is None and context.built_error is None


@when("Caducus is handed an announcement for an account that is not the connected one")
def _other_account(context):
    from papyrus_content.announcements.caducus_x import SubmitRefused

    context.submit_error = None
    try:
        context.x.submit(account_id="somebody-else", event_id="delivery:other:a1", text="A post https://example.com/a", url="https://example.com/a")
    except SubmitRefused as error:
        context.submit_error = error


@then('the hand-over is refused saying "{text}"')
def _hand_over_refused(context, text):
    assert context.submit_error is not None and text in str(context.submit_error), context.submit_error


@then("nothing was queued on the x queue")
def _nothing_queued(context):
    assert [1 for name, _ in context.caducus_queues.sent if name == "x"] == []


@given('X refuses the next post with "{message}"')
def _x_refuses(context, message):
    context.fake_x.script.append(("status", 403, {"detail": message}, {}))


@then("the message goes back to the queue")
def _returned(context):
    assert len(context.returned_to_queue) == 1 and len([1 for name, _ in context.caducus_queues.sent if name == "x"]) == 1, context.returned_to_queue


@then("Caducus waited about {seconds:d} seconds")
def _waited(context, seconds):
    assert len(context.caducus_waits) == 1 and abs(context.caducus_waits[0] - seconds) < 2, context.caducus_waits
