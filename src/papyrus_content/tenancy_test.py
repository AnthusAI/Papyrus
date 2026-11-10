from __future__ import annotations

from papyrus_content.tenancy import TENANCY_MODE_ENVIRONMENT_VARIABLE, is_shared_stack


def test_unset_is_dedicated(monkeypatch):
    monkeypatch.delenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, raising=False)
    assert is_shared_stack() is False


def test_shared_is_reported(monkeypatch):
    monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, "shared")
    assert is_shared_stack() is True


def test_dedicated_and_unknown_values_are_not_shared(monkeypatch):
    for value in ("dedicated", "", "pooled"):
        monkeypatch.setenv(TENANCY_MODE_ENVIRONMENT_VARIABLE, value)
        assert is_shared_stack() is False
