"""What an image costs, from a price file that holds only prices someone has written down. A model with no price is reported unpriced, never as free."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PRICE_FILE = Path(__file__).resolve().parents[1] / "data" / "image_model_prices.json"
BATCH_FACTOR_KEY = "batchFactor"


@lru_cache(maxsize=1)
def _prices() -> dict:
    return json.loads(PRICE_FILE.read_text(encoding="utf-8")).get("models", {})


def estimate_cost(model: str | None, count: int, speed: str) -> dict:
    entry = _prices().get(model or "")
    if not entry or "usdPerImage" not in entry:
        return {"priced": False, "basis": f"{model or 'No model'} has no price on file, so no cost is shown. Unpriced is not free."}
    factor = entry.get(BATCH_FACTOR_KEY, 1) if speed == "batch" else 1
    each = round(entry["usdPerImage"] * factor, 6)
    return {"priced": True, "usd": round(each * count, 6), "perCandidate": each, "basis": entry.get("source", "")}
