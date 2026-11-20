"""The newsletter-to-notifications migration on moto's DynamoDB (the newsletter's real rows) and Caducus's in-memory fakes. ``Move`` is also what
features_backend/notifications-subscriber-migration.feature drives. Nothing here reaches AWS, SES or a real table."""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from typing import Any, Iterator

import pytest

from papyrus_content.newsletter import links as newsletter_links
from papyrus_content.newsletter import records
from papyrus_content.newsletter.manage import apply_unsubscribe
from papyrus_content.newsletter.newsletter_test import Harness, running_harness
from papyrus_content.notifications import migration, migration_cli
from papyrus_content.notifications.legacy_links import SOURCE
from papyrus_content.notifications.notifications_test import Site

ROUNDUP = "weekly"
ALERTS = "alerts-a"
UNTIL = migration_cli.end_of_day("2027-06-30")
LISTS = (
    {"id": ROUNDUP, "name": "Weekly roundup", "description": "", "kind": "roundup", "rule": {}, "approval": "admin"},
    {"id": ALERTS, "name": "Alerts A", "description": "", "rule": {"sections": ["news"]}, "approval": "admin"},
    {"id": "alerts-b", "name": "Alerts B", "description": "", "rule": {"sections": ["security"]}, "approval": "admin"},
)
ENVIRONMENT = {
    "SITE_ID": "alpha", "SITE_ORIGIN": "https://alpha.example.test", "FROM_NAME": "Alpha News", "FROM_ADDRESS": "notify@alpha.example.test",
    "THEME_JSON": "{}", "LISTS_JSON": json.dumps(list(LISTS)),
}


class Move:
    """One site: a newsletter with real subscribers (moto), and the site's notifications function waiting to receive them."""

    def __init__(self, source: Harness) -> None:
        self.source = source
        self.site = Site("alpha", readers=0, lists=LISTS, legacy_token_key=source.keys.token)
        # The real byRecipient index is sparse (its sort key is queuedAt, which alias rows lack); Caducus 0.4.0's in-memory store is not.
        in_memory = self.site.store.by_recipient
        self.site.store.by_recipient = lambda key: [row for row in in_memory(key) if "queuedAt" in row]  # type: ignore[method-assign]
        self.target = migration.Target(self.site.runtime.audience, self.site.runtime.recipient_key)
        self.declared = [entry["id"] for entry in LISTS]
        self.joined = 0

    # -- the newsletter, as readers use it ----------------------------------------------------------------------------

    def join(self, address: str, lists: list[str]) -> None:
        self.joined += 1
        assert self.source.subscribe(address, lists=lists, ip=f"198.51.100.{self.joined}")["statusCode"] == 202
        assert self.source.confirm()["body"]["status"] == "confirmed"
        self.source.now += 4000

    def request_only(self, address: str, lists: list[str]) -> None:
        self.joined += 1
        self.source.subscribe(address, lists=lists, ip=f"198.51.100.{self.joined}")

    def unsubscribe(self, address: str) -> None:
        apply_unsubscribe(self.source.service, self.source.hid(address), None, "unsubscribed:all")

    def bounce(self, address: str) -> None:
        hid = self.source.hid(address)
        records.put_suppression(self.source.store, hid, "bounce", self.source.now)
        apply_unsubscribe(self.source.service, hid, None, "suppressed:bounce")

    def suppress_manually(self, address: str) -> None:
        records.put_suppression(self.source.store, self.source.hid(address), "manual", self.source.now)

    def old_token(self, address: str) -> str:
        return newsletter_links.make_manage_token(self.source.hid(address), self.source.keys)

    # -- the move --------------------------------------------------------------------------------------------------------

    def snapshot(self) -> migration.Snapshot:
        return migration.read_source(self.source.store, self.source.now)

    def plan(self) -> migration.Plan:
        return migration.build_plan(self.snapshot(), self.declared)

    def apply(self, plan: migration.Plan | None = None) -> migration.Result:
        snapshot = self.snapshot()
        return migration.apply(
            plan or migration.build_plan(snapshot, self.declared), snapshot, self.target, old_links_until=UNTIL, declared_lists=self.declared
        )

    def verify(self) -> migration.Verification:
        return migration.verify(self.plan(), self.target, declared_lists=self.declared)

    def table(self) -> dict[Any, Any]:
        return json.loads(json.dumps({str(key): value for key, value in self.site.store.items.items()}, default=str))

    def held(self, address: str) -> list[str]:
        key = self.site.runtime.recipient_key(address)
        return sorted(self.site.runtime.audience.subscribed_lists(key))

    def consent_records(self, address: str) -> list[dict[str, Any]]:
        return self.site.runtime.audience.export(address)["body"]["consent"]


