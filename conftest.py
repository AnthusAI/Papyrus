"""Pytest configuration for Papyrus Python packages under src/."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# Variables that choose a GraphQL lane or a signed-in site. A developer's machine has a real `papyrus login` session in
# ~/.config/papyrus and often a lane in the shell; tests must see neither (PPY-5f119a).
SIGN_IN_ENVIRONMENT = ("PAPYRUS_GRAPHQL_AUTH", "PAPYRUS_CLI_AUTH_CONFIG", "PAPYRUS_GRAPHQL_ENDPOINT")


@pytest.fixture(autouse=True)
def _no_real_sign_in(monkeypatch, tmp_path_factory):
    """Each test starts signed out, in an empty sign-in directory, with no lane chosen; a test that wants a lane sets it."""
    for name in SIGN_IN_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path_factory.mktemp("papyrus-state")))
