from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.notifications import handler as notifications_handler  # noqa: E402
from papyrus_content.notifications.notifications_test import Site  # noqa: E402

READER = "reader@example.test"


def _site(context) -> Site:
    return context.site


def _stories_to(site: Site, address: str) -> list[dict]:
    return [call for call in site.mailer.calls if call["to"] == address and "Confirm" not in call["subject"]]


def _confirm(context, address: str, lists: list[str]) -> None:
    context.manage = getattr(context, "manage", {})
    context.manage[address] = _site(context).join(address, lists)
    _site(context).mailer.calls.clear()


@given('a site "{site_id}" with the lists "stories" (every story) and "security" (the security section)')
def site(context, site_id: str) -> None:
    context.site = Site(site_id, readers=0)


@given('the site lives under the base path "{base}"')
def base_path(context, base: str) -> None:
    context.site = Site("alpha", readers=0, base_path=base)


@when('"{address}" subscribes to "{list_id}" on the site')
def subscribes(context, address: str, list_id: str) -> None:
    context.answer = _site(context).subscribe(address, [list_id])


@when('"{address}" subscribes to "{list_id}" with the wording "{wording}"')
def subscribes_wording(context, address: str, list_id: str, wording: str) -> None:
    context.answer = _site(context).subscribe(address, [list_id], consent=wording)


@given('"{address}" subscribed to "{list_id}" and did not confirm')
def pending(context, address: str, list_id: str) -> None:
    _site(context).subscribe(address, [list_id])
    _site(context).mailer.calls.clear()


@given('"{address}" confirmed "{first}" and "{second}"')
def confirmed_two(context, address: str, first: str, second: str) -> None:
    _confirm(context, address, [first, second])


@given('"{address}" confirmed "{list_id}"')
def confirmed(context, address: str, list_id: str) -> None:
    _confirm(context, address, [list_id])


@when('the story "{title}" is published in the "{section}" section and sent')
def published_and_sent(context, title: str, section: str) -> None:
    site = _site(context)
    context.mark = len(site.mailer.calls)
    site.publish(title, section)
    site.play_queue()
    context.new_mail = site.mailer.calls[context.mark :]


@given('the story "{title}" was published and sent')
def was_published(context, title: str) -> None:
    published_and_sent(context, title, "news")
    context.message = context.new_mail[-1]


@when("the mail provider posts the one-click unsubscribe from that message")
def one_click(context) -> None:
    url = context.message["headers"]["List-Unsubscribe"].strip("<>")
    query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
    context.answer = _site(context).act("unsubscribe", token=query["t"], list=query.get("l"))
    assert context.answer["body"]["status"] == "unsubscribed", context.answer


@when('the reader turns "{list_id}" off on the preferences page')
def turn_off(context, list_id: str) -> None:
    site = _site(context)
    state = site.act("preferences_state", token=context.manage[READER])["body"]
    keep = [entry["id"] for entry in state["lists"] if entry["subscribed"] and entry["id"] != list_id]
    assert site.act("update_preferences", token=context.manage[READER], lists=keep)["body"]["status"] == "saved"


@when('the reader turns "{list_id}" on again on the preferences page')
def turn_on(context, list_id: str) -> None:
    assert _site(context).act("update_preferences", token=context.manage[READER], lists=[list_id])["body"]["status"] == "saved"


@when("SES reports a permanent bounce for that message")
def bounce(context) -> None:
    site = _site(context)
    event = site.ses_event("Bounce", "fake-message-1", bounce={"bounceType": "Permanent"})
    assert notifications_handler.ses_events_with(site.runtime, event) == "bounced"


@when("the reader deletes their data on the preferences page")
def delete(context) -> None:
    context.answer = _site(context).act("delete_subscriber", token=context.manage[READER])


@when("one network submits {count:d} signups for different addresses")
def flood(context, count: int) -> None:
    site = _site(context)
    context.replies = [site.subscribe(f"flood{n}@example.test", ["stories"], ip="198.18.0.%d" % n) for n in range(count)]


