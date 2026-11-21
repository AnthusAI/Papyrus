"""Adopting an automation onto a standing responsibility (PPY-c8175e).

An automation that was running before the agent policy existed is not enforced by it until a person adopts it: names the one
responsibility it fills. Adoption sets ``Automation.responsibility`` and nothing else. It never writes the policy document, so it never
raises a rung and never starts or stops a run by itself; the rung is a separate, explicit admin action (``AgentPolicyStore.set_rung``).
Until both are done the runner starts no run for the automation and records ``nothing`` with the reason ``not_adopted`` or ``rung_off``.
"""
from __future__ import annotations

from typing import Any

from .actor_identity import actor_kind
from .responsibilities import BY_KEY
from .automations import AutomationError, read_record, stored_payload, build_record
from .images.handlers import Caller


def delegated_adopter(caller: Caller, *, person: str, quote: str, agent: str) -> tuple[Caller, str]:
    """An agent adopting on the instruction of the admin whose session it runs in (``agent_policy/delegation.py``): recorded as that person's, entered by the agent.
    Adoption sets no rung, so it is checked as the rung ``off``; the rung stays a separate change with its own ceiling."""
    from .agent_policy import PolicyError
    from .agent_policy.delegation import delegated_caller

    try:
        return delegated_caller(caller, person=person, quote=quote, agent=agent, rung="off")
    except PolicyError as error:
        raise AutomationError(f"{error.message} Nothing was changed.") from error


def adopt(client, caller: Caller, automation_id: str, responsibility: str, *, apply: bool, now: str | None = None,
          on_instruction_of: str = "", quote: str = "", agent: str = "") -> dict[str, Any]:
    """Name the responsibility ``automation_id`` fills. An admin who is a person adopts, or an agent in that person's session on their named instruction.
    Dry run (``apply`` False) writes nothing."""
    instruction = ""
    if caller.kind == "agent" and (on_instruction_of or quote or agent):
        caller, instruction = delegated_adopter(caller, person=on_instruction_of, quote=quote, agent=agent)
    if caller.kind != "person" or not caller.is_admin or not caller.subject:
        raise AutomationError("only an admin who is a person adopts an automation onto a responsibility. Nothing was changed.")
    if responsibility not in BY_KEY:
        raise AutomationError(f"{responsibility!r} is not a responsibility. Choose one of: {', '.join(sorted(BY_KEY))}.")
    row = client.get_record("Automation", automation_id)
    if not row:
        raise AutomationError(f"automation {automation_id} does not exist.")
    existing = read_record(row)
    current = existing.get("responsibility")
    if current and current != responsibility:
        raise AutomationError(f"automation {automation_id} is already adopted as {current}; it is not changed to {responsibility}.")
    result = {"automationId": automation_id, "responsibility": responsibility, "was": current, "changed": current != responsibility,
              "applied": False, **({"instruction": instruction} if instruction else {}), "note": "Adopting does not set a rung. Until an admin sets one in the agent policy, the runner records rung_off and starts nothing."}
    if current == responsibility or not apply:
        return result
    record = build_record({"id": automation_id, "responsibility": responsibility}, existing=existing, actor=caller.subject, now=now)
    client.update_record("Automation", stored_payload(record))
    return {**result, "applied": True}


def run_command(options: dict[str, Any], *, as_json: bool, apply: bool) -> None:
    import json
    import os

    from .graphql_authoring import create_authoring_client
    from .images.profile_handlers import identify

    automation_id, responsibility = options.get("id"), options.get("responsibility")
    if not isinstance(automation_id, str) or not isinstance(responsibility, str):
        raise AutomationError("papyrus automations adopt needs --id <automation id> --responsibility <responsibility>.")
    client = create_authoring_client()[0]
    kind = actor_kind()
    caller = identify(client, Caller(kind=kind))
    result = adopt(client, caller, automation_id, responsibility, apply=apply, on_instruction_of=str(options.get("on-instruction-of") or ""),
                   quote=str(options.get("quote") or ""), agent=str(options.get("agent") or ""))
    if as_json:
        print(json.dumps({"ok": True, "command": "automations adopt", "dryRun": not apply, **result}, indent=2))
        return
    state = "already adopted, nothing to do" if not result["changed"] else ("adopted" if result["applied"] else "dry run, nothing written")
    print("\t".join(["automations", automation_id, f"responsibility {responsibility}", state]))
    print(result["note"])
