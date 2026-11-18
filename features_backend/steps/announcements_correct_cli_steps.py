"""``papyrus announcements correct`` (features_backend/announcements-correct-cli.feature).

The catalog, the Story and the Deliveries are made by announcement_records_steps.py, the worker and the channel by delivery_attempts_steps.py. The command is run through
the real ``announcements.cli.command`` (flag parsing, ``--dry-run``, the JSON envelope) over the operation table's handler for ``announcements_correct``, with a fake judge
and a fixed Story. Nothing is sent and nothing leaves the process; no model is called.
"""
from __future__ import annotations

import io
import json
import shlex
import sys
from pathlib import Path

import parse
from behave import register_type, step, then

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from papyrus_content.announcements import cli, review_handlers  # noqa: E402
from papyrus_content.announcements.eligibility import StoryFacts  # noqa: E402


@parse.with_pattern(r'[^"]*')
def parse_quoted(text):
    return text


register_type(K=parse_quoted)

ORIGIN = "https://machines.example"


def judge_that(verdict):
    def judge(claim, cited, info=None):
        quote = " ".join(cited.values()).split("\n")[0] if verdict == "supported" else ""
        return {"verdict": verdict, "quotes": [quote] if quote else [], "explanation": "", "attribution_lost": False, "claim_is_only_about_source_limits": False}
    return judge


def story_titled(title):
    return StoryFacts(lineage_id="slow-water", item_id="slow-water-v3", version_number=3, story_type="article", section=None, published=True, retired=False, stars=4,
                      title=title, dek="", summary="", body="", path="/slow-water", rated_by="ellie")


@step('the fact check supports what the Story titled "{title:K}" says')
def fact_check_supports(context, title):
    context.correct_story = story_titled(title)
    context.correct_judge = judge_that("supported")


@step("the fact check supports nothing")
def fact_check_supports_nothing(context):
    context.correct_judge = judge_that("not_supported")


def run(context, command, delivery_id, text):
    words = shlex.split(command)
    assert words[:2] == ["announcements", "correct"], command
    review_handlers._publication = lambda client: "publication"   # the publication's key is read from the site's own record, which these specs do not build
    handlers = review_handlers.signed_in_handlers(client_factory=lambda: context.backend, policy_factory=lambda client: None, files=context.files, judge=context.correct_judge,
                                                  story=lambda: context.correct_story, environ={"SITE_ORIGIN": ORIGIN})
    out = io.StringIO()
    code = cli.command(["correct", delivery_id, "--text", text, *words[2:]], handlers=handlers, environ={}, stdout=out)
    context.envelope = json.loads(out.getvalue())
    context.exit_code = code


def delivery_id_of(context, channel, account, generation=None):
    rows = [row for row in context.backend.rows("Delivery") if row["channel"] == channel and row["accountId"] == account]
    assert rows, f"no Delivery for {channel} {account}"
    if generation is not None:
        rows = [row for row in rows if int(row["generation"]) == generation]
    return max(rows, key=lambda row: int(row["generation"]))["id"]


@step('the command "{command:K}" is run on the Delivery "{channel:K}" "{account:K}" with the text "{text:K}"')
def command_on_delivery(context, command, channel, account, text):
    run(context, command, delivery_id_of(context, channel, account), text)


@step('the command "{command:K}" is run on generation {generation:d} of "{channel:K}" "{account:K}" with the text "{text:K}"')
def command_on_generation(context, command, generation, channel, account, text):
    run(context, command, delivery_id_of(context, channel, account, generation), text)


@step('the command "{command:K}" is run on the Delivery "{channel:K}" "{account:K}" with a text of {count:d} letters')
def command_long_text(context, command, channel, account, count):
    run(context, command, delivery_id_of(context, channel, account), " ".join(["water"] * (count // 6)))


@step('the command "{command:K}" is run on the Delivery id "{delivery:K}" with the text "{text:K}"')
def command_on_id(context, command, delivery, text):
    run(context, command, delivery, text)


@then("the command succeeds")
def command_succeeds(context):
    assert context.envelope["ok"] and context.exit_code == 0, context.envelope


@then('the command is refused as "{code:K}" saying "{text:K}"')
def command_refused(context, code, text):
    assert not context.envelope["ok"] and context.exit_code != 0, context.envelope
    error = context.envelope["error"]
    assert error["code"] == code, error
    assert text in error["message"], (text, error["message"])


@then('the command\'s result names generation {generation:d} which supersedes generation {older:d} of "{channel:K}" "{account:K}"')
def result_names(context, generation, older, channel, account):
    result = context.envelope["result"]
    assert result["generation"] == generation and result["id"] == delivery_id_of(context, channel, account, generation), result
    assert result["supersedes"] == delivery_id_of(context, channel, account, older), result


@then('the command\'s result says the review is "{approval:K}" and the checks "{names:K}" passed')
def result_review(context, approval, names):
    result = context.envelope["result"]
    assert result["approval"] == approval, result
    assert [check["name"] for check in result["checks"] if check["passed"]] == names.split(", "), result["checks"]


@then("the command's result says it was a dry run")
def result_dry_run(context):
    assert context.envelope["result"]["dryRun"] is True, context.envelope
