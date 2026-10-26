"""Weekly counts and the change figure (PPY-eb5f28). Pure functions over week numbers."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

WINDOW_WEEKS = 4
MINIMUM_PRIOR_FOR_PERCENT = 5
MINIMUM_HISTORY_FOR_PERCENT = 8
NEW_BELOW_WEEKS = 4
SERIES_SHORT = 8
SERIES_LONG = 26


@dataclass(frozen=True)
class Change:
    last4: int
    prior4: int
    percent: int | None

    def to_dict(self) -> dict:
        return {"last4": self.last4, "prior4": self.prior4, "percent": self.percent}


def series(counts: Mapping[int, int], as_of_week: int, length: int) -> list[int]:
    """``length`` weekly counts, oldest first; the last is the ``as_of_week``."""
    return [int(counts.get(as_of_week - offset, 0)) for offset in range(length - 1, -1, -1)]


def weekly_counts(week_numbers: Iterable[int]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for number in week_numbers:
        counts[number] = counts.get(number, 0) + 1
    return counts


def percent_change(last4: int, prior4: int) -> int | None:
    """``round(100 * (last4 - prior4) / prior4)`` with halves rounded away from zero, or ``None`` on a base under five."""
    if prior4 < MINIMUM_PRIOR_FOR_PERCENT:
        return None
    delta = last4 - prior4
    magnitude = (200 * abs(delta) + prior4) // (2 * prior4)
    return magnitude if delta >= 0 else -magnitude


def change_of(values: list[int], history: int | None = None) -> Change:
    """The last four weeks against the four before them, from a series that ends at the as-of week.

    With ``history`` (weeks since the first confirmed link) the percent is also withheld under eight weeks: the one
    place the cold-start rule for a percent lives."""
    last4 = sum(values[-WINDOW_WEEKS:])
    prior4 = sum(values[-2 * WINDOW_WEEKS : -WINDOW_WEEKS])
    percent = percent_change(last4, prior4)
    if history is not None and history < MINIMUM_HISTORY_FOR_PERCENT:
        percent = None
    return Change(last4=last4, prior4=prior4, percent=percent)


def weeks_of_history(first_week: int, as_of_week: int) -> int:
    return max(0, as_of_week - first_week + 1)


def is_new(history_weeks: int) -> bool:
    return history_weeks < NEW_BELOW_WEEKS


# --- ranking: surprise against the entity's own baseline and the whole corpus's volume (PPY trend quality) -------------------
#
# A raw count rises with the volume of the whole corpus, so an entity everything mentions (a licence, a task, the Hub) tops a
# raw-count ranking every week and carries no news. The score below asks instead: given what the entity had in the four weeks
# before, and given how much the whole corpus grew, how many mentions would we expect in the last four weeks, and how far above that
# is the actual count? Plain Poisson surprise, no model, same input gives the same order.

BROAD_KINDS = frozenset({"licence", "task", "platform"})
PREFERRED_KINDS = frozenset({"maker", "model_family", "model", "concept", "technique"})


@dataclass(frozen=True)
class TrendConfig:
    """Thresholds of trend selection. Every value has a default; ``from_mapping`` reads overrides (``--trend-config`` of ``ideas trends``)."""

    minimum_recent: int = 3  # mentions in the last four weeks an entity needs before it can be a signal at all
    minimum_score: float = 1.0  # kind-weighted Poisson z-score over the expected count; below it an entity is not trending
    baseline_smoothing: float = 1.0  # added to the prior four weeks, so an entity with no history is not infinitely surprising
    broad_kind_weight: float = 0.2  # score multiplier for licence, task and platform (they rise with the corpus; context, not anchors)
    other_kind_weight: float = 0.7  # kinds that are neither broad nor preferred
    broad_kinds: frozenset[str] = BROAD_KINDS
    preferred_kinds: frozenset[str] = PREFERRED_KINDS
    # A maker anchors a draft only when it is notable: on the watchlist, or at least ``minimum_models`` distinct models in the window
    # whose likes add up to ``minimum_likes`` or whose downloads add up to ``minimum_downloads``.
    watchlist: frozenset[str] = frozenset()  # entity keys (maker--nvidia) or names, lower-cased on read
    minimum_models: int = 2
    minimum_likes: int = 100
    minimum_downloads: int = 10_000
    likes_floor: int = 10  # whatever its downloads, a maker needs this many likes (a build pipeline or a bot inflates downloads, nobody likes it)
    anchor_kinds: frozenset[str] = field(default=PREFERRED_KINDS)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object] | None) -> "TrendConfig":
        if not raw:
            return cls()
        known = {name for name in cls.__dataclass_fields__}
        unknown = sorted(set(raw) - known)
        if unknown:
            raise ValueError(f"Unknown trend config setting(s): {', '.join(unknown)}.")
        values: dict[str, object] = {}
        for name, value in raw.items():
            if name in {"broad_kinds", "preferred_kinds", "anchor_kinds"}:
                values[name] = frozenset(str(item) for item in value)  # type: ignore[union-attr]
            elif name == "watchlist":
                values[name] = frozenset(str(item).strip().lower() for item in value)  # type: ignore[union-attr]
            elif name in {"minimum_recent", "minimum_models", "minimum_likes", "minimum_downloads", "likes_floor"}:
                values[name] = int(value)  # type: ignore[arg-type]
            else:
                values[name] = float(value)  # type: ignore[arg-type]
        return cls(**values)  # type: ignore[arg-type]

    def kind_weight(self, kind: str | None) -> float:
        if kind in self.broad_kinds:
            return self.broad_kind_weight
        return 1.0 if kind in self.preferred_kinds else self.other_kind_weight


def corpus_volume(series_rows: Iterable[Sequence[int | float]], length: int = SERIES_SHORT) -> list[float]:
    """Mentions per week across every entity (oldest first): the corpus's own growth, the baseline a single entity is measured against."""
    volume = [0.0] * length
    for values in series_rows:
        padded = [0] * (length - len(values)) + list(values)[-length:]
        for position, value in enumerate(padded):
            volume[position] += value
    return volume


