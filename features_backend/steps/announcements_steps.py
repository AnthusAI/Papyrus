"""X on the Announcement and Delivery records (features_backend/announcements-*.feature, announce-edit-windows.feature).

The pieces are the real ones: the announce agent's worker (``list_cadence.story_wake``) with its X part, the Announcement and Delivery records on their in-memory backend, the
agent policy store, the spend guard and ledger, the one account worker, the withdraw and correct operations. What is stood in for is the world: Caducus's x channel
(``fakes.FakeX``, which asks the real Guard before a post), the model and its judge, the settings document, and the Story. No network, no AWS, and never a real post.
"""
from __future__ import annotations

import io
import json
import shlex
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.agent_policy import AgentPolicyStore  # noqa: E402
from papyrus_content.announcements import blocked_drafts, budget, learned_examples, lines, operations, post, records, review_handlers  # noqa: E402
from papyrus_content.announcements import cli as announcements_cli  # noqa: E402
from papyrus_content.announcements.attempts import Attempts, NotReleasable  # noqa: E402
from papyrus_content.announcements.decisions import Announcements  # noqa: E402
from papyrus_content.announcements.deliveries import Deliveries, Plan  # noqa: E402
from papyrus_content.announcements.eligibility import load_story  # noqa: E402
from papyrus_content.announcements.fakes import FakeFunctions, FakeX, StoryRecordsBackend  # noqa: E402
from papyrus_content.announcements.guard import SpendGuard  # noqa: E402
from papyrus_content.announcements.handlers import signed_in_handlers  # noqa: E402
from papyrus_content.announcements.intake import ChecklistReviewStamps  # noqa: E402
from papyrus_content.announcements.link_reads import StoryRef  # noqa: E402
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles  # noqa: E402
from papyrus_content.announcements.review_policy import RESPONSIBILITY, RUNG_OF  # noqa: E402
from papyrus_content.announcements.spend import SpendLedger  # noqa: E402
from papyrus_content.announcements.withdrawals import Withdrawals  # noqa: E402
from papyrus_content.announcements.x_account import AnnouncementError  # noqa: E402
from papyrus_content.announcements.x_announce import XAnnouncer, XServices  # noqa: E402
from papyrus_content.announcements.x_channel import XChannel  # noqa: E402
from papyrus_content.announcements.x_runner import NotSendable, SpendControl, XRunner  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402
from papyrus_content.list_cadence import story_wake  # noqa: E402
from papyrus_content.list_cadence.announce import Candidate  # noqa: E402
from papyrus_content.list_cadence.store import ListState  # noqa: E402
from papyrus_content.site_store import SiteStore  # noqa: E402
from papyrus_content.site_store_test import FakeS3, FakeTable  # noqa: E402

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-11-13T09:00:00Z"
TENANT = "alpha"
ADMIN = Caller(kind="person", subject="ada", is_admin=True)
PRICES = {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}
SUMMARY = "Whether a system can keep a secret from itself."
DEFAULT_DRAFT = "A look at whether a system can keep a secret from itself."
ORIGIN = "https://machines.example"
NOT_IN_STORY = "first proof ever"


class Account:
    def __init__(self, key):
        self.key = key


class Price:
    def __init__(self, amount):
        self.amount = amount


class RecordingX(XAnnouncer):
    """The announce agent's X part, remembering what it decided in its last wake."""

    last = None

    def consider(self, lineage):
        self.last = super().consider(lineage)
        return self.last


# --- the world ---------------------------------------------------------------------------------------------------------------------------------------


def setup(context):
    context.backend = StoryRecordsBackend()
    context.files = MemoryDeliveryFiles(context.backend)
    context.deliveries = Deliveries(context.backend, context.files)
    context.announcements = Announcements(context.backend, context.deliveries)
    context.ledger = SpendLedger(context.backend)
    context.functions = FakeFunctions(lambda: NOW.timestamp())
    context.told = []
    context.control = SpendControl(settings=context.functions, connection=context.functions.status, ledger=context.ledger,
                                   notify=lambda kind, facts: context.told.append((kind, dict(facts))), now=lambda: NOW)
    context.guard = SpendGuard(context.ledger, context.functions, lambda: NOW)
    context.x = FakeX()
    context.x.guard = context.guard
    context.now = NOW_ISO
    context.model_calls = []
    context.model_input = None
    context.draft_text = DEFAULT_DRAFT
    context.unsupported = [NOT_IN_STORY]
    context.rule_problems = []
    context.guidelines = "Voice: plain and kind."
    context.lineage = None
    context.counter = 0
    context.failure = None
    context.last = None
    context.considered = None
    context.refusal = None
    context.send_refusal = None
    context.require_reviewed = False
    context.reviewed_stories = set()
    context.removal_crash = False
    s3, catalogue = FakeS3(), FakeTable()
    clock = iter(f"2026-11-16T00:{minute:02d}:{second:02d}Z" for minute in range(60) for second in range(60))
    context.policy = AgentPolicyStore(SiteStore(s3, "bucket", catalogue, now=lambda: next(clock)))
    context.backend.tenant_id = TENANT
    context.edit_windows = []
    context.flush_stamps = None


class Stamps:
    """The human review stamp a spec says a Story has: the reader of ``intake.ReviewStamps``."""

    def __init__(self, context):
        self.context = context

    def reviewed(self, lineage, version):
        return lineage in self.context.reviewed_stories


def policy_state(context):
    return context.policy.read(TENANT)


def xservices(context):
    def llm(system, user, schema):
        context.model_calls.append(user)
        context.model_input = user
        context.model_system = system
        return {"text": context.draft_text}

    def judge(claim, cited, info=None):
        source = " ".join(cited.values())
        bad = any(phrase.lower() in claim.lower() for phrase in context.unsupported)
        return {"verdict": "not_supported" if bad else "supported", "quotes": [] if bad else [source.split("\n")[0]], "explanation": "",
                "attribution_lost": False, "claim_is_only_about_source_limits": False}

    return XServices(settings=context.functions.read, connection=context.functions.status, story=lambda lineage: load_story(context.backend, lineage, item_url_style="clean"),
                     site_origin=lambda: ORIGIN, guidelines_for=lambda story: context.guidelines, llm=llm, judge=judge,
                     rule_lane=(lambda text: context.rule_problems) if context.rule_problems else None, model="gpt-6-luna",
                     learned=lambda: learned_examples.load(context.deliveries, channel="x", kind="story_published", words_of=lambda text: post.LINK.sub("", text).strip()),
                     guideline_layers=lambda story: list(getattr(context, "guideline_layers", [])))


