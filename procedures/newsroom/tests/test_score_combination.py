"""Score combination (PPY-0b2cbb, PPY-1bf366): the shrinkage rule, new-account weighting and account-age filters.

The reproduction tests drive the committed simulation (docs/score-combination/sim.py, seed 20261022, items.csv) with the plugin's own
ranking functions in place of the simulation's scoring for the two options that matter, so the numbers in docs/score-combination.md
are checked against the code that ships.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from papyrus_content.projection.writers import LocalDirectoryWriter
from papyrus_content.reader_steering import ranking
from papyrus_content.reader_steering.ranking import RankingParameters
from papyrus_content.reader_steering.snapshot import SnapshotSettings, build_snapshot, settings_from_mapping
from reader_fixtures import ReaderBackend, run_snapshot, subject_for

try:
    import numpy  # noqa: F401

    SIM_PATH = Path(__file__).resolve().parents[3] / "docs" / "score-combination" / "sim.py"
    _spec = importlib.util.spec_from_file_location("score_combination_sim", SIM_PATH)
    sim = importlib.util.module_from_spec(_spec)
    sys.modules["score_combination_sim"] = sim
    _spec.loader.exec_module(sim)
except ImportError:  # numpy comes with the cyclotron group; without it only the reproduction is skipped
    sim = None

NOW = 1_800_000_000.0
HOUR = 3600
DIMENSIONS = ("real", "useful")
SHRINKAGE = RankingParameters(combination="shrinkage", new_account_weight=1 / 3, rising_minimum_account_hours=24.0)
BLEND = RankingParameters()


def timestamp(seconds: float) -> str:
    return __import__("datetime").datetime.fromtimestamp(seconds, tz=__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vote(subject: str, reader: str, dimension: str, value: int = 1, role: str = "reader", at_hours_ago: float = 1.0) -> dict:
    return {"subjectKey": subject, "readerId": reader, "dimension": dimension, "value": value, "voterRole": role, "createdAt": timestamp(NOW - at_hours_ago * HOUR)}


def profile(reader: str, age_hours: float) -> dict:
    """A profile that is ``age_hours`` old at ``NOW``."""
    return {"readerId": reader, "handle": reader, "createdAt": timestamp(NOW - age_hours * HOUR)}


def build(votes, profiles, ranking_parameters=SHRINKAGE, **changes):
    published = {"a": timestamp(NOW - 10 * HOUR), "b": timestamp(NOW - 10 * HOUR)}
    settings = SnapshotSettings(dimensions=DIMENSIONS, ranking=ranking_parameters, **changes)
    return build_snapshot(votes, profiles, published_at=published, now_seconds=NOW, settings=settings)


class ShrinkageFunctionTests(unittest.TestCase):
    def test_the_editor_score_is_a_prior_worth_k_ratings(self) -> None:
        # n = 20 = k: half way, but the cap (0.4) holds it at 0.4 of the distance
        capped = ranking.shrinkage_front_score([4.0], [2.0], [20.0], 0, SHRINKAGE)
        self.assertEqual(capped, 3.2)
        uncapped = ranking.shrinkage_front_score([4.0], [2.0], [20.0], 0, RankingParameters(combination="shrinkage", reader_share_cap=1.0))
        self.assertEqual(uncapped, 3.0)

    def test_the_reader_share_grows_with_n_and_stops_at_the_cap(self) -> None:
        shares = [ranking.reader_share(n, SHRINKAGE) for n in (0, 1, 5, 13.333333, 30, 1000)]
        self.assertEqual(shares[0], 0.0)
        self.assertAlmostEqual(shares[1], 1 / 21)
        self.assertAlmostEqual(shares[2], 0.2)
        self.assertAlmostEqual(shares[3], 0.4, places=4)
        self.assertEqual(shares[4:], [0.4, 0.4])

    def test_one_rating_moves_the_score_a_little_and_the_fifth_does_not_lurch(self) -> None:
        four = ranking.shrinkage_front_score([4.0], [2.0], [4.0], 0, SHRINKAGE)
        five = ranking.shrinkage_front_score([4.0], [2.0], [5.0], 0, SHRINKAGE)
        self.assertLess(abs(five - four), 0.1)
        self.assertLess(ranking.shrinkage_front_score([4.0], [2.0], [1.0], 0, SHRINKAGE), 4.0)
        # the blend, by contrast, jumps by half the distance at the fifth
        self.assertEqual(ranking.front_score(4.0, 2.0, 4, 0, BLEND) - ranking.front_score(4.0, 2.0, 5, 0, BLEND), 1.0)

    def test_the_composite_is_the_mean_of_the_dimensions_and_decay_multiplies(self) -> None:
        score = ranking.shrinkage_front_score([4.0, 3.0], [None, 5.0], [0.0, 5.0], 48, SHRINKAGE)
        self.assertEqual(score, ranking.rounded((4.0 + 3.0 + 0.2 * 2.0) / 2 * 0.5))

    def test_dimensions_missing_an_editor_or_a_reader_score_are_handled(self) -> None:
        self.assertEqual(ranking.shrinkage_front_score([None], [3.0], [2.0], 0, SHRINKAGE), 3.0, "readers alone carry a dimension the editor has not rated")
        self.assertEqual(ranking.shrinkage_front_score([4.0, None], [None, None], [0.0, 0.0], 0, SHRINKAGE), 4.0)
        self.assertIsNone(ranking.shrinkage_front_score([None], [None], [0.0], 0, SHRINKAGE))
        self.assertEqual(ranking.shrinkage_front_score([4.0], [2.0], [0.0], 0, SHRINKAGE), 4.0, "a reader mean with no weight is ignored")

    def test_reader_minimum_does_not_gate_shrinkage(self) -> None:
        gated = RankingParameters(combination="shrinkage", reader_minimum=50)
        self.assertEqual(ranking.shrinkage_front_score([4.0], [2.0], [1.0], 0, gated), ranking.shrinkage_front_score([4.0], [2.0], [1.0], 0, SHRINKAGE))


class SettingsTests(unittest.TestCase):
    def test_blend_is_the_default_and_keeps_every_site_unchanged(self) -> None:
        parameters = settings_from_mapping({"dimensions": ["real"], "ranking": {}}).ranking
        self.assertEqual((parameters.combination, parameters.new_account_weight, parameters.rising_minimum_account_hours), ("blend", 1.0, 0.0))

    def test_shrinkage_turns_on_the_adopted_defaults(self) -> None:
        parameters = settings_from_mapping({"ranking": {"combination": "shrinkage"}, "limits": {"newAccountHours": 12}}).ranking
        self.assertEqual((parameters.shrinkage_k, parameters.reader_share_cap), (20.0, 0.4))
        self.assertAlmostEqual(parameters.new_account_weight, 1 / 3)
        self.assertEqual((parameters.rising_minimum_account_hours, parameters.new_account_hours), (24.0, 12.0))

    def test_the_account_age_rules_can_be_set_explicitly(self) -> None:
        parameters = settings_from_mapping(
            {"ranking": {"combination": "shrinkage", "shrinkageK": 10, "readerShareCap": 0.5, "newAccountWeight": 0.5, "risingMinimumAccountHours": 0}}
        ).ranking
        self.assertEqual((parameters.shrinkage_k, parameters.reader_share_cap, parameters.new_account_weight, parameters.rising_minimum_account_hours), (10.0, 0.5, 0.5, 0.0))

    def test_an_unknown_combination_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            settings_from_mapping({"ranking": {"combination": "wilson"}})


class SnapshotAccountAgeTests(unittest.TestCase):
    def test_new_account_ratings_count_a_third_in_the_mean_and_in_n(self) -> None:
        profiles = [profile("old", 100), profile("new", 5)]
        votes = [vote("a", "old", "real", 5), vote("a", "new", "real", 1), vote("a", "e", "real", 3, role="editor")]
        row = build(votes, profiles).board["front"][0]
        weighted_mean = (5 + 1 / 3) / (4 / 3)
        share = (4 / 3) / (20 + 4 / 3)
        expected = (3 + share * (weighted_mean - 3)) * ranking.decay(10, 48)
        self.assertAlmostEqual(row["score"], expected, places=3)
        self.assertEqual(row["readerN"], ranking.rounded(4 / 3))
        # the displayed statistics stay plain counts of what readers did
        stats = build(votes, profiles).items["items"]["a"]["ratings"]["real"]["reader"]
        self.assertEqual((stats["n"], stats["mean"]), (2, 3.0))

    def test_age_is_taken_when_the_vote_was_cast(self) -> None:
        # a profile 30 hours old at NOW that rated 29 hours ago was 1 hour old then: still discounted
        votes = [vote("a", "sock", "real", 1, at_hours_ago=29), vote("a", "e", "real", 3, role="editor")]
        discounted = build(votes, [profile("sock", 30)]).board["front"][0]
        self.assertEqual(discounted["readerN"], ranking.rounded(1 / 3))
        full = build([vote("a", "sock", "real", 1, at_hours_ago=1), votes[1]], [profile("sock", 30)]).board["front"][0]
        self.assertEqual(full["readerN"], 1)

    def test_a_vote_with_no_profile_row_counts_in_full(self) -> None:
        row = build([vote("a", "ghost", "real", 4), vote("a", "e", "real", 3, role="editor")], []).board["front"][0]
        self.assertEqual(row["readerN"], 1)

    def test_blend_ignores_account_age_unless_a_weight_is_configured(self) -> None:
        votes = [vote("a", "n%d" % number, "real", 5) for number in range(5)] + [vote("a", "e", "real", 3, role="editor")]
        profiles = [profile("n%d" % number, 1) for number in range(5)]
        plain = build(votes, profiles, BLEND).board["front"][0]
        self.assertEqual((plain["readerN"], plain["score"]), (5, ranking.rounded(4.0 * ranking.decay(10, 48))))
        weighted = build(votes, profiles, RankingParameters(new_account_weight=1 / 3)).board["front"][0]
        self.assertEqual(weighted["score"], ranking.rounded(3.0 * ranking.decay(10, 48)), "5 sock ratings at a third are under the blend's minimum of 5")

    def test_rising_counts_only_upvotes_from_old_enough_accounts(self) -> None:
        profiles = [profile("old", 100), profile("new", 5)]
        votes = [vote("a", "old", "up"), vote("a", "new", "up")]
        self.assertEqual(build(votes, profiles).board["rising"], [{"subject": "a", "upvotes": 1}])
        self.assertEqual(build(votes, profiles, BLEND).board["rising"], [{"subject": "a", "upvotes": 2}], "0 hours is the old behaviour")
        self.assertEqual(build(votes, profiles).items["items"]["a"]["up"], 2, "the displayed upvote count is not filtered")

    def test_used_it_reporters_are_distinct_old_enough_readers(self) -> None:
        profiles = [profile("old1", 100), profile("old2", 50), profile("new", 5)]
        votes = [vote("a", "old1", "used-it"), vote("a", "old2", "used-it"), vote("a", "new", "used-it"), vote("a", "e", "used-it", role="editor")]
        item = build(votes, profiles).items["items"]["a"]
        self.assertEqual((item["usedIt"], item["usedItReporters"]), (4, 2))
        self.assertEqual(build(votes, profiles, BLEND).items["items"]["a"]["usedItReporters"], 3, "no age rule under blend; the editor is still not a reader")

    def test_a_site_can_apply_the_three_report_rule_from_the_reporters(self) -> None:
        profiles = [profile("r%d" % number, 100) for number in range(3)] + [profile("s%d" % number, 2) for number in range(3)]
        socks = [vote("a", "s%d" % number, "used-it") for number in range(3)]
        self.assertEqual(build(socks, profiles).items["items"]["a"]["usedItReporters"], 0)
        honest = socks + [vote("a", "r%d" % number, "used-it") for number in range(3)]
        self.assertGreaterEqual(build(honest, profiles).items["items"]["a"]["usedItReporters"], 3)

    def test_the_board_publishes_the_active_parameters(self) -> None:
        parameters = build([vote("a", "x", "real", 3)], []).board["parameters"]
        self.assertEqual(parameters["combination"], "shrinkage")
        self.assertEqual((parameters["shrinkageK"], parameters["readerShareCap"]), (20.0, 0.4))
        self.assertAlmostEqual(parameters["newAccountWeight"], 1 / 3)
        self.assertEqual((parameters["newAccountHours"], parameters["risingMinimumAccountHours"]), (24.0, 24.0))
        self.assertEqual(build([vote("a", "x", "real", 3)], [], BLEND).board["parameters"]["combination"], "blend")


class SnapshotTableTests(unittest.TestCase):
    """The reader-snapshot task against moto tables: profile ages come from the real profile rows."""

    SHRINKAGE_SETTINGS = {"combination": "shrinkage"}

    def run_task(self, backend, ranking_settings):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalDirectoryWriter(Path(directory))
            run_snapshot(backend, store, ranking=ranking_settings)
            return (
                json.loads(store.get("_data/reader/items.json")),
                json.loads(store.get("_data/reader/board.json")),
            )

    def populate(self, backend) -> None:
        old, young, editor = subject_for("old"), subject_for("young"), subject_for("editor")
        backend.call(old, "me")
        backend.call(editor, "me", staff=True)
        backend.age_everyone()
        backend.call(young, "me")
        backend.call(editor, "rating", {"subject": "item-one", "dimension": "real", "value": 3}, staff=True)
        for reader, value in ((old, 5), (young, 1)):
            backend.call(reader, "vote", {"subject": "item-one", "dimension": "up", "on": True})
            backend.call(reader, "vote", {"subject": "item-one", "dimension": "used-it", "on": True})
            backend.call(reader, "rating", {"subject": "item-one", "dimension": "real", "value": value})

    def test_a_day_old_profile_counts_a_third_and_is_filtered_from_rising_and_the_reporters(self) -> None:
        with ReaderBackend() as backend:
            self.populate(backend)
            items, board = self.run_task(backend, self.SHRINKAGE_SETTINGS)
        item = items["items"]["item-one"]
        self.assertEqual((item["up"], item["usedIt"], item["usedItReporters"]), (2, 2, 1))
        self.assertEqual(board["rising"], [{"subject": "item-one", "upvotes": 1}])
        front = board["front"][0]
        self.assertEqual(front["readerN"], ranking.rounded(4 / 3))
        weighted_mean = (5 + 1 / 3) / (4 / 3)
        share = (4 / 3) / (20 + 4 / 3)
        self.assertAlmostEqual(front["score"], (3 + share * (weighted_mean - 3)) * ranking.decay(front["ageHours"], 48), places=3)
        self.assertEqual(board["parameters"]["combination"], "shrinkage")

    def test_the_default_ranking_settings_leave_the_snapshot_as_it_was(self) -> None:
        with ReaderBackend() as backend:
            self.populate(backend)
            items, board = self.run_task(backend, {})
        self.assertEqual(items["items"]["item-one"]["usedItReporters"], 2)
        self.assertEqual(board["rising"], [{"subject": "item-one", "upvotes": 2}])
        self.assertEqual(board["front"][0]["readerN"], 2)
        self.assertEqual(board["front"][0]["score"], ranking.rounded(3.0 * ranking.decay(board["front"][0]["ageHours"], 48)), "under the minimum of 5, the editor composite alone")


@unittest.skipIf(sim is None, "numpy is not installed")
class SimulationReproductionTests(unittest.TestCase):
    """The committed simulation's key numbers, with the plugin's ranking functions doing the scoring for A (blend) and B20cap.4 (shrinkage)."""

    @classmethod
    def setUpClass(cls) -> None:
        import numpy as np

        original = sim.scores
        blend = RankingParameters(reader_minimum=sim.READER_MINIMUM, editor_weight=sim.EDITOR_WEIGHT)
        shrinkage = RankingParameters(combination="shrinkage")

        def plugin_scores(s, key):
            if key not in ("A", "B20cap.4"):
                return original(s, key)
            out = np.empty(sim.N)
            for index in range(sim.N):
                counts = np.broadcast_to(s["nw"][index], 4)  # the cold-start state keeps one count per item
                means = [float(s["sw"][index][d] / counts[d]) if counts[d] > 0 else None for d in range(4)]
                editor = [float(value) for value in sim.EDITOR[index]]
                if key == "A":
                    value = ranking.front_score(sum(editor) / 4, ranking.composite(means), float(counts.max()), 0.0, blend)
                else:
                    value = ranking.shrinkage_front_score(editor, means, [float(c) for c in counts], 0.0, shrinkage)
                out[index] = value
            return out

        # The simulation draws from one generator in a fixed order; replay the scenarios before the two that are checked.
        rng = np.random.default_rng(sim.SEED)
        sim.stability(rng)
        sim.disagreement(rng)
        sim.d_sensitivity(rng)
        sim.scores = plugin_scores
        try:
            cls.brigade = {(row["target_editor_rank"], row["sock_weight"], row["option"]): row for row in sim.brigade(rng)}
            sim.scores = original
            sim.brigade_down(rng)
            sim.scores = plugin_scores
            cls.cold_start = {row["option"]: row for row in sim.cold_start(rng)}
        finally:
            sim.scores = original

    def test_the_fifth_rating_no_longer_lurches(self) -> None:
        self.assertAlmostEqual(self.cold_start["A"]["rank_jump_when_5th_rating_arrives"], 7.31, delta=0.5)
        self.assertAlmostEqual(self.cold_start["B20cap.4"]["rank_jump_when_5th_rating_arrives"], 1.2, delta=0.3)

    def test_socks_needed_to_put_a_mid_table_item_in_the_top_five(self) -> None:
        def socks(weight: str, option: str) -> int:
            return int(self.brigade[(35, weight, option)]["socks_to_top5_median"])

        # Tolerances are wide on purpose: the median sits on a flat part of the curve and other numpy versions draw slightly different
        # streams (CI got 33 where a local numpy gets 28). What must hold is the size of the effect.
        self.assertAlmostEqual(socks("full weight", "A"), 13, delta=4)
        self.assertAlmostEqual(socks("full weight", "B20cap.4"), 28, delta=8)
        self.assertAlmostEqual(socks("1/3 weight (new account)", "A"), 40, delta=12)
        self.assertAlmostEqual(socks("1/3 weight (new account)", "B20cap.4"), 96, delta=30)
        for weight in ("full weight", "1/3 weight (new account)"):
            self.assertGreater(socks(weight, "B20cap.4"), 1.8 * socks(weight, "A"), "shrinkage needs about twice the socks the blend does")
        self.assertGreater(socks("1/3 weight (new account)", "B20cap.4"), 2.5 * socks("full weight", "B20cap.4") - 15, "a third-weight sock costs about three times as many")


if __name__ == "__main__":
    unittest.main()
