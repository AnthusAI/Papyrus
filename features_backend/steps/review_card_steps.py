import json
import subprocess
from pathlib import Path

from behave import given, then, when

from papyrus_content import review_requests as rr

REPO_ROOT = Path(__file__).resolve().parents[2]


def card_request(mode, state="open", answer=None, story="story-1"):
    return {
        "id": "rr-card", "subject": {"type": "story", "id": story}, "mode": mode, "reason": "A reason", "ask": None,
        "raisedBy": "reference-intake", "raisedAt": "2026-10-22T10:00:00Z", "deadline": None, "state": state, "answer": answer,
        "links": [], "history": [], "appliedIn": None, "updatedAt": "2026-10-22T11:00:00Z",
    }


def answer_of(decision, by):
    return {"decision": decision, "feedback": None, "steer": None, "by": by, "at": "2026-10-22T11:00:00Z"}


def render_card(context, request, deleted=(), titles=None):
    payload = json.dumps({"request": request, "deletedStories": list(deleted), "storyTitles": titles or {}})
    done = subprocess.run(["npx", "tsx", str(REPO_ROOT / "scripts" / "review-card-probe.ts"), payload],
                          cwd=REPO_ROOT, capture_output=True, text=True, check=True)
    context.card = done.stdout


@when("the editor acknowledges the request")
def acknowledge(context):
    context.answered = rr.answer_review(context.client, context.request_id, decision="acknowledge", by="editor", roles=["editor"], now=context.clock.now)


@then('the stored decision is "{decision}"')
def stored_decision(context, decision):
    assert rr.get_review(context.client, context.request_id, sweep=False)["answer"]["decision"] == decision


@then('the card says "{wanted}" and not "{unwanted}"')
def card_says_not(context, wanted, unwanted):
    if getattr(context, "card", None) is None:
        render_card(context, rr.get_review(context.client, context.request_id, sweep=False))
    assert wanted in context.card and unwanted not in context.card, context.card


@then('the card says "{wanted}"')
def card_says(context, wanted):
    if getattr(context, "card", None) is None:
        render_card(context, rr.get_review(context.client, context.request_id, sweep=False))
    assert wanted in context.card, context.card


@given('a flag answered with the old decision "{decision}" by "{by}"')
def old_flag(context, decision, by):
    context.card = None
    render_card(context, card_request("flag", "answered", answer_of(decision, by)))


@given('a hard gate answered with the decision "{decision}" by "{by}"')
def hard_gate(context, decision, by):
    render_card(context, card_request("hard_gate", "answered", answer_of(decision, by)))


@then("acknowledging the request is refused because only a flag is acknowledged")
def refused(context):
    try:
        rr.answer_review(context.client, context.request_id, decision="acknowledge", by="editor", roles=["editor"], now=context.clock.now)
    except rr.ReviewError as error:
        assert "only a flag is acknowledged" in str(error)
        return
    raise AssertionError("a hard gate was acknowledged")


@given('an open flag about the story "{story}" that no longer exists')
def deleted_flag(context, story):
    render_card(context, card_request("flag", story=story), deleted=[story])


@given('an open flag about the story "{story}" titled "{title}" that still exists')
def live_flag(context, story, title):
    render_card(context, card_request("flag", story=story), titles={story: title})
