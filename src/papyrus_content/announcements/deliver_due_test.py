"""The scheduled send's one step, over the in-memory records and Caducus's x channel (the behaviour, through the runner, is
features_backend/announcements/delivery-scheduled-send.feature)."""
from datetime import datetime, timezone

from papyrus_content import follow_up_timers as fu
from papyrus_content.announcements import budget
from papyrus_content.announcements.deliver_due import DeliverServices, deliver_due_run
from papyrus_content.announcements.deliveries import Deliveries, Plan
from papyrus_content.announcements.delivery_timers import OWNER, PROCEDURE_KEY, DeliveryTimers
from papyrus_content.announcements.fakes import FakeFunctions, FakeX, StoryRecordsBackend
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles
from papyrus_content.announcements.spend import SpendLedger
from papyrus_content.announcements.withdrawals import Withdrawals
from papyrus_content.announcements.x_channel import XChannel
from papyrus_content.announcements.x_runner import SpendControl, XRunner
from papyrus_content.follow_up_timers_test import Api
from papyrus_content.spend_ledger_test import FakeLedgerTable

NOW = datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc)
DRAFTED, LOCK, RELEASE = "2026-11-22T09:00:00Z", "2026-11-22T09:50:00Z", "2026-11-22T10:00:00Z"
WORDS = "A look at whether a system can keep a secret from itself.\n\nhttps://machines.example/s"
PRICES = {"createPost": 0.015, "createPostWithUrl": 0.2, "deletePost": 0.01, "readPost": 0.005, "asOf": "2026-11-12"}
ENVIRONMENT = {"PAPYRUS_AGENT_PUBLICATION_ID": "mom", "PAPYRUS_AWS_ACCOUNT_ID": "123456789012", "AWS_REGION": "us-east-1",
               "PAPYRUS_AGENT_TENANT_ID": "alpha", "PAPYRUS_SITE_BUCKET": "site-bucket"}
ENDPOINT = "https://abcdefghijklmnopqrstuvwxyz.appsync-api.us-east-1.amazonaws.com/graphql"


class Site:
    def __init__(self, *, mode="on"):
        self.backend = StoryRecordsBackend()
        self.api = Api()
        self.timers = DeliveryTimers.from_environment(ENVIRONMENT, appsync_endpoint=ENDPOINT, client=self.api)
        self.deliveries = Deliveries(self.backend, MemoryDeliveryFiles(self.backend), self.timers)
        self.functions = FakeFunctions(lambda: NOW.timestamp())
        self.functions.save({"mode": mode, "rules": {"minStars": 5, "storyTypes": ["article"]}, "budget": 10.0, "billingCycleDay": 1, "prices": PRICES, "labelConfirmed": True},
                            "connected")
        self.control = SpendControl(settings=self.functions, connection=self.functions.status, ledger=SpendLedger(FakeLedgerTable(), "site"), now=lambda: NOW)
        self.x = FakeX()
        channel = XChannel(self.x, budget_wait_until=lambda: budget.next_cycle_start(budget.cycle_start(NOW, 1), 1).isoformat() + "T00:00:00Z")
        runner = XRunner(self.deliveries, Withdrawals(self.deliveries, None, removers=lambda row: channel), channel, self.control)
        self.services = DeliverServices(self.deliveries, send_x=runner.send_due)

    def draft(self, approval="soft", lock_at=RELEASE):
        plan = Plan(channel="x", account_id="mom", approval=approval, approval_policy="publication default", text=WORDS, lock_at=lock_at, release_at=RELEASE)
        return self.deliveries.create("announcement-1", plan, release_at=RELEASE, by="announce", now=DRAFTED)

    def entry_times(self):
        return sorted(entry["ScheduleExpression"] for entry in self.api.entries.values())


def test_the_timer_names_the_engine_procedure_and_the_time_it_waits_for():
    site = Site()
    row = site.draft()
    request = site.timers.wake_request(row)
    assert request["procedureKey"] == PROCEDURE_KEY == "deliver_due"
    assert request["input"] == {"deliveryId": row["id"], "dueAt": RELEASE} and request["wakeKey"] == fu.follow_up_key(OWNER, row["id"], RELEASE)
    assert (request["tenantId"], request["siteBucket"]) == ("alpha", "site-bucket")
    assert site.entry_times() == ["at(2026-11-22T10:00:00)"]