def services(context):
    return operations.Services(client=context.backend, x=xservices(context), control=context.control, deliveries=context.deliveries)


def save(context, **changes):
    operations.update_settings(services(context), changes, by="ryan")


def mom(context, *, mode, stars=5, sections=None, budget_amount="10.00"):
    changes = {"mode": mode, "minStars": stars, "storyTypes": ["article"], "budget": budget_amount, "billingCycleDay": 1, "prices": PRICES, "labelConfirmed": True}
    if sections:
        changes["sections"] = list(sections)
    save(context, **changes)
    if context.edit_windows:
        save(context, editWindows=list(context.edit_windows))


def story(context, *, stars=5, published=True, story_type="article", section=None, rated_by="ellie"):
    context.counter += 1
    context.lineage = f"story-{context.counter}"
    context.backend.add_story(context.lineage, stars=stars, published=published, story_type=story_type, section=section, summary=SUMMARY)
    context.backend.items[f"{context.lineage}-v1"]["starRatedBy"] = rated_by


def read_story(context):
    def read(lineage):
        published = context.backend.published.get(f"published-{lineage}")
        if not published:
            return None
        head = context.backend.items[f"{lineage}-v1"]
        return Candidate(StoryRef(lineage, head["id"], int(published.get("versionNumber") or 1)), published.get("section"), published.get("type"), [], int(head.get("starRating") or 0), False)

    return read


def wake(context, lineage=None, change="stage_entered"):
    """One wake of the announce agent for the Story: the real worker with its X part, over the real records."""
    lineage = lineage or context.lineage
    version = int(context.backend.items[f"{lineage}-v1"].get("versionNumber") or 1)
    x = RecordingX(xservices(context), context.announcements, policy_state(context), Stamps(context), by="announce")
    request = {"input": {"story": lineage, "version": f"{lineage}-v{version}", "change": change, "stage": "published" if change == "stage_entered" else None}}
    context.failure = None
    try:
        context.last = story_wake.run_story_wake(request, ListState(1, {"schemaVersion": 1, "lists": {}}), context.announcements, read_story=read_story(context),
                                                 draft=lambda *_: "", policy_rung=lambda _: "off", account_id="site", by="announce", now=context.now, x=x,
                                                 edit_settings=context.functions.read())
    except Exception as error:   # noqa: BLE001 - the specs ask what the wake said
        context.failure, context.last = error, None
    context.considered = x.last


def x_rows(context):
    return [dict(row) for row in context.backend.rows("Delivery") if row["channel"] == "x"]


def x_row(context, generation=None):
    rows = x_rows(context)
    assert rows, "the Announcement has no X Delivery"
    if generation is not None:
        return next(row for row in rows if int(row["generation"]) == generation)
    return max(rows, key=lambda row: int(row["generation"]))


def x_row_fresh(context, generation=None):
    return context.deliveries.get(x_row(context, generation)["id"])


def announcement_of(context):
    return context.announcements.by_dedupe_key(records.story_published_key(context.lineage))


def words_of(row):
    return lines.delivery_line(row, NOW_ISO)["words"]


def runner(context):
    channel = XChannel(context.x, budget_wait_until=lambda: budget.next_cycle_start(budget.cycle_start(NOW, 1), 1).isoformat() + "T00:00:00Z")
    context.channel = channel
    withdrawals = Withdrawals(context.deliveries, context.announcements, removers=lambda row: channel)
    return XRunner(context.deliveries, withdrawals, channel, context.control, by="deliver")


def try_send(context, action):
    context.send_refusal = None
    try:
        return action()
    except (NotSendable, NotReleasable) as refused:
        context.send_refusal = refused
        return None


def release_announcement(context):
    context.announcements.release_due(NOW_ISO)


# --- givens -------------------------------------------------------------------------------------------------------------------------------------------


@given("a site whose quality floor is {floor:d} stars")
def _floor(context, floor):
    setup(context)


@given('an X account "{account}" is connected to the site')
def _account(context, account):
    context.account = account


@given("no X account is connected to the site")
def _no_account(context):
    context.functions.connected = {"connection": "not_connected"}


@given("the site never turned announcements on")
def _never(context):
    pass


@given("the announce agent may act without a person's release")
def _may_act(context):
    context.policy.set_rung(TENANT, ADMIN, RESPONSIBILITY, RUNG_OF["none"], reason="Seed")


@given('the announce agent is at the rung "{rung}"')
def _rung(context, rung):
    context.policy.set_rung(TENANT, ADMIN, RESPONSIBILITY, rung, reason="Seed")


@given("the publication wants a person's review of a Story before X announces it")
def _requires_review(context):
    save(context, requireReviewedSource=True)


@given("the site announces Articles rated {stars:d} stars, in Dry run")
def _dry(context, stars):
    mom(context, mode="dry_run", stars=stars)


@given('the site announces Articles rated {stars:d} stars in the "{section}" section, in Dry run')
def _section(context, stars, section):
    mom(context, mode="dry_run", stars=stars, sections=[section])


@given("the site announces Articles rated {stars:d} stars with a budget of ${amount}, in Dry run")
def _budget(context, stars, amount):
    mom(context, mode="dry_run", stars=stars, budget_amount=amount)


@given("the mode is On")
def _on(context):
    save(context, mode="on")


@given("the owner turns the mode Off")
def _off(context):
    save(context, mode="off")


@given("the owner turns the mode to Dry run and a second Story is published")
def _to_dry(context):
    first = context.lineage
    save(context, mode="dry_run")
    story(context)
    wake(context)
    context.first_lineage = first


@given('X will refuse posts with "{message}"')
def _refuse(context, message):
    context.x.fail_with = message


@given("the account needs reconnecting")
def _reconnect(context):
    context.functions.connected = {"connection": "needs_reconnecting", "accountId": "mom", "handle": "@mom_test"}


