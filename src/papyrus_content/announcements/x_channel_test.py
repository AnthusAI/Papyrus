"""The parts of X on the Announcement and Delivery records that need no site (the behaviour is features_backend/announcements-x-*.feature, announcements-withdraw.feature)."""
from datetime import datetime, timezone

import pytest

from papyrus_content.announcements.attempts import ANSWER_FAILED, ANSWER_REFUSED, ANSWER_SENT, QUEUED
from papyrus_content.announcements.fakes import FakeFunctions, FakeX, StoryRecordsBackend
from papyrus_content.announcements.records import BUDGET_REACHED_CODE, PAUSED_CODE, RecordError
from papyrus_content.announcements.spend import SpendLedger
from papyrus_content.spend_ledger_test import FakeLedgerTable
from papyrus_content.announcements.x_channel import XChannel, link_of
from papyrus_content.announcements.x_runner import NotSendable, SpendControl

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
ROW = {"id": "a#x#mom#g1", "channel": "x", "accountId": "mom"}
POST = "A look at secrets.\n\nhttps://machines.example/s?utm_source=x"


def test_a_post_carries_the_last_link_in_its_words():
    assert link_of("See https://a.example then\n\nhttps://b.example/x") == "https://b.example/x"
    with pytest.raises(RecordError):
        link_of("No link here")


def test_the_channel_reads_caducus_records_as_answers():
    x = FakeX()
    channel = XChannel(x, budget_wait_until=lambda: "2026-12-01T00:00:00Z")
    assert channel.delivery("e1") is None
    channel.submit(ROW, POST, "e1")
    assert channel.delivery("e1").status == QUEUED
    x.deliver("e1")
    assert channel.delivery("e1").status == ANSWER_SENT and channel.delivery("e1").provider_id
    channel.submit(ROW, POST, "e2")
    x.fail_with = "403 Forbidden"
    x.deliver("e2")
    assert (channel.delivery("e2").status, channel.delivery("e2").code) == (ANSWER_FAILED, "403 Forbidden")
    x.fail_with = None
    channel.submit(ROW, POST, "e3")
    x.deliver("e3", refusal="Budget reached for this cycle")
    assert (channel.delivery("e3").status, channel.delivery("e3").code, channel.delivery("e3").wait_until) == (ANSWER_REFUSED, BUDGET_REACHED_CODE, "2026-12-01T00:00:00Z")
    channel.submit(ROW, POST, "e4")
    x.deliver("e4", refusal="Announcements are paused")
    assert (channel.delivery("e4").code, channel.delivery("e4").wait_until) == (PAUSED_CODE, None)


def test_a_post_is_deleted_once_and_its_record_is_read_again():
    x = FakeX()
    channel = XChannel(x)
    channel.submit(ROW, POST, "e1")
    with pytest.raises(RecordError):
        channel.delete("e1", by="ada")   # it is not up at X yet
    x.deliver("e1")
    first = channel.delete("e1", by="ada")
    again = channel.delete("e1", by="bea")
    assert x.withdrawals == ["e1"] and first == again and first.by == "ada" and first.cost == "0.210"
    assert channel.delivery("e1").status == ANSWER_SENT   # the attempt's own answer does not change
    assert channel.removal("e1") == first


def test_a_delivery_of_another_channel_is_not_handed_to_x():
    with pytest.raises(RecordError):
        XChannel(FakeX()).submit({"id": "a#email#site#g1", "channel": "email", "accountId": "site"}, POST, "e1")


def control(**connection):
    functions = FakeFunctions(lambda: NOW.timestamp())
    functions.connected = {"connection": "connected", "accountId": "mom", "handle": "@mom_test", **connection}
    return SpendControl(settings=functions, connection=functions.status, ledger=SpendLedger(FakeLedgerTable(), "site"), now=lambda: NOW), functions


def test_nothing_is_sent_until_the_owner_turns_announcements_on():
    owner, _ = control()
    with pytest.raises(NotSendable) as refused:
        owner.ready_to_send()
    assert refused.value.code == "not_on"


def test_a_site_with_no_budget_or_billing_day_sends_nothing():
    owner, functions = control()
    document = functions.read()
    functions.settings.store.put({**document, "mode": "on", "budget": None, "billingCycleDay": None, "labelConfirmed": True,
                                  "rules": {**document["rules"], "minStars": 5, "storyTypes": ["article"]}})
    with pytest.raises(NotSendable) as refused:
        owner.ready_to_send()
    assert refused.value.code == "settings_incomplete" and "Enter a budget" in str(refused.value)
