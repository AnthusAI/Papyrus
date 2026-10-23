"""Estimated cost of a procedure run from the model usage it reports (PPY-112007).

`procedure_runner_child` reports one usage entry per model call. This turns them into dollars with a small
price table kept as data (`data/model_prices.json`), so adding or correcting a model never needs a code change.
A call whose model has no price is listed as unpriced and left out of the total: the estimate then says it is
partial. Nothing here is a bill.

A request whose input exceeds a model's `aboveInputTokens` is billed whole at that model's above-tier rates.
Cached input tokens are billed at the cached rate; the rest of the input at the input rate.
"""
from __future__ import annotations

import json
from importlib import resources
from typing import Any

PRICE_FILE = "model_prices.json"
TOKENS_PER_PRICE = 1_000_000


def load_prices(path=None) -> dict[str, dict[str, Any]]:
    """The model price table. An unreadable table prices nothing (every model is reported unpriced)."""
    try:
        text = (resources.files(__package__).joinpath("data", PRICE_FILE).read_text(encoding="utf-8")
                if path is None else path.read_text(encoding="utf-8"))
        models = json.loads(text).get("models")
        return models if isinstance(models, dict) else {}
    except (OSError, ValueError):
        return {}


def price_for(model: str | None, prices: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The price entry for a reported model name: exact, without a provider prefix, or the longest listed prefix
    (a dated release such as gpt-6-luna-2026-09-01)."""
    name = str(model or "").strip().lower().rsplit("/", 1)[-1]
    if name in prices:
        return prices[name]
    matches = [key for key in prices if name.startswith(key + "-")]
    return prices[max(matches, key=len)] if matches else None


def _tokens(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def call_cost(call: dict[str, Any], price: dict[str, Any]) -> float:
    prompt, output = _tokens(call.get("promptTokens")), _tokens(call.get("completionTokens"))
    cached = min(_tokens(call.get("cachedTokens")), prompt)
    above = prompt > price.get("aboveInputTokens", float("inf"))
    input_rate = price.get("aboveInputUsdPerMtok", price["inputUsdPerMtok"]) if above else price["inputUsdPerMtok"]
    output_rate = price.get("aboveOutputUsdPerMtok", price["outputUsdPerMtok"]) if above else price["outputUsdPerMtok"]
    cached_rate = price.get("cachedInputUsdPerMtok", input_rate)
    return ((prompt - cached) * input_rate + cached * cached_rate + output * output_rate) / TOKENS_PER_PRICE


def estimate_cost(calls: list[dict[str, Any]] | None, prices: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """`{costUsd, complete, unpricedModels, calls, promptTokens, completionTokens, models}` for the reported calls.

    `costUsd` is None when nothing was reported or no call could be priced."""
    prices = load_prices() if prices is None else prices
    calls = [call for call in (calls or []) if isinstance(call, dict)]
    total, priced, unpriced, models = 0.0, 0, set(), {}
    for call in calls:
        model = str(call.get("model") or "unknown")
        models[model] = models.get(model, 0) + 1
        price = price_for(model, prices)
        if price is None:
            unpriced.add(model)
            continue
        total += call_cost(call, price)
        priced += 1
    return {"costUsd": round(total, 6) if priced else None, "complete": bool(calls) and not unpriced,
            "unpricedModels": sorted(unpriced), "calls": len(calls),
            "promptTokens": sum(_tokens(call.get("promptTokens")) for call in calls),
            "completionTokens": sum(_tokens(call.get("completionTokens")) for call in calls),
            "models": models}
