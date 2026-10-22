"""Reader snapshot math, ranking, URL policy keys, the projection task and the privacy scan."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.engine import reconcile
from papyrus_content.projection.plugins import is_plugin_runtime_key
from papyrus_content.projection.standard.config import standard_settings_from_mapping
from papyrus_content.projection.standard.urls import UrlPolicy
from papyrus_content.projection.writers import LocalDirectoryWriter
from papyrus_content.publishing import published_item_id_for
from papyrus_content.reader_steering import ranking
from papyrus_content.reader_steering.ranking import HypeGapGroups, RankingParameters
from papyrus_content.reader_steering.retirement import DisabledRetirementPoll
from papyrus_content.reader_steering.snapshot import (
    BOARD_FILE,
    ITEMS_FILE,
    READERS_FILE,
    KarmaWeights,
    SnapshotSettings,
    build_snapshot,
    encoded,
    rating_stats,
    settings_from_mapping,
)
from papyrus_content.reader_steering.task import (
    PROFILE_TABLE_ENV,
    SETTINGS_ENV,
    VOTE_TABLE_ENV,
    ReaderSnapshotNotEnabled,
    run_reader_snapshot,
    snapshot_key,
)
from procedures.newsroom.tests.incremental_site import seeded_site
from reader_fixtures import ReaderBackend, TABLE_NAMES, run_snapshot, subject_for
from reader_privacy import identity_leaks, scan_files

NOW = 1_800_000_000.0
HOUR = 3600
DIMENSIONS = ("real", "useful")
HYPE_DIMENSIONS = ("notable", "novel", "real", "useful")


def policy_for(base_path: str = "") -> UrlPolicy:
    urls = {"basePath": base_path} if base_path else {}
    return UrlPolicy(standard_settings_from_mapping({"site": {"name": "Example"}, "urls": urls}))


def timestamp(seconds: float) -> str:
    return __import__("datetime").datetime.fromtimestamp(seconds, tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vote(subject: str, reader: str, dimension: str, value: int = 1, role: str = "reader", age_hours: float = 100.0) -> dict:
    return {"subjectKey": subject, "readerId": reader, "dimension": dimension, "value": value, "voterRole": role, "createdAt": timestamp(NOW - age_hours * HOUR)}


def settings(**changes) -> SnapshotSettings:
    return SnapshotSettings(**{"dimensions": DIMENSIONS, **changes})


def snapshot(votes, profiles=(), published=None, **changes):
    published = {"a": timestamp(NOW - 10 * HOUR), "b": timestamp(NOW - 10 * HOUR)} if published is None else published
    return build_snapshot(votes, profiles, published_at=published, now_seconds=NOW, settings=settings(**changes))


class RankingTests(unittest.TestCase):
    parameters = RankingParameters(half_life_hours=48, reader_minimum=5, editor_weight=0.5)

    def test_decay_halves_each_half_life_and_never_exceeds_one(self) -> None:
        self.assertEqual(ranking.decay(0, 48), 1.0)
        self.assertAlmostEqual(ranking.decay(48, 48), 0.5)
        self.assertAlmostEqual(ranking.decay(96, 48), 0.25)
        self.assertEqual(ranking.decay(-5, 48), 1.0, "an item dated in the future counts as new")

    def test_composite_ignores_dimensions_without_ratings(self) -> None:
        self.assertEqual(ranking.composite([4.0, None, 2.0]), 3.0)
        self.assertIsNone(ranking.composite([None, None]))
        self.assertIsNone(ranking.composite([]))

    def test_front_is_the_editor_composite_times_decay_until_readers_have_rated(self) -> None:
        self.assertEqual(ranking.front_score(4.0, 1.0, 4, 0, self.parameters), 4.0, "four readers are not enough")
        self.assertEqual(ranking.front_score(4.0, None, 0, 48, self.parameters), 2.0)
        self.assertEqual(ranking.front_score(4.0, 2.0, 5, 0, self.parameters), 3.0, "blended once readers have rated")
        self.assertEqual(ranking.front_score(None, 2.0, 5, 0, self.parameters), 2.0, "readers alone can carry an item")
        self.assertIsNone(ranking.front_score(None, 2.0, 4, 0, self.parameters), "no editor score and too few readers: not ranked")
        self.assertIsNone(ranking.front_score(None, None, 0, 0, self.parameters))

    def test_editor_weight_sets_the_blend(self) -> None:
        heavy = RankingParameters(editor_weight=1.0)
        self.assertEqual(ranking.front_score(4.0, 2.0, 9, 0, heavy), 4.0)
        light = RankingParameters(editor_weight=0.0)
        self.assertEqual(ranking.front_score(4.0, 2.0, 9, 0, light), 2.0)

    def test_hype_gap_is_the_plus_mean_minus_the_minus_mean(self) -> None:
        groups = HypeGapGroups(plus=("notable", "novel"), minus=("real", "useful"))
        means = {"notable": 5.0, "novel": 4.0, "real": 3.0, "useful": 2.0}
        counts = {dimension: 5 for dimension in means}
        self.assertEqual(ranking.hype_gap(groups, means, counts, 5), 2.0, "mean(5, 4) - mean(3, 2)")
        self.assertEqual(ranking.hype_gap(HypeGapGroups(("notable",), ("real",)), means, counts, 5), 2.0)
        self.assertEqual(ranking.hype_gap(HypeGapGroups(("real",), ("notable",)), means, counts, 5), -2.0, "a negative gap is a gap")

    def test_hype_gap_needs_the_minimum_on_every_dimension_involved(self) -> None:
        groups = HypeGapGroups(plus=("notable",), minus=("real", "useful"))
        means = {"notable": 4.0, "real": 3.0, "useful": 3.0, "extra": 1.0}
        self.assertEqual(ranking.hype_gap(groups, means, {"notable": 5, "real": 5, "useful": 5}, 5), 1.0)
        self.assertIsNone(ranking.hype_gap(groups, means, {"notable": 5, "real": 5, "useful": 4}, 5), "one dimension at 4 ratings blocks the gap")
        self.assertIsNone(ranking.hype_gap(groups, {**means, "useful": None}, {"notable": 9, "real": 9, "useful": 0}, 5))
        self.assertEqual(ranking.hype_gap(groups, means, {"notable": 1, "real": 1, "useful": 1}, 1), 1.0, "a minimum of one is enough for editors")

    def test_without_both_groups_there_is_no_hype_gap(self) -> None:
        means, counts = {"real": 3.0, "notable": 4.0}, {"real": 9, "notable": 9}
        self.assertIsNone(ranking.hype_gap(HypeGapGroups((), ("real",)), means, counts, 1))
        self.assertIsNone(ranking.hype_gap(HypeGapGroups(("notable",), ()), means, counts, 1))

    def test_rank_orders_by_score_then_subject_and_drops_unscored(self) -> None:
        rows = [{"subject": "b", "score": 2.0}, {"subject": "a", "score": 2.0}, {"subject": "c", "score": 3.0}, {"subject": "d", "score": None}]
        self.assertEqual([row["subject"] for row in ranking.rank(rows, "score")], ["c", "a", "b"])


class StatsTests(unittest.TestCase):
    def test_mean_n_and_histogram(self) -> None:
        self.assertEqual(rating_stats([5, 5, 3, 1]), {"mean": 3.5, "n": 4, "hist": [1, 0, 1, 0, 2]})
        self.assertEqual(rating_stats([]), {"mean": None, "n": 0, "hist": [0, 0, 0, 0, 0]})
        self.assertEqual(rating_stats([2, 3, 3])["mean"], 2.6667)


class SnapshotTests(unittest.TestCase):
    def test_ratings_are_split_by_voter_role_with_mean_n_and_histogram(self) -> None:
        votes = [
            vote("a", "r1", "real", 4), vote("a", "r2", "real", 5), vote("a", "r3", "real", 4),
            vote("a", "e1", "real", 2, role="editor"),
            vote("a", "r1", "useful", 1),
        ]
        item = snapshot(votes).items["items"]["a"]
        self.assertEqual(item["ratings"]["real"]["reader"], {"mean": 4.3333, "n": 3, "hist": [0, 0, 0, 2, 1]})
        self.assertEqual(item["ratings"]["real"]["editor"], {"mean": 2.0, "n": 1, "hist": [0, 1, 0, 0, 0]})
        self.assertEqual(item["ratings"]["useful"]["editor"]["n"], 0)
        self.assertEqual((item["editor"], item["reader"]), (2.0, 2.6667))

    def test_up_and_used_it_count_every_role_and_unconfigured_dimensions_are_ignored(self) -> None:
        votes = [vote("a", "r1", "up"), vote("a", "r2", "up"), vote("a", "e1", "up", role="editor"), vote("a", "r1", "used-it"), vote("a", "r1", "bogus", 3)]
        item = snapshot(votes).items["items"]["a"]
        self.assertEqual((item["up"], item["usedIt"]), (3, 1))
        self.assertEqual(sorted(item["ratings"]), ["real", "useful"])

    def test_hype_gap_is_reported_separately_for_readers_and_editors(self) -> None:
        groups = HypeGapGroups(plus=("notable", "novel"), minus=("real", "useful"))

        def votes(readers: int) -> list[dict]:
            rows = [vote("a", "e1", dimension, value, role="editor") for dimension, value in (("notable", 5), ("novel", 4), ("real", 2), ("useful", 2))]
            for dimension, value in (("notable", 3), ("novel", 3), ("real", 4), ("useful", 4)):
                rows += [vote("a", f"r{number}", dimension, value) for number in range(readers)]
            return rows

        item = snapshot(votes(5), dimensions=HYPE_DIMENSIONS, hype_gap=groups).items["items"]["a"]
        self.assertEqual(item["hypeGap"], {"reader": -1.0, "editor": 2.5}, "readers: mean(3, 3) - mean(4, 4); editors: mean(5, 4) - mean(2, 2)")
        short = snapshot(votes(4), dimensions=HYPE_DIMENSIONS, hype_gap=groups).items["items"]["a"]
        self.assertEqual(short["hypeGap"], {"reader": None, "editor": 2.5}, "four readers are too few; the editor gap does not wait for them")

    def test_the_editor_gap_needs_every_dimension_rated_by_an_editor(self) -> None:
        groups = HypeGapGroups(plus=("notable",), minus=("real",))
        votes = [vote("a", "e1", "notable", 5, role="editor")] + [vote("a", f"r{number}", dimension, 3) for number in range(5) for dimension in ("notable", "real")]
        item = snapshot(votes, dimensions=HYPE_DIMENSIONS, hype_gap=groups).items["items"]["a"]
        self.assertEqual(item["hypeGap"], {"reader": 0.0, "editor": None})

    def test_no_hype_gap_configuration_means_no_hype_gap(self) -> None:
        votes = [vote("a", f"r{number}", dimension, 3) for number in range(9) for dimension in DIMENSIONS]
        self.assertIsNone(snapshot(votes).items["items"]["a"]["hypeGap"])

    def test_hype_gap_groups_come_from_the_publication(self) -> None:
        parsed = settings_from_mapping({"dimensions": ["real", "notable"], "hypeGap": {"plus": ["notable"], "minus": ["real"]}})
        self.assertEqual(parsed.hype_gap, HypeGapGroups(plus=("notable",), minus=("real",)))
        self.assertIsNone(settings_from_mapping({"dimensions": ["real"]}).hype_gap)

    def test_rising_counts_upvotes_in_the_window(self) -> None:
        votes = [vote("a", f"r{number}", "up", age_hours=1) for number in range(3)] + [vote("b", "r1", "up", age_hours=7), vote("b", "r2", "up", age_hours=5.9)]
        votes += [vote("a", "r9", "up", age_hours=6.01)]
        board = snapshot(votes).board
        self.assertEqual(board["rising"], [{"subject": "a", "upvotes": 3}, {"subject": "b", "upvotes": 1}])

    def test_rising_follows_the_configured_window(self) -> None:
        votes = [vote("a", "r1", "up", age_hours=20)]
        self.assertEqual(snapshot(votes).board["rising"], [])
        wide = snapshot(votes, ranking=RankingParameters(rising_window_hours=24))
        self.assertEqual(wide.board["rising"], [{"subject": "a", "upvotes": 1}])

    def test_front_carries_the_raw_components_next_to_the_score(self) -> None:
        votes = [vote("a", "e1", "real", 4, role="editor"), vote("a", "e1", "useful", 2, role="editor"), vote("b", "e1", "real", 5, role="editor")]
        published = {"a": timestamp(NOW - 48 * HOUR), "b": timestamp(NOW)}
        front = snapshot(votes, published=published).board["front"]
        self.assertEqual([row["subject"] for row in front], ["b", "a"])
        self.assertEqual(front[1], {"subject": "a", "score": 1.5, "editor": 3.0, "reader": None, "readerN": 0, "ageHours": 48.0})
        self.assertEqual(front[0]["score"], 5.0)

    def test_unpublished_subjects_are_left_out(self) -> None:
        votes = [vote("gone", "r1", "up", age_hours=1), vote("a", "r1", "up", age_hours=1)]
        result = snapshot(votes, published={"a": timestamp(NOW)})
        self.assertEqual(list(result.items["items"]), ["a"])
        self.assertEqual([row["subject"] for row in result.board["rising"]], ["a"])

    def test_karma_is_zero_for_everyone_until_submissions_exist(self) -> None:
        profiles = [{"readerId": "r1", "handle": "alice", "karma": 0}, {"readerId": "r2", "handle": "bob", "karma": 0}]
        result = snapshot([vote("a", "r1", "up"), vote("a", "r2", "used-it")], profiles)
        self.assertEqual(result.karma, {"r1": 0, "r2": 0})
        self.assertEqual(result.readers["readers"], [])

    def test_karma_counts_upvotes_and_used_it_reports_on_a_readers_submissions_from_others(self) -> None:
        profiles = [{"readerId": "r1", "handle": "alice"}, {"readerId": "r2", "handle": "bob"}, {"readerId": "r3", "handle": "carol"}, {"readerId": "r4"}]
        votes = [
            vote("a", "r2", "up"), vote("a", "r3", "up"), vote("a", "r1", "up"),
            vote("a", "r2", "used-it"), vote("b", "r1", "up"), vote("b", "r4", "used-it"),
        ]
        submitters = {"a": "r1", "b": "r4"}
        result = build_snapshot(
            votes, profiles, published_at={"a": None, "b": None}, now_seconds=NOW, settings=settings(karma=KarmaWeights(upvote=1, used_it=2)),
            submitter_of=submitters.get,
        )
        self.assertEqual(result.karma, {"r1": 4, "r2": 0, "r3": 0, "r4": 1})
        self.assertEqual(result.readers["readers"], [{"readerId": "r1", "handle": "alice", "karma": 4}], "a reader without a handle is not listed")

    def test_karma_weights_come_from_the_publication(self) -> None:
        parsed = settings_from_mapping({"dimensions": ["real"], "karma": {"upvoteWeight": 3, "usedItWeight": 0.5}, "ranking": {"halfLifeHours": 10}, "hypeMinimum": 7})
        self.assertEqual((parsed.karma.upvote, parsed.karma.used_it, parsed.ranking.half_life_hours, parsed.ranking.hype_minimum), (3.0, 0.5, 10.0, 7))
        self.assertEqual(settings_from_mapping({}).ranking, RankingParameters())

    def test_readers_are_ranked_by_karma_then_handle(self) -> None:
        profiles = [{"readerId": f"r{number}", "handle": handle} for number, handle in enumerate(["zed", "amy", "bob"], start=1)]
        votes = [vote("a", "x", "up"), vote("a", "y", "up"), vote("b", "x", "up")]
        result = build_snapshot(
            votes, profiles, published_at={"a": None, "b": None}, now_seconds=NOW, settings=settings(),
            submitter_of={"a": "r1", "b": "r2"}.get,
        )
        self.assertEqual([(row["handle"], row["karma"]) for row in result.readers["readers"]], [("zed", 2), ("amy", 1)])

    def test_the_encoding_is_byte_stable_and_sorted(self) -> None:
        first = encoded(snapshot([vote("a", "r1", "up")]).items)
        second = encoded(snapshot([vote("a", "r1", "up")]).items)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(list(json.loads(first)), sorted(json.loads(first)))

    def test_raters_counts_distinct_readers_with_any_rating_not_upvotes_or_editors(self) -> None:
        votes = [
            vote("a", "r1", "real", 4), vote("a", "r1", "useful", 3), vote("a", "r2", "useful", 5),
            vote("a", "r3", "up"), vote("a", "r4", "used-it"), vote("a", "e1", "real", 5, role="editor"),
            vote("a", "r5", "other", 4), vote("b", "r1", "real", 2),
        ]
        items = snapshot(votes).items["items"]
        self.assertEqual(items["a"]["raters"], 2, "r1 counted once; the upvoter, used-it, editor and unknown dimension are not raters")
        self.assertEqual(items["a"]["up"], 1)
        self.assertEqual(items["b"]["raters"], 1)

    def test_the_board_publishes_the_display_minimum_from_the_hype_minimum(self) -> None:
        default = snapshot([vote("a", "r1", "real", 4)]).board["parameters"]
        self.assertEqual(default["displayMinimum"], 5)
        configured = snapshot([vote("a", "r1", "real", 4)], ranking=RankingParameters(hype_minimum=8)).board["parameters"]
        self.assertEqual(configured["displayMinimum"], 8)


class UrlPolicyTests(unittest.TestCase):
    def test_snapshot_keys_follow_the_base_path(self) -> None:
        rooted = SimpleNamespace(policy=policy_for())
        self.assertEqual(snapshot_key(rooted, ITEMS_FILE), "_data/reader/items.json")
        prefixed = SimpleNamespace(policy=policy_for("posts"))
        self.assertEqual([snapshot_key(prefixed, name) for name in (ITEMS_FILE, BOARD_FILE, READERS_FILE)], ["posts/_data/reader/items.json", "posts/_data/reader/board.json", "posts/_data/reader/readers.json"])
        self.assertEqual(snapshot_key(SimpleNamespace(), BOARD_FILE), "_data/reader/board.json", "a projector without a policy serves from the root")

    def test_plugin_runtime_keys_are_recognised_under_any_base_path(self) -> None:
        for key in ("_data/reader/items.json", "posts/_data/reader/board.json", "a/b/_data/reader/readers.json"):
            self.assertTrue(is_plugin_runtime_key(key), key)
        for key in ("_data/search-index.json", "posts/index.html", "x_data/reader/items.json", "_data/readers.json"):
            self.assertFalse(is_plugin_runtime_key(key), key)


class SnapshotTaskTests(unittest.TestCase):
    def run_task(self, backend: ReaderBackend, store: LocalDirectoryWriter, *, base_path: str = "", invalidate=None, published=("item-one", "item-two")):
        return run_snapshot(backend, store, base_path=base_path, invalidate=invalidate, published=published)

    def test_votes_in_the_tables_become_public_files_under_the_policy_and_the_edge_is_purged(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            alice, bob = subject_for("alice"), subject_for("bob")
            backend.call(alice, "handle", {"handle": "quiet-fox"})
            backend.call(alice, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            backend.call(bob, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            backend.call(alice, "rating", {"subject": "item-one", "dimension": "real", "value": 4}, staff=True)
            backend.call(bob, "rating", {"subject": "item-one", "dimension": "real", "value": 2})
            store = LocalDirectoryWriter(Path(directory))
            purged: list[list[str]] = []
            report = self.run_task(backend, store, base_path="posts", invalidate=lambda keys: purged.append(list(keys)) or keys)
            self.assertEqual(report.written, ["posts/_data/reader/items.json", "posts/_data/reader/board.json", "posts/_data/reader/readers.json", "posts/_data/reader/subjects.json", "posts/_data/reader/submissions.json", "posts/_data/reader/votes/item.json", "posts/_data/reader/votes/submission.json"])
            items = json.loads(store.get("posts/_data/reader/items.json"))
            self.assertEqual(items["items"]["item-one"]["up"], 2)
            self.assertEqual(items["items"]["item-one"]["ratings"]["real"]["editor"]["mean"], 4.0)
            self.assertEqual(items["items"]["item-one"]["ratings"]["real"]["reader"]["mean"], 2.0)
            self.assertEqual([row["subject"] for row in json.loads(store.get("posts/_data/reader/board.json"))["front"]], ["item-one"])
            self.assertEqual(json.loads(store.get("posts/_data/reader/readers.json"))["readers"], [])
            self.assertEqual(purged, [report.written], "exactly the five files are purged, never a wildcard")
            self.assertFalse(any("*" in key for key in report.purged))
            self.assertFalse(report.retirement_poll.enabled)
            self.assertEqual(report.to_dict()["retirementPoll"]["pages"], 0)

    def test_the_subjects_index_and_the_new_list_describe_what_the_board_lists(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            alice, bob = subject_for("alice"), subject_for("bob")
            backend.call(alice, "handle", {"handle": "quiet-fox"})
            backend.call(alice, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            backend.call(alice, "rating", {"subject": "item-one", "dimension": "real", "value": 4}, staff=True)
            backend.call(bob, "handle", {"handle": "calm-owl"})
            submitted = backend.call(bob, "submit", {"url": "https://Example.com/post/1#x", "title": "A small tool"})["body"]
            backend.call(alice, "vote", {"subject": submitted["subject"], "dimension": "up", "on": True})
            store = LocalDirectoryWriter(Path(directory))
            self.run_task(backend, store, base_path="posts")
            board = json.loads(store.get("posts/_data/reader/board.json"))
            subjects = json.loads(store.get("posts/_data/reader/subjects.json"))
            self.assertEqual([(row["subject"], row["kind"]) for row in board["new"]], [(submitted["subject"], "submission"), ("item-one", "item"), ("item-two", "item")], "newest first, items and pending submissions interleaved")
            self.assertEqual(subjects["generatedAt"], board["generatedAt"])
            self.assertEqual(
                subjects["subjects"]["item-one"],
                {"kind": "item", "title": "Title of item-one", "url": "/posts/item-one.html", "section": None, "date": subjects["subjects"]["item-one"]["date"]},
            )
            self.assertRegex(subjects["subjects"]["item-one"]["date"], r"^\d{4}-\d{2}-\d{2}$")
            entry = subjects["subjects"][submitted["subject"]]
            self.assertEqual((entry["kind"], entry["state"], entry["url"], entry["domain"], entry["title"]), ("submission", "pending", "https://example.com/post/1", "example.com", "A small tool"))
            self.assertEqual(sorted(subjects["subjects"]), sorted({row["subject"] for key in ("front", "rising", "new") for row in board[key]}), "only the subjects some list shows")
            self.assertEqual(sorted(entry), ["date", "domain", "kind", "section", "state", "title", "url"])

    def test_an_item_without_a_page_and_an_unpublished_item_are_not_listed(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            store = LocalDirectoryWriter(Path(directory))
            self.run_task(backend, store, published=("item-two",))
            self.assertEqual([row["subject"] for row in json.loads(store.get("_data/reader/board.json"))["new"]], ["item-two"])

    def test_the_new_list_is_capped_and_a_promoted_submission_is_not_pending(self) -> None:
        items = [{"subject": f"i{number}", "publishedAt": timestamp(NOW - number * HOUR), "title": "t", "url": "/t/", "section": None, "date": "2026-01-01"} for number in range(60)]
        pending = {"id": "sub-" + "a" * 24, "canonicalUrl": "https://example.com/a", "domain": "example.com", "title": "T", "readerId": "r", "state": "pending", "createdAt": timestamp(NOW - 30.5 * HOUR)}
        promoted = {**pending, "id": "sub-" + "b" * 24, "state": "promoted", "createdAt": timestamp(NOW - HOUR / 2)}
        result = build_snapshot([], [], published_at={}, now_seconds=NOW, settings=settings(), submissions=[pending, promoted], published_items=items)
        subjects = [row["subject"] for row in result.board["new"]]
        self.assertEqual(len(subjects), 50)
        self.assertEqual(subjects[:2], ["i0", "i1"])
        self.assertIn(pending["id"], subjects)
        self.assertNotIn(promoted["id"], subjects)
        self.assertEqual(subjects.index(pending["id"]), 31, "interleaved by time: after i30 (30 h) and before i31 (31 h)")

    def test_the_run_without_an_edge_distribution_still_writes(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            store = LocalDirectoryWriter(Path(directory))
            report = self.run_task(backend, store, invalidate=None)
            self.assertEqual(report.purged, [])
            self.assertEqual(json.loads(store.get("_data/reader/items.json"))["items"], {})

    def test_a_failing_purge_does_not_fail_the_run(self) -> None:
        def failing(keys):
            raise RuntimeError("throttled")

        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            report = self.run_task(backend, LocalDirectoryWriter(Path(directory)), invalidate=failing)
            self.assertEqual((report.purged, report.purge_error), ([], "RuntimeError"))

    def test_unpublished_items_drop_out_of_the_next_snapshot(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            backend.call(subject_for("alice"), "vote", {"subject": "item-one", "dimension": "up", "on": True})
            store = LocalDirectoryWriter(Path(directory))
            self.run_task(backend, store)
            self.assertIn("item-one", json.loads(store.get("_data/reader/items.json"))["items"])
            self.run_task(backend, store, published=("item-two",))
            self.assertNotIn("item-one", json.loads(store.get("_data/reader/items.json"))["items"])

    def test_karma_is_materialised_on_the_profile_only_when_it_changes(self) -> None:
        with ReaderBackend() as backend, tempfile.TemporaryDirectory() as directory:
            alice = subject_for("alice")
            backend.call(alice, "me")
            store = LocalDirectoryWriter(Path(directory))
            self.assertEqual(self.run_task(backend, store).karma_updated, 0)
            backend.table("profile").update_item(Key={"id": alice}, UpdateExpression="SET karma = :k", ExpressionAttributeValues={":k": 9})
            self.assertEqual(self.run_task(backend, store).karma_updated, 1)
            self.assertEqual(int(backend.table("profile").get_item(Key={"id": alice})["Item"]["karma"]), 0)

    def test_a_site_without_the_plugin_settings_refuses_the_task(self) -> None:
        with self.assertRaises(ReaderSnapshotNotEnabled):
            run_reader_snapshot(SimpleNamespace(), SimpleNamespace(), environment={})

    def test_the_retirement_poll_is_a_disabled_no_op(self) -> None:
        poll = DisabledRetirementPoll()
        self.assertFalse(poll.enabled)
        retired = poll.fetch("cursor-1")
        self.assertEqual((retired.retired, retired.cursor, retired.more), ((), "cursor-1", False))


class ReconcileKeepsTheSnapshotTests(unittest.TestCase):
    def test_reconcile_never_calls_the_snapshot_an_orphan(self) -> None:
        for kind in ("generic", "feed", "public"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                site = seeded_site(kind, Path(temporary))
                for key in (ITEMS_FILE, BOARD_FILE, READERS_FILE, "posts/" + ITEMS_FILE):
                    site.store.put(key, b"{}\n")
                preview = reconcile(site.context, dry_run=True)
                self.assertEqual([key for key in preview.orphan_pages if "reader" in key], [])
                reconcile(site.context)
                for key in (ITEMS_FILE, BOARD_FILE, READERS_FILE, "posts/" + ITEMS_FILE):
                    self.assertEqual(site.store.get(key), b"{}\n", key)

    def test_other_data_files_are_still_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            site = seeded_site("public", Path(temporary))
            site.store.put("_data/ghost.json", b"[]\n")
            self.assertIn("_data/ghost.json", reconcile(site.context, dry_run=True).orphan_pages)


class PluginAssetsTests(unittest.TestCase):
    def test_the_manifest_lists_the_files_the_projector_ships(self) -> None:
        import re

        from papyrus_content.projection.plugins import plugin_static_files

        source = (Path(__file__).resolve().parents[3] / "amplify" / "plugins" / "reader-steering" / "papyrus.plugin.ts").read_text()
        declared = re.search(r"staticAssets: \[(.*?)\]", source, re.S).group(1)
        self.assertEqual(sorted(re.findall(r'"([^"]+)"', declared)), sorted(plugin_static_files(["reader-steering"])))
        files = plugin_static_files(["reader-steering"])
        self.assertEqual(sorted(files), ["_plugins/papyrus-reader@1.css", "_plugins/papyrus-reader@1.js"])
        self.assertTrue(all(body for body in files.values()))

    def test_the_islands_script_has_no_identity_in_it(self) -> None:
        from papyrus_content.projection.plugins import plugin_static_files

        script = plugin_static_files(["reader-steering"])["_plugins/papyrus-reader@1.js"].decode("utf-8")
        self.assertEqual(identity_leaks(script.replace("ss1_", "")), [], "the script holds no subject, email or person id")
        self.assertNotIn("innerHTML", script, "untrusted handles are only ever set as text")


class PrivacyScanTests(unittest.TestCase):
    """The snapshot and the projected pages of a fixture site with votes and profiles never identify a person (ship-b3933d)."""

    PERSON_IDS = (str(uuid.UUID(int=9)), str(uuid.UUID(int=10)))

    def test_the_scan_itself_catches_each_kind_of_leak(self) -> None:
        reader_id = str(uuid.UUID(int=5))
        self.assertEqual(identity_leaks(f"readerId {reader_id}", [reader_id]), [])
        self.assertEqual(identity_leaks(f"id {self.PERSON_IDS[0]}", [reader_id]), [self.PERSON_IDS[0]])
        self.assertTrue(identity_leaks("ss1_" + "A" * 43))
        self.assertTrue(identity_leaks("ssdev_" + "B" * 43))
        self.assertTrue(identity_leaks("mail reader@example.test now"))
        self.assertTrue(identity_leaks('{"personId": "x"}'))
        self.assertTrue(identity_leaks("person_abcdef123"))
        self.assertEqual(identity_leaks("Updated 5 min ago. Quiet-fox rated it 4 of 5."), [])

    def test_snapshot_files_and_projected_pages_carry_no_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, ReaderBackend() as backend:
            site = seeded_site("public", Path(temporary))
            for number, name in enumerate(["alice", "bob", "carol"]):
                subject = subject_for(name)
                backend.call(subject, "handle", {"handle": f"reader-{number}"})
                backend.call(subject, "vote", {"subject": "item-one", "dimension": "up", "on": True})
                backend.call(subject, "rating", {"subject": "item-one", "dimension": "real", "value": 3 + number % 2}, staff=name == "alice")
            profiles = backend.table("profile").scan()["Items"]
            for profile in profiles:
                profile["email"] = "reader@example.test"
                profile["personId"] = self.PERSON_IDS[0]
                backend.table("profile").put_item(Item=profile)
            reader_ids = [profile["readerId"] for profile in profiles]
            row = {"id": published_item_id_for("item-one"), "itemLineageId": "item-one", "sourceItemId": "item-one", "type": "article", "status": "published", "slug": "item-one", "section": "articles", "title": "Item one", "publishedAt": timestamp(NOW - HOUR), "metadata": "{}"}
            client = SimpleNamespace(get_record=lambda model, record_id: {"status": "published", "publishedAt": timestamp(NOW - HOUR)}, list_published_item_summaries=lambda: [row])
            context = SimpleNamespace(projector=site.projector, writer=site.store, invalidate=None)
            environment = {
                SETTINGS_ENV: json.dumps({"dimensions": ["real"], "karma": {}, "ranking": {}, "hypeMinimum": 5}),
                VOTE_TABLE_ENV: TABLE_NAMES["vote"],
                PROFILE_TABLE_ENV: TABLE_NAMES["profile"],
            }
            run_reader_snapshot(context, client, environment=environment, resource=backend.resource, now_seconds=NOW, submitter_of=lambda subject: reader_ids[0])
            written = {path.relative_to(Path(temporary) / "incremental").as_posix(): path.read_bytes() for path in (Path(temporary) / "incremental").rglob("*") if path.is_file()}
            self.assertIn("_data/reader/items.json", written)
            self.assertIn("_data/reader/readers.json", written)
            self.assertEqual(sorted(json.loads(written["_data/reader/subjects.json"])["subjects"]), ["item-one"], "the subjects index is part of the scan")
            self.assertTrue(any(name.endswith(".html") for name in written), "projected pages are part of the scan")
            self.assertEqual(scan_files(written, reader_ids), {})
            readers = json.loads(written["_data/reader/readers.json"])["readers"]
            self.assertTrue(readers and all(set(row) == {"readerId", "handle", "karma"} for row in readers))


if __name__ == "__main__":
    unittest.main()
