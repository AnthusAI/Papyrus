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
