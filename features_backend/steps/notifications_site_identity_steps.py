from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from behave import given, then, when

REPO_ROOT = Path(__file__).resolve().parents[2]
for entry in (REPO_ROOT / "src", REPO_ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from papyrus_content.newsletter.events import handle_ses_event  # noqa: E402
from papyrus_content.notifications import handler as notifications_handler  # noqa: E402
from papyrus_content.notifications.notifications_test import FakeSes, Site, alarm  # noqa: E402
from papyrus_content.notifications.pause import alarm_names, handle_alarm  # noqa: E402
from papyrus_content.notifications.sending import SendingPaused  # noqa: E402

BOUNCES = {"Permanent bounce": ("Bounce", {"bounce": {"bounceType": "Permanent"}}), "Transient bounce": ("Bounce", {"bounce": {"bounceType": "Transient"}}), "Delivery": ("Delivery", {}), "Complaint": ("Complaint", {})}


@given("the site's configuration set is paused")
def paused(context) -> None:
    context.site.mailer.script = [SendingPaused("sending is paused for configuration set papyrus-alpha")]


@given("the site has no postal address")
def no_postal(context) -> None:
    context.sites["alpha"] = context.site = Site("alpha", postal_address=None)


@given('the site has the postal address "{address}"')
def postal(context, address: str) -> None:
    context.sites["alpha"] = context.site = Site("alpha", postal_address=address)


@given('the story "{title}" was sent')
def was_sent(context, title: str) -> None:
    context.site.publish(title, "news")
    context.site.play_queue()


@when("the delivery is marketing mail")
def marketing(context) -> None:
    context.site.make_public()


@when('SES reports "{event}" for the message')
def reports(context, event: str) -> None:
    kind, extra = BOUNCES[event]
    notifications_handler.ses_events_with(context.site.runtime, context.site.ses_event(kind, "fake-message-1", **extra))


@when("SES reports a bounce for the message tagged with another site")
def other_site(context) -> None:
    event = context.site.ses_event("Bounce", "fake-message-1", site="beta", bounce={"bounceType": "Permanent"})
    notifications_handler.ses_events_with(context.site.runtime, event)


@when("SES reports a bounce for a newsletter subscriber's message")
def newsletter_message(context) -> None:
    event = {"detail": {"eventType": "Bounce", "bounce": {"bounceType": "Permanent"}, "mail": {"messageId": "fake-message-1", "tags": {"sub": ["a" * 32], "site": ["alpha"]}}}}
    notifications_handler.ses_events_with(context.site.runtime, event)


@when("SES reports a permanent bounce for notification mail on the shared configuration set")
def notification_bounce(context) -> None:
    tags = {"site": ["alpha"], "delivery": ["d" * 32], "kind": ["story.published"]}
    message = {"eventType": "Bounce", "bounce": {"bounceType": "Permanent"}, "mail": {"messageId": "m1", "tags": tags}}
    context.newsletter_answer = handle_ses_event(SimpleNamespace(settings=SimpleNamespace(site_id="alpha")), message)


@when("the site's bounce rate alarm enters ALARM")
def bounce_alarm(context) -> None:
    context.ses = FakeSes()
    handle_alarm(context.site.settings, context.ses, alarm(alarm_names("alpha")[0], "ALARM"))


@when("the site's bounce rate alarm returns to OK")
def alarm_ok(context) -> None:
    context.ses = FakeSes()
    handle_alarm(context.site.settings, context.ses, alarm(alarm_names("alpha")[0], "OK"))


@when("another site's complaint rate alarm enters ALARM")
def other_alarm(context) -> None:
    handle_alarm(context.site.settings, context.ses, alarm(alarm_names("beta")[1], "ALARM"))


@then('the email is tagged with the site "{site_id}", the kind "{kind}" and its delivery')
def tagged(context, site_id: str, kind: str) -> None:
    tags = context.site.mailer.calls[0]["tags"]
    assert tags["site"] == site_id and tags["kind"] == kind and tags["delivery"], tags


@then('the site\'s configuration set is "{name}"')
def configuration_set(context, name: str) -> None:
    assert context.site.settings.configuration_set == name


@then("the site sent no mail")
def none_sent(context) -> None:
    assert context.site.mailer.calls == []


@then('the delivery is "{status}" because "{reason}"')
def failed_because(context, status: str, reason: str) -> None:
    (row,) = context.site.deliveries()
    assert (row["status"], row["reason"]) == (status, reason), row


@then('the delivery is "{status}"')
def delivery_is(context, status: str) -> None:
    assert context.site.deliveries()[0]["status"] == status


@then('the email footer shows "{line}"')
def footer(context, line: str) -> None:
    call = context.site.mailer.calls[0]
    assert line in call["html"] and line in call["text"]


@then("the newsletter function ignores the event")
def newsletter_ignores(context) -> None:
    assert context.newsletter_answer == "ignored"


@then('sending is turned off for the configuration set "{name}"')
def turned_off(context, name: str) -> None:
    assert context.ses.calls == [{"ConfigurationSetName": name, "SendingEnabled": False}]


@then("sending is not turned off")
def not_turned_off(context) -> None:
    assert context.ses.calls == []
