"""The arithmetic behind automatic acceptance: the Wilson bound, the learned threshold and delay (features_backend/reference-automatic-acceptance.feature)."""
import math

from papyrus_content.auto_accept import learn_threshold, quantile, wilson_lower_bound


def test_the_wilson_lower_bound_matches_the_textbook_values():
    assert math.isclose(wilson_lower_bound(40, 40), 40 / (40 + 1.96**2), rel_tol=1e-9)
    assert wilson_lower_bound(0, 0) == 0.0
    assert wilson_lower_bound(0, 10) == 0.0
    assert 0.49 < wilson_lower_bound(8, 10) < 0.5


def test_the_threshold_is_the_smallest_confidence_that_meets_the_precision():
    votes = [(0.6, False)] * 10 + [(0.8, True)] * 5 + [(0.8, False)] * 5 + [(0.95, True)] * 60
    learned = learn_threshold(votes, 0.9)
    assert learned["threshold"] == 0.95 and learned["votes"] == 60 and learned["accepted"] == 60
    assert learned["lowerBound"] >= 0.9


def test_a_lower_confidence_wins_when_it_already_meets_the_precision():
    votes = [(0.7, True)] * 50 + [(0.9, True)] * 50
    assert learn_threshold(votes, 0.9)["threshold"] == 0.7


def test_nothing_qualifies_with_few_or_disagreeing_votes():
    assert learn_threshold([], 0.9)["threshold"] is None
    assert learn_threshold([(0.9, True)] * 5, 0.9)["threshold"] is None
    mixed = learn_threshold([(0.9, True)] * 20 + [(0.9, False)] * 20, 0.9)
    assert mixed["threshold"] is None and "target precision" in mixed["reason"] and mixed["votes"] == 40


def test_the_quantile_is_the_nearest_rank():
    assert quantile([], 0.9) is None
    assert quantile([5], 0.9) == 5
    assert quantile(list(range(1, 11)), 0.9) == 9
    assert quantile(list(range(1, 11)), 1.0) == 10
    assert quantile([3, 1, 2], 0.5) == 2