@contextmanager
def moving() -> Iterator[Move]:
    with running_harness() as source:
        yield Move(source)


@pytest.fixture
def move() -> Iterator[Move]:
    with moving() as world:
        yield world


READER, OTHER, THIRD = "reader@example.com", "other@example.com", "third@example.com"


def test_a_confirmed_subscriber_moves_with_their_consent_evidence_and_no_mail(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    original = move.source.profile(READER)["consent"]
    result = move.apply()
    assert (result.imported, result.refused) == (1, [])
    assert move.held(READER) == [ALERTS, ROUNDUP]
    (evidence,) = move.consent_records(READER)
    assert evidence["source"] == "migrated" and evidence["from"] == SOURCE
    assert {name: evidence[name] for name in original} == original, "every original field is copied unchanged"
    assert move.site.mailer.calls == [] and move.site.queues.sent == [], "no confirmation or any other mail"


def test_pending_and_unsubscribed_readers_are_not_carried(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.request_only(OTHER, [ROUNDUP])
    move.join(THIRD, [ROUNDUP])
    move.unsubscribe(THIRD)
    plan = move.plan()
    assert [sub.address for sub in plan.carried] == [READER]
    assert plan.not_carried == {"pending": 1, "unsubscribed": 1}
    move.apply()
    assert move.held(OTHER) == [] and move.held(THIRD) == []


def test_counts_match_source_after_a_run(move: Move) -> None:
    for number in range(3):
        move.join(f"a{number}@example.com", [ROUNDUP, ALERTS])
    move.join("b@example.com", [ALERTS])
    move.join("bounced@example.com", [ROUNDUP])
    move.bounce("bounced@example.com")
    move.join("held@example.com", [ALERTS])
    move.suppress_manually("held@example.com")
    plan = move.plan()
    assert plan.per_list[ROUNDUP]["confirmed"] == 3 and plan.per_list[ALERTS]["confirmed"] == 5 and plan.suppressed == {"bounce": 1, "manual": 1}
    assert plan.consent == {"with_evidence": 6, "without_evidence": 0}
    move.apply()
    report = move.verify()
    assert report.ok, report.as_dict()
    assert report.per_list[ROUNDUP] == {"source": 3, "target": 3} and report.per_list[ALERTS] == {"source": 5, "target": 5}
    assert report.suppressed == {"source": 2, "target": 2} and report.consent == {"source": 6, "target": 6} and report.aliases == {"source": 6, "target": 6}


def test_a_second_run_changes_nothing(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    move.join(OTHER, [ALERTS])
    move.bounce(OTHER)
    move.apply()
    before = move.table()
    second = move.apply()
    assert (second.imported, second.unchanged, second.settled) == (0, 2, 0)
    assert move.table() == before


def test_someone_who_left_the_newsletter_since_the_last_run_is_unsubscribed_there_too(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    move.join(OTHER, [ALERTS])
    move.apply()
    apply_unsubscribe(move.source.service, move.source.hid(READER), [ALERTS], "unsubscribed:alerts-a")
    move.unsubscribe(OTHER)
    second = move.apply()
    assert second.settled == 2
    assert move.held(READER) == [ROUNDUP] and move.held(OTHER) == []
    assert move.verify().ok


def test_a_problem_stops_a_real_run_and_writes_nothing(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    move.declared = [ROUNDUP]
    plan = move.plan()
    assert plan.problems == [f"list_not_declared:{ALERTS}"]
    before = move.table()
    with pytest.raises(migration.Refused):
        move.apply(plan)
    assert move.table() == before


def test_a_confirmed_subscriber_with_no_consent_evidence_is_a_problem_not_a_guess(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    profile = move.source.store.get_profile(move.source.hid(READER))
    assert profile is not None
    profile.pop("consent")
    move.source.store.save(profile, int(profile["rev"]))
    assert move.plan().problems == ["no_consent_evidence:1"]


def test_a_suppression_with_no_profile_is_counted_and_not_carried(move: Move) -> None:
    records.put_suppression(move.source.store, "f" * 32, "bounce", move.source.now)
    assert move.plan().orphan_suppressions == 1 and move.plan().carried == []


def test_the_plan_prints_counts_and_masks_addresses(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.join(OTHER, [ALERTS])
    move.bounce(OTHER)
    text = migration.render_plan(move.plan())
    assert "list weekly: 1 confirmed" in text and "Suppressed: bounce 1" in text and "o***@example.com" in text
    assert OTHER not in text and READER not in text


# -- old links ---------------------------------------------------------------------------------------------------------------


def test_an_old_manage_link_applies_in_the_new_system(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    move.apply()
    old = move.old_token(READER)
    state = move.site.act("preferences_state", token=old)
    assert state["body"]["status"] == "ready" and {entry["id"] for entry in state["body"]["lists"] if entry["subscribed"]} == {ROUNDUP, ALERTS}
    assert move.site.act("update_preferences", token=old, lists=[ROUNDUP])["body"]["status"] == "saved"
    assert move.held(READER) == [ROUNDUP]


def test_an_old_unsubscribe_link_applies_in_the_new_system(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    move.apply()
    assert move.site.act("unsubscribe", token=move.old_token(READER), list=ALERTS)["body"]["status"] == "unsubscribed"
    assert move.held(READER) == [ROUNDUP]
    assert move.site.act("unsubscribe", token=move.old_token(READER))["body"]["status"] == "unsubscribed"
    assert move.held(READER) == []


def test_an_old_link_of_someone_not_moved_is_invalid(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    assert move.site.act("preferences_state", token=move.old_token(READER))["statusCode"] == 400


def test_old_links_stop_at_the_date_the_owner_chose(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.apply()
    move.site.clock.now = move.site.clock.now.__class__.fromtimestamp(UNTIL + 1, tz=move.site.clock.now.tzinfo)
    assert move.site.act("preferences_state", token=move.old_token(READER))["statusCode"] == 400


def test_an_old_confirm_token_is_never_accepted(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.apply()
    assert move.site.act("confirm", token=move.old_token(READER))["statusCode"] == 400


def test_a_new_link_still_works_while_old_links_are_honoured(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.apply()
    new = move.site.runtime.audience.manage_token(move.site.runtime.recipient_key(READER))
    assert move.site.act("preferences_state", token=new)["body"]["status"] == "ready"


# -- suppression and kinds -------------------------------------------------------------------------------------------------


def test_a_bounced_and_a_manually_suppressed_address_are_not_mailed_the_next_story(move: Move) -> None:
    move.join("bounced@example.com", [ALERTS])
    move.bounce("bounced@example.com")
    move.join("held@example.com", [ALERTS])
    move.suppress_manually("held@example.com")
    move.join(READER, [ALERTS])
    move.apply()
    move.site.publish("Rates held steady", "news")
    move.site.play_queue()
    assert [call["to"] for call in move.site.mailer.calls] == [READER]


def test_a_roundup_subscriber_is_not_mailed_each_story(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.join(OTHER, [ALERTS])
    move.apply()
    move.site.publish("Rates held steady", "news")
    move.site.play_queue()
    assert [call["to"] for call in move.site.mailer.calls] == [OTHER]


def test_an_erased_address_is_never_brought_back(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    move.apply()
    assert move.site.act("delete_subscriber", token=move.old_token(READER))["body"]["status"] == "deleted"
    again = move.apply()
    assert again.refused == ["r***@example.com"] and move.held(READER) == []


# -- the command -------------------------------------------------------------------------------------------------------------


def run_cli(move: Move, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = migration_cli.main(
        list(argv), environment=ENVIRONMENT, store_factory=lambda table: move.source.store, runtime_factory=lambda: move.site.runtime,
        now=lambda: move.source.now, out=out,
    )
    return code, out.getvalue()


def test_the_command_prints_a_dry_run_and_writes_nothing(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    before = move.table()
    code, text = run_cli(move, "run", "--newsletter-table", "newsletter", "--dry-run")
    assert code == 0 and "Carried to notifications: 1 subscribers" in text
    assert move.table() == before


def test_the_command_refuses_to_write_without_the_freeze_and_a_date(move: Move) -> None:
    move.join(READER, [ROUNDUP])
    with pytest.raises(SystemExit):
        run_cli(move, "run", "--newsletter-table", "newsletter")
    assert move.held(READER) == []


def test_the_command_runs_then_verifies(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    code, text = run_cli(move, "run", "--newsletter-table", "newsletter", "--sends-frozen", "--old-links-until", "2027-06-30")
    assert code == 0 and "Imported 1" in text
    code, text = run_cli(move, "verify", "--newsletter-table", "newsletter")
    assert code == 0 and "every count matches" in text
    code, report = run_cli(move, "verify", "--newsletter-table", "newsletter", "--json")
    assert json.loads(report)["ok"] is True


def test_verify_fails_when_the_target_differs(move: Move) -> None:
    move.join(READER, [ROUNDUP, ALERTS])
    move.apply()
    move.site.act("update_preferences", token=move.site.runtime.audience.manage_token(move.site.runtime.recipient_key(READER)), lists=[ROUNDUP])
    code, text = run_cli(move, "verify", "--newsletter-table", "newsletter")
    assert code == 1 and "DOES NOT MATCH" in text and "MISMATCH" in text


def test_the_end_of_day_is_the_last_second_in_utc() -> None:
    assert migration_cli.end_of_day("1970-01-02") == 2 * 86400 - 1
