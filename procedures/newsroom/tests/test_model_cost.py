"""Automations step 2 (PPY-112007): usage per model call becomes an estimated cost from a price table kept as data."""
import json

import pytest

from papyrus_content import model_cost as mc
from papyrus_content.procedure_runner_child import UsageCollector


def call(prompt, completion, *, model="gpt-6-luna", cached=0):
    return {"agent": "analyst", "model": model, "provider": "openai", "promptTokens": prompt, "completionTokens": completion, "cachedTokens": cached}


def test_the_shipped_table_prices_gpt_6_luna_from_data():
    prices = mc.load_prices()
    assert prices["gpt-6-luna"]["inputUsdPerMtok"] == 0.10 and prices["gpt-6-luna"]["outputUsdPerMtok"] == 0.50
    assert prices["gpt-6-luna"]["cachedInputUsdPerMtok"] == 0.01 and "LiteLLM" in prices["gpt-6-luna"]["source"]


def test_a_call_costs_input_plus_output_at_per_million_rates():
    estimate = mc.estimate_cost([call(100_000, 10_000)])   # 0.1 M in at 0.10 + 0.01 M out at 0.50
    assert estimate["costUsd"] == pytest.approx(0.015) and estimate["complete"] is True and estimate["unpricedModels"] == []
    assert (estimate["calls"], estimate["promptTokens"], estimate["completionTokens"], estimate["models"]) == (1, 100_000, 10_000, {"gpt-6-luna": 1})


def test_cached_input_is_billed_at_the_cached_rate():
    estimate = mc.estimate_cost([call(100_000, 0, cached=50_000)])   # 50k at 0.10 + 50k at 0.01
    assert estimate["costUsd"] == pytest.approx(0.0055)
    assert mc.estimate_cost([call(1_000, 0, cached=9_999)])["costUsd"] == pytest.approx(1_000 * 0.01 / 1_000_000)   # cached never exceeds the prompt


def test_a_request_over_the_tier_is_billed_whole_at_the_above_rates():
    estimate = mc.estimate_cost([call(300_000, 2_000)])   # 0.3 M at 0.20 + 0.002 M at 0.75
    assert estimate["costUsd"] == pytest.approx(0.06 + 0.0015)
    at_threshold = mc.estimate_cost([call(272_000, 0)])
    assert at_threshold["costUsd"] == pytest.approx(0.0272)   # not above: the standard rate


def test_calls_add_up_and_a_provider_prefix_or_dated_release_finds_the_price():
    estimate = mc.estimate_cost([call(100_000, 0), call(100_000, 0, model="openai/gpt-6-luna"), call(100_000, 0, model="gpt-6-luna-2026-09-01")])
    assert estimate["costUsd"] == pytest.approx(0.03) and estimate["models"] == {
        "gpt-6-luna": 1, "openai/gpt-6-luna": 1, "gpt-6-luna-2026-09-01": 1}


def test_an_unpriced_model_is_listed_and_never_counted_as_free():
    estimate = mc.estimate_cost([call(100_000, 0), call(100_000, 0, model="mystery-1")])
    assert estimate["costUsd"] == pytest.approx(0.01) and estimate["complete"] is False and estimate["unpricedModels"] == ["mystery-1"]
    only_unpriced = mc.estimate_cost([call(100_000, 0, model="mystery-1")])
    assert only_unpriced["costUsd"] is None and only_unpriced["complete"] is False


def test_no_calls_means_no_cost_and_not_zero():
    for calls in (None, [], ["not a call"]):
        estimate = mc.estimate_cost(calls)
        assert estimate["costUsd"] is None and estimate["complete"] is False and estimate["calls"] == 0


def test_bad_token_counts_count_as_zero():
    assert mc.estimate_cost([call("many", None)])["costUsd"] == 0.0
    assert mc.estimate_cost([{"model": "gpt-6-luna", "promptTokens": -5, "completionTokens": True}])["costUsd"] == 0.0


def test_the_price_table_is_data_so_a_new_model_needs_no_code(tmp_path):
    table = tmp_path / "prices.json"
    table.write_text(json.dumps({"models": {"new-model": {"inputUsdPerMtok": 1.0, "outputUsdPerMtok": 2.0}}}))
    prices = mc.load_prices(table)
    assert mc.estimate_cost([call(1_000_000, 500_000, model="new-model")], prices)["costUsd"] == pytest.approx(2.0)
    assert mc.estimate_cost([call(1_000_000, 0)], prices)["costUsd"] is None   # luna is not in this table


def test_an_unreadable_price_table_prices_nothing(tmp_path):
    broken = tmp_path / "prices.json"
    broken.write_text("{nope")
    assert mc.load_prices(broken) == {} and mc.load_prices(tmp_path / "missing.json") == {}
    assert mc.estimate_cost([call(1, 1)], {})["costUsd"] is None


# --- what the child reports -------------------------------------------------------------------------------------------------


class CostEvent:
    """The fields of Tactus's CostEvent that the collector reads."""

    def __init__(self, **fields):
        self.__dict__.update({"agent_name": "analyst", "model": "gpt-6-luna", "provider": "openai", "prompt_tokens": 1000,
                              "completion_tokens": 200, "total_tokens": 1200, "total_cost": 0.0, "cache_tokens": None, **fields})


class LogEvent:
    message = "hello"


def test_the_collector_keeps_the_usage_of_each_model_call_and_ignores_other_events():
    collector = UsageCollector()
    collector.log(LogEvent())
    collector.log(CostEvent())
    collector.log(CostEvent(model="openai/gpt-6-luna", prompt_tokens=5000, cache_tokens=2000))
    assert collector.calls == [
        {"agent": "analyst", "model": "gpt-6-luna", "provider": "openai", "promptTokens": 1000, "completionTokens": 200, "cachedTokens": 0},
        {"agent": "analyst", "model": "openai/gpt-6-luna", "provider": "openai", "promptTokens": 5000, "completionTokens": 200, "cachedTokens": 2000}]
    assert len(collector.cost_events) == 2 and collector.supports_streaming is False   # Tactus totals these itself


def test_the_child_reports_usage_even_when_the_procedure_fails_part_way(tmp_path, monkeypatch):
    from papyrus_content import procedure_runner_child as child

    def failing(source_path, inputs, usage=None):
        usage.log(CostEvent())
        raise RuntimeError("the model refused")
    monkeypatch.setattr(child, "run", failing)
    (tmp_path / "p.tac").write_text("x")
    (tmp_path / "in.json").write_text("{}")
    assert child.main([str(tmp_path / "p.tac"), str(tmp_path / "in.json"), str(tmp_path / "out.json")]) == 1
    outcome = json.loads((tmp_path / "out.json").read_text())
    assert outcome["success"] is False and "the model refused" in outcome["error"] and outcome["usage"][0]["promptTokens"] == 1000


def test_the_child_runs_real_tactus_with_the_collector_attached(tmp_path):
    pytest.importorskip("tactus")
    from papyrus_content import procedure_runner_child as child

    source = tmp_path / "procedure.tac"
    source.write_text('Procedure {\n  input = {},\n  output = {ok = field.boolean{required = true}},\n  function(input)\n    return {ok = true}\n  end\n}\n')
    outcome = child.run(source, {})
    assert outcome["success"] is True and outcome["output"] == {"ok": True} and outcome["usage"] == []   # no model call, no usage
