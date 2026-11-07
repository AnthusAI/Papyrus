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