def surprise(last4: float, prior4: float, volume_last4: float, volume_prior4: float, smoothing: float = 1.0) -> float:
    """Poisson z-score of ``last4`` over the count expected if the entity kept its share of the corpus: ``(prior4 + smoothing)`` scaled by
    how much total volume grew. Positive means more mentions than the corpus's growth explains."""
    growth = (volume_last4 / volume_prior4) if volume_prior4 > 0 else 1.0
    expected = (prior4 + smoothing) * growth
    return (last4 - expected) / math.sqrt(expected) if expected > 0 else 0.0


def trend_score(kind: str | None, values: Sequence[int | float], volume: Sequence[float], config: TrendConfig) -> dict[str, float]:
    """``{"surprise", "score", "last4", "prior4"}`` of one entity's eight-week series against the corpus ``volume``; the score is the
    surprise times the weight of the entity's kind (broad kinds are demoted)."""
    last4, prior4 = float(sum(values[-WINDOW_WEEKS:])), float(sum(values[-2 * WINDOW_WEEKS : -WINDOW_WEEKS]))
    z = surprise(last4, prior4, sum(volume[-WINDOW_WEEKS:]), sum(volume[-2 * WINDOW_WEEKS : -WINDOW_WEEKS]), config.baseline_smoothing)
    return {"surprise": round(z, 3), "score": round(z * config.kind_weight(kind), 3), "last4": last4, "prior4": prior4}


def rank_trending(rows: Iterable[tuple[str, str | None, Sequence[int | float]]], config: TrendConfig | None = None) -> list[dict[str, float | str | None]]:
    """The trending order of ``(key, kind, series8)`` rows: entities with at least ``minimum_recent`` mentions in the last four weeks and a
    weighted score of at least ``minimum_score``, highest score first, then more recent mentions, then the key."""
    config = config or TrendConfig()
    materialised = list(rows)
    volume = corpus_volume(values for _key, _kind, values in materialised)
    ranked = []
    for key, kind, values in materialised:
        result = trend_score(kind, values, volume, config)
        if result["last4"] >= config.minimum_recent and result["score"] >= config.minimum_score:
            ranked.append({"key": key, "kind": kind, **result})
    return sorted(ranked, key=lambda row: (-row["score"], -row["last4"], row["key"]))
