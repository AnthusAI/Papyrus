from papyrus_content import run_attention


def test_only_failed_and_unknown_runs_carry_the_key():
    assert run_attention.attention_fields("failed", "2026-11-19T09:00:00Z") == {"attentionKey": "attention", "dueAt": "2026-11-19T09:00:00Z"}
    assert run_attention.attention_fields("unknown", "2026-11-19T09:00:00Z")["attentionKey"] == "attention"
    for outcome in ("acted", "nothing", "asked", None):
        assert run_attention.attention_fields(outcome, "2026-11-19T09:00:00Z") == {}


def test_a_run_with_no_finish_time_has_no_attention_time():
    assert run_attention.attention_fields("failed", None) == {}


def test_an_acknowledged_run_needs_nobody():
    assert run_attention.needs_attention({"outcome": "failed"})
    assert not run_attention.needs_attention({"outcome": "failed", "acknowledgedAt": "2026-11-19T10:00:00Z"})
    assert not run_attention.needs_attention({"outcome": "acted"})
