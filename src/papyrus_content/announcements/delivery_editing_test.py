"""The editing window of a Delivery, in the small: blocks and pins, versions, the lock and the edit windows (the features are the specification, delivery-*.feature)."""
from __future__ import annotations

import pytest

from papyrus_content.announcements import delivery_text as dt
from papyrus_content.announcements import edit_windows
from papyrus_content.announcements.deliveries import Deliveries, Plan
from papyrus_content.announcements.delivery_lock import APPROVED_AND_LOCKED, LOCKED, WAITING_FOR_PERSON, lock_at_time, unlock
from papyrus_content.announcements.delivery_versions import Locked, StaleVersion, Versions
from papyrus_content.announcements.records_fakes import MemoryDeliveryFiles, RecordsBackend
from papyrus_content.announcements.x_account import AnnouncementError

NOW = "2026-11-16T14:00:00Z"
LOCK = "2026-11-16T14:15:00Z"
RELEASE = "2026-11-16T14:20:00Z"


def make(approval="soft", text="One.\n\nTwo.\n\nThree."):
    backend = RecordsBackend()
    deliveries = Deliveries(backend, MemoryDeliveryFiles(backend))
    row = deliveries.create("announcement-1", Plan(channel="x", account_id="handle", approval=approval, approval_policy="publication policy (agent policy version 1)", text=text,
                                                    lock_at=LOCK), release_at=RELEASE, by="announce", now=NOW)
    return deliveries, Versions(deliveries), row["id"]


def test_blocks_are_the_paragraphs_and_a_text_with_no_words_has_none():
    assert dt.split_blocks("One.\n\n  Two.  \n \nThree.\n") == ["One.", "Two.", "Three."]
    assert dt.split_blocks("") == []


def test_a_redraft_keeps_every_pinned_block_word_for_word_wherever_the_redraft_put_things():
    current = [("A", dt.MACHINE_FLAGS), ("B, by a person", dt.HUMAN_FLAGS), ("C", dt.MACHINE_FLAGS)]
    texts, flags = dt.merge_redraft(current, ["X", "Y", "Z"])
    assert texts == ["X", "B, by a person", "Z"] and flags[1] == dt.HUMAN_FLAGS and flags[0] == dt.MACHINE_FLAGS
    texts, flags = dt.merge_redraft(current, ["B, by a person", "Y"])
    assert texts == ["B, by a person", "Y"] and flags[0] == dt.HUMAN_FLAGS
    texts, flags = dt.merge_redraft(current, ["Only"])
    assert texts == ["Only", "B, by a person"] and flags[1] == dt.HUMAN_FLAGS
    texts, _ = dt.merge_redraft([("P", dt.HUMAN_FLAGS), ("Q", dt.HUMAN_FLAGS)], ["X"])
    assert texts == ["P", "Q"], "two pins are both kept even when the redraft has room for one"


def test_a_person_keeps_the_flags_of_a_block_they_only_moved_and_pins_the_ones_they_changed():
    previous = [("A", dt.MACHINE_FLAGS), ("B", dt.HUMAN_FLAGS)]
    assert dt.person_flags(previous, ["B", "A", "New"]) == [dt.HUMAN_FLAGS, dt.MACHINE_FLAGS, dt.HUMAN_FLAGS]


def test_every_save_is_a_new_version_naming_the_one_it_replaces_and_no_file_is_overwritten():
    deliveries, versions, row_id = make()
    first = versions.save(row_id, replaces=1, text="One.\n\nTwo, better.\n\nThree.", by="ellie", now=NOW)
    second = versions.save(row_id, replaces=2, text="One.\n\nTwo, better.\n\nThree, too.", by="sierra", now=NOW)
    row = deliveries.get(row_id)
    assert (first.status, second.status, int(row["version"])) == ("saved", "saved", 3)
    assert [(e["number"], e["replaces"], e["by"]) for e in dt.versions_of(row)] == [(1, None, "announce"), (2, 1, "ellie"), (3, 2, "sierra")]
    assert [deliveries.files.get(row_id, f"v{n}") for n in (1, 2, 3)] == ["One.\n\nTwo.\n\nThree.", "One.\n\nTwo, better.\n\nThree.", "One.\n\nTwo, better.\n\nThree, too."]
    assert row["textKey"] == dt.entry_of(row, 3)["key"] and row["contentHash"] == dt.entry_of(row, 3)["contentHash"]
    assert [b["pinned"] for b in dt.entry_of(row, 2)["blocks"]] == [False, True, False]


def test_a_stale_save_names_the_version_that_replaced_the_one_it_read_and_a_redraft_is_dropped():
    deliveries, versions, row_id = make()
    versions.save(row_id, replaces=1, text="Ellie's.", by="ellie", now=NOW)
    with pytest.raises(StaleVersion) as stale:
        versions.save(row_id, replaces=1, text="Sierra's.", by="sierra", now=NOW)
    assert stale.value.replaced_by["number"] == 2 and "version 2, saved by ellie" in str(stale.value) and stale.value.head == 2
    dropped = versions.redraft(row_id, replaces=1, text="A machine's.", by="announce", now=NOW)
    assert dropped.dropped and deliveries.get(row_id)["version"] == 2


