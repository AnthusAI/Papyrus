"""The runner's Broadcaster hands each call to the site's broadcast function, and the function's answers come back as the in-process Broadcaster's results and errors."""
from __future__ import annotations

import pytest

from papyrus_content.announcements.caducus_x import SubmitRefused
from papyrus_content.announcements.channel import DeliveryView
from papyrus_content.announcements.records import RecordError
from papyrus_content.announcements.remote_broadcaster import RemoteBroadcaster, function_name_for
from papyrus_content.notifications.handler import broadcast_with

SITE_FUNCTION = function_name_for("machines-on-machines")


class BroadcasterAtTheSite:
    def __init__(self, refuse_submit=False):
        self.submitted, self.refuse_submit = [], refuse_submit

    def submit(self, *, account_id, event_id, text, url):
        if self.refuse_submit:
            raise SubmitRefused(f"Caducus refused the announcement {event_id}: paused.")
        self.submitted.append((account_id, event_id, text, url))

    def delivery(self, event_id):
        return DeliveryView(status="sent", post_id="1900", cost="0.20", attempts=1) if event_id == "known" else None

    def withdraw(self, event_id, *, by):
        if event_id != "known":
            raise RecordError(f"Caducus has no delivery for {event_id}, so there is no post to delete.")
        return DeliveryView(status="withdrawn", post_id="1900", withdrawn_by=by)


class SiteRuntime:
    def __init__(self, broadcaster):
        self.broadcaster = broadcaster


def through_the_site(broadcaster):
    calls = []

    def invoke(function_name, payload):
        calls.append(function_name)
        return broadcast_with(SiteRuntime(broadcaster), payload)

    return RemoteBroadcaster(SITE_FUNCTION, invoke), calls


def test_a_submit_reaches_the_sites_broadcaster_through_its_function():
    site = BroadcasterAtTheSite()
    remote, calls = through_the_site(site)
    remote.submit(account_id="42", event_id="delivery:d1:a1", text="Words", url="https://news.example/s")
    assert site.submitted == [("42", "delivery:d1:a1", "Words", "https://news.example/s")]
    assert calls == ["papyrus-notifications-broadcast-machines-on-machines"]


def test_a_refused_submit_is_the_same_refusal_on_the_runner():
    remote, _ = through_the_site(BroadcasterAtTheSite(refuse_submit=True))
    with pytest.raises(SubmitRefused):
        remote.submit(account_id="42", event_id="delivery:d1:a1", text="Words", url="https://news.example/s")


def test_a_delivery_comes_back_as_a_view_or_none():
    remote, _ = through_the_site(BroadcasterAtTheSite())
    assert remote.delivery("known") == DeliveryView(status="sent", post_id="1900", cost="0.20", attempts=1)
    assert remote.delivery("unknown") is None


def test_a_withdraw_returns_the_view_and_a_missing_one_is_a_record_error():
    remote, _ = through_the_site(BroadcasterAtTheSite())
    assert remote.withdraw("known", by="ryan").status == "withdrawn"
    with pytest.raises(RecordError) as refused:
        remote.withdraw("unknown", by="ryan")
    assert not isinstance(refused.value, SubmitRefused)


def test_a_site_not_wired_for_x_answers_that_nothing_can_be_posted():
    remote, _ = through_the_site(None)
    with pytest.raises(RecordError, match="not wired for X"):
        remote.delivery("known")


def test_only_a_sites_broadcast_function_is_invoked():
    with pytest.raises(ValueError):
        RemoteBroadcaster("papyrus-notifications-machines-on-machines", lambda name, payload: {})
