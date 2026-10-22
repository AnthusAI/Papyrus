"""Votes on any subject type and flags with a reason: reader-actions against moto tables."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reader_fixtures import ReaderBackend, reader_handler, subject_for  # noqa: E402

ALICE = subject_for("alice")
BOB = subject_for("bob")
PROPOSAL = {"type": "proposal", "id": "prop-1"}
STORY = {"type": "story", "id": "weekly-2026-42"}
TYPES = ("item", "submission", "story", "proposal", "concept")


def backend(types=TYPES) -> ReaderBackend:
    return ReaderBackend(subject_types=tuple(types))


def vote(b: ReaderBackend, who: str, subject, value) -> dict:
    return b.call(who, "vote", {"subject": subject, "value": value})


class SubjectKeyTests(unittest.TestCase):
    def test_items_and_submissions_keep_their_bare_id_and_the_rest_are_prefixed(self) -> None:
        self.assertEqual(reader_handler.subject_key("item", "item-one"), "item-one")
        self.assertEqual(reader_handler.subject_key("submission", "sub-" + "a" * 24), "sub-" + "a" * 24)
        self.assertEqual(reader_handler.subject_key("proposal", "prop-1"), "proposal:prop-1")

    def test_a_bare_string_is_read_by_its_shape(self) -> None:
        self.assertEqual(reader_handler.legacy_subject_type("sub-" + "a" * 24), "submission")
        self.assertEqual(reader_handler.legacy_subject_type("item-one"), "item")


class TypedVoteTests(unittest.TestCase):
    def test_a_signed_in_reader_can_up_and_downvote_a_proposal_and_a_story(self) -> None:
        with backend() as b:
            self.assertEqual(vote(b, ALICE, PROPOSAL, 1)["statusCode"], 200)
            self.assertEqual(vote(b, BOB, STORY, -1)["statusCode"], 200)
            rows = {row["subjectKey"]: row for row in b.votes()}
            self.assertEqual(rows["proposal:prop-1"]["value"], 1)
            self.assertEqual(rows["proposal:prop-1"]["subjectType"], "proposal")
            self.assertEqual(rows["story:weekly-2026-42"]["value"], -1)

    def test_switching_replaces_the_vote_and_removing_deletes_it(self) -> None:
        with backend() as b:
            vote(b, ALICE, PROPOSAL, 1)
            vote(b, ALICE, PROPOSAL, -1)
            self.assertEqual([row["value"] for row in b.votes()], [-1])
            self.assertEqual(vote(b, ALICE, PROPOSAL, None)["statusCode"], 200)
            self.assertEqual(b.votes(), [])

    def test_one_vote_per_reader_and_subject_but_the_same_id_under_two_types_is_two_subjects(self) -> None:
        with backend() as b:
            for _ in range(3):
                vote(b, ALICE, PROPOSAL, 1)
            vote(b, ALICE, {"type": "concept", "id": "prop-1"}, 1)
            self.assertEqual(len(b.votes()), 2)

    def test_a_type_the_publication_has_not_enabled_is_refused(self) -> None:
        with backend(("item",)) as b:
            answer = vote(b, ALICE, PROPOSAL, 1)
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, "unknown_subject_type"))
            self.assertEqual(b.votes(), [])

    def test_a_type_that_does_not_exist_is_refused_even_when_enabled_by_mistake(self) -> None:
        with backend(("item", "person")) as b:
            answer = vote(b, ALICE, {"type": "person", "id": "x"}, 1)
            self.assertEqual(answer["body"]["error"], "unknown_subject_type")

    def test_an_item_vote_through_the_new_shape_needs_a_published_item(self) -> None:
        with backend() as b:
            self.assertEqual(vote(b, ALICE, {"type": "item", "id": "item-one"}, -1)["statusCode"], 200)
            answer = vote(b, ALICE, {"type": "item", "id": "not-published"}, 1)
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (404, "unknown_subject"))
            self.assertEqual([row["subjectKey"] for row in b.votes()], ["item-one"])

    def test_a_new_item_vote_and_an_old_one_are_the_same_row(self) -> None:
        with backend() as b:
            b.call(ALICE, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            vote(b, ALICE, {"type": "item", "id": "item-one"}, -1)
            rows = b.votes()
            self.assertEqual([(row["subjectKey"], row["dimension"], row["value"]) for row in rows], [("item-one", "up", -1)])

    def test_malformed_votes_are_refused(self) -> None:
        with backend() as b:
            for subject, value in [
                (PROPOSAL, 0), (PROPOSAL, 2), (PROPOSAL, True), (PROPOSAL, "1"),
                ({"type": "proposal"}, 1), ({"type": "proposal", "id": "a b"}, 1), ({"type": "proposal", "id": ""}, 1),
                ({"type": "proposal", "id": "x", "extra": 1}, 1), ({"type": 7, "id": "x"}, 1),
            ]:
                answer = vote(b, ALICE, subject, value)
                self.assertEqual(answer["statusCode"], 422, (subject, value))
            answer = b.call(ALICE, "vote", {"subject": PROPOSAL, "value": 1, "dimension": "used-it"})
            self.assertEqual(answer["statusCode"], 422)
            self.assertEqual(b.votes(), [])

    def test_the_reply_and_the_stored_row_carry_no_identity(self) -> None:
        with backend() as b:
            answer = vote(b, ALICE, PROPOSAL, 1)
            self.assertNotIn(ALICE, json.dumps(answer))
            row = b.votes()[0]
            self.assertNotIn(ALICE, json.dumps(row, default=str))
            self.assertNotIn("siteSubject", row)

    def test_a_banned_reader_cannot_vote_and_a_limited_reader_cannot_vote(self) -> None:
        with backend() as b:
            b.call(ALICE, "me")
            b.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "banned"})
            self.assertEqual(vote(b, ALICE, PROPOSAL, 1)["body"]["error"], "reader_banned")
            b.table("profile").update_item(Key={"id": ALICE}, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "state"}, ExpressionAttributeValues={":s": "limited"})
            self.assertEqual(vote(b, ALICE, PROPOSAL, 1)["body"]["error"], "reader_limited")

    def test_votes_share_the_hourly_allowance(self) -> None:
        with ReaderBackend(subject_types=TYPES, actions_per_hour=3) as b:
            answers = [vote(b, ALICE, {"type": "proposal", "id": f"p{n}"}, 1)["statusCode"] for n in range(3)]
            self.assertEqual(answers, [200, 429, 429])

    def test_a_vote_schedules_the_snapshot(self) -> None:
        with backend() as b:
            vote(b, ALICE, PROPOSAL, 1)
            self.assertEqual(len(b.schedules()), 1)


class ReaderStateTests(unittest.TestCase):
    def test_me_answers_the_readers_own_vote_by_subject_key(self) -> None:
        with backend() as b:
            vote(b, ALICE, PROPOSAL, -1)
            vote(b, ALICE, {"type": "item", "id": "item-one"}, 1)
            state = b.call(ALICE, "me", {"subjects": ["proposal:prop-1", {"type": "item", "id": "item-one"}, {"type": "story", "id": "none"}]})["body"]
            self.assertEqual(state["votes"], {"proposal:prop-1": {"up": -1}, "item-one": {"up": 1}})

    def test_me_refuses_a_subject_of_a_disabled_type(self) -> None:
        with backend(("item",)) as b:
            answer = b.call(ALICE, "me", {"subjects": [PROPOSAL]})
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (422, "invalid_subjects"))


class FlagTests(unittest.TestCase):
    def flag(self, b, who, **payload) -> dict:
        return b.call(who, "flag", {"subject": PROPOSAL, **payload})

    def test_wrong_needs_a_reason(self) -> None:
        with backend() as b:
            answer = self.flag(b, ALICE, kind="wrong", reason="The number is off by a factor of ten.")
            self.assertEqual(answer["statusCode"], 200)
            row = b.flags()[0]
            self.assertEqual((row["subjectKey"], row["subjectType"], row["kind"]), ("proposal:prop-1", "proposal", "wrong"))
            self.assertEqual(row["reason"], "The number is off by a factor of ten.")
            self.assertNotIn(ALICE, json.dumps(row, default=str))
            for reason in (None, "", "   ", 7, "x" * 501, "bad\x07text", "write to a@example.com"):
                self.assertEqual(self.flag(b, ALICE, kind="wrong", reason=reason)["body"]["error"], "invalid_reason", reason)

    def test_belongs_under_needs_a_target_subject(self) -> None:
        with backend() as b:
            ok = self.flag(b, ALICE, kind="belongs_under", reason="It is about hardware.", target={"type": "concept", "id": "hardware"})
            self.assertEqual(ok["statusCode"], 200)
            self.assertEqual(b.flags()[0]["targetKey"], "concept:hardware")
            for target in (None, "hardware", {"type": "concept"}, {"type": "person", "id": "x"}, PROPOSAL):
                answer = self.flag(b, BOB, kind="belongs_under", reason="r", target=target)
                self.assertEqual(answer["statusCode"], 422, target)
            self.assertEqual(self.flag(b, BOB, kind="belongs_under", reason="r", target={"type": "concept", "id": "x"}, name="n")["statusCode"], 422)

    def test_better_name_needs_a_suggested_name(self) -> None:
        with backend() as b:
            ok = self.flag(b, ALICE, kind="better_name", reason="Clearer.", name="  Edge inference ")
            self.assertEqual(ok["statusCode"], 200)
            self.assertEqual(b.flags()[0]["suggestedName"], "Edge inference")
            for name in (None, "", " ", "n" * 121, "a@example.com"):
                self.assertEqual(self.flag(b, BOB, kind="better_name", reason="r", name=name)["statusCode"], 422, name)

    def test_wrong_takes_no_target_or_name(self) -> None:
        with backend() as b:
            self.assertEqual(self.flag(b, ALICE, kind="wrong", reason="r", name="x")["statusCode"], 422)

    def test_unknown_kind_and_unknown_fields_are_refused(self) -> None:
        with backend() as b:
            self.assertEqual(self.flag(b, ALICE, kind="spam", reason="r")["body"]["error"], "invalid_flag_kind")
            self.assertEqual(self.flag(b, ALICE, kind="wrong", reason="r", extra=1)["body"]["error"], "invalid_flag")

    def test_one_flag_per_reader_subject_and_kind_and_flags_are_not_votes(self) -> None:
        with backend() as b:
            self.flag(b, ALICE, kind="wrong", reason="first")
            self.flag(b, ALICE, kind="wrong", reason="second")
            self.flag(b, ALICE, kind="better_name", reason="r", name="N")
            self.assertEqual(sorted((row["kind"], row["reason"]) for row in b.flags()), [("better_name", "r"), ("wrong", "second")])
            self.assertEqual(b.votes(), [])

    def test_a_flag_on_a_disabled_type_or_an_unpublished_item_is_refused(self) -> None:
        with backend(("item",)) as b:
            self.assertEqual(b.call(ALICE, "flag", {"subject": PROPOSAL, "kind": "wrong", "reason": "r"})["body"]["error"], "unknown_subject_type")
            answer = b.call(ALICE, "flag", {"subject": {"type": "item", "id": "nope"}, "kind": "wrong", "reason": "r"})
            self.assertEqual((answer["statusCode"], answer["body"]["error"]), (404, "unknown_subject"))
            self.assertEqual(b.flags(), [])

    def test_a_flag_is_rate_limited_and_schedules_the_snapshot(self) -> None:
        with ReaderBackend(subject_types=TYPES, actions_per_hour=1) as b:
            self.assertEqual(self.flag(b, ALICE, kind="wrong", reason="r")["statusCode"], 200)
            self.assertEqual(self.flag(b, ALICE, kind="better_name", reason="r", name="n")["statusCode"], 429)
            self.assertEqual(len(b.schedules()), 1)


if __name__ == "__main__":
    unittest.main()
