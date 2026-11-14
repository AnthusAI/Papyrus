"""Translation spend learned from runs, never a fixed cap (PPY-2bc7e5).

A run's cost is close to linear in the source text it translates. The prediction is the median measured cost per source character of earlier
finished runs **of the same language** (Spanish and Chinese are kept apart) times this run's source characters. The band above it is learned
too: Tukey's upper fence over the same measured rates (third quartile plus one and a half interquartile ranges, the standard outlier rule), so
a run far above what that language usually costs is held with the reason and marked as an outlier, never cut off silently. Until a language has
enough runs for quartiles (four), no band exists and the run is governed by the caller's ceiling and the site's translations budget alone.

A caller may also pass an explicit ceiling (a person's decision for one run, such as a capped trial). When the prediction is above it the run
waits before calling any model; when the spend reaches it the run finishes its round and holds.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median, quantiles
from typing import Any, Iterable

MINIMUM_RUNS_FOR_A_BAND = 4   # quartiles need at least four measurements


@dataclass(frozen=True)
class Prediction:
    language: str
    source_characters: int
    runs: int                       # measured runs of this language the prediction is learned from
    predicted_usd: float | None     # None until the language has a measured run
    upper_usd: float | None         # None until the language has enough runs for a band

    def payload(self) -> dict[str, Any]:
        return {"language": self.language, "sourceCharacters": self.source_characters, "runs": self.runs,
                "predictedUsd": None if self.predicted_usd is None else round(self.predicted_usd, 6),
                "upperUsd": None if self.upper_usd is None else round(self.upper_usd, 6)}


def predict(language: str, source_characters: int, history: Iterable[dict[str, Any]]) -> Prediction:
    """``history``: earlier finished runs as ``{language, sourceCharacters, costUsd}`` (from their provenance records)."""
    rates = [float(run["costUsd"]) / int(run["sourceCharacters"]) for run in history
             if run.get("language") == language and int(run.get("sourceCharacters") or 0) > 0 and run.get("costUsd") is not None]
    if not rates:
        return Prediction(language, source_characters, 0, None, None)
    predicted = median(rates) * source_characters
    upper = None
    if len(rates) >= MINIMUM_RUNS_FOR_A_BAND:
        first, _, third = quantiles(rates, n=4)
        upper = (third + 1.5 * (third - first)) * source_characters
    return Prediction(language, source_characters, len(rates), predicted, upper)
