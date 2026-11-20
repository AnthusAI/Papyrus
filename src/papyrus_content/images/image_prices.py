"""What an image costs, from a price file that holds only prices someone has read from the provider's published pricing.

OpenAI prices gpt-image-2.5-flare per token and publishes no per-image figure, so a plan's estimate stays unpriced (never free) and the cost of a picture is
worked out afterwards from the tokens the provider reports it used. Rates live in ``data/image_model_prices.json`` with their source and the date read.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PRICE_FILE = Path(__file__).resolve().parents[1] / "data" / "image_model_prices.json"
PER_MILLION = 1_000_000


@lru_cache(maxsize=1)
def _prices() -> dict:
    return json.loads(PRICE_FILE.read_text(encoding="utf-8")).get("models", {})


def estimate_cost(model: str | None, count: int, speed: str) -> dict:
    entry = _prices().get(model or "")
    if not entry or "usdPerImage" not in entry:
        return {"priced": False, "basis": f"{model or 'No model'} has no per-image price published, so no cost is shown before it is made. Unpriced is not free."}
    each = round(entry["usdPerImage"] * (entry.get("batchFactor", 1) if speed == "batch" else 1), 6)
    return {"priced": True, "usd": round(each * count, 6), "perCandidate": each, "basis": entry.get("source", "")}


def actual_cost(model: str | None, input_tokens: int, output_tokens: int, speed: str) -> float | None:
    """The cost of one picture from the tokens the provider reported, or None when the rates are not on file (including Batch input, which is not published)."""
    rates = (_prices().get(model or "") or {}).get("tokenRates")
    if not rates:
        return None
    if speed == "batch":
        if "batchInputUsdPerMtok" not in rates or "batchOutputUsdPerMtok" not in rates:
            return None
        return round((input_tokens * rates["batchInputUsdPerMtok"] + output_tokens * rates["batchOutputUsdPerMtok"]) / PER_MILLION, 6)
    return round((input_tokens * rates["inputUsdPerMtok"] + output_tokens * rates["outputUsdPerMtok"]) / PER_MILLION, 6)
