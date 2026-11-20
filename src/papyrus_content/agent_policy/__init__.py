"""The agent policy document: how far each always-on agent may go on one site (PPY-51ea61, slice E1).

One versioned ``SiteDocument`` of kind ``agents`` per site. ``document`` says what it may hold, ``resolve`` answers what rung applies
and whether a run may start, and ``store`` changes it (admins only, each change a new version with who, when and why).
"""
from .document import EMPTY_DOCUMENT, RUNGS, SCOPE_DIMENSIONS, PolicyError, validate_document
from .resolve import Effective, PolicyState, StartDecision, decide_start, effective
from .run_gate import Gate, PersonStart, PolicyGate, PolicyNotLocated, PolicyUnreadable, RunDecision, UnlocatedPolicy
from . import set_rung
from .store import AgentPolicyStore

__all__ = [
    "AgentPolicyStore", "Gate", "PersonStart", "PolicyGate", "PolicyNotLocated", "PolicyUnreadable", "RunDecision", "UnlocatedPolicy", "EMPTY_DOCUMENT", "Effective", "PolicyError", "PolicyState", "RUNGS", "SCOPE_DIMENSIONS", "StartDecision", "set_rung",
    "decide_start", "effective", "validate_document",
]
