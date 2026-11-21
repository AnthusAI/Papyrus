"""An agent changing the agent policy on a named person's instruction (the way ``stories set-stars --agent`` rates for the signed-in person).

The signed-in session is that person's (an admin, read from the token), the agent is named and recorded, and the person's own words are kept in the reason. The agent
must name the person the session belongs to and quote them, and may not raise a rung above ``DELEGATED_RUNG_CEILING``: anything higher is the person's own change.
Nothing can verify that the person said the words; they are a record, not proof, and the ceiling and the admin-session rule limit what a wrong claim can do.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..agent_rungs import RUNGS
from .document import PolicyError

#: The highest rung an agent may set on a person's instruction. Anything above it stays a person's own change.
DELEGATED_RUNG_CEILING = "prepare"


def delegated_caller(caller: Any, *, person: str, quote: str, agent: str, rung: str) -> tuple[Any, str]:
    """``(the caller to change the policy as, the words to add to the reason)``. Raises ``PolicyError`` when it may not."""
    person, quote, agent = (person or "").strip(), (quote or "").strip(), (agent or "").strip()
    if not (person and quote and agent):
        raise PolicyError("blocked", "An agent changes the agent policy only on a named person's instruction: give the person, their words and your name.")
    if not caller.is_admin or not caller.subject:
        raise PolicyError("not_authorized", "The signed-in session is not an admin's, so nothing can be changed on anyone's instruction.")
    if caller.subject.strip().lower() != person.lower():
        raise PolicyError("not_authorized", f"This session belongs to {caller.subject}, not {person}: an agent may act only on the instruction of the person whose session it runs in.")
    if rung not in RUNGS:
        raise PolicyError("invalid_input", f"rung is one of: {', '.join(RUNGS)}.")
    if RUNGS.index(rung) > RUNGS.index(DELEGATED_RUNG_CEILING):
        raise PolicyError("blocked", f"An agent may set a rung up to {DELEGATED_RUNG_CEILING} on a person's instruction; {rung} is the person's own change.")
    return replace(caller, kind="person", subject=f"{caller.subject} via cli ({agent})"), f"(entered by {agent} on the instruction of {person}: \"{quote}\")"
