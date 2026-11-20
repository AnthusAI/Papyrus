from __future__ import annotations

import pytest

from papyrus_content import actor_identity
from papyrus_content.actor_identity import actor_kind


def test_a_caller_with_a_terminal_and_no_agent_runtime_is_a_person():
    assert actor_kind({}, interactive=True) == "person"


def test_a_caller_with_no_terminal_is_an_agent_even_when_it_says_nothing():
    assert actor_kind({}, interactive=False) == "agent"


def test_the_label_still_forces_agent_even_at_a_terminal():
    assert actor_kind({"PAPYRUS_ACTOR_KIND": "Agent"}, interactive=True) == "agent"


def test_claiming_to_be_a_person_does_not_make_one():
    assert actor_kind({"PAPYRUS_ACTOR_KIND": "person"}, interactive=False) == "agent"


@pytest.mark.parametrize("marker", actor_identity.AGENT_RUNTIME_MARKERS)
def test_an_agent_runtime_marker_makes_the_caller_an_agent_even_at_a_terminal(marker):
    assert actor_kind({marker: "1"}, interactive=True) == "agent"


def test_the_terminal_is_read_from_standard_input_when_not_given(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(actor_identity, "terminal_is_interactive", lambda: False)
    assert actor_kind({}) == "agent"
    monkeypatch.setattr(actor_identity, "terminal_is_interactive", lambda: True)
    assert actor_kind({}) == "person"


def test_a_closed_standard_input_is_not_a_terminal(monkeypatch):
    monkeypatch.undo()

    class Closed:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("sys.stdin", Closed())
    assert actor_identity.terminal_is_interactive() is False
