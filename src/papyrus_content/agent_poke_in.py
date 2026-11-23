"""Poke-in operations: pause, resume and wake now (PPY-e6f31e, slice H3; the kill switches, PPY-3f68f4, slice J2).

Each is one row of the operation table (``agents_pause``, ``agents_resume``, ``agents_wake`` in ``images/operations.py``), so the newsroom and the command line
ask for the same thing by the same name and get the same answer from this module:

* **Pause** one agent, or every agent on the site, with a reason. It is a new version of the site's agent policy (who, when and why), written only through the
  agent-policy function for a signed-in person. The runner reads the policy at the start of every run, so a pause stops the next run: the wake still arrives,
  and its run record says "nothing to do" with the reason ``paused``. The record keeps the wake (``procedure_runner.kept_wake``).
* **Resume** lifts the pause, as a new version. Ticks a timer skipped stay skipped. A change wake the pause stopped is not lost: each subject whose latest wake
  for the agent was stopped by the pause gets that wake once more, found through the run index by agent and request time from when the pause began, never by
  reading a table. Each sent wake has a key made from the stopped wake's key and the policy version of the resume, so running the catch-up again sends nothing
  new, and two stopped wakes for one subject send one.
* **Wake now** sends one agent's latest wake for one subject again, through the site's wake queue, once. The run re-reads the subject as it is now, as every run
  does; the wake only says which subject. An agent that has never been woken for the subject has nothing to send, and is told so.

A wake sent again keeps the stopped wake's subject and version, and its trigger says who sent it, why, and which wake it repeats; the run record's summary says
the same, so who and why are on the run as well as on the policy version.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, Mapping

from . import agent_wakes, wake_keys
from .agent_policy.document import PolicyError
from .agent_policy.resolve import PolicyState
from .agent_policy.store import AgentPolicyStore
from .images.handlers import Caller

RUN_MODEL = "ProcedureRun"
RUN_WAKES_INDEX = "procedureRunWakesByAutomation"
PAUSED_REASON = "paused"
RESUMED, WOKEN = "resume", "wake"
MAX_SUMMARY_CHARACTERS = 500


class PokeInError(Exception):
    """A poke-in the records cannot carry out. ``code`` is one of the operation table's error codes."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def person_label(caller: Caller) -> str:
    return caller.subject or "a person"


# --- the run records -------------------------------------------------------------------------------------------------------------------------------