@given('the model drafts "{text}"')
def _drafts(context, text):
    context.draft_text = text


@given('the model now drafts "{text}"')
def _now_drafts(context, text):
    context.draft_text = text
    context.unsupported = []


@given("the model drafts a post of {count:d} characters")
def _long(context, count):
    context.draft_text = ("secrets " * 100)[:count].strip()


@given('the editorial rules reject the draft with "{message}"')
def _rules(context, message):
    context.rule_problems = [message]


@given("the site has no writing guidelines")
def _no_guidelines(context):
    context.guidelines = ""


@given("announcements are paused")
def _paused(context):
    operations.pause_announcements(services(context), by="ryan")


@given("${amount} is already spent this cycle")
def _spent(context, amount):
    context.guard.charged(Account("CHANNELACCT#x#mom"), Price(amount))


@given("${amount} is already spent in the last cycle")
def _spent_before(context, amount):
    context.ledger.add_spend("mom", budget.cycle_start(datetime(2026, 10, 20, tzinfo=timezone.utc), 1), Decimal(amount))


@given("a {stars:d}-star Article is published")
def _publish_given(context, stars):
    story(context, stars=stars)
    wake(context)


@given("a published {stars:d}-star Article that the announce agent already looked at")
def _looked_at(context, stars):
    story(context, stars=stars)
    wake(context)


@given("an announced Article")
def _announced(context):
    story(context)
    wake(context)


@given("a retired {stars:d}-star Article")
def _retired(context, stars):
    story(context, stars=stars)
    context.backend.retire(context.lineage)


@given("the Article is retired")
def _retire_now(context):
    context.backend.retire(context.lineage)


@given("an Announcement for the Article that has an email Delivery")
def _with_email(context):
    ref = StoryRef(context.lineage, f"{context.lineage}-v1", 1)
    plan = Plan(channel="email", account_id="site", approval="none", approval_policy="publication policy", text="An alert about the Article", audience=("everything",))
    context.announcements.announce(dedupe_key=records.story_published_key(context.lineage), kind="story_published", stories=[ref], plans=[plan], created_by="announce",
                                   trigger="page_live", now=context.now)


@given("the edit window for story_published on x is {window:d} minutes with a lock lead of {lead:d} minutes")
def _window_x(context, window, lead):
    context.edit_windows.append({"kind": "story_published", "channel": "x", "windowMinutes": window, "lockLeadMinutes": lead})
    save(context, editWindows=list(context.edit_windows))


@given("the edit window for the kind story_published is {window:d} minutes with a lock lead of {lead:d} minutes")
def _window_kind(context, window, lead):
    context.edit_windows.append({"kind": "story_published", "windowMinutes": window, "lockLeadMinutes": lead})
    save(context, editWindows=list(context.edit_windows))


@given("the next write of a blocked Delivery fails as if the connection dropped")
def _crash(context):
    context.backend.fail_next("update", "Delivery")


@given("the X Delivery was sent and Caducus posted it for ${amount}")
def _x_sent(context, amount):
    run = runner(context)
    run.send(x_row(context)["id"], now=context.now)
    context.x.post_price = amount
    for event in list(context.x.events):
        if context.x.deliveries[event]["status"] == "queued":
            context.x.deliver(event)
    run.settle(x_row(context)["id"], now=context.now)
    release_announcement(context)
    assert x_row_fresh(context)["state"] == "sent", x_row_fresh(context)


@given("an email Delivery on the same Announcement was sent")
def _email_sent(context):
    announcement = announcement_of(context)
    plan = Plan(channel="email", account_id="site", approval="none", approval_policy="publication policy", text="The email as it went", audience=("everything",))
    row = context.deliveries.add(announcement["id"], plan, release_at=NOW_ISO, by="announce", now=context.now)
    entry = {"number": 1, "at": NOW_ISO, "eventId": f"delivery:{row['id']}:a1", "outcome": "sent", "closedAt": NOW_ISO}
    context.deliveries._change(row, {"state": "sent", "attempts": [entry]}, by="deliver", note="attempt 1 sent", now=NOW_ISO)
    context.email_id = row["id"]


@given('a manual X Delivery on another Announcement was recorded as posted by "{who}"')
def _manual_sent(context, who):
    ref = StoryRef(context.lineage, f"{context.lineage}-v1", 1)
    plan = Plan(channel="x", account_id="mom", approval="none", approval_policy="publication policy", text="Posted by hand", mode="manual")
    outcome = context.announcements.announce(dedupe_key="manual:hand-1", kind="manual", stories=[ref], plans=[plan], created_by=who, trigger="person", now=context.now)
    context.manual_id = outcome.deliveries[0]["id"]
    Attempts(context.deliveries).record_manual(context.manual_id, "https://x.example/status/1", by=who, now=context.now)


@given('the channel deleted the post but the Delivery was not written')
def _deleted_not_written(context):
    row = x_row_fresh(context)
    from papyrus_content.announcements.withdrawals import sent_event

    XChannel(context.x).delete(sent_event(row), by="ada")


@given("the channel deleted the old post but the old Delivery was not written")
def _deleted_old_not_written(context):
    from papyrus_content.announcements.withdrawals import sent_event

    old = x_row_fresh(context, 1)
    XChannel(context.x).delete(sent_event(old), by="ada")


# --- whens: Stories and the announce agent -------------------------------------------------------------------------------------------------------------


@when("a {stars:d}-star Article is published")
def _publish(context, stars):
    story(context, stars=stars)
    wake(context)


@when('a {stars:d}-star Article "{title}" is published')
def _publish_titled(context, stars, title):
    story(context, stars=stars)
    wake(context)


@when("an unrated Article is published")
def _unrated(context):
    story(context, stars=None)
    wake(context)


@when("an unrated Article is published and a model predicts 5 stars for it")
def _predicted(context):
    story(context, stars=None)
    context.backend.items[f"{context.lineage}-v1"]["predictedStars"] = 5
    wake(context)


@when("a {stars:d}-star Post is published")
def _post(context, stars):
    story(context, stars=stars, story_type="post")
    wake(context)


