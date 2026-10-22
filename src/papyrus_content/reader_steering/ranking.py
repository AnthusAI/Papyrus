"""How scores rank items. One module on purpose: the combination of editor and reader scores lives here (PPY-0b2cbb, decided 2026-10-22).

``blend`` is the original rule (editor composite, then a fixed-weight blend after ``reader_minimum`` ratings). ``shrinkage`` is the adopted
alternative in docs/score-combination.md: per dimension, the editor score is a prior worth ``shrinkage_k`` ratings and the reader share is capped.

Every function is pure. The snapshot writes the raw components next to the score, so changing a formula here
changes ranking without moving any data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

COMBINATION_BLEND = "blend"
COMBINATION_SHRINKAGE = "shrinkage"
COMBINATIONS = (COMBINATION_BLEND, COMBINATION_SHRINKAGE)
SCORE_DECIMALS = 4
HOURS_PER_DAY = 24


@dataclass(frozen=True)
class RankingParameters:
    half_life_hours: float = 48.0
    rising_window_hours: float = 6.0
    reader_minimum: int = 5
    editor_weight: float = 0.5
    hype_minimum: int = 5
    combination: str = COMBINATION_BLEND
    shrinkage_k: float = 20.0
    reader_share_cap: float = 0.4
    new_account_weight: float = 1.0
    """Weight of a rating from a profile younger than ``new_account_hours`` (in the reader mean and in ``n``)."""
    new_account_hours: float = 24.0
    rising_minimum_account_hours: float = 0.0
    """Rising and the used-it reporter count only take profiles at least this old; 0 takes every profile."""


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


def reader_share(n: float, parameters: RankingParameters) -> float:
    """The weight of the reader mean against the editor score: ``n / (k + n)``, never more than ``reader_share_cap``."""
    return min(n / (parameters.shrinkage_k + n), parameters.reader_share_cap) if n > 0 else 0.0


def shrinkage_front_score(
    editor_means: Iterable[float | None],
    reader_means: Iterable[float | None],
    reader_weights: Iterable[float],
    age_hours: float,
    parameters: RankingParameters,
) -> float | None:
    """Front under shrinkage: per dimension ``E + share * (readerMean - E)``, the mean of those, times time decay.

    The three iterables run in step over the dimensions. ``reader_weights`` is the weighted number of reader ratings on that dimension
    (a rating from a young account counts less). A dimension without an editor score takes the reader mean alone; one without either is
    left out; an item with no dimension is not ranked. ``reader_minimum`` plays no part.
    """
    per_dimension: list[float] = []
    for editor, reader, weight in zip(editor_means, reader_means, reader_weights, strict=True):
        if reader is None or weight <= 0:
            reader = None
        if editor is None:
            if reader is not None:
                per_dimension.append(reader)
        elif reader is None:
            per_dimension.append(editor)
        else:
            per_dimension.append(editor + reader_share(weight, parameters) * (reader - editor))
    base = composite(per_dimension)
    return None if base is None else rounded(base * decay(age_hours, parameters.half_life_hours))


@dataclass(frozen=True)
class HypeGapGroups:
    """The dimensions whose mean is added (``plus``) and subtracted (``minus``) to make the hype gap."""

    plus: tuple[str, ...]
    minus: tuple[str, ...]

    @property
    def involved(self) -> tuple[str, ...]:
        return self.plus + self.minus


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def hype_gap(
    groups: HypeGapGroups,
    means: Mapping[str, float | None],
    counts: Mapping[str, int],
    minimum: int,
) -> float | None:
    """``mean(plus dimensions) - mean(minus dimensions)``, or ``None`` when any dimension involved is short of ratings.

    Used once for the reader means and once for the editor scores. Every dimension of both groups needs a mean and at
    least ``minimum`` ratings (``counts``): a gap built on a handful of votes is noise. Without groups there is no gap.
    """
    if not groups.plus or not groups.minus:
        return None
    if any(means.get(dimension) is None or counts.get(dimension, 0) < minimum for dimension in groups.involved):
        return None
    plus = _mean([means[dimension] for dimension in groups.plus])  # type: ignore[misc]
    minus = _mean([means[dimension] for dimension in groups.minus])  # type: ignore[misc]
    return rounded(plus - minus)


def rank(rows: Iterable[dict], score_field: str) -> list[dict]:
    """Highest score first; ties by subject so the order is stable between runs."""
    return sorted((row for row in rows if row.get(score_field) is not None), key=lambda row: (-row[score_field], row["subject"]))
