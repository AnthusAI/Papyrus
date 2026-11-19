"""The living issue's contribution rules (``living_issue.py``): disjoint blocks, pins, exclusions, the floor, approval."""

from __future__ import annotations

import pytest

from papyrus_content.newsletter import living_issue as li

AT = "2027-01-13T10:00:00Z"


def fresh() -> li.Issue:
    return li.Issue("weekly", "2027-02")


def with_entries(*ids: str, section: str | None = "tools") -> li.Issue:
    issue = li.insert(fresh(), base=1, actor="inserter", found=[(item, section, "reached three stars") for item in ids], at=AT)
    return issue


def test_the_inserter_adds_machine_entries_with_actor_and_reason_and_touches_no_human_field():
    issue = li.edit_field(fresh(), base=1, actor="Ed", human=True, name="intro", value="Hello.")
    after = li.insert(issue, base=2, actor="inserter", found=[("a", "tools", "reached three stars")], at=AT)
    assert after.fields == issue.fields and after.touched == issue.touched
    assert [(e.id, e.added_by, e.reason) for e in after.entries] == [("a", "inserter", "reached three stars")]
    assert after.log[-1] == li.Version(3, "inserter", False, ("entries",))


def test_an_agent_and_a_person_on_disjoint_blocks_both_land():
    base = with_entries("a")
    human = li.edit_field(base, base=base.version, actor="Ed", human=True, name="intro", value="Hello.")
    both = li.insert(human, base=base.version, actor="inserter", found=[("b", "tools", "x")], at=AT)   # the agent started from the older version
    assert both.fields["intro"] == "Hello." and [e.id for e in both.entries] == ["a", "b"]
    assert [v.actor for v in both.log[-2:]] == ["Ed", "inserter"]


def test_two_writers_of_the_same_field_the_second_is_told_and_nothing_is_overwritten():
    base = fresh()
    first = li.edit_field(base, base=1, actor="Ann", human=True, name="intro", value="Ann's words")
    with pytest.raises(li.Conflict) as caught:
        li.edit_field(first, base=1, actor="Bo", human=True, name="intro", value="Bo's words")
    assert caught.value.current == "Ann's words" and first.fields["intro"] == "Ann's words"


def test_an_agent_cannot_overwrite_a_field_a_person_touched_but_may_write_an_untouched_one():
    issue = li.edit_field(fresh(), base=1, actor="Ed", human=True, name="intro", value="Mine")
    with pytest.raises(li.NeedsSuggestion):
        li.edit_field(issue, base=issue.version, actor="agent", human=False, name="intro", value="Better")
    written = li.edit_field(issue, base=issue.version, actor="agent", human=False, name="subject", value="Subject")
    assert written.fields["subject"] == "Subject" and "subject" not in written.touched


def test_a_person_editing_a_machine_entry_pins_it():
    issue = with_entries("a", "b")
    pinned = li.edit_entry(issue, base=issue.version, actor="Ed", item_id="a", copy="My blurb")
    entry = pinned.entry("a")
    assert entry.pinned and entry.copy == "My blurb" and not pinned.entry("b").pinned
    assert li.edit_entry(pinned, base=pinned.version, actor="Ed", item_id="b", keep=True).entry("b").pinned


def test_a_pin_moves_an_entry_to_its_position():
    issue = with_entries("a", "b", "c")
    pinned = li.edit_entry(issue, base=issue.version, actor="Ed", item_id="c", position=0)
    assert [e.id for e in li.ordered(pinned)] == ["c", "a", "b"]