@when('a {stars:d}-star Article in the "{section}" section is published')
def _in_section(context, stars, section):
    story(context, stars=stars, section=section)
    wake(context)


@when("a {stars:d}-star Article is saved as a draft")
def _draft(context, stars):
    story(context, stars=stars, published=False)
    wake(context)


@when('a Story rated {stars:d} stars by the machine "{who}" is published')
def _machine_rated(context, stars, who):
    story(context, stars=stars, rated_by=f"agent:{who}")
    wake(context)


@when('a Story rated {stars:d} stars by the person "{who}" is published')
def _person_rated(context, stars, who):
    story(context, stars=stars, rated_by=who)
    wake(context)


@when("a person rates a Story {stars:d} stars and it is published")
def _rated_published(context, stars):
    story(context, stars=stars)
    wake(context)


@when("the announce agent wakes for the Article")
def _wakes(context):
    wake(context)


@when("an editor rates the Article {stars:d} stars")
def _rate(context, stars):
    context.backend.rate(context.lineage, stars, by="ellie")


@when("a person rates the Article again and the announce agent wakes for it")
def _rate_again(context):
    wake(context, change="rated")


@when("the Story changes to version {version:d} and the announce agent wakes for it")
def _version(context, version):
    context.backend.items[f"{context.lineage}-v1"]["versionNumber"] = version
    context.backend.published[f"published-{context.lineage}"]["versionNumber"] = version
    wake(context)


@when("the guidelines change and the announce agent wakes for the Article")
def _guidelines_change(context):
    context.guidelines = "Voice: plain, kind and brief."
    wake(context)


@when("the Article is announced again because a corrected version was published")
def _again(context):
    wake(context)


@when('the clock reads "{when}"')
def _clock(context, when):
    context.now = when


@when("the owner sets the announcement minimum to {stars:d} stars")
def _low(context, stars):
    _try_save(context, minStars=stars)


def _try_save(context, **changes):
    try:
        save(context, **changes)
        context.refusal = None
    except AnnouncementError as error:
        context.refusal = error


@when("the owner turns the mode On without confirming the Automated label")
def _no_label(context):
    _try_save(context, mode="on", minStars=5, storyTypes=["article"], prices=PRICES, budget="10.00", billingCycleDay=1)


@when("the owner turns the mode On without a budget")
def _no_budget(context):
    _try_save(context, mode="on", minStars=5, storyTypes=["article"], prices=PRICES, labelConfirmed=True)


@when("the owner pauses announcements")
def _pause(context):
    operations.pause_announcements(services(context), by="ryan")


@when("the owner resumes announcements")
def _resume(context):
    operations.resume_announcements(services(context), by="ryan")


@when("the owner raises the budget to ${amount}")
def _raise(context, amount):
    save(context, budget=amount)


# --- whens: the deliver side and Caducus --------------------------------------------------------------------------------------------------------------


@when("the deliver side sends the X Delivery")
def _sends(context):
    try_send(context, lambda: runner(context).send(x_row(context)["id"], now=context.now))


@given("the deliver side sends the X Delivery")
def _sends_given(context):
    _sends(context)


@when("the deliver side tries to send the X Delivery")
def _tries(context):
    _sends(context)


@when("the deliver side sends what is due")
def _sends_due(context):
    context.sent_due = runner(context).send_due(context.now)


@when("the deliver side reads what Caducus recorded")
def _reads(context):
    runner(context).settle(x_row(context)["id"], now=context.now)


@given("the deliver side reads what Caducus recorded")
def _reads_given(context):
    _reads(context)


def _caducus_delivers(context, amount=None, refusal=None):
    if amount is not None:
        context.x.post_price = amount
    for event in list(context.x.events):
        if context.x.deliveries[event]["status"] == "queued":
            context.x.deliver(event, refusal=refusal)


@when("Caducus posts it for ${amount}")
def _caducus_posts(context, amount):
    _caducus_delivers(context, amount)


@given("Caducus posts it for ${amount}")
def _caducus_posts_given(context, amount):
    _caducus_delivers(context, amount)


@when('Caducus\'s guard refuses it with "{reason}"')
@given('Caducus\'s guard refuses it with "{reason}"')
def _guard_refuses(context, reason):
    _caducus_delivers(context, refusal=reason)


@when("Caducus reports a ${amount} charge on the account")
def _charge(context, amount):
    context.guard.charged(Account("CHANNELACCT#x#mom"), Price(amount))


@when("the account's X Deliveries are listed")
def _list(context):
    context.backend.reads.clear()
    context.listed = list(context.deliveries.for_account("x", "mom"))


# --- whens: withdraw and correct ----------------------------------------------------------------------------------------------------------------------


def _handlers(context, removers=None, judge=None, story_facts=None):
    review_handlers._publication = lambda client: "publication"   # the publication's key is read from the site's own record, which these specs do not build
    return review_handlers.signed_in_handlers(client_factory=lambda: context.backend, policy_factory=lambda client: None, files=context.files, judge=judge or _judge("supported"),
                                              story=story_facts or (lambda: load_story(context.backend, context.lineage, item_url_style="clean")),
                                              environ={"SITE_ORIGIN": ORIGIN, "ITEM_URL_STYLE": "clean"}, removers=removers)


def _judge(verdict):
    def judge(claim, cited, info=None):
        quote = " ".join(cited.values()).split("\n")[0] if verdict == "supported" else ""
        return {"verdict": verdict, "quotes": [quote] if quote else [], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}
    return judge


def _caller(who):
    return Caller(kind="agent", subject=who) if who == "announce" else Caller(kind="person", subject=who)


def _withdraw(context, who, delivery, removers):
    context.envelope = execute("announcements_withdraw", {"delivery": delivery}, _caller(who), {"announcements_withdraw": _handlers(context, removers)["announcements_withdraw"]})
    context.withdraw_error = None if context.envelope["ok"] else context.envelope["error"]


def _own_channel(context):
    channel = XChannel(context.x)
    return lambda row: channel


@when('the person "{who}" withdraws the X Delivery through the site\'s own X channel')
@given('the person "{who}" withdraws the X Delivery through the site\'s own X channel')
def _withdraw_with_channel(context, who):
    _withdraw(context, who, x_row(context)["id"], _own_channel(context))


