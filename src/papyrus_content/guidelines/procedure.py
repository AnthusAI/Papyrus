"""The site's Story procedure (PPY-8fe7e6): which steps a Story goes through, in what order, before it publishes.

The default is the engine's list (``newsroom_process.STEPS``). A site saves its own as a ``procedure`` document: ``steps`` is the whole ordered list, ending
with ``publish``. An entry naming a built-in step keeps that step's checks and status and may change its words (``title``, ``role``, ``command``, ``note``)
and whether it is ``optional``; leaving a built-in step out removes it from the site's procedure. An entry with a new key is a step of the site's own, done
by hand with a findings note: it needs a ``title`` and a ``stage`` and may carry ``role``, ``command``, ``note``, ``optional`` and ``versioned``.
"""
from __future__ import annotations

from typing import Any

from .document import Field, Problem
from .site_rules import register_rule_kind

KIND = "procedure"


def _steps(value: Any) -> str | None:
    from papyrus_content.newsroom_process import procedure_problems

    problems = procedure_problems({"steps": value})
    return "; ".join(f"{path.removeprefix('steps')} {message}".strip() for path, message in problems) or None


register_rule_kind(KIND, {"steps": Field(_steps, "prose")})