def test_removing_needs_a_reason_and_the_inserter_never_adds_it_back_until_restored():
    issue = with_entries("a", "b")
    with pytest.raises(li.NotAllowed):
        li.remove_entry(issue, base=issue.version, actor="Ed", item_id="a", reason="  ", at=AT)
    removed = li.remove_entry(issue, base=issue.version, actor="Ed", item_id="a", reason="Off topic", at=AT)
    assert removed.entry("a") is None and removed.exclusions[0].reason == "Off topic" and removed.exclusions[0].by == "Ed"
    again = li.insert(removed, base=removed.version, actor="inserter", found=[("a", "tools", "x"), ("c", "tools", "x")], at=AT)
    assert [e.id for e in again.entries] == ["b", "c"]
    restored = li.restore_entry(again, base=again.version, actor="Ed", item_id="a", at=AT)
    assert restored.exclusions[0].restored_by == "Ed" and len(restored.exclusions) == 1   # nothing is deleted
    assert li.insert(restored, base=restored.version, actor="inserter", found=[("a", "tools", "x")], at=AT).entry("a") is not None


def test_the_floor_removes_even_a_pinned_entry_and_a_re_rating_brings_it_back_with_the_persons_copy():
    issue = with_entries("a", "b")
    pinned = li.edit_entry(issue, base=issue.version, actor="Ed", item_id="a", copy="My blurb")
    dropped = li.drop_below_floor(pinned, actor="inserter", stars={"a": 2, "b": 3}, floor=3)
    assert [e.id for e in dropped.entries] == ["b"] and dropped.removed[0][1] == li.BELOW_FLOOR and not dropped.exclusions
    back = li.insert(dropped, base=dropped.version, actor="inserter", found=[("a", "tools", "x")], at=AT)
    assert back.entry("a").copy == "My blurb" and not back.removed


def test_the_floor_leaves_a_person_excluded_entry_excluded():
    issue = li.remove_entry(with_entries("a"), base=2, actor="Ed", item_id="a", reason="No", at=AT)
    assert li.insert(issue, base=issue.version, actor="inserter", found=[("a", "tools", "x")], at=AT).entries == ()


def test_only_admins_approve_and_an_empty_issue_cannot_be_approved():
    issue = with_entries("a")
    with pytest.raises(li.NotAllowed, match="admin"):
        li.approve(issue, actor="Ed", admin=False, send_at=AT)
    with pytest.raises(li.NotAllowed, match="no entries"):
        li.approve(fresh(), actor="Ann", admin=True, send_at=AT)
    approved = li.approve(issue, actor="Ann", admin=True, send_at=AT)
    assert approved.status == "approved" and li.ready_to_send(approved)


def test_the_inserter_pauses_while_approved_and_resumes_after_an_edit_returns_it_to_draft():
    approved = li.approve(with_entries("a"), actor="Ann", admin=True, send_at=AT)
    assert li.insert(approved, base=approved.version, actor="inserter", found=[("b", "tools", "x")], at=AT) is approved
    edited = li.edit_field(approved, base=approved.version, actor="Ed", human=True, name="intro", value="New")
    assert edited.status == "draft" and edited.note == li.EDITED_AFTER_APPROVAL and not li.ready_to_send(edited)
    assert li.insert(edited, base=edited.version, actor="inserter", found=[("b", "tools", "x")], at=AT).entry("b") is not None


def test_a_below_floor_removal_after_approval_returns_the_issue_to_draft():
    approved = li.approve(with_entries("a", "b"), actor="Ann", admin=True, send_at=AT)
    dropped = li.drop_below_floor(approved, actor="inserter", stars={"a": 2, "b": 4}, floor=3)
    assert dropped.status == "draft" and dropped.note == li.EDITED_AFTER_APPROVAL and not li.ready_to_send(dropped)


def test_approval_covers_the_content_not_who_added_what():
    one = with_entries("a")
    other = li.insert(fresh(), base=1, actor="someone else", found=[("a", "tools", "other reason")], at="2027-02-01T00:00:00Z")
    assert li.fingerprint(one) == li.fingerprint(other)
    assert li.fingerprint(one) != li.fingerprint(li.edit_field(one, base=2, actor="Ed", human=True, name="intro", value="x"))