class RunLedger:
    """One agent's runs, through the run index by automation and request time: the runs from a moment on, or the newest first. Never a list of the table."""

    def __init__(self, client: Any, tenant_id: str | None):
        self._client, self._tenant_id = client, tenant_id

    def _of_site(self, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        from .tenancy import rows_for_tenant

        return rows_for_tenant(RUN_MODEL, self._tenant_id, rows)

    def runs_since(self, automation_id: str, since: str) -> list[dict[str, Any]]:
        rows = self._client.list_by_index(RUN_WAKES_INDEX, automation_id, sort_condition={"ge": since})
        return sorted(self._of_site(rows), key=lambda row: (str(row.get("requestedAt") or ""), str(row.get("id") or "")))

    def newest_first(self, automation_id: str) -> Iterator[dict[str, Any]]:
        for row in self._client.iterate_newest_first(RUN_WAKES_INDEX, automation_id):
            if self._of_site([row]):
                yield row


def kept_wake(row: Mapping[str, Any]) -> dict[str, Any] | None:
    """The wake a run record kept (``procedure_runner.kept_wake``), or None when it kept none."""
    wake = row.get("wake")
    if isinstance(wake, str):
        try:
            wake = json.loads(wake)
        except ValueError:
            return None
    return wake if isinstance(wake, dict) and wake.get("wakeKey") else None


def subject_of(wake: Mapping[str, Any]) -> str:
    return agent_wakes.wake_of(dict(wake))["subject"]


def sent_again(wake: Mapping[str, Any], *, marker: str, poke: str, by: str, reason: str, at: str) -> dict[str, Any]:
    """The same wake under a new key: the stopped wake's owner, subject and version, and what changed with ``+<marker>`` added, so sending it again is one
    run and a different poke is another. Its trigger says who sent it, why, and which wake it repeats."""
    key = wake_keys.checked(wake.get("wakeKey"))
    parts = key.split(wake_keys.SEPARATOR)
    if len(parts) != 4:
        raise PokeInError("constraint_conflict", f"{key} is not a change wake, so it is not sent again: a timer's tick or a person's run is never repeated.")
    owner, subject, version, what = parts
    trigger = dict(wake.get("trigger") or {})
    verb = "resumed" if poke == RESUMED else "woke it now"
    summary = f"{by} {verb} ({reason.strip()}); this repeats: {trigger.get('summary') or key}"
    trigger.update(summary=summary[:MAX_SUMMARY_CHARACTERS], poke={"kind": poke, "by": by, "reason": reason.strip(), "at": at, "repeats": key})
    return {**dict(wake), "wakeKey": wake_keys.change_key(owner, subject, version, f"{what}+{marker}"), "trigger": trigger}


# --- pause and resume ------------------------------------------------------------------------------------------------------------------------------


def _held(state: PolicyState, agent: str | None) -> dict[str, Any]:
    return dict(state.document["site"] if agent is None else state.document["agents"].get(agent) or {})


def _pause_shown(entry: Mapping[str, Any]) -> dict[str, Any]:
    if not entry.get("paused"):
        return {"paused": False}
    return {"paused": True, "reason": entry.get("pausedReason"), "pausedAt": entry.get("pausedAt"), "pausedBy": entry.get("pausedBy")}


def pauses(state: PolicyState) -> dict[str, Any]:
    """What is paused on the site: the site, and each agent the policy names, in words a person reads."""
    agents = {name: _pause_shown(entry) for name, entry in sorted(state.document["agents"].items())}
    return {"policyVersion": state.version, "site": _pause_shown(state.document["site"]), "agents": agents}


def pause(policy: AgentPolicyStore, tenant_id: str, caller: Caller, *, agent: str | None, reason: str, at: str | None = None) -> dict[str, Any]:
    """Pause one agent (its responsibility, as the policy names it) or, with no ``agent``, the site. A new version of the policy; the next run is stopped."""
    before = policy.read(tenant_id)
    after = policy.pause(tenant_id, caller, reason=reason, responsibility=agent, at=at or utc_now())
    return {"scope": "site" if agent is None else "agent", "agent": agent, **_pause_shown(_held(after, agent)),
            "changed": after.version != before.version, "policyVersion": {"before": before.version, "after": after.version}}


def resume(policy: AgentPolicyStore, tenant_id: str, caller: Caller, *, agent: str | None, reason: str, listeners: Callable[[], Mapping[str, Any]],
           ledger: RunLedger, send: Callable[..., Any], at: str | None = None) -> dict[str, Any]:
    """Lift the pause of one agent or of the site, then send once each change wake the pause stopped, for the agents it lifted it from."""
    before = policy.read(tenant_id)
    lifted = _held(before, agent)
    after = policy.resume(tenant_id, caller, reason=reason, responsibility=agent)
    result: dict[str, Any] = {"scope": "site" if agent is None else "agent", "agent": agent, "paused": False, "changed": after.version != before.version,
                              "policyVersion": {"before": before.version, "after": after.version}, "caughtUp": [], "notes": []}
    if not lifted.get("paused"):
        result["notes"].append(f"{agent or 'The site'} was not paused, so nothing was stopped and nothing is caught up.")
        return result
    since = lifted.get("pausedAt")
    if not since:
        result["notes"].append("This pause was made before a pause kept when it began, so the wakes it stopped cannot be found: nothing was caught up. "
                               "Wake an agent now for a subject that needs it.")
        return result
    document = after.document
    if agent is not None and document["site"].get("paused"):
        result["notes"].append(f"The site is still paused, so {agent} runs nothing yet; its stopped wakes are caught up when the site is resumed.")
        return result
    agents = _change_woken_agents(listeners(), agent, document)
    for responsibility in sorted({entry["responsibility"] for entry in agents.values()}):
        if (document["agents"].get(responsibility) or {}).get("paused"):
            result["notes"].append(f"{responsibility} is still paused itself, so its stopped wakes wait for its own resume.")
    by = person_label(caller)
    moment = at or utc_now()
    for automation_id, entry in sorted(agents.items()):
        if (document["agents"].get(entry["responsibility"]) or {}).get("paused"):
            continue
        for wake in stopped_wakes(ledger, automation_id, since):
            again = sent_again(wake, marker=f"resumed-v{after.version}", poke=RESUMED, by=by, reason=reason, at=moment)
            send(again)
            result["caughtUp"].append({"agent": automation_id, "subject": subject_of(wake), "wakeKey": again["wakeKey"], "repeats": wake["wakeKey"]})
    return result


def _change_woken_agents(index: Mapping[str, Any], responsibility: str | None, document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The agents the listener index says listen for changes, by automation id; with ``responsibility``, only that responsibility's."""
    found: dict[str, dict[str, Any]] = {}
    for entries in ((index or {}).get("changes") or {}).values():
        for entry in entries:
            if responsibility is None or entry.get("responsibility") == responsibility:
                found.setdefault(entry["agent"], entry)
    return found


def stopped_wakes(ledger: RunLedger, automation_id: str, since: str) -> list[dict[str, Any]]:
    """For each subject, its latest wake from ``since`` on, when that wake was stopped by a pause: what resuming sends once. A subject whose latest wake ran
    needs nothing."""
    latest: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for row in ledger.runs_since(automation_id, since):
        wake = kept_wake(row)
        if wake is None:
            continue
        latest[subject_of(wake)] = (row, wake)
    stopped = [(row, wake) for row, wake in latest.values() if row.get("outcomeReason") == PAUSED_REASON]
    return [wake for _, wake in sorted(stopped, key=lambda pair: str(pair[0].get("requestedAt") or ""))]


# --- wake now --------------------------------------------------------------------------------------------------------------------------------------


def wake(ledger: RunLedger, send: Callable[..., Any], caller: Caller, *, agent: str, subject: str, reason: str, request_id: str | None = None,
         at: str | None = None) -> dict[str, Any]:
    """Send the agent's latest wake for the subject again, once, through the site's wake queue."""
    if caller.kind != "person":
        raise PolicyError("human_required", "Wake now is a person's request; an agent asks another agent with a handoff.")
    if not reason.strip():
        raise PolicyError("invalid_input", "Say why the agent is woken now.")
    latest = next((found for found in (kept_wake(row) for row in ledger.newest_first(agent)) if found is not None and subject_of(found) == subject), None)
    if latest is None:
        raise PokeInError("not_found", f"{agent} has never been woken for {subject}, so there is no wake to send again. It wakes when {subject} changes in a way it listens for.")
    request_key = caller.request_id or uuid.uuid4().hex
    again = sent_again(latest, marker=f"woken-{request_key}", poke=WOKEN, by=person_label(caller), reason=reason, at=at or utc_now())
    send(again)
    return {"agent": agent, "subject": subject, "wakeKey": again["wakeKey"], "repeats": latest["wakeKey"], "requestedBy": person_label(caller), "reason": reason.strip()}
