"""What the runner tells an agent's procedure about the run it is in (PPY-d85860, slice L1).

The runner reads the site's agent policy once, before it starts a run, and asks the gate about the operations a procedure names when the run ends. A
procedure that must write through the gate while it works (the rating agent writes a rating only at a rung that allows it) needs the same policy, the
responsibility and the run's own deadline. The runner puts them in one environment variable of the child process, so the procedure's gate is the one gate
over the one policy the run was decided under: there is no second copy of the rung and no rung typed into a procedure.

Only a run an agent's wake started has one. A person's own run has no policy and no responsibility, so ``from_environment`` answers ``None`` and a
procedure that needs a run context refuses to run without it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content.agent_policy.resolve import PolicyState

ENVIRONMENT_KEY = "PAPYRUS_AGENT_RUN"


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    responsibility: str
    policy: PolicyState
    deadline: float | None   # the moment the child is stopped, as seconds since the epoch; None when nothing limits it


def to_environment(run_id: str, responsibility: str, policy: PolicyState, deadline: float | None) -> dict[str, str]:
    """The one environment entry the runner adds to the child of an agent's run."""
    return {ENVIRONMENT_KEY: json.dumps({"runId": run_id, "responsibility": responsibility, "deadline": deadline,
                                         "policy": {"version": policy.version, "document": policy.document}})}


def from_environment(environ: Mapping[str, str]) -> AgentRun | None:
    """The run's context, or None when the process was not started by an agent's wake. A value that is present and unreadable is an error, not a missing one."""
    text = environ.get(ENVIRONMENT_KEY)
    if not text:
        return None
    try:
        data: Any = json.loads(text)
        return AgentRun(str(data["runId"]), str(data["responsibility"]), PolicyState(int(data["policy"]["version"]), dict(data["policy"]["document"])),
                        None if data.get("deadline") is None else float(data["deadline"]))
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError(f"{ENVIRONMENT_KEY} is not a run context the runner wrote: {error}") from error