@when('the person "{who}" withdraws the X Delivery from the signed-in command line')
def _withdraw_cli(context, who):
    _withdraw(context, who, x_row(context)["id"], None)


@when("the announce agent withdraws the X Delivery from the signed-in command line")
def _agent_withdraw_cli(context):
    _withdraw(context, "announce", x_row(context)["id"], None)


@when("the announce agent withdraws the X Delivery through the site's own X channel")
def _agent_withdraw_channel(context):
    _withdraw(context, "announce", x_row(context)["id"], _own_channel(context))


@when('the person "{who}" withdraws generation {generation:d} of the X Delivery through the site\'s own X channel')
def _withdraw_generation(context, who, generation):
    _withdraw(context, who, x_row(context, generation)["id"], _own_channel(context))


@when('the person "{who}" withdraws the email Delivery through the site\'s own X channel')
def _withdraw_email(context, who):
    _withdraw(context, who, context.email_id, _own_channel(context))


@when('the person "{who}" withdraws the manual X Delivery through the site\'s own X channel')
def _withdraw_manual(context, who):
    _withdraw(context, who, context.manual_id, _own_channel(context))


@when('the person "{who}" withdraws the dry run')
def _withdraw_dry(context, who):
    _withdraw(context, who, x_row(context)["id"], None)


def _correct(context, who, delivery, text, removers, judge=None):
    context.envelope = execute("announcements_correct", {"delivery": delivery, "text": text}, _caller(who),
                               {"announcements_correct": _handlers(context, removers, judge)["announcements_correct"]})


@when('the person "{who}" corrects the X Delivery with the words "{words}" through the site\'s own X channel')
@given('the person "{who}" corrected the X Delivery with the words "{words}" through the site\'s own X channel')
def _correct_with_channel(context, who, words):
    _correct(context, who, x_row(context)["id"], words, _own_channel(context))
    assert context.envelope["ok"], context.envelope


@when('the person "{who}" corrects the X Delivery again with the words "{words}" through the site\'s own X channel')
def _correct_again(context, who, words):
    _correct(context, who, x_row(context, 1)["id"], words, _own_channel(context))
    assert context.envelope["ok"], context.envelope


@when('the person "{who}" corrects the X Delivery with the words "{words}" from the signed-in command line')
@given('the person "{who}" corrected the X Delivery with the words "{words}" from the signed-in command line')
def _correct_cli(context, who, words):
    _correct(context, who, x_row(context)["id"], words, None)
    assert context.envelope["ok"], context.envelope


@when('the person "{who}" corrects the email Delivery with the words "{words}" through the site\'s own X channel')
def _correct_email(context, who, words):
    _correct(context, who, context.email_id, words, _own_channel(context))
    assert context.envelope["ok"], context.envelope


@when('the person "{who}" corrects the X Delivery with the words "{words}" through the site\'s own X channel and the fact check supports nothing')
def _correct_unsupported(context, who, words):
    _correct(context, who, x_row(context)["id"], words, _own_channel(context), judge=_judge("not_supported"))


# --- thens: Stories, records and reasons ---------------------------------------------------------------------------------------------------------------


@then("nothing is announced on X")
def _nothing(context):
    assert not x_rows(context), x_rows(context)


@then('the reason is "{code}"')
def _reason(context, code):
    held = context.considered.prepared.held if context.considered and context.considered.prepared else None
    assert held is not None and held.code == code, (held, context.failure)


@then("the catalog holds {announcements:d} Announcement and {deliveries:d} Delivery")
@then("the catalog holds {announcements:d} Announcement and {deliveries:d} Deliveries")
def _holds(context, announcements, deliveries):
    assert len(context.backend.rows("AnnouncementDecision")) == announcements, context.backend.rows("AnnouncementDecision")
    assert len(context.backend.rows("Delivery")) == deliveries, [row["id"] for row in context.backend.rows("Delivery")]


@then('the Delivery is on the channel "{channel}" for the account "{account}"')
def _on_channel(context, channel, account):
    row = context.backend.rows("Delivery")[0]
    assert (row["channel"], row["accountId"]) == (channel, account), row


@then("the Announcement is linked to the Story")
def _linked(context):
    assert context.announcements.stories(announcement_of(context)["id"]), "no announces link"


@then('the X Delivery reads "{words}"')
def _reads_words(context, words):
    row = x_row_fresh(context)
    assert words_of(row) == words, (words_of(row), row.get("blockedReason"), str(context.send_refusal), row.get("dueAt"), row.get("nextAttemptAt"))


@then('the dry run Delivery reads "{words}"')
def _dry_reads(context, words):
    assert words_of(x_row_fresh(context)) == words


@then('the email Delivery reads "{words}"')
def _email_reads(context, words):
    assert words_of(context.deliveries.get(context.email_id)) == words


@then('the manual X Delivery reads "{words}"')
def _manual_reads(context, words):
    assert words_of(context.deliveries.get(context.manual_id)) == words


@then('the run added the channel "{channel}" to the Announcement that existed')
def _added(context, channel):
    assert context.last is not None and context.last.added == (channel,), (context.last, context.failure)


@then("the model was asked once")
def _asked_once(context):
    assert len(context.model_calls) == 1, context.model_calls


@then("the model was asked twice")
def _asked_twice(context):
    assert len(context.model_calls) == 2, context.model_calls


@then("the model was given only the title, the dek and the summary")
def _only(context):
    assert set(json.loads(context.model_input)) == {"title", "dek", "summary"}


@then("the post in the Delivery's words carries the Article's link")
def _carries(context):
    assert context.deliveries.text(x_row_fresh(context)).count("https://machines.example/") == 1


@then("the Delivery lists the checks length, markup and facts as passed")
def _checks(context):
    checks = {check["name"]: check["passed"] for check in records.json_list(x_row_fresh(context)["checks"]) if check["name"] != "inputs"}
    assert checks == {"length": True, "markup": True, "facts": True}, checks


@then("the words are kept in S3, not on the row")
def _words_in_s3(context):
    row = x_row_fresh(context)
    assert "text" not in row and "post" not in row and row.get("textKey")
    assert context.deliveries.text(row).startswith(DEFAULT_DRAFT)


