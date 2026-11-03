"""Where to stop reading a ranked list of neighbours. Lives here (not in ``papyrus_content``) because the ``knowledgeQuery`` Lambda bundles this
package alone."""
from __future__ import annotations


def knee_cut_count(similarities: list[float]) -> int:
    """How many of the descending ``similarities`` to keep: everything before the largest drop between consecutive
    scores among the first half. A single score, or none, has no drop and is kept whole."""
    if len(similarities) < 2:
        return len(similarities)
    gap_count = max(1, len(similarities) // 2)
    gaps = [similarities[index] - similarities[index + 1] for index in range(gap_count)]
    return gaps.index(max(gaps)) + 1


def search_cut_count(similarities: list[float]) -> int:
    """How many of the descending ``similarities`` to keep for a search list, where recall matters as much as precision.

    ``knee_cut_count`` cuts at the largest single drop, which suits link suggestions (a few sure links) but, on a real neighbour list where one
    hit stands clear of a smoothly falling tail, keeps just that one. This finds the bend of the whole curve instead: scale ranks and scores to
    0..1 and take the point farthest from the straight line joining the first and last score. A curve that is steep and then flattens keeps the
    steep part; one that holds up and then falls keeps the part that held up; a flat curve has no bend and is kept whole. The caller's list is
    already bounded by the vector index's own limit (S3 Vectors returns at most 100), so there is no cap here."""
    count = len(similarities)
    if count < 3:
        return count
    top, bottom = similarities[0], similarities[-1]
    spread = top - bottom
    if spread <= 0:
        return count
    best_index, best_gap = 0, 0.0
    for index, similarity in enumerate(similarities):
        above_line = (similarity - bottom) / spread - (1 - index / (count - 1))   # > 0 above the chord, < 0 below it
        if abs(above_line) > abs(best_gap):
            best_index, best_gap = index, above_line
    if best_gap > 0:
        return best_index + 1   # held up, then fell: keep up to and including the last high point
    return max(1, best_index)   # fell steeply, then flattened: keep the steep part, the bend itself starts the tail
