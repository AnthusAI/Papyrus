"""Announcements (features_backend/announcements-*.feature). A fake backend, a fake document store and a fake Caducus x channel: no network, no AWS, no real post."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.announcements import budget, operations, post  # noqa: E402
from papyrus_content.announcements.channel import ChannelNotAvailable  # noqa: E402
from papyrus_content.announcements.engine import Services, process_story, standing  # noqa: E402
from papyrus_content.announcements.fakes import FakeBackend, FakeFunctions, FakeX, MemoryFiles  # noqa: E402
from papyrus_content.announcements.guard import SpendGuard  # noqa: E402
from papyrus_content.announcements.x_account import AnnouncementError  # noqa: E402
from papyrus_content.announcements.store import AnnouncementStore, announcement_id  # noqa: E402

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
PRICES = {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}
SUMMARY = "Whether a system can keep a secret from itself."
DEFAULT_DRAFT = "A look at whether a system can keep a secret from itself."


class Account:
    def __init__(self, key):
        self.key = key


class Price:
    def __init__(self, amount):
        self.amount = amount


def setup(context):
    context.backend = FakeBackend()
    context.files = MemoryFiles(context.backend)
    context.store = AnnouncementStore(context.backend, context.files)
    context.x = FakeX()
    context.told = []
    context.model_calls = []
    context.model_input = None
    context.draft_text = DEFAULT_DRAFT
    context.unsupported = []
    context.rule_problems = []
    context.guidelines = "Voice: plain and kind."
    context.functions = FakeFunctions(lambda: NOW.timestamp())
    context.wired = True
    context.failure = None
    context.last = None
    context.lineage = None
    context.counter = 0
    context.refusal = None
    context.shown = None


def services(context):
    def llm(system, user, schema):
        context.model_calls.append(user)
        context.model_input = user
        return {"text": context.draft_text}

    def judge(claim, cited, info=None):
        source = " ".join(cited.values())
        bad = any(phrase.lower() in claim.lower() for phrase in context.unsupported)
        return {"verdict": "not_supported" if bad else "supported", "quotes": [] if bad else [source.split("\n")[0]], "explanation": "",
                "attribution_lost": False, "claim_is_only_about_source_limits": False}

    return Services(
        client=context.backend, store=context.store, site_origin="https://machines.example", item_url_style="clean",
        guidelines_for=lambda story: context.guidelines, llm=llm, judge=judge, rule_lane=(lambda text: context.rule_problems) if context.rule_problems else None,
        broadcaster=context.x if context.wired else None, settings=context.functions, connection=context.functions.status,
        notify=lambda kind, facts: context.told.append((kind, dict(facts))), now=lambda: NOW, model="gpt-6-luna",
    )


def save(context, **changes):
    operations.update_settings(services(context), changes, by="ryan")


def mom(context, *, mode, stars=5, sections=None, budget_amount="10.00"):
    changes = {"mode": mode, "minStars": stars, "storyTypes": ["article"], "budget": budget_amount, "billingCycleDay": 1, "prices": PRICES, "labelConfirmed": True}
    if sections:
        changes["sections"] = list(sections)
    save(context, **changes)


def story(context, *, stars=5, published=True, story_type="article", section=None):
    context.counter += 1
    context.lineage = f"story-{context.counter}"
    context.backend.add_story(context.lineage, stars=stars, published=published, story_type=story_type, section=section, summary=SUMMARY)


def announce(context, trigger="first_publish"):
    context.failure = None
    try:
        context.last = process_story(services(context), context.lineage, trigger=trigger)
    except ChannelNotAvailable as error:
        context.failure = error
        context.last = None


def row_of(context):
    return context.store.get("mom", context.lineage)


def label(context):
    return operations.label_of(row_of(context))


def guard(context):
    return SpendGuard(context.store, context.functions, lambda: NOW)


ACCOUNT = Account("CHANNELACCT#x#mom")


# --- givens -----------------------------------------------------------------------------------------------------------------------------------------

@given("a site whose quality floor is {floor:d} stars")
def _floor(context, floor):
    setup(context)
    

@given('an X account "{account}" is connected to the site')
def _account(context, account):
    context.account = account


@given("the site never turned announcements on")
def _never(context):
    pass


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


@given("the site has no X channel wired")
def _unwired(context):
    context.wired = False


@given('X will refuse posts with "{message}"')
def _refuse(context, message):
    context.x.fail_with = message


@given("the account needs reconnecting")
def _reconnect(context):
    context.functions.connected = {"connection": "needs_reconnecting", "accountId": "mom", "handle": "@mom_test"}


@given('the model drafts "{text}"')
def _drafts(context, text):
    context.draft_text = text
    context.unsupported = ["first proof ever"]


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
    guard(context).charged(ACCOUNT, Price(amount))


@given("${amount} is already spent in the last cycle")
def _spent_before(context, amount):
    context.store.add_spend("mom", budget.cycle_start(datetime(2026, 10, 20, tzinfo=timezone.utc), 1), Decimal(amount))


@given("a {stars:d}-star Article is published")
def _publish_given(context, stars):
    story(context, stars=stars)
    announce(context)


@given("a published {stars:d}-star Article")
def _published(context, stars):
    story(context, stars=stars)
    announce(context)


@given("a retired {stars:d}-star Article")
def _retired(context, stars):
    story(context, stars=stars)
    context.backend.retire(context.lineage)


@given("an announced Article")
def _announced(context):
    story(context)
    announce(context)


# --- whens ------------------------------------------------------------------------------------------------------------------------------------------

@when("a {stars:d}-star Article is published")
def _publish(context, stars):
    story(context, stars=stars)
    announce(context)


@when('a {stars:d}-star Article "{title}" is published')
def _publish_titled(context, stars, title):
    story(context, stars=stars)
    announce(context)


@when("an unrated Article is published")
def _unrated(context):
    story(context, stars=None)
    announce(context)


@when("a {stars:d}-star Post is published")
def _post(context, stars):
    story(context, stars=stars, story_type="post")
    announce(context)


@when('a {stars:d}-star Article in the "{section}" section is published')
def _in_section(context, stars, section):
    story(context, stars=stars, section=section)
    announce(context)


@when("a {stars:d}-star Article is saved as a draft")
def _draft(context, stars):
    story(context, stars=stars, published=False)
    announce(context)


@when("an editor rates the Article {stars:d} stars")
def _rate(context, stars):
    context.backend.rate(context.lineage, stars)
    announce(context, "rated")


@when("the Article is announced again because a corrected version was published")
def _again(context):
    announce(context)


@when("the Article is announced")
def _announce(context):
    announce(context)


def _try_save(context, **changes):
    try:
        save(context, **changes)
        context.refusal = None
    except AnnouncementError as error:
        context.refusal = error


@when("the owner sets the announcement minimum to {stars:d} stars")
def _low(context, stars):
    _try_save(context, minStars=stars)


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


@when("Caducus posts it for ${amount}")
def _caducus_posts(context, amount):
    context.x.post_price = amount
    for event in list(context.x.events):
        context.x.deliver(event)


@when('Caducus\'s guard refuses it with "{reason}"')
def _guard_refuses(context, reason):
    for event in list(context.x.events):
        context.x.deliver(event, refusal=reason)


@when("the announcement is refreshed")
def _refresh(context):
    context.shown = operations.show(services(context), announcement_id("mom", context.lineage))


@when("Caducus reports a ${amount} charge on the account")
def _charge(context, amount):
    guard(context).charged(ACCOUNT, Price(amount))


@when("the account's announcements are listed")
def _list(context):
    context.backend.reads.clear()
    context.listed = operations.listing(services(context))


# --- thens ------------------------------------------------------------------------------------------------------------------------------------------

@then("nothing is announced")
def _nothing(context):
    assert context.last and context.last["status"] == "ignored", context.last
    assert row_of(context) is None


@then("no announcement is listed")
def _none_listed(context):
    assert operations.listing(services(context)) == []


@then('the announcement settings are refused with "{message}"')
def _refused(context, message):
    assert context.refusal is not None and message in str(context.refusal), context.refusal


@then('the Article is recorded as "{text}"')
def _recorded(context, text):
    assert label(context) == text, (label(context), context.last)


@then('the Article is "{text}"')
def _article_is(context, text):
    assert label(context) == text, (label(context), context.last)


@then('the announcement is "{text}"')
def _announcement_is(context, text):
    assert label(context) == text, (label(context), context.last)


@then("there is still exactly one announcement for it")
def _one(context):
    rows = [r for r in context.backend.records.get("Announcement", {}).values() if r["storyLineageId"] == context.lineage]
    assert len(rows) == 1, rows


@then("the recorded post ends with the Article's link tagged utm_source=x, utm_medium=social and utm_campaign=announcement")
def _link(context):
    document = context.store.document(announcement_id("mom", context.lineage))
    assert document["post"].endswith(f"https://machines.example/{context.lineage}?utm_source=x&utm_medium=social&utm_campaign=announcement"), document["post"]


@then("the recorded post carries the Article's link")
def _carries(context):
    assert context.store.document(announcement_id("mom", context.lineage))["post"].count("https://machines.example/") == 1


@then("the recorded post weighs no more than {limit:d}")
def _weight(context, limit):
    assert post.weighted_length(context.store.document(announcement_id("mom", context.lineage))["post"]) <= limit


@then("nothing was handed to the X channel")
def _nothing_sent(context):
    assert context.x.submissions == []


@then("nothing was spent")
def _nothing_spent(context):
    assert row_of(context)["cost"] == "0" and context.store.spent("mom", budget.cycle_start(NOW, 1)) is None


@then("the announcement lists the checks length, markup and facts as passed")
def _checks(context):
    checks = {c["name"]: c["passed"] for c in row_of(context)["checks"]}
    assert checks == {"length": True, "markup": True, "facts": True}, checks


@then("the post text is kept in the document store, not on the row")
def _text_in_s3(context):
    row = row_of(context)
    assert "text" not in row and "post" not in row
    assert context.files.get(row["id"])["text"] == DEFAULT_DRAFT


@then("exactly one event \"story.announce:mom:\" followed by the Article's lineage was handed to the X channel")
def _event(context):
    assert context.x.submissions == [f"story.announce:mom:{context.lineage}"], context.x.submissions


@then("exactly one event was handed to the X channel")
def _one_event(context):
    assert context.x.submissions == [f"story.announce:mom:{context.lineage}"], context.x.submissions


@then("the announcement was posted with a post id and a cost of {cost}")
def _posted(context, cost):
    row = row_of(context)
    assert row["state"] == "posted" and row["postId"] and Decimal(row["cost"]) == Decimal(cost), row


@then('the announcement failed with the message "{message}"')
def _failed(context, message):
    row = row_of(context)
    assert row["state"] == "failed" and row["error"] == message, row


@then("the announcement fails clearly because the X channel is not deployed")
def _unwired_failed(context):
    assert isinstance(context.failure, ChannelNotAvailable), context.failure
    assert row_of(context) is None


@then('the settings say the pause was made by "{who}" with the reason "{reason}"')
def _pause_says(context, who, reason):
    pause = context.functions.read()["pause"]
    assert pause["paused"] and pause["by"] == who and pause["detail"] == reason, pause


@then('announcements are paused with "{reason}"')
def _paused_with(context, reason):
    pause = context.functions.read()["pause"]
    assert pause["paused"] and pause["detail"] == reason and pause["by"] == "system" and pause["reason"] == "budget", pause


@then("announcements are paused")
def _is_paused(context):
    assert context.functions.read()["pause"]["paused"]


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


@then("the editors are told a check failed")
def _told_check(context):
    assert any(kind == "announcement.check-failed" for kind, _ in context.told), context.told


@then('the editors see "{message}"')
def _editors_see(context, message):
    assert any(message in failure for kind, facts in context.told if kind == "announcement.check-failed" for failure in facts["failures"]), context.told
    assert message in row_of(context)["error"]


@then('the editors see a message starting "{start}"')
def _editors_start(context, start):
    assert any(failure.startswith(start) for kind, facts in context.told if kind == "announcement.check-failed" for failure in facts["failures"]), context.told


@then('the guard refuses a ${amount} post with "{reason}"')
def _guard_refuse(context, amount, reason):
    assert guard(context).refusal(ACCOUNT, Price(amount)) == reason


@then("the guard allows a ${amount} post")
def _guard_allow(context, amount):
    assert guard(context).refusal(ACCOUNT, Price(amount)) is None


@then("the spend this cycle is ${amount}")
def _spend_is(context, amount):
    assert Decimal(context.store.spent("mom", budget.cycle_start(NOW, 1))) == Decimal(amount)


@then('the standing reads "{sentence}"')
def _standing(context, sentence):
    assert standing(services(context), operations.current(services(context))).sentence() == sentence


@then('{count:d} eligible Stories in {days:d} days at ${price} a post suggests "{sentence}"')
def _suggest(context, count, days, price, sentence):
    assert budget.suggestion(count, days, {"prices": {"createPostWithUrl": price}})["sentence"] == sentence


@then("the model was given only the title, the dek and the summary")
def _only(context):
    assert set(json.loads(context.model_input)) == {"title", "dek", "summary"}


@then("the model was asked once")
def _asked_once(context):
    assert len(context.model_calls) == 1, context.model_calls


@then("no approval step exists anywhere in the settings")
def _no_approval(context):
    assert "approv" not in str(context.functions.read()).lower()


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


@then('looking the Story up shows account "mom", the post id, the time and the cost {cost}')
def _lookup(context, cost):
    row = context.store.get("mom", context.lineage)
    assert row["accountId"] == "mom" and row["postId"] and row["postedAt"] and Decimal(row["cost"]) == Decimal(cost), row


@then('the history reads "Handed to the X channel" and then "Posted", each with a time and an actor')
def _history(context):
    history = row_of(context)["history"]
    assert [h["note"] for h in history] == ["Handed to the X channel", "Posted"], history
    assert all(h["at"] and h["by"] for h in history)


@then('the announcement keeps the message "{message}" and {count:d} attempt in its history')
def _failure_kept(context, message, count):
    row = row_of(context)
    assert row["error"] == message and row["attempts"] == count and any(message in h["note"] for h in row["history"]), row


@then("they were read through the account index only")
def _index_only(context):
    assert context.backend.reads and all(index == "announcementsByAccountAndCreatedAt" for index, _ in context.backend.reads), context.backend.reads


@then('the events handed over are the Article\'s event and its "r2" event')
def _events(context):
    assert context.x.submissions == [f"story.announce:mom:{context.lineage}", f"story.announce:mom:{context.lineage}:r2"], context.x.submissions


# --- the command line -------------------------------------------------------------------------------------------------------------------------------

import io  # noqa: E402
import shlex  # noqa: E402

from papyrus_content.announcements import cli as announcements_cli  # noqa: E402
from papyrus_content.announcements.handlers import signed_in_handlers  # noqa: E402


def cli_judge(claim, cited, info=None):
    return {"verdict": "supported", "quotes": [" ".join(cited.values()).split("\n")[0]], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


def run_cli(context, line, *, agent=False, guidelines="Voice: plain and kind."):
    words = shlex.split(line)
    assert words[:2] == ["papyrus", "announcements"], line
    handlers = signed_in_handlers(lambda: context.backend, {"SITE_ORIGIN": "https://machines.example", "ITEM_URL_STYLE": "clean"},
                                  llm=lambda system, user, schema: {"text": DEFAULT_DRAFT}, judge=cli_judge, guidelines_text=guidelines, files=context.files, functions=context.functions)
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


@given('a published {stars:d}-star Article "{lineage}" that was announced')
def _cli_announced(context, stars, lineage):
    _cli_story(context, stars, lineage)
    announce(context)


@when('a person types "{line}"')
def _person_runs(context, line):
    run_cli(context, line)


@when('an agent types "{line}"')
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


@then("no announcement row is recorded")
def _cli_none(context):
    assert not context.backend.records.get("Announcement")


@then('the announcement answer is not passed and says "{message}"')
def _cli_refused_preview(context, message):
    result = context.cli_answer["result"]
    assert result["passed"] is False and message in result["failures"][0], result


@then('the announcement list has one announcement labelled "{text}"')
def _cli_list(context, text):
    rows = context.cli_answer["result"]["announcements"]
    assert len(rows) == 1 and rows[0]["label"] == text, rows


@then("the announcement answer has the announcement and its stored post text")
def _cli_show(context):
    result = context.cli_answer["result"]
    assert result["announcement"]["storyLineageId"] == "story-1" and result["document"]["text"] == DEFAULT_DRAFT, result