@then("the Delivery has no words yet")
def _no_words(context):
    assert not x_row_fresh(context).get("textKey")


@then('the Delivery has these words in S3 "{words}"')
def _words_are(context, words):
    assert context.deliveries.text(x_row_fresh(context)).startswith(words), context.deliveries.text(x_row_fresh(context))


def _flag_text(context):
    flag = blocked_drafts.open_flag(context.backend, announcement_of(context)["id"])
    assert flag is not None, "no open review request for the Announcement"
    return flag["reason"] + " " + str(flag.get("ask") or "")


@then('the Announcement\'s flag says "{text}"')
def _flag_says(context, text):
    assert text in _flag_text(context), _flag_text(context)


@then("exactly {count:d} review request was raised about the Announcement")
def _flags(context, count):
    rows = [row for row in context.backend.rows("ReviewRequest") if row.get("subjectId") == announcement_of(context)["id"] or announcement_of(context)["id"] in json.dumps(row)]
    assert len(rows) == count, rows


@then("the Delivery is not in the due index")
def _not_due(context):
    assert x_row_fresh(context).get("dueAt") is None


@then("the Delivery has no due time")
def _no_due(context):
    assert x_row_fresh(context).get("dueAt") is None, x_row_fresh(context)


@then("the announce agent's run failed")
def _run_failed(context):
    assert context.failure is not None


@then('the X Delivery is released at "{release}" and locks at "{lock}"')
def _window(context, release, lock):
    row = x_row_fresh(context)
    assert (row["releaseAt"], row["lockAt"]) == (release, lock), (row["releaseAt"], row["lockAt"])


@then('the Announcement is released at "{release}"')
def _announcement_release(context, release):
    assert announcement_of(context)["releaseAt"] == release, announcement_of(context)["releaseAt"]


@then('the Announcement is "{state}"')
def _announcement_state(context, state):
    assert context.announcements.get(announcement_of(context)["id"])["state"] == state


@then("the announcement settings are refused with \"{message}\"")
def _refused(context, message):
    assert context.refusal is not None and message in str(context.refusal), context.refusal


# --- thens: dry run, sending and the budget ------------------------------------------------------------------------------------------------------------


@then("the post in the Delivery's words ends with the Article's link tagged utm_source=x, utm_medium=social and utm_campaign=announcement")
def _link(context):
    text = context.deliveries.text(x_row_fresh(context))
    assert text.endswith(f"https://machines.example/{context.lineage}?utm_source=x&utm_medium=social&utm_campaign=announcement"), text


@then("the post in the Delivery's words weighs no more than {limit:d}")
def _weight(context, limit):
    assert post.weighted_length(context.deliveries.text(x_row_fresh(context))) <= limit


@then("nothing was handed to the X channel")
def _nothing_sent(context):
    assert context.x.submissions == []


@then("nothing was spent")
def _nothing_spent(context):
    assert x_row_fresh(context)["cost"] == "0" and context.ledger.spent("mom", budget.cycle_start(NOW, 1)) is None


@then("nothing was posted")
def _nothing_posted(context):
    assert all(delivery["status"] != "sent" for delivery in context.x.deliveries.values()), context.x.deliveries


@then('the deliver side refuses saying "{text}"')
def _deliver_refuses(context, text):
    assert isinstance(context.send_refusal, NotSendable) and text in str(context.send_refusal), context.send_refusal


@then("the deliver side says the Delivery is not waiting to be sent")
def _not_waiting(context):
    assert isinstance(context.send_refusal, NotReleasable) and "not waiting to be sent" in str(context.send_refusal), context.send_refusal


@then("exactly one event was handed to the X channel under the Delivery's first attempt id")
def _first_event(context):
    assert context.x.submissions == [f"delivery:{x_row(context)['id']}:a1"], context.x.submissions


@then("no event carries a round suffix")
def _no_round(context):
    assert all(event.rsplit(":", 1)[-1] in {"a1", "a2", "a3"} and ":r" not in event for event in context.x.submissions), context.x.submissions


@then('the X Delivery has no field "{field}"')
def _no_field(context, field):
    assert field not in x_row_fresh(context)


@then("the X Delivery has a post id and a cost of {cost}")
def _posted(context, cost):
    row = x_row_fresh(context)
    assert row["providerId"] and Decimal(row["cost"]) == Decimal(cost), row


@then('the Delivery\'s last attempt says "{words}" with the code "{code}"')
def _last_attempt(context, words, code):
    line = lines.delivery_line(x_row_fresh(context), NOW_ISO)["lastAttempt"]
    assert line["words"] == words and line["code"] == code, line


@then('the history of the X Delivery reads "{first}", "{second}" and "{third}", each with a time and an actor')
def _history(context, first, second, third):
    history = records.json_list(x_row_fresh(context)["history"])
    notes = [entry["note"] for entry in history]
    assert notes[0].startswith(first) and notes[1].startswith(second) and notes[-1].startswith(third), notes
    assert all(entry["at"] and entry["by"] for entry in history)


@then("they were read through the account index only")
def _index_only(context):
    assert context.backend.reads and all(index == "deliveriesByAccount" for index, _ in context.backend.reads), context.backend.reads


@then('the settings say the pause was made by "{who}" with the reason "{reason}"')
def _pause_says(context, who, reason):
    pause = context.functions.read()["pause"]
    assert pause["paused"] and pause["by"] == who and pause["detail"] == reason, pause


@then('announcements are paused with "{reason}"')
def _paused_with(context, reason):
    pause = context.functions.read()["pause"]
    assert pause["paused"] and pause["detail"] == reason and pause["by"] == "system" and pause["reason"] == "budget", pause


@then("announcements are still paused")
def _still_paused(context):
    assert context.functions.read()["pause"]["paused"]


@then("announcements are no longer paused")
def _not_paused(context):
    assert not context.functions.read()["pause"]["paused"]


@then("the editors are told the budget was reached")
def _told_budget(context):
    assert any(kind == "announcement.budget-reached" for kind, _ in context.told), context.told


