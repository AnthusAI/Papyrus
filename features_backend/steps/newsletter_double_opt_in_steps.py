from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter import addresses  # noqa: E402
from papyrus_content.newsletter.newsletter_test import ORIGIN, running_harness  # noqa: E402
from papyrus_content.newsletter.rate import IP_LIMIT  # noqa: E402

FLOOD_ADDRESS = "192.0.2.50"


def after_scenario_cleanup(context) -> None:
    manager = getattr(context, "harness_manager", None)
    if manager is not None:
        manager.__exit__(None, None, None)
        context.harness_manager = None


@given('a site whose newsletter plugin offers the lists "weekly", "alerts-a" and "alerts-b"')
def site_with_lists(context) -> None:
    context.harness_manager = running_harness()
    context.harness = context.harness_manager.__enter__()
    context.add_cleanup(after_scenario_cleanup, context)
    context.tokens = []
    context.answer = None


def ask(context, lists: str, email: str, **changes) -> None:
    context.answer = context.harness.subscribe(email, lists=lists, **changes)["body"]["status"]


def emailed_tokens(context) -> list[str]:
    import re

    found = []
    for message in context.harness.ses.sent:
        text = message["Content"]["Simple"]["Body"]["Text"]["Data"]
        found.append(re.search(r"/newsletter/confirm/\?token=([A-Za-z0-9_.-]+)", text).group(1))
    return found


@given('"{email}" has asked for "{lists}"')
def has_asked(context, email: str, lists: str) -> None:
    ask(context, lists, email)


@given('"{email}" has asked for "{lists}" and confirmed')
def has_confirmed(context, email: str, lists: str) -> None:
    ask(context, lists, email)
    context.harness.confirm()


@given('an address in the state "{state}"')
def address_in_state(context, state: str) -> None:
    harness = context.harness
    context.address = "visitor@example.com"
    context.ip = "198.51.100.7"
    if state == "pending":
        ask(context, "weekly", context.address)
        harness.now += 4000
    elif state == "confirmed":
        ask(context, "weekly", context.address)
        harness.confirm()
        harness.now += 4000
    elif state == "suppressed":
        harness.store.client.put_item(
            TableName="newsletter",
            Item={"pk": {"S": f"SUPP#{harness.hid(context.address)}"}, "sk": {"S": "SUPP"}, "reason": {"S": "bounce"}},
        )
    elif state == "rate limited":
        context.ip = FLOOD_ADDRESS
        for number in range(IP_LIMIT):
            harness.subscribe(f"flood{number}@example.com", ip=FLOOD_ADDRESS)
    elif state == "mail unavailable":
        harness.ses.fail = True
    context.sent_before = len(harness.ses.sent)


@when('a visitor asks for "{lists}" with that address')
def ask_with_state_address(context, lists: str) -> None:
    ask(context, lists, context.address, ip=context.ip)


@when('a visitor asks for "{lists}" with "{email}"')
def ask_plainly(context, lists: str, email: str) -> None:
    ask(context, lists, email)


@when('a visitor asks for "{lists}" with "{email}" with the hidden field filled')
def ask_with_honeypot(context, lists: str, email: str) -> None:
    ask(context, lists, email, honeypot="http://spam.example")


@when('a visitor asks for "{lists}" with "{email}" one second after rendering')
def ask_too_fast(context, lists: str, email: str) -> None:
    ask(context, lists, email, renderedAt=int((context.harness.now - 1) * 1000))


@when('a visitor asks for "{lists}" with "{email}" a day and an hour after rendering')
def ask_too_slow(context, lists: str, email: str) -> None:
    ask(context, lists, email, renderedAt=int((context.harness.now - 25 * 3600) * 1000))


@when('a visitor asks for "{lists}" with "{email}" normally')
def ask_normally(context, lists: str, email: str) -> None:
    ask(context, lists, email)


@when("{hours:d} hours pass")
def hours_pass(context, hours: int) -> None:
    context.harness.now += hours * 3600


@when("the visitor confirms with the emailed link")
def confirm_latest(context) -> None:
    context.answer = context.harness.confirm()["body"]["status"]


@when("the visitor confirms with the first emailed link")
def confirm_first(context) -> None:
    context.answer = context.harness.confirm(emailed_tokens(context)[0])["body"]["status"]


@when("the confirmation page is shown for the emailed link")
def show_page(context) -> None:
    context.answer = context.harness.service.dispatch(
        {"action": "confirm_page_state", "token": context.harness.last_token()}
    )["body"]["status"]


@then('the answer is "{status}"')
def answer_is(context, status: str) -> None:
    assert context.answer == status, context.answer


@then("{count:d} confirmation email is sent naming \"{name}\"")
@then("{count:d} confirmation emails are sent naming \"{name}\"")
def emails_naming(context, count: int, name: str) -> None:
    assert len(context.harness.ses.sent) == count, len(context.harness.ses.sent)
    assert name in context.harness.ses.sent[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]


@then("{count:d} confirmation emails have been sent")
def emails_sent(context, count: int) -> None:
    assert len(context.harness.ses.sent) == count, len(context.harness.ses.sent)


@then("no confirmation email is sent")
def no_email(context) -> None:
    assert len(context.harness.ses.sent) == getattr(context, "sent_before", 0), len(context.harness.ses.sent)


@then("nothing is stored")
def nothing_stored(context) -> None:
    assert context.harness.items() == []


@then('the newest confirmation email names "{named}" but not "{unnamed}"')
def newest_names(context, named: str, unnamed: str) -> None:
    text = context.harness.ses.sent[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert named in text and unnamed not in text


@then('"{email}" is "{status}" and is not a member of "{list_id}"')
def is_status_not_member(context, email: str, status: str, list_id: str) -> None:
    assert context.harness.profile(email)["status"] == status
    assert context.harness.store.memberships(context.harness.hid(email))[list_id].get("gsiList") is None


@then('"{email}" is "{status}" and is a member of "{list_id}"')
def is_status_member(context, email: str, status: str, list_id: str) -> None:
    assert context.harness.profile(email)["status"] == status
    row = context.harness.store.memberships(context.harness.hid(email))[list_id]
    assert row["status"] == "subscribed" and row["gsiList"] == list_id


@then("the consent evidence records the wording, the page and both addresses")
def consent_evidence(context) -> None:
    consent = context.harness.profile("reader@example.com")["consent"]
    assert consent["wording"] and consent["pageUrl"].startswith(ORIGIN)
    assert consent["requestIpHash"] and consent["confirmIp"] and consent["confirmedAt"] and consent["requestedAt"]
    assert "198.51.100.7" not in consent.values()


@when("a mail scanner sends HEAD to the legacy {route} link")
def scanner_head(context, route: str) -> None:
    import json
    import subprocess

    token = context.harness.last_token()
    done = subprocess.run(
        ["npx", "tsx", str(REPO_ROOT / "scripts" / "newsletter-head-probe.ts"), route, token],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    )
    context.head = json.loads(done.stdout.strip().splitlines()[-1])


@then('the link answers 302 to the clean "{page}" page with no body')
def head_redirects(context, page: str) -> None:
    assert context.head["status"] == 302, context.head
    assert context.head["path"] == page, context.head
    assert context.head["body"] == "", context.head
    assert context.head["calls"] == 0, context.head
