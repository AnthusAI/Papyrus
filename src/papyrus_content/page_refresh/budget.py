"""Hard guardrails on invalidation spending, enforced inside the tool and not left to an agent's judgment (PPY-105508).

* A per-call cap on paths (default 25; ``publication.cache.maxInvalidationPaths``). Above it the call is refused, naming ``--force-paths N``.
  Nothing implies the force flag: not ``--indexes``, not ``--all``, not a re-render.
* A dry run is the default for more than 5 paths: the list is printed and a second call with ``--run`` (``confirm: true``) does it.

Invalidation goes through the content-actions function, which enforces both. A raw ``aws cloudfront create-invalidation`` bypasses them: never use it.
There is no wildcard operation at all; a whole-site ``/*`` cannot be requested through these tools.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_PATH_CAP = 25
DRY_RUN_ABOVE = 5
PATH_CAP_ENV = "PAPYRUS_INVALIDATION_MAX_PATHS"


@dataclass(frozen=True)
class Budget:
    path_cap: int = DEFAULT_PATH_CAP


def budget_from_environment(environment: Mapping[str, str] | None = None) -> Budget:
    env = os.environ if environment is None else environment
    raw = (env.get(PATH_CAP_ENV) or "").strip()
    return Budget(int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_PATH_CAP)