@then("the editors are told the account needs reconnecting")
def _told_reconnect(context):
    assert any(kind == "announcement.account-needs-reconnecting" for kind, _ in context.told), context.told


@then("the Delivery has no attempts")
def _no_attempts(context):
    assert not records.attempt_log(x_row_fresh(context))


@then("the events handed over are the Delivery's attempt 1 and attempt 2 events")
def _events(context):
    base = f"delivery:{x_row(context)['id']}"
    assert context.x.submissions == [f"{base}:a1", f"{base}:a2"], context.x.submissions


@then('the guard refuses a ${amount} post with "{reason}"')
def _guard_refuse(context, amount, reason):
    assert context.guard.refusal(Account("CHANNELACCT#x#mom"), Price(amount)) == reason


@then("the guard allows a ${amount} post")
def _guard_allow(context, amount):
    assert context.guard.refusal(Account("CHANNELACCT#x#mom"), Price(amount)) is None


@then("the spend this cycle is ${amount}")
def _spend_is(context, amount):
    assert Decimal(context.ledger.spent("mom", budget.cycle_start(NOW, 1))) == Decimal(amount)


@then('the standing reads "{sentence}"')
def _standing(context, sentence):
    assert context.control.standing(context.control.current()).sentence() == sentence


@then('{count:d} eligible Stories in {days:d} days at ${price} a post suggests "{sentence}"')
def _suggest(context, count, days, price, sentence):
    assert budget.suggestion(count, days, {"prices": {"createPostWithUrl": price}})["sentence"] == sentence


@then('"{text}" weighs 23 for the link plus its other characters')
def _weighs(context, text):
    assert post.weighted_length(text) == 23 + len("A link  counts")


@then("a text of {count:d} Japanese characters weighs {weight:d}")
def _jp(context, count, weight):
    assert post.weighted_length("あ" * count) == weight


@then("a text of {count:d} Japanese characters is too long by {over:d}")
def _jp_long(context, count, over):
    assert post.too_long_by("あ" * count) == over


@then('the link "{url}" becomes "{tagged}"')
def _tag(context, url, tagged):
    assert post.tagged_link(url) == tagged


# --- thens: withdraw and correct ----------------------------------------------------------------------------------------------------------------------


@then("the post was deleted at X once")
def _deleted_once(context):
    assert len(context.x.withdrawals) == 1, context.x.withdrawals


@then("no post was deleted")
def _none_deleted(context):
    assert context.x.withdrawals == [], context.x.withdrawals


@then("the post was deleted at X {count:d} times")
def _deleted_times(context, count):
    assert len(context.x.withdrawals) == count, context.x.withdrawals


@then('the X Delivery\'s history says it was withdrawn by "{who}"')
def _withdrawn_by(context, who):
    history = records.json_list(x_row_fresh(context)["history"])
    assert any(entry["state"] == "withdrawn" and entry["by"] == who and f"withdrawn by {who}" in entry["note"] for entry in history), history


@then('the X Delivery\'s history does not say "{who}"')
def _not_by(context, who):
    assert all(who not in json.dumps(entry) for entry in records.json_list(x_row_fresh(context)["history"]))


@then("the X Delivery's cost is {cost}")
def _x_cost(context, cost):
    assert Decimal(x_row_fresh(context)["cost"]) == Decimal(cost), x_row_fresh(context)["cost"]


@then('the withdrawal is refused saying "{text}"')
def _withdraw_refused(context, text):
    assert context.withdraw_error is not None and text in context.withdraw_error["message"], context.envelope


@then('the withdrawal is refused as "{code}" saying "{text}"')
def _withdraw_refused_as(context, code, text):
    assert context.withdraw_error is not None and context.withdraw_error["code"] == code and text in context.withdraw_error["message"], context.envelope


@then('the withdrawal went through and the X Delivery reads "{words}"')
def _withdraw_ok(context, words):
    assert context.envelope["ok"], context.envelope
    assert words_of(x_row_fresh(context)) == words


@then('the correction is refused as "{code}" saying "{text}"')
def _correct_refused(context, code, text):
    error = context.envelope["error"] if not context.envelope["ok"] else {}
    assert error.get("code") == code and text in error.get("message", ""), context.envelope


@then("generation {generation:d} of the X Delivery is superseded by generation {newer:d}")
def _superseded(context, generation, newer):
    old, new = x_row_fresh(context, generation), x_row_fresh(context, newer)
    assert old["state"] == "superseded" and old["supersededBy"] == new["id"] and new["supersedes"] == old["id"], (old["state"], old.get("supersededBy"))


@then("generation {generation:d} of the X Delivery has the cost {cost}")
def _generation_cost(context, generation, cost):
    assert Decimal(x_row_fresh(context, generation)["cost"]) == Decimal(cost), x_row_fresh(context, generation)["cost"]


@then('generation {generation:d} of the X Delivery has these words in S3 "{words}"')
def _generation_words(context, generation, words):
    assert context.deliveries.text(x_row_fresh(context, generation)).startswith(words), context.deliveries.text(x_row_fresh(context, generation))


@then('generation {generation:d} of the X Delivery is "{words}"')
def _generation_state(context, generation, words):
    assert words_of(x_row_fresh(context, generation)) == words, words_of(x_row_fresh(context, generation))


@then("the old post was deleted before the new event was handed over")
def _order(context):
    log = context.x.log
    deleted = next(index for index, (kind, _) in enumerate(log) if kind == "withdraw")
    handed = [index for index, (kind, event) in enumerate(log) if kind == "submit" and event.endswith("#g2:a1")]
    assert handed and deleted < handed[0], log


@then("the live Delivery of the X channel is generation {generation:d}")
def _live_x(context, generation):
    live = [row for row in context.deliveries.live_for_announcement(announcement_of(context)["id"]) if row["channel"] == "x"]
    assert len(live) == 1 and int(live[0]["generation"]) == generation, live


@then("the live Delivery of the email channel is generation {generation:d}")
def _live_email(context, generation):
    live = [row for row in context.deliveries.live_for_announcement(announcement_of(context)["id"]) if row["channel"] == "email"]
    assert len(live) == 1 and int(live[0]["generation"]) == generation, live


