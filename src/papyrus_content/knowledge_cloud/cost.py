"""What a stage of the cloud knowledge run cost: Fargate compute plus the language-model calls it made (PPY cost accounting).

Every ledger row of a stage carries ``details.cost``::

    {"computeSeconds": 412, "computeBasis": "task", "vCpu": 4, "memoryGiB": 16, "ephemeralStorageGiB": 40, "computeUsd": 0.0214,
     "llm": {"calls": 35, "inputTokens": 91000, "outputTokens": 12000, "cachedInputTokens": 0, "usd": 0.0151,
             "byModel": {"gpt-6-luna": {"calls": 35, "inputTokens": 91000, "outputTokens": 12000, "usd": 0.0151}}},
     "totalUsd": 0.0365, "priceBasis": "...", "attempts": 1}

An estimate from list prices and the usage objects the model API returned, never a bill. A figure that cannot be known is
``null`` with a ``reason`` beside it (an unknown task size, a model with no price, a response without usage); ``totalUsd`` then
sums what is known and ``partial`` is true. Nothing here may fail a stage: the caller treats an error as "no cost recorded".
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections.abc import Callable, Mapping
from typing import Any

from .. import model_cost

#: Fargate on ARM (Graviton), Linux, US East (N. Virginia), per hour, as used in docs/knowledge-cloud-run.md. Recorded 2026-10-26
#: from the AWS Fargate pricing page (https://aws.amazon.com/fargate/pricing/); check it there before trusting a change in the bill.
FARGATE_ARM_US_EAST_1 = {
    "asOf": "2026-10-26",
    "source": "AWS Fargate pricing, Linux/ARM, US East (N. Virginia)",
    "vCpuUsdPerHour": 0.03238,
    "memoryUsdPerGbHour": 0.00356,
    "ephemeralStorageUsdPerGbHour": 0.000111,
    "freeEphemeralStorageGiB": 20,
    "minimumSeconds": 60,
}
PRICE_BASIS = f"{FARGATE_ARM_US_EAST_1['source']} ({FARGATE_ARM_US_EAST_1['asOf']}); {model_cost.PRICE_FILE} for models"


def _money(value: float) -> float:
    return round(value, 6)


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _sum_known(*values: float | None) -> float:
    return sum(value for value in values if value is not None)


# -- the task a stage runs in -----------------------------------------------------------------------------------------
def _parse_time(text: Any) -> dt.datetime | None:
    if not isinstance(text, str) or not text:
        return None
    clean = text.strip().replace("Z", "+00:00")
    head, plus, tail = clean.partition("+")
    if "." in head:  # ECS reports nanoseconds; datetime holds microseconds
        whole, _dot, fraction = head.partition(".")
        head = f"{whole}.{fraction[:6]}"
    try:
        parsed = dt.datetime.fromisoformat(head + (plus + tail if plus else ""))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _fetch_task_metadata(environment: Mapping[str, str]) -> dict[str, Any]:
    base = (environment.get("ECS_CONTAINER_METADATA_URI_V4") or "").strip()
    if not base:
        return {}
    import urllib.request  # noqa: PLC0415

    with urllib.request.urlopen(base.rstrip("/") + "/task", timeout=2) as response:  # noqa: S310 - the link-local ECS endpoint
        return json.loads(response.read().decode("utf-8"))


def task_resources(environment: Mapping[str, str], fetch: Callable[[Mapping[str, str]], dict[str, Any]] = _fetch_task_metadata) -> dict[str, Any]:
    """The size of the Fargate task this process runs in, from the ECS task metadata endpoint (v4) the platform provides.

    ``KNOWLEDGE_TASK_VCPU`` and ``KNOWLEDGE_TASK_MEMORY_MIB`` fill in what the endpoint does not say. Any of ``vCpu``, ``memoryGiB``,
    ``ephemeralStorageGiB`` and ``startedAt`` (when the task began to pull its image, which is when Fargate starts to bill) may be None."""
    try:
        metadata = fetch(environment) or {}
    except Exception:  # noqa: BLE001 - outside ECS, or an endpoint that does not answer: the size is then unknown
        metadata = {}
    limits = metadata.get("Limits") or {}
    vcpu = limits.get("CPU") or _number(environment.get("KNOWLEDGE_TASK_VCPU")) or None
    memory_mib = limits.get("Memory") or _number(environment.get("KNOWLEDGE_TASK_MEMORY_MIB")) or None
    storage_mib = (metadata.get("EphemeralStorageMetrics") or {}).get("Reserved")
    return {
        "vCpu": float(vcpu) if vcpu else None,
        "memoryGiB": float(memory_mib) / 1024 if memory_mib else None,
        "ephemeralStorageGiB": round(float(storage_mib) / 1024) if storage_mib else None,
        "startedAt": _parse_time(metadata.get("PullStartedAt")),
    }


def _plain_number(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(float(value), 3)


def compute_usd(seconds: int, vcpu: float, memory_gib: float, storage_gib: float | None) -> float:
    rates = FARGATE_ARM_US_EAST_1
    hours = seconds / 3600
    extra_storage = max((storage_gib or 0) - rates["freeEphemeralStorageGiB"], 0)
    return _money(hours * (vcpu * rates["vCpuUsdPerHour"] + memory_gib * rates["memoryUsdPerGbHour"] + extra_storage * rates["ephemeralStorageUsdPerGbHour"]))


# -- the model calls a stage made ------------------------------------------------------------------------------------
def usage_entry(model: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """One model call from a Responses API body: ``{model, promptTokens, completionTokens, cachedTokens}``; ``usageMissing`` when
    the response carried no usage object (the call happened, its tokens are unknown)."""
    usage = body.get("usage") if isinstance(body, Mapping) else None
    entry: dict[str, Any] = {"model": str(body.get("model") or model) if isinstance(body, Mapping) else model}
    if not isinstance(usage, Mapping):
        return {**entry, "usageMissing": True}
    entry["promptTokens"] = int(usage.get("input_tokens") or 0)
    entry["completionTokens"] = int(usage.get("output_tokens") or 0)
    entry["cachedTokens"] = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
    return entry


def llm_cost(calls: list[dict[str, Any]], prices: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """``{calls, inputTokens, outputTokens, cachedInputTokens, usd, byModel}`` for the usage entries of a stage. ``usd`` is None, with a
    ``reason``, when any call has no usage or its model has no price (the tokens that are known are still counted)."""
    prices = model_cost.load_prices() if prices is None else prices
    by_model: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        grouped.setdefault(str(call.get("model") or "unknown"), []).append(call)
    for model, group in sorted(grouped.items()):
        known = [call for call in group if not call.get("usageMissing")]
        estimate = model_cost.estimate_cost(known, prices)
        row: dict[str, Any] = {
            "calls": len(group), "inputTokens": estimate["promptTokens"], "outputTokens": estimate["completionTokens"],
            "cachedInputTokens": sum(model_cost._tokens(call.get("cachedTokens")) for call in known),
        }
        if len(known) < len(group):
            row["usd"], row["reason"] = None, f"{len(group) - len(known)} response(s) carried no usage object"
        elif model in estimate["unpricedModels"]:
            row["usd"], row["reason"] = None, f"no price for model {model} in {model_cost.PRICE_FILE}"
        else:
            row["usd"] = estimate["costUsd"] if estimate["costUsd"] is not None else 0.0
        if row.get("reason"):
            reasons.append(f"{model}: {row['reason']}")
        by_model[model] = row
    usd = None if reasons else _money(sum(row["usd"] for row in by_model.values()))
    result: dict[str, Any] = {
        "calls": len(calls),
        "inputTokens": sum(row["inputTokens"] for row in by_model.values()),
        "outputTokens": sum(row["outputTokens"] for row in by_model.values()),
        "cachedInputTokens": sum(row["cachedInputTokens"] for row in by_model.values()),
        "usd": usd,
        "byModel": by_model,
    }
    if reasons:
        result["reason"] = "; ".join(reasons)
    return result


# -- one stage ---------------------------------------------------------------------------------------------------------
def stage_cost(*, elapsed_seconds: float, task: Mapping[str, Any], now: dt.datetime, calls: list[dict[str, Any]],
               prices: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The cost of one attempt of a stage. The seconds run from the task's first image pull (when Fargate starts to bill) to now when the
    platform says so, otherwise from the stage's start; Fargate bills at least 60 seconds."""
    started = task.get("startedAt")
    measured = (now - started).total_seconds() if isinstance(started, dt.datetime) else None
    basis = "task" if measured is not None and measured >= elapsed_seconds else "stage"
    seconds = max(math.ceil(measured if basis == "task" else elapsed_seconds), FARGATE_ARM_US_EAST_1["minimumSeconds"])
    vcpu, memory, storage = task.get("vCpu"), task.get("memoryGiB"), task.get("ephemeralStorageGiB")
    cost: dict[str, Any] = {
        "computeSeconds": seconds, "computeBasis": basis,
        "vCpu": _plain_number(vcpu), "memoryGiB": _plain_number(memory), "ephemeralStorageGiB": _plain_number(storage),
    }
    if vcpu and memory:
        cost["computeUsd"] = compute_usd(seconds, float(vcpu), float(memory), storage)
    else:
        cost["computeUsd"], cost["computeReason"] = None, "the task size is unknown (no ECS task metadata, no KNOWLEDGE_TASK_VCPU / KNOWLEDGE_TASK_MEMORY_MIB)"
    cost["llm"] = llm_cost(calls, prices)
    return finish_cost(cost)


