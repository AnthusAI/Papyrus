"""Who is at the command line: a person, or an agent. Fail closed: a caller is a person only when there is positive evidence of one.

A person's floor (turning announcements on, raising an agent's rung, changing a binding constraint) used to be open to anyone who did not say they were an agent,
which is an honor system. Now a caller is an agent unless **all** of these hold:

* ``PAPYRUS_ACTOR_KIND`` is not ``agent``, which still forces agent;
* none of the markers a coding-agent runtime puts in the environment of every command it runs is set (``AGENT_RUNTIME_MARKERS``), so an agent that leaves out
  the label is still recognised by the runtime that runs it;
* the command's input is an interactive terminal, which a person typing has and a process an agent spawns does not.

A process with no terminal (a script, a CI step, an agent's shell tool, a pipe) is therefore an agent, and a person who needs such a floor runs the command in a
terminal. Nothing here can stop a model that deliberately allocates a terminal and clears the runtime's markers: the server must decide from the credential for that
(an agent identity or claim), which is the next step. This closes the case that was wide open, an agent that simply says nothing.
"""
from __future__ import annotations

import os
import sys
from typing import Mapping

ACTOR_KIND_VARIABLE = "PAPYRUS_ACTOR_KIND"
AGENT, PERSON = "agent", "person"
AGENT_RUNTIME_MARKERS = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_REMOTE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID",
    "CURSOR_AGENT", "CURSOR_TRACE_ID", "CODEX_SANDBOX", "CODEX_HOME_SESSION", "CODEX_CI", "GEMINI_CLI", "AIDER_CHAT_HISTORY_FILE",
    "OPENCODE", "COPILOT_AGENT", "GITHUB_COPILOT_AGENT", "WINDSURF_AGENT", "AMP_THREAD_ID", "CI", "GITHUB_ACTIONS",
)


def terminal_is_interactive() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except (ValueError, OSError):
        return False


def actor_kind(environ: Mapping[str, str] | None = None, *, interactive: bool | None = None) -> str:
    environment = os.environ if environ is None else environ
    if str(environment.get(ACTOR_KIND_VARIABLE, "")).strip().lower() == AGENT:
        return AGENT
    if any(str(environment.get(marker, "")).strip() for marker in AGENT_RUNTIME_MARKERS):
        return AGENT
    is_interactive = terminal_is_interactive() if interactive is None else interactive
    return PERSON if is_interactive else AGENT
