"""The snapshot's output for votes and flags on any subject type: counts, net, score, and no identity."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter  # noqa: E402
from papyrus_content.reader_steering.snapshot import SnapshotSettings, build_snapshot, settings_from_mapping, vote_summary  # noqa: E402
from reader_fixtures import ReaderBackend, run_snapshot, subject_for  # noqa: E402
from reader_privacy import scan_files  # noqa: E402

TYPES = ("item", "submission", "story", "proposal", "concept")
PROPOSAL = {"type": "proposal", "id": "prop-1"}
NOW = 1_800_000_000.0
DAY = 24 * 3600


def run(backend: ReaderBackend, directory: str, ranking: dict | None = None, published=("item-one", "item-two")):
    writer = LocalDirectoryWriter(Path(directory))
    run_snapshot(backend, writer, subject_types=TYPES, ranking=ranking, published=published)
    return writer


def read(writer, key: str) -> dict:
    return json.loads(writer.get(key))


class SummaryTests(unittest.TestCase):
    settings = settings_from_mapping({"ranking": {"combination": "shrinkage"}, "limits": {"newAccountHours": 24}})
    created = "2027-01-01T00:00:00Z"

    def vote(self, reader: str, value: int, *, role: str = "reader", at_hours: float = 0.0) -> dict:
        return {"readerId": reader, "dimension": "up", "value": value, "voterRole": role, "createdAt": f"2027-01-0{1 + int(at_hours // 24)}T00:00:00Z"}

    def ages(self, *old: str, young: tuple[str, ...] = ()):
        profiles = [{"readerId": reader, "createdAt": "2026-12-01T00:00:00Z"} for reader in old]
        profiles += [{"readerId": reader, "createdAt": self.created} for reader in young]
        from papyrus_content.reader_steering.snapshot import account_ages

        return account_ages(profiles)

    def test_counts_and_net_of_old_accounts(self) -> None:
        votes = [self.vote("a", 1), self.vote("b", 1), self.vote("c", -1)]
        summary = vote_summary(votes, [], self.ages("a", "b", "c"), self.settings)
        self.assertEqual((summary["up"], summary["down"], summary["net"]), (2, 1, 1.0))

    def test_a_young_account_weighs_a_third_in_net_but_counts_whole_in_up_and_down(self) -> None:
        votes = [self.vote("a", 1), self.vote("kid", -1)]
        summary = vote_summary(votes, [], self.ages("a", young=("kid",)), self.settings)
        self.assertEqual((summary["up"], summary["down"]), (1, 1))
        self.assertAlmostEqual(summary["net"], 1 - 1 / 3, places=4)

    def test_an_editor_always_weighs_one(self) -> None:
        summary = vote_summary([self.vote("kid", 1, role="editor")], [], self.ages(young=("kid",)), self.settings)
        self.assertEqual(summary["net"], 1.0)

    def test_score_is_shrunk_toward_zero_and_capped(self) -> None:
        one = vote_summary([self.vote("a", 1)], [], self.ages("a"), self.settings)
        self.assertAlmostEqual(one["score"], round(1 / 21, 4), places=4)
        many = vote_summary([self.vote(f"r{n}", 1) for n in range(500)], [], lambda vote: None, self.settings)
        self.assertEqual(many["score"], 0.4)
        down = vote_summary([self.vote(f"r{n}", -1) for n in range(500)], [], lambda vote: None, self.settings)
        self.assertEqual(down["score"], -0.4)

    def test_no_votes_is_all_zero(self) -> None:
        self.assertEqual(vote_summary([], [], lambda vote: None, self.settings), {"up": 0, "down": 0, "net": 0.0, "score": 0.0, "flags": {"wrong": 0, "belongs_under": 0, "better_name": 0}})

    def test_flags_are_counted_per_kind(self) -> None:
        flags = [{"kind": "wrong"}, {"kind": "wrong"}, {"kind": "better_name"}, {"kind": "other"}]
        self.assertEqual(vote_summary([], flags, lambda vote: None, self.settings)["flags"], {"wrong": 2, "belongs_under": 0, "better_name": 1})

    def test_ratings_in_the_up_dimension_do_not_exist_and_other_dimensions_are_ignored(self) -> None:
        votes = [{**self.vote("a", 1), "dimension": "used-it"}]
        self.assertEqual(vote_summary(votes, [], self.ages("a"), self.settings)["up"], 0)

    def test_default_subject_types_are_item_and_submission(self) -> None:
        self.assertEqual(SnapshotSettings().subject_types, ("item", "submission"))
        self.assertEqual(settings_from_mapping({"subjects": {"types": ["proposal"]}}).subject_types, ("proposal",))


class SnapshotFilesTests(unittest.TestCase):
    def build(self, backend: ReaderBackend, ranking: dict | None = None, published=("item-one", "item-two")):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return run(backend, directory.name, ranking, published)

    def test_proposal_and_story_votes_show_up_down_and_net_in_the_per_type_files_and_subjects_json(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            for name, value in (("a", 1), ("b", 1), ("c", -1)):
                backend.call(subject_for(name), "vote", {"subject": PROPOSAL, "value": value})
            backend.call(subject_for("a"), "vote", {"subject": {"type": "story", "id": "weekly-42"}, "value": -1})
            writer = self.build(backend, {"combination": "shrinkage"})
            proposal = read(writer, "_data/reader/votes/proposal.json")
            self.assertEqual((proposal["type"], list(proposal["subjects"])), ("proposal", ["prop-1"]))
            entry = proposal["subjects"]["prop-1"]
            self.assertEqual((entry["up"], entry["down"]), (2, 1))
            self.assertAlmostEqual(entry["net"], 1 / 3 + 1 / 3 - 1 / 3, places=3)  # all three accounts are new
            self.assertEqual(read(writer, "_data/reader/votes/story.json")["subjects"]["weekly-42"]["down"], 1)
            subjects = read(writer, "_data/reader/subjects.json")
            self.assertEqual(subjects["types"], list(TYPES))
            self.assertEqual(subjects["votes"]["proposal"]["prop-1"], entry)
            self.assertEqual(read(writer, "_data/reader/votes/concept.json")["subjects"], {})
            keyed = read(writer, "_data/reader/items.json")["items"]["proposal:prop-1"]
            self.assertEqual({key: keyed[key] for key in ("up", "down", "net", "comments")}, {"up": 2, "down": 1, "net": entry["net"], "comments": 0})
            self.assertIn("story:weekly-42", read(writer, "_data/reader/items.json")["items"])

    def test_item_entries_gain_down_net_score_and_flags_and_keep_up(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            backend.call(subject_for("a"), "vote", {"subject": "item-one", "dimension": "up", "on": True})
            backend.call(subject_for("b"), "vote", {"subject": {"type": "item", "id": "item-one"}, "value": -1})
            backend.call(subject_for("c"), "flag", {"subject": {"type": "item", "id": "item-one"}, "kind": "wrong", "reason": "No."})
            writer = self.build(backend)
            entry = read(writer, "_data/reader/items.json")["items"]["item-one"]
            self.assertEqual((entry["up"], entry["down"]), (1, 1))
            self.assertEqual(entry["flags"], {"wrong": 1, "belongs_under": 0, "better_name": 0})
            self.assertEqual(read(writer, "_data/reader/votes/item.json")["subjects"]["item-one"]["up"], 1)

    def test_a_downvote_is_not_rising_and_earns_no_karma(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            backend.call(subject_for("b"), "vote", {"subject": {"type": "item", "id": "item-one"}, "value": -1})
            writer = self.build(backend)
            self.assertEqual(read(writer, "_data/reader/board.json")["rising"], [])
            self.assertEqual(read(writer, "_data/reader/items.json")["items"]["item-one"]["up"], 0)

    def test_flags_reach_the_files_as_counts_only(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            backend.call(subject_for("a"), "flag", {"subject": PROPOSAL, "kind": "wrong", "reason": "secret reason text"})
            backend.call(subject_for("b"), "flag", {"subject": PROPOSAL, "kind": "better_name", "reason": "r", "name": "Suggested thing"})
            backend.call(subject_for("c"), "flag", {"subject": PROPOSAL, "kind": "belongs_under", "reason": "r", "target": {"type": "concept", "id": "hardware"}})
            writer = self.build(backend)
            entry = read(writer, "_data/reader/votes/proposal.json")["subjects"]["prop-1"]
            self.assertEqual(entry["flags"], {"wrong": 1, "belongs_under": 1, "better_name": 1})
            published = " ".join(writer.get(entry_.key).decode() for entry_ in writer.list(""))
            for private in ("secret reason text", "Suggested thing", "hardware"):
                self.assertNotIn(private, published)

    def test_a_disabled_type_is_left_out(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            backend.call(subject_for("a"), "vote", {"subject": PROPOSAL, "value": 1})
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            writer = LocalDirectoryWriter(Path(directory.name))
            run_snapshot(backend, writer, subject_types=("item", "submission"))
            self.assertIsNone(writer.get("_data/reader/votes/proposal.json"))
            self.assertEqual(sorted(read(writer, "_data/reader/subjects.json")["votes"]), ["item", "submission"])

    def test_votes_on_unpublished_items_are_ignored_but_other_types_need_no_record(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            backend.call(subject_for("a"), "vote", {"subject": {"type": "item", "id": "item-one"}, "value": 1})
            backend.call(subject_for("a"), "vote", {"subject": PROPOSAL, "value": 1})
            writer = self.build(backend, published=("item-two",))
            self.assertEqual(read(writer, "_data/reader/votes/item.json")["subjects"], {})
            self.assertIn("prop-1", read(writer, "_data/reader/votes/proposal.json")["subjects"])

    def test_the_files_carry_no_identity(self) -> None:
        with ReaderBackend(subject_types=TYPES) as backend:
            backend.call(subject_for("a"), "vote", {"subject": PROPOSAL, "value": 1})
            backend.call(subject_for("a"), "flag", {"subject": PROPOSAL, "kind": "wrong", "reason": "r"})
            writer = self.build(backend)
            files = {entry.key: writer.get(entry.key) for entry in writer.list("")}
            self.assertIn("_data/reader/votes/proposal.json", files)
            self.assertEqual(scan_files(files), {})

    def test_old_rows_without_a_subject_type_are_items(self) -> None:
        snapshot = build_snapshot(
            [{"subjectKey": "item-one", "readerId": "r1", "dimension": "up", "value": 1, "voterRole": "reader", "createdAt": "2027-01-01T00:00:00Z"}],
            [],
            published_at={"item-one": "2027-01-01T00:00:00Z"},
            now_seconds=NOW,
            settings=SnapshotSettings(),
        )
        self.assertEqual(snapshot.items["items"]["item-one"]["up"], 1)
        self.assertEqual(snapshot.votes["item"]["subjects"]["item-one"]["up"], 1)


if __name__ == "__main__":
    unittest.main()
