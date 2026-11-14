"""The editor tier of proposals: pin, hold, override, batch vote exclusion, limited and spam accounts, and the needs-a-look list."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering import proposal_votes  # noqa: E402
from reader_fixtures import ReaderBackend, operator_identity, proposal_handler, run_snapshot, subject_for  # noqa: E402

rules = proposal_handler.proposal_rules
BODY = "# Name the agents cluster\n\nThe cluster mixes tool use with planning.\n"
TYPES = ("item", "proposal")


def file_one(backend: ReaderBackend, **overrides) -> str:
    answer = backend.proposal_call("fileProposal", {"kind": "story_draft", "title": "Agents are eating the board", "body": BODY, **overrides})
    assert answer["status"] == "ok", answer
    return answer["id"]


def move(backend: ReaderBackend, proposal: str, state: str, **extra) -> dict:
    return backend.proposal_call("transitionProposal", {"proposalId": proposal, "state": state, **extra})


def edit(backend: ReaderBackend, proposal: str, action: str, **extra) -> dict:
    return backend.proposal_call("editProposal", {"proposalId": proposal, "action": action, **extra})


def row_of(backend: ReaderBackend, proposal: str) -> dict:
    return backend.table("proposal").get_item(Key={"id": proposal})["Item"]


def to_review(backend: ReaderBackend, proposal: str) -> None:
    assert move(backend, proposal, "in_steering")["status"] == "ok"
    assert move(backend, proposal, "editor_review")["status"] == "ok"


def sign_up(backend: ReaderBackend, prefix: str, count: int) -> None:
    """Create ``count`` reader profiles now (a handle is the cheapest action that makes one)."""
    for index in range(count):
        assert backend.call(subject_for(f"{prefix}{index}"), "handle", {"handle": f"{prefix}-{index}"})["statusCode"] == 200


def cast(backend: ReaderBackend, prefix: str, index: int, proposal: str, value: int) -> None:
    answer = backend.call(subject_for(f"{prefix}{index}"), "vote", {"subject": {"type": "proposal", "id": proposal}, "value": value})
    assert answer["statusCode"] == 200, answer


def reader_id(backend: ReaderBackend, prefix: str, index: int) -> str:
    return backend.table("profile").get_item(Key={"id": subject_for(f"{prefix}{index}")})["Item"]["readerId"]


def seasoned_voters(backend: ReaderBackend, prefix: str, count: int) -> None:
    """Readers whose accounts are three days old by the time the clock is moved on."""
    sign_up(backend, prefix, count)
    backend.age_everyone()


class Published:
    """Runs the snapshot into a temporary directory and reads the public proposal files back."""

    def __init__(self, backend: ReaderBackend) -> None:
        self.backend = backend
        self.directory = tempfile.TemporaryDirectory()
        self.writer = LocalDirectoryWriter(Path(self.directory.name))

    def close(self) -> None:
        self.directory.cleanup()

    def run(self) -> dict:
        self.backend.now += 120
        run_snapshot(self.backend, self.writer, subject_types=TYPES)
        return json.loads(self.writer.get("_data/proposals/index.json"))["proposals"][0]

    def everything(self) -> str:
        return "".join(entry.key + (self.writer.get(entry.key) or b"").decode() for entry in self.writer.list())


class EditorActionTests(unittest.TestCase):
    def test_pin_and_unpin_show_in_the_public_entry_and_are_logged_privately(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            self.assertFalse(published.run()["pinned"])
            self.assertEqual(edit(backend, identifier, "pin")["status"], "ok")
            self.assertTrue(published.run()["pinned"])
            self.assertEqual(edit(backend, identifier, "pin")["error"], "already_pinned")
            self.assertEqual(edit(backend, identifier, "unpin")["status"], "ok")
            self.assertEqual(edit(backend, identifier, "unpin")["error"], "not_pinned")
            self.assertFalse(published.run()["pinned"])
            log = json.loads(row_of(backend, identifier)["editorLog"])
            self.assertEqual([entry["action"] for entry in log], ["pin", "unpin"])
            self.assertNotIn("editorLog", published.everything())
            self.assertNotIn("staff-sub-1", published.everything())

    def test_a_proposal_on_hold_cannot_move_until_it_is_released(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            self.assertEqual(edit(backend, identifier, "hold")["status"], "ok")
            self.assertEqual(edit(backend, identifier, "hold")["error"], "already_held")
            self.assertEqual(move(backend, identifier, "in_steering")["error"], "proposal_held")
            self.assertEqual(row_of(backend, identifier)["state"], "draft")
            self.assertTrue(published.run()["held"])
            self.assertEqual(edit(backend, identifier, "release")["status"], "ok")
            self.assertEqual(edit(backend, identifier, "release")["error"], "not_held")
            self.assertEqual(move(backend, identifier, "in_steering")["status"], "ok")
            self.assertFalse(published.run()["held"])

    def test_a_decided_proposal_cannot_be_put_on_hold_but_can_be_pinned(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            identifier = file_one(backend)
            to_review(backend, identifier)
            self.assertEqual(move(backend, identifier, "approved", reason="Clear.")["status"], "ok")
            self.assertEqual(edit(backend, identifier, "hold")["error"], "proposal_decided")
            self.assertEqual(edit(backend, identifier, "pin")["status"], "ok")

    def test_an_override_is_stored_with_its_public_reason_and_the_community_result_stays(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            seasoned_voters(backend, "old", 3)
            for index in range(3):
                cast(backend, "old", index, identifier, 1)
            to_review(backend, identifier)
            before = published.run()
            self.assertEqual((before["communityResult"]["up"], before["override"]), (3, None))
            self.assertEqual(move(backend, identifier, "overridden_by_editor", result="declined")["error"], "reason_required")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", reason="Coordinated.")["error"], "result_required")
            self.assertEqual(move(backend, identifier, "overridden_by_editor", reason="Sources are weak.", result="declined")["status"], "ok")
            stored = json.loads(row_of(backend, identifier)["override"])
            self.assertEqual((stored["result"], stored["reason"]), ("declined", "Sources are weak."))
            after = published.run()
            self.assertEqual((after["override"]["result"], after["override"]["reason"], after["override"]["by"]), ("declined", "Sources are weak.", "Editor"))
            self.assertEqual(after["communityResult"]["up"], 3, "the community result is still shown beside the override")
            self.assertEqual(after["communityResult"]["at"], before["communityResult"]["at"])

    def test_an_override_stored_before_the_field_existed_is_read_from_the_history(self) -> None:
        history = [{"from": "editor_review", "to": "overridden_by_editor", "by": "staff", "actor": "s", "reason": "Old.", "at": "2026-10-22T09:00:00Z", "result": "approved"}]
        from papyrus_content.reader_steering import proposals as public

        entry = public.override_of({"state": "overridden_by_editor", "history": json.dumps(history)})
        self.assertEqual(entry, {"result": "approved", "reason": "Old.", "by": "Editor", "at": "2026-10-22T09:00:00Z"})
        self.assertIsNone(public.override_of({"state": "approved", "history": json.dumps(history)}))

    def test_only_editors_and_admins_may_edit_and_an_operator_is_refused(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            identifier = file_one(backend)
            for groups in ((), ("reader",), ("viewer",)):
                self.assertEqual(backend.proposal_call("editProposal", {"proposalId": identifier, "action": "pin"}, groups=groups)["error"], "not_staff")
            anonymous = backend.appsync("editProposal", {"proposalId": identifier, "action": "pin"}, {})
            self.assertEqual(anonymous["error"], "not_staff")
            for action, extra in (("pin", {}), ("hold", {}), ("exclude_votes", {"rule": "new-accounts-24h"})):
                answer = backend.operator_proposal_call("editProposal", {"proposalId": identifier, "action": action, **extra})
                self.assertEqual((answer["status"], answer["error"]), ("refused", "operator_not_allowed"), action)
            other_account = backend.operator_proposal_call("editProposal", {"proposalId": identifier, "action": "pin"}, identity=operator_identity(accountId="999999999999"))
            self.assertEqual(other_account["status"], "refused")
            row = row_of(backend, identifier)
            self.assertFalse(row.get("pinned"))
            self.assertNotIn("editorLog", row)
            self.assertEqual(backend.proposal_call("editProposal", {"proposalId": identifier, "action": "pin"}, groups=("admin",))["status"], "ok")

    def test_bad_requests_are_refused(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            identifier = file_one(backend)
            cases = [
                ({"proposalId": "nope", "action": "pin"}, "invalid_proposal"),
                ({"proposalId": "prop-" + "0" * 32, "action": "pin"}, "not_found"),
                ({"proposalId": identifier, "action": "shred"}, "invalid_action"),
                ({"proposalId": identifier, "action": "exclude_votes"}, "invalid_rule"),
                ({"proposalId": identifier, "action": "exclude_votes", "rule": "everyone"}, "invalid_rule"),
                ({"proposalId": identifier, "action": "undo_exclusion"}, "invalid_exclusion"),
                ({"proposalId": identifier, "action": "undo_exclusion", "exclusionId": "exc-" + "0" * 12}, "unknown_exclusion"),
            ]
            for arguments, error in cases:
                with self.subTest(error=error, arguments=arguments):
                    self.assertEqual(backend.proposal_call("editProposal", arguments)["error"], error)

    def test_the_direct_resolver_shape_reaches_edit_proposal_too(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            identifier = file_one(backend)
            answer = backend.proposal_call("editProposal", {"proposalId": identifier, "action": "pin"}, shape="info")
            self.assertEqual(answer["status"], "ok", answer)

    def test_two_edits_from_the_same_view_do_not_both_land(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            identifier = file_one(backend)
            seen = row_of(backend, identifier)
            first = rules.edit_plan(seen, "pin", actor_sub="a", now_iso="2026-10-22T10:00:00Z")
            second = rules.edit_plan(seen, "hold", actor_sub="b", now_iso="2026-10-22T10:00:01Z")
            self.assertTrue(backend.proposal_store.change_proposal(identifier, first, "draft", "2026-10-22T10:00:00Z", expected_updated_at=seen["updatedAt"]))
            self.assertFalse(backend.proposal_store.change_proposal(identifier, second, "draft", "2026-10-22T10:00:01Z", expected_updated_at=seen["updatedAt"]))
            row = row_of(backend, identifier)
            self.assertEqual((row["pinned"], row.get("held")), (True, None))


class VoteExclusionTests(unittest.TestCase):
    def scene(self, backend: ReaderBackend, published: Published) -> str:
        """Three seasoned readers up and four brand-new accounts down on one proposal in steering."""
        identifier = file_one(backend)
        move(backend, identifier, "in_steering")
        seasoned_voters(backend, "old", 3)
        sign_up(backend, "new", 4)
        for index in range(3):
            cast(backend, "old", index, identifier, 1)
        for index in range(4):
            cast(backend, "new", index, identifier, -1)
        return identifier

    def test_excluding_new_accounts_removes_their_votes_from_the_tally_and_says_so_publicly(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = self.scene(backend, published)
            before = published.run()
            self.assertEqual((before["votes"]["up"], before["votes"]["down"]), (3, 4))
            self.assertEqual(before["excluded"], {"votes": 0, "rules": [], "note": None})
            receipt = edit(backend, identifier, "exclude_votes", rule="new-accounts-24h")
            self.assertEqual(receipt["status"], "ok")
            self.assertRegex(receipt["id"], r"exc-[0-9a-f]{12}")
            after = published.run()
            self.assertEqual((after["votes"]["up"], after["votes"]["down"], after["votes"]["net"]), (3, 0, 3.0))
            self.assertEqual(after["excluded"]["votes"], 4)
            self.assertEqual(after["excluded"]["note"], "Excluded 4 votes from accounts under 24 h")
            rule = after["excluded"]["rules"][0]
            self.assertEqual((rule["id"], rule["rule"], rule["label"], rule["votes"]), (receipt["id"], "new-accounts-24h", "accounts under 24 h", 4))
            self.assertNotIn("staff-sub-1", published.everything())
            self.assertNotIn("actor", json.dumps(after))

    def test_undoing_the_exclusion_counts_the_votes_again_and_the_note_goes(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = self.scene(backend, published)
            receipt = edit(backend, identifier, "exclude_votes", rule="new-accounts-24h")
            published.run()
            self.assertEqual(edit(backend, identifier, "undo_exclusion", exclusionId=receipt["id"])["status"], "ok")
            self.assertEqual(edit(backend, identifier, "undo_exclusion", exclusionId=receipt["id"])["error"], "already_undone")
            restored = published.run()
            self.assertEqual((restored["votes"]["up"], restored["votes"]["down"]), (3, 4))
            self.assertEqual(restored["excluded"], {"votes": 0, "rules": [], "note": None})
            kept = json.loads(row_of(backend, identifier)["exclusions"])
            self.assertEqual(len(kept), 1, "the undone exclusion stays on the private record")
            self.assertTrue(kept[0]["undoneAt"])

    def test_one_vote_reads_in_the_singular(self) -> None:
        self.assertEqual(proposal_votes.public_exclusions({"exclusions": json.dumps([{"id": "exc-aaaaaaaaaaaa", "rule": "new-accounts-24h", "at": "t"}])}, {"exc-aaaaaaaaaaaa": 1})["note"], "Excluded 1 vote from accounts under 24 h")

    def test_the_batch_covers_the_votes_already_cast_not_later_ones(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = self.scene(backend, published)
            edit(backend, identifier, "exclude_votes", rule="new-accounts-24h")
            backend.now += 60
            sign_up(backend, "late", 2)
            for index in range(2):
                cast(backend, "late", index, identifier, -1)
            entry = published.run()
            self.assertEqual((entry["votes"]["up"], entry["votes"]["down"]), (3, 2))
            self.assertEqual(entry["excluded"]["votes"], 4)

    def test_the_frozen_community_result_is_fixed_again_without_the_excluded_votes(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = self.scene(backend, published)
            move(backend, identifier, "editor_review")
            self.assertEqual(published.run()["communityResult"]["down"], 4)
            receipt = edit(backend, identifier, "exclude_votes", rule="new-accounts-24h")
            self.assertNotIn("communityResult", row_of(backend, identifier))
            self.assertEqual(published.run()["communityResult"]["down"], 0)
            edit(backend, identifier, "undo_exclusion", exclusionId=receipt["id"])
            self.assertEqual(published.run()["communityResult"]["down"], 4)

    def test_votes_of_limited_and_banned_accounts_are_excluded_and_returning_them_counts_again(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            seasoned_voters(backend, "old", 4)
            for index in range(4):
                cast(backend, "old", index, identifier, 1)
            self.assertEqual(published.run()["votes"]["up"], 4)
            self.assertEqual(backend.staff_call("limit", "reader", reader_id(backend, "old", 0))["status"], "ok")
            self.assertEqual(backend.staff_call("ban", "reader", reader_id(backend, "old", 1), reason="Spam.")["status"], "ok")
            entry = published.run()
            self.assertEqual(entry["votes"]["up"], 2)
            self.assertEqual(entry["excluded"]["note"], "Excluded 2 votes from limited or spam accounts")
            self.assertEqual(entry["excluded"]["rules"], [{"id": None, "rule": "limited-or-spam", "label": "limited or spam accounts", "votes": 2, "at": None}])
            self.assertEqual(backend.staff_call("unban", "reader", reader_id(backend, "old", 1))["status"], "ok")
            self.assertEqual(published.run()["votes"]["up"], 3)

    def test_a_limited_account_does_not_change_the_tally_of_an_item(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            sign_up(backend, "old", 1)
            backend.age_everyone()
            backend.call(subject_for("old0"), "vote", {"subject": {"type": "item", "id": "item-one"}, "value": 1})
            backend.staff_call("limit", "reader", reader_id(backend, "old", 0))
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            writer = LocalDirectoryWriter(Path(directory.name))
            run_snapshot(backend, writer, subject_types=TYPES)
            items = json.loads(writer.get("_data/reader/items.json"))["items"]
            self.assertEqual(items["item-one"]["up"], 1, "the exclusion is for proposals only")

    def test_an_unknown_age_is_not_held_against_a_vote(self) -> None:
        proposal = {"id": "prop-1", "exclusions": json.dumps([{"id": "exc-aaaaaaaaaaaa", "rule": "new-accounts-24h", "at": "2026-10-22T10:00:00Z"}])}
        votes = [{"subjectKey": "proposal:prop-1", "readerId": "r", "dimension": "up", "value": 1, "createdAt": "2026-10-22T09:00:00Z"}]
        kept, excluded = proposal_votes.partition_votes(votes, [], [proposal], lambda vote: None)
        self.assertEqual((len(kept), excluded), (1, {}))
        kept, excluded = proposal_votes.partition_votes(votes, [], [proposal], lambda vote: 2.0)
        self.assertEqual((kept, excluded), ([], {"prop-1": {"exc-aaaaaaaaaaaa": 1}}))
        kept, _ = proposal_votes.partition_votes(votes, [], [], lambda vote: 2.0)
        self.assertEqual(len(kept), 1, "a vote on a proposal nobody passed in is left alone")


class NeedsALookTests(unittest.TestCase):
    def attention(self, backend: ReaderBackend, identifier: str) -> list[dict]:
        row = row_of(backend, identifier)
        return json.loads(row["needsLook"])["reasons"] if row.get("needsLook") else []

    def test_a_spike_of_votes_in_an_hour_is_listed_with_its_reason(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            move(backend, identifier, "in_steering")
            seasoned_voters(backend, "old", 12)
            for index in range(12):
                cast(backend, "old", index, identifier, 1)
            published.run()
            reasons = self.attention(backend, identifier)
            self.assertEqual([reason["code"] for reason in reasons], ["vote_spike"])
            self.assertEqual(reasons[0]["label"], "Vote spike")
            self.assertIn("12 votes in the last hour", reasons[0]["detail"])

    def test_votes_spread_over_a_day_are_not_a_spike(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            move(backend, identifier, "in_steering")
            seasoned_voters(backend, "old", 12)
            for index in range(12):
                cast(backend, "old", index, identifier, 1)
                backend.now += 3600
            published.run()
            self.assertEqual(self.attention(backend, identifier), [])

    def test_a_surge_from_new_accounts_is_listed_and_excluding_them_clears_it(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            move(backend, identifier, "in_steering")
            seasoned_voters(backend, "old", 3)
            sign_up(backend, "new", 6)
            for index in range(3):
                cast(backend, "old", index, identifier, 1)
            for index in range(6):
                cast(backend, "new", index, identifier, 1)
            published.run()
            reasons = self.attention(backend, identifier)
            self.assertEqual([reason["code"] for reason in reasons], ["new_account_surge"])
            self.assertIn("6 of 9 votes", reasons[0]["detail"])
            edit(backend, identifier, "exclude_votes", rule="new-accounts-24h")
            published.run()
            self.assertEqual(self.attention(backend, identifier), [])
            self.assertNotIn("needsLook", row_of(backend, identifier))

    def test_a_community_against_the_ai_that_proposed_it_is_listed(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            move(backend, identifier, "in_steering")
            seasoned_voters(backend, "old", 6)
            cast(backend, "old", 0, identifier, 1)
            for index in range(1, 6):
                cast(backend, "old", index, identifier, -1)
            published.run()
            reasons = self.attention(backend, identifier)
            self.assertEqual([reason["code"] for reason in reasons], ["community_ai_disagreement"])
            self.assertEqual(reasons[0]["detail"], "The AI proposed it; readers voted 1 up and 5 down")

    def test_a_decided_proposal_is_not_listed_and_nothing_editor_only_is_public(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            published = Published(backend)
            self.addCleanup(published.close)
            identifier = file_one(backend)
            move(backend, identifier, "in_steering")
            seasoned_voters(backend, "old", 12)
            for index in range(12):
                cast(backend, "old", index, identifier, 1)
            published.run()
            self.assertTrue(self.attention(backend, identifier))
            text = published.everything()
            for private in ("needsLook", "vote_spike", "reasons", "editorLog", "exclusions"):
                self.assertNotIn(private, text)
            move(backend, identifier, "editor_review")
            move(backend, identifier, "approved", reason="Fine.")
            published.run()
            self.assertEqual(self.attention(backend, identifier), [])

    def test_the_same_rows_and_clock_give_the_same_reasons(self) -> None:
        row = {"id": "prop-1", "state": "in_steering", "proposer": "ai"}
        votes = [{"subjectKey": "proposal:prop-1", "readerId": f"r{index}", "dimension": "up", "value": -1, "createdAt": "2026-10-22T09:00:00Z"} for index in range(6)]
        first = proposal_votes.needs_a_look(row, votes, lambda vote: 100.0, 1_790_000_000.0)
        again = proposal_votes.needs_a_look(row, list(reversed(votes)), lambda vote: 100.0, 1_790_000_000.0)
        self.assertEqual(first, again)
        self.assertEqual([reason["code"] for reason in first], ["community_ai_disagreement"])


if __name__ == "__main__":
    unittest.main()
