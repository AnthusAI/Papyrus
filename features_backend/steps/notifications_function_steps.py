from __future__ import annotations

import sys
from pathlib import Path

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.notifications import handler as notifications_handler  # noqa: E402
from papyrus_content.notifications.notifications_test import Site  # noqa: E402


@given('a site "{site_id}" with the notifications plugin and one confirmed subscriber')
def site_with_plugin(context, site_id: str) -> None:
    context.sites = getattr(context, "sites", {})
    context.sites[site_id] = Site(site_id)
    context.site = context.sites["alpha"]


@given('a second site "{site_id}" with the notifications plugin and one confirmed subscriber')
def second_site(context, site_id: str) -> None:
    context.sites[site_id] = Site(site_id)


@given('the site\'s list only covers the "{section}" section')
def list_covers(context, section: str) -> None:
    context.sites["alpha"] = context.site = Site("alpha", rule={"sections": [section]})


@given('the story "{title}" is published in the "{section}" section')
@when('the story "{title}" is published in the "{section}" section')
def story_published(context, title: str, section: str) -> None:
    context.lineage = context.site.add_story(title, section)
    context.answer = context.site.announce(context.lineage)


@when('the story "{title}" is published in the "{section}" section of "{site_id}"')
def story_published_on(context, title: str, section: str, site_id: str) -> None:
    context.answer = context.sites[site_id].publish(title, section)


@when("the same story announcement arrives again")
def delivered_again(context) -> None:
    context.answer = context.site.announce(context.lineage)


@when("the email queue is played through the sender")
def play(context) -> None:
    context.site.play_queue()


@when("an announcement arrives for a story that is no longer published")
def unpublished(context) -> None:
    context.answer = context.site.announce(context.site.add_story("Gone", "news", status="unpublished"))


@when("an announcement arrives with an event id that is not a story event id")
def bad_event_id(context) -> None:
    lineage = context.site.add_story("Rates held steady", "news")
    context.answer = notifications_handler.route(context.site.runtime, {**Site.announcement(lineage), "eventId": "alarm.fired:1"})


@when('a reader\'s "{action}" request reaches the function')
def reader_request(context, action: str) -> None:
    context.answer = notifications_handler.route(
        context.site.runtime, {"action": action, "email": "reader@example.test", "lists": ["stories"], "token": "not-a-token"}
    )


@then("{count:d} email is sent to the subscriber")
@then("{count:d} emails are sent to the subscriber")
def emails_sent(context, count: int) -> None:
    calls = context.site.mailer.calls
    assert len(calls) == count, calls
    assert all(call["to"] == context.site.addresses[0] for call in calls)


@then('the email subject is "{subject}"')
def subject(context, subject: str) -> None:
    assert context.site.mailer.calls[0]["subject"] == subject


@then('the email links to "{url}"')
def links_to(context, url: str) -> None:
    call = context.site.mailer.calls[0]
    assert url in call["html"] and url in call["text"]


@then("the email uses the site's accent colour")
def accent(context) -> None:
    assert "#aa3300" in context.site.mailer.calls[0]["html"]


@then("the email says why the subscriber received it")
def reason(context) -> None:
    assert "You get this because you subscribed to new stories from Alpha News" in context.site.mailer.calls[0]["text"]


@then("no email is queued")
def nothing_queued(context) -> None:
    assert context.site.queues.sent == []


@then('the function answers "{status}"')
def answers(context, status: str) -> None:
    assert context.answer["status"] == status, context.answer


@then('the delivery log of "{site_id}" has {count:d} delivery')
def log_has(context, site_id: str, count: int) -> None:
    assert len(context.sites[site_id].deliveries()) == count


@then('the delivery log of "{site_id}" is empty')
def log_empty(context, site_id: str) -> None:
    assert context.sites[site_id].deliveries() == []


@then("the function does not answer 503")
def not_503(context) -> None:
    assert context.answer["statusCode"] != 503, context.answer
