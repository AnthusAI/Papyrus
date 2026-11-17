"""The hard floors that bear on how high a rung may be set (architecture section 5.5; the gate that enforces them at run time is slice E4, PPY-36e7c9).

A floor holds at every rung. Most of them are checked when an agent calls an operation, in the gate. One is also checked when a person sets
the rung, because it is the reason the top rung exists to be refused: "doubt stops automatic publishing, even on a fully automatic site"
(an error-level finding a bot cannot fix, a contradicted claim, a legal-screen hit, the loop limit). The gate that turns ``publish_*`` into a
hard gate on doubt is not built yet, so nothing yet stops an agent at ``publish_auto`` from publishing through one of those. Until it is,
no responsibility is set to ``publish_auto``. When slice E4 lands it replaces ``publish_auto_refusal`` with the check it enforces.
"""
from __future__ import annotations

PUBLISH_AUTO = "publish_auto"


def publish_auto_refusal(responsibility: str) -> str:
    """Why ``responsibility`` may not be set to ``publish_auto`` now."""
    return (f"{responsibility} cannot be set to {PUBLISH_AUTO}: a hard floor says doubt (an error-level finding, a contradicted claim, a legal-screen hit, the loop limit) "
            "stops automatic publishing at every rung, and the gate that enforces that floor (slice E4, PPY-36e7c9) is not built. Use publish_soft or lower.")
