"""How scores rank items. One module on purpose: the combination of editor and reader scores is an open exploration (PPY-0b2cbb).

Every function is pure. The snapshot writes the raw components next to the score, so changing a formula here
changes ranking without moving any data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

SCORE_DECIMALS = 4
HOURS_PER_DAY = 24


@dataclass(frozen=True)
class RankingParameters:
    half_life_hours: float = 48.0
    rising_window_hours: float = 6.0
    reader_minimum: int = 5
    editor_weight: float = 0.5
    hype_minimum: int = 5


def rounded(value: float) -> float:
    return round(value, SCORE_DECIMALS)


def decay(age_hours: float, half_life_hours: float) -> float:
    """Half of the weight is gone after one half-life; an item from the future counts as new."""
    return 0.5 ** (max(age_hours, 0.0) / half_life_hours)


def composite(means: Iterable[float | None]) -> float | None:
    """The mean of the dimension means that exist, or ``None`` when no dimension has a rating."""
    present = [mean for mean in means if mean is not None]
    return sum(present) / len(present) if present else None


def front_score(
    editor: float | None, reader: float | None, reader_n: int, age_hours: float, parameters: RankingParameters
) -> float | None:
    """Front: the editor composite times time decay until readers have rated, then editor and reader blended.

    ``reader_n`` is the largest number of reader ratings on any dimension. An item with no usable composite is not ranked.
    """
    readers_have_rated = reader is not None and reader_n >= parameters.reader_minimum
    if readers_have_rated and editor is not None:
        base = editor * parameters.editor_weight + reader * (1.0 - parameters.editor_weight)
    elif readers_have_rated:
        base = reader
    elif editor is not None:
        base = editor
    else:
        return None
    return rounded(base * decay(age_hours, parameters.half_life_hours))


def hype_gap(
    editor_means: Mapping[str, float | None], reader_means: Mapping[str, float | None], reader_counts: Mapping[str, int], minimum: int
) -> float | None:
    """Editor composite minus reader composite over the dimensions the editor rated.

    ``None`` unless every one of those dimensions has at least ``minimum`` reader ratings: a gap built on a handful of votes is noise.
    """
    involved = [dimension for dimension, mean in editor_means.items() if mean is not None]
    if not involved or any(reader_means.get(dimension) is None or reader_counts.get(dimension, 0) < minimum for dimension in involved):
        return None
    editor = composite(editor_means[dimension] for dimension in involved)
    reader = composite(reader_means[dimension] for dimension in involved)
    return rounded(editor - reader) if editor is not None and reader is not None else None


def rank(rows: Iterable[dict], score_field: str) -> list[dict]:
    """Highest score first; ties by subject so the order is stable between runs."""
    return sorted((row for row in rows if row.get(score_field) is not None), key=lambda row: (-row[score_field], row["subject"]))