@then("the email Delivery generation {generation:d} is superseded by generation {newer:d}")
def _email_superseded(context, generation, newer):
    rows = {int(row["generation"]): row for row in context.backend.rows("Delivery") if row["channel"] == "email"}
    assert rows[generation]["state"] == "superseded" and rows[newer]["supersedes"] == rows[generation]["id"], rows


# --- the data schema and the code, once the old row shape is gone --------------------------------------------------------------------------------------


def _schema_text():
    return (REPO_ROOT / "amplify" / "functions" / "announcements" / "schema.ts").read_text()


@then('the data schema has no model named "{name}"')
def _no_model(context, name):
    import re

    assert not re.search(rf"^\s{{2}}{name}: a\s*$", _schema_text(), flags=re.M), f"the schema still defines the model {name}"


@then('the data schema has no index named "{name}"')
def _no_index(context, name):
    assert name not in _schema_text()


@then('the data schema still has the models "{first}", "{second}", "{third}", "{fourth}" and "{fifth}"')
def _still_models(context, first, second, third, fourth, fifth):
    import re

    for name in (first, second, third, fourth, fifth):
        assert re.search(rf"^\s{{2}}{name}: a\s*$", _schema_text(), flags=re.M), f"the schema does not define {name}"


@then('the GraphQL index definitions have no index named "{name}"')
def _no_graphql_index(context, name):
    from papyrus_content.graphql_authoring import INDEX_DEFINITIONS

    assert name not in INDEX_DEFINITIONS


@then('the GraphQL models the lane can list have no model named "{name}"')
def _no_graphql_model(context, name):
    from papyrus_content.graphql_authoring import GET_DEFINITIONS, LIST_DEFINITIONS

    assert name not in LIST_DEFINITIONS and name not in GET_DEFINITIONS


@then('no attachment owner kind maps to the model "{name}"')
def _no_owner(context, name):
    from papyrus_content.model_attachments import MODEL_ATTACHMENT_OWNER_MODELS

    assert name not in MODEL_ATTACHMENT_OWNER_MODELS.values()


@then('there is no module named "{module}"')
def _no_module(context, module):
    import importlib.util

    assert importlib.util.find_spec(module) is None


# --- the command line ---------------------------------------------------------------------------------------------------------------------------------


def cli_judge(claim, cited, info=None):
    return {"verdict": "supported", "quotes": [" ".join(cited.values()).split("\n")[0]], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


def run_cli(context, line, *, agent=False, guidelines="Voice: plain and kind."):
    words = shlex.split(line)
    assert words[:2] == ["papyrus", "announcements"], line
    handlers = signed_in_handlers(lambda: context.backend, {"SITE_ORIGIN": ORIGIN, "ITEM_URL_STYLE": "clean"}, llm=lambda system, user, schema: {"text": DEFAULT_DRAFT}, judge=cli_judge,
                                  guidelines_text=guidelines, files=context.files, functions=context.functions)
    out = io.StringIO()
    status = announcements_cli.command(words[2:], handlers=handlers, environ={"PAPYRUS_ACTOR_KIND": "agent"} if agent else {}, stdout=out)
    context.cli_status, context.cli_answer = status, json.loads(out.getvalue())
    return context.cli_answer


@given("the announcement commands run against the site's backend")
def _cli_backend(context):
    pass


@given('the announcement settings are saved for the account "{account}" in Dry run at {stars:d} stars')
def _cli_settings(context, account, stars):
    mom(context, mode="dry_run", stars=stars)


@given('a published {stars:d}-star Article "{lineage}"')
def _cli_story(context, stars, lineage):
    context.lineage = lineage
    context.backend.add_story(lineage, stars=stars, summary=SUMMARY)


@when('a person types "{line}"')
def _person_runs(context, line):
    run_cli(context, line)


@when('an AI agent types "{line}"')
def _agent_runs(context, line):
    run_cli(context, line, agent=True)


@when('a person types "{line}" with no writing guidelines')
def _no_guidelines_cli(context, line):
    run_cli(context, line, guidelines="")


@when("a person saves the announcement settings in Dry run at {stars:d} stars with a budget of ${amount}")
def _save_cli(context, stars, amount):
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "prices.json"
        path.write_text(json.dumps({"prices": PRICES}))
        run_cli(context, f"papyrus announcements settings set --mode dry_run --min-stars {stars} --story-types article --budget {amount} "
                         f"--billing-cycle-day 1 --label-confirmed --input-file {path}")


@then("the announcement command succeeds")
def _cli_ok(context):
    assert context.cli_status == 0 and context.cli_answer["ok"], context.cli_answer


@then('the announcement command fails with "{code}"')
def _cli_fails(context, code):
    assert context.cli_status == 2 and context.cli_answer["error"]["code"] == code, context.cli_answer


@then('the announcement answer shows mode "{mode}" and the account "{account}"')
def _cli_mode(context, mode, account):
    result = context.cli_answer["result"]
    assert result["settings"]["mode"] == mode and result["connection"]["accountId"] == account, result


@then('the announcement answer says "{message}"')
def _cli_says(context, message):
    assert message in context.cli_answer["error"]["message"], context.cli_answer


@then('"{line}" shows mode "{mode}" and minStars {stars:d}')
def _cli_shows(context, line, mode, stars):
    answer = run_cli(context, line)
    assert answer["result"]["settings"]["mode"] == mode and answer["result"]["settings"]["rules"]["minStars"] == stars, answer


@then('"{line}" shows paused {value}')
def _cli_paused(context, line, value):
    assert run_cli(context, line)["result"]["paused"] is (value == "true")


@then("the announcement answer has the exact post with the tagged link and sent false")
def _cli_post(context):
    result = context.cli_answer["result"]
    assert result["post"].startswith(DEFAULT_DRAFT) and "utm_source=x" in result["post"] and result["sent"] is False and result["passed"], result


@then("no Announcement or Delivery is recorded")
def _cli_none(context):
    assert not context.backend.rows("AnnouncementDecision") and not context.backend.rows("Delivery")


@then('the announcement answer is not passed and says "{message}"')
def _cli_refused_preview(context, message):
    result = context.cli_answer["result"]
    assert result["passed"] is False and message in result["failures"][0], result