@then('the function answers {code:d} "{status}"')
def answers(context, code: int, status: str) -> None:
    assert context.answer["statusCode"] == code and context.answer["body"]["status"] == status, context.answer


@then('one confirmation in the site\'s design is mailed to "{address}"')
def one_confirmation(context, address: str) -> None:
    (mail,) = _site(context).mailer.calls
    assert mail["to"] == address and mail["subject"] == "Confirm your subscription to Alpha News"
    assert "#aa3300" in mail["html"] and "Confirm subscription" in mail["html"]


@then("its button goes to the site's confirm page with a token and no address")
def button(context) -> None:
    link = _site(context).confirm_link(READER)
    assert link.startswith("https://alpha.example.test/notifications/confirm/?token=v1.") and READER not in link


@then('the confirmation\'s button goes to "{prefix}"')
def button_prefix(context, prefix: str) -> None:
    assert _site(context).confirm_link(READER).startswith(prefix + "?token=")


@then('nothing is mailed to "{address}"')
def nothing(context, address: str) -> None:
    assert not [call for call in _site(context).mailer.calls if call["to"] == address]


@then('no story reaches "{address}"')
@then('no story reaches "{address}" after the unsubscribe')
@then('no story reaches "{address}" after the change')
def no_story(context, address: str) -> None:
    assert not [call for call in context.new_mail if call["to"] == address]


@then('the story reaches "{first}" and "{second}" once each')
def reaches_both(context, first: str, second: str) -> None:
    assert sorted(call["to"] for call in context.new_mail) == sorted([first, second])


@then('the story reaches only "{address}"')
def reaches_only(context, address: str) -> None:
    assert [call["to"] for call in context.new_mail] == [address]


@then("the message carries List-Unsubscribe to the site's one-click endpoint and List-Unsubscribe-Post")
def headers(context) -> None:
    mail = context.new_mail[-1]
    assert mail["headers"]["List-Unsubscribe"].startswith("<https://alpha.example.test/api/notifications/unsubscribe?t=v1.")
    assert mail["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert READER not in json.dumps(mail["headers"])


@then("its footer links to the site's preferences and unsubscribe pages")
def footer_links(context) -> None:
    text = context.new_mail[-1]["text"]
    assert re.search(r"https://alpha\.example\.test/notifications/preferences/\?token=v1\.", text)
    assert re.search(r"https://alpha\.example\.test/notifications/unsubscribe/\?token=v1\.[^\s]+list=stories", text)


@then("its footer shows the site's postal address")
def postal(context) -> None:
    assert "1 Example Way" in context.new_mail[-1]["text"]


@then('"{address}" is suppressed')
def suppressed(context, address: str) -> None:
    audience = _site(context).runtime.audience
    assert audience.suppression(audience._keys.recipient(address)) == "bounce"


@then('"{address}" is no longer suppressed')
def not_suppressed(context, address: str) -> None:
    audience = _site(context).runtime.audience
    assert audience.suppression(audience._keys.recipient(address)) is None


@then('the site asked SES to clear "{address}" from the account suppression list')
def cleared(context, address: str) -> None:
    assert _site(context).unsuppressed == [address]


@then('no row of the site\'s table holds "{address}"')
def no_row(context, address: str) -> None:
    assert address not in json.dumps(list(_site(context).store.items.values()))


@then('the later ones are answered {code:d} "{status}" and mailed nothing')
def later_limited(context, code: int, status: str) -> None:
    codes = [reply["statusCode"] for reply in context.replies]
    assert codes[0] == 202 and code in codes, codes
    first = codes.index(code)
    assert all(c == code for c in codes[first:])
    assert all(reply["body"]["status"] == status for reply in context.replies[first:])
    limited = {f"flood{n}@example.test" for n in range(first, len(codes))}
    assert not [call for call in _site(context).mailer.calls if call["to"] in limited]
