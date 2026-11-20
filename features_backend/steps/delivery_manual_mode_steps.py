"""Manual mode (features_backend/announcements/delivery-manual-mode.feature): a person posts a Delivery's words by hand and records the address.

The catalog, the Story and the Deliveries are made by announcement_records_steps.py; the worker and the channel by delivery_attempts_steps.py. The words are checked by the
real announcement checks (``drafting.check_draft``) with a judge that supports what the Story says. The record is made through the operation table
(``announcements_record_manual``), as a person's command or the console would. No network, no AWS, nothing is posted anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

import parse
from behave import register_type, step, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.announcements import blocked_drafts, review_handlers  # noqa: E402
from papyrus_content.announcements.drafting import check_draft  # noqa: E402
from papyrus_content.announcements.eligibility import StoryFacts  # noqa: E402
from papyrus_content.announcements.records import attempt_log  # noqa: E402
from papyrus_content.images.handlers import Caller, execute  # noqa: E402


@parse.with_pattern(r'[^"]*')
def parse_quoted(text):
    return text


register_type(M=parse_quoted)

LINK = "https://machines.example/slow-water"


def delivery(context, channel, account):
    rows = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account]
    assert rows, f"no Delivery for {channel} {account}"
    return context.deliveries.get(max(rows, key=lambda row: int(row["generation"]))["id"])


def supportive_judge(claim, cited, info=None):
    quote = " ".join(cited.values()).split("\n")[0]
    return {"verdict": "supported", "quotes": [quote], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


def unsupportive_judge(claim, cited, info=None):
    return {"verdict": "not_supported", "quotes": [], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}


def facts(title):
    return StoryFacts(lineage_id="slow-water", item_id="slow-water-v3", version_number=3, story_type="article", section=None, published=True, retired=False, stars=4,
                      title=title, dek="", summary="", body="", path="/slow-water", rated_by="ellie")


def check_words(context, channel, account, title, judge):
    row = delivery(context, channel, account)
    text = context.deliveries.text(row)
    checks = check_draft(text, LINK, facts(title), judge=judge)
    context.checks = checks
    failures = [message for check in checks if not check["passed"] for message in check["problems"]]
    if failures:
        blocked_drafts.block_and_flag(context.deliveries, row, problems=failures, by="announce", now=context.now)
    else:
        context.deliveries.mark_ready(row, by="announce", now=context.now)


@step('the words of the Delivery "{channel:M}" "{account:M}" are checked against the Story titled "{title:M}"')
def words_checked(context, channel, account, title):
    check_words(context, channel, account, title, supportive_judge)


@step('the words of the Delivery "{channel:M}" "{account:M}" are checked and the fact check supports nothing')
def words_checked_unsupported(context, channel, account):
    check_words(context, channel, account, "A look at secrets", unsupportive_judge)


@step('the Delivery "{channel:M}" "{account:M}" has mode "{mode:M}" and is "{state:M}"')
def mode_and_state(context, channel, account, mode, state):
    row = delivery(context, channel, account)
    assert (row["mode"], row["state"]) == (mode, state), (row["mode"], row["state"])


@step("every check on the words passed")
def every_check_passed(context):
    assert context.checks and all(check["passed"] for check in context.checks), context.checks


def handlers(context):
    review_handlers._publication = lambda client: "publication"   # the publication's key is read from the site's own record, which these specs do not build
    return review_handlers.signed_in_handlers(client_factory=lambda: context.backend, policy_factory=lambda client: None, files=context.files)


def record(context, caller, channel, account, url):
    context.envelope = execute("announcements_record_manual", {"delivery": delivery(context, channel, account)["id"], "url": url}, caller, handlers(context))
    return context.envelope


@step('the person "{who:M}" records the address "{url:M}" for the Delivery "{channel:M}" "{account:M}"')
def person_records(context, who, url, channel, account):
    record(context, Caller(kind="person", subject=who), channel, account, url)


@step('an agent tries to record the address "{url:M}" for the Delivery "{channel:M}" "{account:M}"')
def agent_records(context, url, channel, account):
    record(context, Caller(kind="agent", subject="announce"), channel, account, url)


@step("the record is accepted")
def record_accepted(context):
    assert context.envelope["ok"], context.envelope


@step('the record is refused saying "{text:M}"')
def record_refused(context, text):
    assert not context.envelope["ok"], context.envelope
    message = context.envelope["error"]["message"]
    assert text in message, (text, message)


@step('the record is refused as "{code:M}"')
def record_refused_as(context, code):
    assert not context.envelope["ok"] and context.envelope["error"]["code"] == code, context.envelope


@step('the Delivery "{channel:M}" "{account:M}" is sent with the address "{url:M}"')
def sent_with_address(context, channel, account, url):
    row = delivery(context, channel, account)
    assert row["state"] == "sent" and row["resultUrl"] == url, (row["state"], row.get("resultUrl"))


@step('the Delivery "{channel:M}" "{account:M}" is not sent and has no address')
def not_sent(context, channel, account):
    row = delivery(context, channel, account)
    assert row["state"] != "sent" and not row.get("resultUrl"), (row["state"], row.get("resultUrl"))
    assert not attempt_log(row)


@step('the attempt log of the Delivery "{channel:M}" "{account:M}" names "{who:M}"')
def attempt_names(context, channel, account, who):
    log = attempt_log(delivery(context, channel, account))
    assert len(log) == 1 and log[0]["by"] == who and log[0]["outcome"] == "sent" and log[0]["number"] == 1, log
    assert "eventId" not in log[0], log


@step('the attempt log of the Delivery "{channel:M}" "{account:M}" has {count:d} entry')
def attempt_count(context, channel, account, count):
    assert len(attempt_log(delivery(context, channel, account))) == count
