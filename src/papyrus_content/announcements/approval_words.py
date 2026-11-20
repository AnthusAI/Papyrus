"""How a Delivery's review reads in the Announcements list and the Story drawer (PPY-97c0f2).

Words first, then a mark (a Lucide icon name), never colour alone. It reads one Delivery row and nothing else, so the image service function can say it without the agent
policy (``review_policy.py`` owns the policy and re-exports ``approval_label``)."""
from __future__ import annotations

from typing import Any, Mapping

from .records import SOFT, SYSTEM

#: Every mark (a Lucide icon name) ``approval_label`` can say.
MARKS = ("bot", "user-check", "hourglass", "hand")


def approval_label(row: Mapping[str, Any]) -> dict[str, str]:
    """How a Delivery's review reads in the Announcements list: words first, then a mark (a Lucide icon name), never colour alone.

    ``Sent automatically by publication policy`` and ``Released by a person`` are the two the ticket names; a Delivery that has not been released says what it waits for."""
    approval, policy, by = row.get("approval"), str(row.get("approvalPolicy") or ""), row.get("approvedBy")
    source = policy.rsplit(" (agent policy version", 1)[0] if policy else "policy"
    going = row.get("lockedVersion") if row.get("lockedVersion") is not None else row.get("version")   # the version that goes out: the locked one once it is locked
    approved = row.get("approvedVersion") is not None and int(row["approvedVersion"]) == int(going or 0)
    if approved and by == SYSTEM:
        return {"words": f"Released automatically by {source}", "mark": "bot", "approval": str(approval)}
    if approved:
        return {"words": f"Released by a person ({by})", "mark": "user-check", "approval": str(approval)}
    if approval == SOFT:
        return {"words": f"Goes at its lock time unless a person stops it ({source})", "mark": "hourglass", "approval": SOFT}
    return {"words": f"Waits for a person to release it ({source})", "mark": "hand", "approval": str(approval)}
