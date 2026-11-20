"""Pytest configuration for Papyrus Python packages under src/."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))



import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _checklist_gate_off():
    """Publishing refuses while a required checklist step is open (docs/story-procedure.md). Tests about something else publish Stories freely, so the gate is
    off for the whole session (module fixtures publish too); a test module that exercises the rule asks for ``real_checklist_gate``."""
    from papyrus_content import story_checklist

    real = story_checklist.require_checklist_closed
    story_checklist.require_checklist_closed = lambda client, item: None
    yield real
    story_checklist.require_checklist_closed = real


@pytest.fixture
def real_checklist_gate(_checklist_gate_off, monkeypatch):
    from papyrus_content import story_checklist

    monkeypatch.setattr(story_checklist, "require_checklist_closed", _checklist_gate_off)


# Variables that choose a GraphQL lane or a signed-in site. A developer's machine often has a real `papyrus login` session in
# ~/.config/papyrus and a lane in the shell; CI has neither. Every test starts like CI: signed out, in an empty sign-in directory,
# with no lane named (the signed-in lane is the default). A test that wants a lane or a session sets it (PPY-5f119a).
SIGN_IN_ENVIRONMENT = ("PAPYRUS_GRAPHQL_AUTH", "PAPYRUS_CLI_AUTH_CONFIG", "PAPYRUS_SITE")


@pytest.fixture(autouse=True)
def _signed_out_by_default(monkeypatch, tmp_path_factory):
    for name in SIGN_IN_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PAPYRUS_CLI_STATE_DIR", str(tmp_path_factory.mktemp("papyrus-state")))