def test_a_soft_delivery_nobody_acted_on_is_approved_locked_and_handed_to_x_at_its_time():
    site = Site()
    row = site.draft()
    done = deliver_due_run(site.services, row["id"], RELEASE, now=RELEASE)
    assert (done["run_outcome"], done["run_outcome_reason"]) == ("acted", "sent"), done
    written = site.deliveries.get(row["id"])
    assert written["state"] == "sending" and written["approvedBy"] == "system" and written["lockedVersion"] == 1
    assert [event["text"] for event in site.x.events.values()] == [WORDS]
    assert site.api.entries == {}, "nothing is pending, so the timer is gone"


def test_a_lock_before_the_release_locks_and_moves_the_timer_to_the_release():
    site = Site()
    row = site.draft(lock_at=LOCK)
    assert site.entry_times() == ["at(2026-11-22T09:50:00)"]
    locked = deliver_due_run(site.services, row["id"], LOCK, now=LOCK)
    assert (locked["run_outcome"], locked["run_outcome_reason"]) == ("acted", "locked"), locked
    assert site.entry_times() == ["at(2026-11-22T10:00:00)"] and not site.x.events
    sent = deliver_due_run(site.services, row["id"], RELEASE, now=RELEASE)
    assert (sent["run_outcome"], sent["run_outcome_reason"]) == ("acted", "sent"), sent


def test_a_hard_delivery_with_no_approval_asks_a_person_once_and_sends_nothing():
    site = Site()
    row = site.draft(approval="hard")
    first = deliver_due_run(site.services, row["id"], RELEASE, now=RELEASE)
    again = deliver_due_run(site.services, row["id"], RELEASE, now="2026-11-22T12:00:00Z")
    assert (first["run_outcome"], first["run_outcome_reason"]) == ("asked", "waiting_for_person"), first
    assert first["result"]["flag"] == again["result"]["flag"] and len(site.backend.rows("ReviewRequest")) == 1
    assert not site.x.events and site.deliveries.get(row["id"])["dueAt"] == RELEASE


def test_a_wake_for_a_time_that_moved_does_nothing():
    site = Site()
    row = site.draft()
    site.deliveries.move_release(row, "2026-11-22T11:00:00Z", by="ada", now="2026-11-22T09:30:00Z")
    done = deliver_due_run(site.services, row["id"], RELEASE, now=RELEASE)
    assert (done["run_outcome"], done["run_outcome_reason"]) == ("nothing", "not_waiting"), done
    assert not site.x.events and site.entry_times() == ["at(2026-11-22T11:00:00)"]


def test_a_site_whose_announcements_are_not_on_sends_nothing():
    site = Site(mode="dry_run")
    row = site.draft()
    done = deliver_due_run(site.services, row["id"], RELEASE, now=RELEASE)
    assert (done["run_outcome"], done["run_outcome_reason"]) == ("acted", "locked"), done   # the lock is the engine's; the send is X's, and X is not on
    assert not site.x.events


def test_a_run_that_writes_deliveries_without_the_sites_timers_stops_and_names_what_is_missing():
    import pytest

    from papyrus_content.list_cadence.story_wake import StoryWakeError, site_delivery_timers

    class Client:
        endpoint = ENDPOINT

    assert isinstance(site_delivery_timers(ENVIRONMENT, Client()), DeliveryTimers)
    with pytest.raises(StoryWakeError, match="PAPYRUS_AWS_ACCOUNT_ID, PAPYRUS_SITE_BUCKET"):
        site_delivery_timers({**ENVIRONMENT, "PAPYRUS_AWS_ACCOUNT_ID": "", "PAPYRUS_SITE_BUCKET": ""}, Client())


def test_the_write_door_holds_the_timers_its_environment_names_and_none_where_the_site_is_not_named():
    from papyrus_content.image_service import site_delivery_timers

    timers = site_delivery_timers({**ENVIRONMENT, "PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT})
    assert isinstance(timers, DeliveryTimers) and timers._base["tenantId"] == "alpha" and timers._base["appsyncEndpoint"] == ENDPOINT
    assert site_delivery_timers({"PAPYRUS_GRAPHQL_ENDPOINT": ENDPOINT}) is None
