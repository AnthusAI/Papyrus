from __future__ import annotations

import json
import pathlib
import sys
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from papyrus_content.reference_suggestions import knee_cut_count  # noqa: E402
from papyrus_content.suggestion_calibration import NO_CUT_REASON, calibrate, load_calibration  # noqa: E402


def decided_row(score, accepted, object_kind="reference", decided_by="user:sub-1", provenance="suggested"):
    return {"objectKind": object_kind, "score": score,
            "metadata": json.dumps({"provenance": provenance, "decision": "accepted" if accepted else "rejected", "decidedBy": decided_by})}


def separable_decisions(object_kind="reference"):
    """Forty rejected at 0.5 and forty accepted at 0.8: only the high group reaches 90% precision."""
    return [decided_row(0.5, False, object_kind) for _ in range(40)] + [decided_row(0.8, True, object_kind) for _ in range(40)]


class FeedClient:
    def __init__(self, rows):
        self.rows, self.reads = rows, []

    def list_by_index(self, index_name, key_value, *, limit=100):
        self.reads.append((index_name, key_value))
        return self.rows


class SuggestionCalibrationTests(unittest.TestCase):
    def test_separable_decisions_cut_at_the_accepted_group(self):
        calibration = calibrate(separable_decisions())
        self.assertEqual(calibration.reference.threshold, 0.8)
        self.assertEqual(calibration.label("reference", 0.9), "likely")
        self.assertEqual(calibration.label("reference", 0.6), "possible")

    def test_too_few_decisions_give_no_cut_and_no_marks(self):
        calibration = calibrate([decided_row(0.9, True) for _ in range(3)])
        self.assertIsNone(calibration.reference.threshold)
        self.assertEqual(calibration.reference.reason, NO_CUT_REASON)
        self.assertIsNone(calibration.label("reference", 0.9))
        self.assertIsNone(calibration.cut("reference", knee_cut_count))

    def test_no_decisions_at_all_give_no_cut(self):
        self.assertEqual(calibrate([]).reference.reason, NO_CUT_REASON)

    def test_disagreeing_decisions_give_no_cut(self):
        rows = [decided_row(0.7, index % 2 == 0) for index in range(60)]
        self.assertIsNone(calibrate(rows).reference.threshold)

    def test_reference_and_concept_cuts_are_separate(self):
        calibration = calibrate(separable_decisions("reference") + [decided_row(0.9, True, "semanticNode") for _ in range(2)])
        self.assertEqual(calibration.reference.threshold, 0.8)
        self.assertIsNone(calibration.concept.threshold)
        self.assertEqual(calibration.concept.decisions, 2)

    def test_only_a_persons_decisions_on_suggestions_count(self):
        rows = [decided_row(0.8, True, decided_by="auto:vector") for _ in range(50)] + [decided_row(0.8, True, provenance="human") for _ in range(50)]
        self.assertEqual(calibrate(rows).reference.decisions, 0)

    def test_the_cut_keeps_everything_at_or_above_it_and_at_least_the_knee(self):
        calibration = calibrate(separable_decisions())
        choose = calibration.cut("reference", knee_cut_count)
        self.assertEqual(choose([0.9, 0.85, 0.8, 0.79, 0.3, 0.2]), 3)
        self.assertEqual(choose([0.6, 0.55, 0.2, 0.1]), 2)

    def test_loading_is_one_read_of_the_link_feed(self):
        client = FeedClient(separable_decisions())
        self.assertEqual(load_calibration(client).reference.threshold, 0.8)
        self.assertEqual(client.reads, [("semanticRelationsByNewsroomFeedAndCreatedAt", "reference-links")])


if __name__ == "__main__":
    unittest.main()