def finish_cost(cost: dict[str, Any]) -> dict[str, Any]:
    """Set ``totalUsd`` (what is known), ``partial`` and ``priceBasis`` on a cost record."""
    llm_usd = cost["llm"]["usd"]
    cost["totalUsd"] = _money(_sum_known(cost.get("computeUsd"), llm_usd))
    cost["partial"] = cost.get("computeUsd") is None or llm_usd is None
    cost["priceBasis"] = PRICE_BASIS
    if not cost["partial"]:
        cost.pop("partial")
    return cost


def _merge_llm(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    for source in (first.get("byModel") or {}, second.get("byModel") or {}):
        for model, row in source.items():
            into = by_model.setdefault(model, {"calls": 0, "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "usd": 0.0})
            for key in ("calls", "inputTokens", "outputTokens", "cachedInputTokens"):
                into[key] += int(row.get(key) or 0)
            into["usd"] = None if into["usd"] is None or row.get("usd") is None else _money(into["usd"] + row["usd"])
            if row.get("reason"):
                into["reason"] = row["reason"]
    reasons = [f"{model}: {row['reason']}" for model, row in by_model.items() if row.get("reason")]
    merged: dict[str, Any] = {
        "calls": int(first.get("calls") or 0) + int(second.get("calls") or 0),
        "inputTokens": int(first.get("inputTokens") or 0) + int(second.get("inputTokens") or 0),
        "outputTokens": int(first.get("outputTokens") or 0) + int(second.get("outputTokens") or 0),
        "cachedInputTokens": int(first.get("cachedInputTokens") or 0) + int(second.get("cachedInputTokens") or 0),
        "usd": None if reasons else _money(sum(row["usd"] for row in by_model.values())),
        "byModel": by_model,
    }
    if reasons:
        merged["reason"] = "; ".join(reasons)
    return merged


def add_attempt(earlier: Mapping[str, Any] | None, latest: dict[str, Any]) -> dict[str, Any]:
    """Fold the cost of the failed attempts before this one into it: a retry pays again, and the stage's cost is all of it."""
    if not earlier:
        return {**latest, "attempts": 1}
    merged = {**latest}
    merged["computeSeconds"] = int(earlier.get("computeSeconds") or 0) + int(latest.get("computeSeconds") or 0)
    merged["computeUsd"] = None if earlier.get("computeUsd") is None or latest.get("computeUsd") is None else _money(earlier["computeUsd"] + latest["computeUsd"])
    if merged["computeUsd"] is None:
        merged["computeReason"] = latest.get("computeReason") or earlier.get("computeReason")
    else:
        merged.pop("computeReason", None)
    merged["llm"] = _merge_llm(earlier.get("llm") or {}, latest["llm"])
    merged["attempts"] = int(earlier.get("attempts") or 1) + 1
    merged.pop("partial", None)
    return finish_cost(merged)


# -- one run -----------------------------------------------------------------------------------------------------------
def run_total(rows: list[Mapping[str, Any]], stage_order: tuple[str, ...]) -> dict[str, Any]:
    """The cost and duration of one execution from its stage rows (ledger items, numbers already as float/int).

    ``stages`` lists each stage's seconds and dollars; a stage with no recorded cost (a run from before cost accounting) makes the total partial."""
    by_stage = {row.get("stage"): row for row in rows if row.get("stage") in stage_order}
    stages: dict[str, dict[str, Any]] = {}
    seconds, compute, llm_usd, partial = 0, 0.0, 0.0, False
    calls = input_tokens = output_tokens = 0
    starts, finishes = [], []
    for stage in stage_order:
        row = by_stage.get(stage)
        if row is None:
            continue
        cost = (row.get("details") or {}).get("cost")
        entry: dict[str, Any] = {"status": row.get("status"), "seconds": duration_seconds(row)}
        if cost:
            entry.update({"computeSeconds": cost.get("computeSeconds"), "totalUsd": cost.get("totalUsd")})
            seconds += int(cost.get("computeSeconds") or 0)
            compute += _number(cost.get("computeUsd"))
            llm_usd += _number((cost.get("llm") or {}).get("usd"))
            calls += int((cost.get("llm") or {}).get("calls") or 0)
            input_tokens += int((cost.get("llm") or {}).get("inputTokens") or 0)
            output_tokens += int((cost.get("llm") or {}).get("outputTokens") or 0)
            partial = partial or bool(cost.get("partial"))
        else:
            partial = True
        stages[stage] = entry
        for key, bucket in (("startedAt", starts), ("finishedAt", finishes)):
            moment = _parse_time(row.get(key))
            if moment:
                bucket.append(moment)
    done = [stage for stage in stage_order if by_stage.get(stage, {}).get("status") == "succeeded"]
    failed = [stage for stage in stage_order if by_stage.get(stage, {}).get("status") == "failed"]
    status = "succeeded" if len(done) == len(stage_order) else "failed" if failed else "running" if starts else "empty"
    partial = partial or len(stages) < len(stage_order)
    total: dict[str, Any] = {
        "status": status,
        "durationSeconds": int((max(finishes) - min(starts)).total_seconds()) if starts and finishes else None,
        "computeSeconds": seconds, "computeUsd": _money(compute),
        "llm": {"calls": calls, "inputTokens": input_tokens, "outputTokens": output_tokens, "usd": _money(llm_usd)},
        "totalUsd": _money(compute + llm_usd), "stages": stages,
    }
    if partial:
        total["partial"] = True
    return total


def duration_seconds(row: Mapping[str, Any]) -> int | None:
    started, finished = _parse_time(row.get("startedAt")), _parse_time(row.get("finishedAt"))
    return int((finished - started).total_seconds()) if started and finished else None