def test_an_identical_save_is_not_a_version_and_a_save_needs_words():
    deliveries, versions, row_id = make()
    assert versions.save(row_id, replaces=1, text="One.\n\nTwo.\n\nThree.", by="ellie", now=NOW).status == "unchanged"
    with pytest.raises(Exception, match="has words"):
        versions.save(row_id, replaces=1, text="  ", by="ellie", now=NOW)
    assert deliveries.get(row_id)["version"] == 1


def test_the_lock_by_review_and_the_late_edit_after_it():
    deliveries, versions, row_id = make("soft")
    outcome = lock_at_time(deliveries, row_id, now=LOCK)
    row = outcome.row
    assert outcome.action == APPROVED_AND_LOCKED and (row["approvedBy"], row["approvedVersion"], row["lockedVersion"], row["lockedAt"]) == ("system", 1, 1, LOCK)
    with pytest.raises(Locked, match="explicit unlock"):
        versions.save(row_id, replaces=1, text="Late.", by="ellie", now=LOCK)
    assert lock_at_time(deliveries, row_id, now="2026-11-16T14:17:00Z").action == "already_locked"
    unlocked = unlock(deliveries, row_id, by="ellie", now="2026-11-16T14:16:00Z", lock_at="2026-11-16T14:18:00Z")
    assert unlocked["lockedAt"] is None and unlocked["lockAt"] == "2026-11-16T14:18:00Z" and unlocked["approvedVersion"] == 1
    versions.save(row_id, replaces=1, text="Not late now.", by="ellie", now="2026-11-16T14:16:00Z")


def test_a_hard_delivery_with_no_approval_is_not_locked_and_a_none_one_locks_the_policy_approved_version():
    deliveries, _, row_id = make("hard")
    assert lock_at_time(deliveries, row_id, now=LOCK).action == WAITING_FOR_PERSON and not deliveries.get(row_id).get("lockedAt")
    deliveries, _, row_id = make("none")
    assert lock_at_time(deliveries, row_id, now=LOCK).action == LOCKED


def test_an_edit_while_an_attempt_is_open_is_a_preferred_version_that_leaves_the_locked_one_to_be_sent():
    from papyrus_content.announcements.attempts import Attempts

    deliveries, versions, row_id = make("none")
    lock_at_time(deliveries, row_id, now=LOCK)
    row, entry = Attempts(deliveries).open(row_id, by="worker", now=RELEASE)
    assert entry["version"] == 1
    saved = versions.save(row_id, replaces=1, text="How it should have read.", by="ellie", now=RELEASE)
    row = deliveries.get(row_id)
    assert saved.status == "preferred" and row["preferredVersion"] == 2 and row["lockedVersion"] == 1
    assert deliveries.sent_text(row) == "One.\n\nTwo.\n\nThree." and deliveries.text(row) == "How it should have read."


def test_the_narrowest_window_wins_and_a_window_that_is_not_possible_is_refused():
    settings = {edit_windows.KEY: edit_windows.validate([{"windowMinutes": 60}, {"channel": "x", "windowMinutes": 30}, {"kind": "story_published", "windowMinutes": 20, "lockLeadMinutes": 4},
                                                         {"kind": "story_published", "channel": "x", "windowMinutes": 10, "lockLeadMinutes": 2}])}
    windows = edit_windows.windows_of(settings)
    assert edit_windows.resolve(windows, "story_published", "x").window_minutes == 10
    assert edit_windows.resolve(windows, "story_published", "linkedin").window_minutes == 20
    assert edit_windows.resolve(windows, "roundup", "x").window_minutes == 30
    assert edit_windows.resolve(windows, "roundup", "email").window_minutes == 60
    for bad in ([{"windowMinutes": 5, "lockLeadMinutes": 6}], [{"windowMinutes": -1}], [{"windowMinutes": 5}, {"windowMinutes": 6}], {"windowMinutes": 5}, [{"windowMinutes": 5, "colour": "red"}]):
        with pytest.raises(AnnouncementError):
            edit_windows.validate(bad)
    release, plans = edit_windows.apply(settings, "story_published", [Plan("x", "h", "soft", "p", "Hi"), Plan("email", "h", "soft", "p", "Hi", lock_at="2026-11-16T14:03:00Z")], now=NOW)
    assert release == "2026-11-16T14:10:00Z" and [(p.release_at, p.lock_at) for p in plans] == [("2026-11-16T14:10:00Z", "2026-11-16T14:08:00Z"), ("2026-11-16T14:20:00Z", "2026-11-16T14:03:00Z")]


def test_a_person_after_the_send_saves_a_preferred_version_and_a_machine_is_refused():
    from papyrus_content.announcements.delivery_versions import NotEditable, PREFERRED
    from papyrus_content.announcements.records import SENT

    deliveries, versions, row_id = make(approval="none")
    deliveries._change(deliveries.get(row_id), {"state": SENT}, by="worker", note="sent", now=NOW)
    saved = versions.save(row_id, replaces=1, text="How it should have read.", by="ellie", preferred_only=True)
    assert saved.status == PREFERRED and saved.row["preferredVersion"] == 2 and saved.row["state"] == SENT
    with pytest.raises(NotEditable):
        versions.save(row_id, replaces=2, text="A machine idea.", by="announce", owner=dt.MACHINE)


def test_preferred_only_refuses_a_delivery_that_has_not_gone_out():
    from papyrus_content.announcements.delivery_versions import NotEditable

    _, versions, row_id = make()
    with pytest.raises(NotEditable):
        versions.save(row_id, replaces=1, text="Too early.", by="ellie", preferred_only=True)
