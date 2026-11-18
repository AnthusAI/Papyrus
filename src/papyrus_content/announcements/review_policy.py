"""Human review of announcements is a per-publication setting, and it is the announce responsibility's rung on the autonomy ladder (PPY-97c0f2).

There is no second setting. ``announcementReview`` is how the site's agent policy document (``papyrus_content.agent_policy``) names the rung of the ``announce``
responsibility, in the words the Delivery already uses for approval:

===========  ================  ==========================================================================================
approval     rung              what it means
===========  ================  ==========================================================================================
``hard``     ``prepare``       the machine drafts; a person must release it
``soft``     ``publish_soft``  a person may edit or stop it before its lock time; silence lets it go
``none``     ``publish_auto``  fully automatic: the first person to see it is a reader
===========  ================  ==========================================================================================

A rung below ``prepare`` (off, observe, propose, draft) means the announce agent prepares no Delivery at all, so none is written and the reason is said.

**Overrides, narrowest wins:** the publication's own rung, then a channel override (LinkedIn ``hard`` while X is ``none``), then an Announcement kind override
(roundups ``hard``, story posts ``none``), then a list override (newsletters). Each is optional. They are the ladder's overrides (``agent_policy.resolve``), so one
resolver answers every responsibility; this module only reads the ``announce`` entry and turns the rung into the approval a Delivery records.

The choice is written to each Delivery as ``approval`` and ``approvalPolicy`` (where it came from: the publication, or which override, and the version of the policy
document). It applies to Announcements created afterwards: a Delivery keeps what it was created with unless an editor changes that one (``Deliveries.change_approval``).

**``requireReviewedSource`` is not a rung.** It is a condition on the input and lives in the announcement settings (``settings.py``, ``rules.requireReviewedSource``,
off unless a person turns it on): when on, an Announcement is created only for a Story a person has reviewed on its current version (``intake.py``).

No value here is a default of the code: the only data this module names are the two sets the ticket lists for a publication that has just been made
(``NEW_PUBLICATION``) and for Machines on Machines (``MACHINES_ON_MACHINES``), and neither is applied to any site by a deploy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from papyrus_content.agent_policy.document import PolicyError, scope_of
from papyrus_content.agent_policy.resolve import PolicyState, decide_start, effective
from papyrus_content.agent_policy.store import AgentPolicyStore
from papyrus_content.images.handlers import Caller

from .records import HARD, NONE, SOFT, SYSTEM

RESPONSIBILITY = "announce"
#: The ways an announcement's review can be narrowed: an Announcement kind, a channel, a list. (The ladder also has Story type and section; the announce rung is not narrowed by those.)
REVIEW_SCOPES = ("list", "kind", "channel")

RUNG_OF = {HARD: "prepare", SOFT: "publish_soft", NONE: "publish_auto"}
APPROVAL_OF = {rung: approval for approval, rung in RUNG_OF.items()}

#: What the ticket lists for a publication made from now on, and for Machines on Machines. Plain data for the person who applies it; a deploy never writes the policy document.
NEW_PUBLICATION: dict[str, Any] = {"announce": {"rung": RUNG_OF[SOFT]}, "requireReviewedSource": False}
MACHINES_ON_MACHINES: dict[str, Any] = {"announce": {"rung": RUNG_OF[SOFT], "overrides": [{"kind": "roundup", "rung": RUNG_OF[HARD]}]}, "requireReviewedSource": True}

#: Why a channel gets no Delivery, in the words the Announcements list shows.
OFF_WORDS = "the announce agent is off, so no Delivery is prepared"


@dataclass(frozen=True)
class ReviewChoice:
    """What the policy says for one channel and kind: the approval the Delivery is created with, or why it is not created."""

    approval: str | None            # none, soft or hard; None when no Delivery is prepared
    rung: str
    where: str                      # "publication" or "override"
    scope: dict[str, str] | None    # the override's scope, when where is "override"
    policy_version: int
    reason: str | None = None       # why no Delivery is prepared; None when one is

    @property
    def prepares(self) -> bool:
        return self.approval is not None

    @property
    def policy(self) -> str:
        """Where the value came from, as the Delivery's ``approvalPolicy`` records it."""
        if self.where == "publication":
            source = "publication policy"
        else:
            source = "override: " + ", ".join(f"{dimension} {value}" for dimension, value in (self.scope or {}).items())
        return f"{source} (agent policy version {self.policy_version})"


def choose(state: PolicyState, *, channel: str, kind: str, list_id: str | None = None) -> ReviewChoice:
    """The review the ``announce`` rung gives a Delivery on ``channel`` for an Announcement of ``kind`` (and, for a newsletter, ``list_id``). Reads only the policy."""
    context = {"channel": channel, "kind": kind, **({"list": list_id} if list_id else {})}
    found = effective(state, RESPONSIBILITY, context)
    start = decide_start(state, RESPONSIBILITY, context)
    where = "override" if found.source == "override" else "publication"
    scope = scope_of(found.override) if found.override else None
    if not start.start:
        return ReviewChoice(None, found.rung, where, scope, state.version, start.reason if start.reason_code == "paused" else OFF_WORDS)
    approval = APPROVAL_OF.get(found.rung)
    if approval is None:
        return ReviewChoice(None, found.rung, where, scope, state.version,
                            f"announce is at {found.rung}; a Delivery is prepared from prepare upwards (hard), publish_soft (soft) or publish_auto (none)")
    return ReviewChoice(approval, found.rung, where, scope, state.version)


# --- the words and marks the list shows --------------------------------------------------------------------------------------------------------------


def approval_label(row: Mapping[str, Any]) -> dict[str, str]:
    """How a Delivery's review reads in the Announcements list: words first, then a mark (a Lucide icon name), never colour alone.

    ``Sent automatically by publication policy`` and ``Released by a person`` are the two the ticket names; a Delivery that has not been released says what it waits for."""
    approval, policy, by = row.get("approval"), str(row.get("approvalPolicy") or ""), row.get("approvedBy")
    source = policy.rsplit(" (agent policy version", 1)[0] if policy else "policy"
    approved = row.get("approvedVersion") is not None and int(row["approvedVersion"]) == int(row.get("version") or 0)
    if approved and by == SYSTEM:
        return {"words": f"Released automatically by {source}", "mark": "bot", "approval": str(approval)}
    if approved:
        return {"words": f"Released by a person ({by})", "mark": "user-check", "approval": str(approval)}
    if approval == SOFT:
        return {"words": f"Goes at its lock time unless a person stops it ({source})", "mark": "hourglass", "approval": SOFT}
    return {"words": f"Waits for a person to release it ({source})", "mark": "hand", "approval": str(approval)}


# --- changing the policy: a person's, an admin's --------------------------------------------------------------------------------------------------------


def set_review(policy: AgentPolicyStore, tenant_id: str, caller: Caller, approval: str, *, reason: str, scope: Mapping[str, str] | None = None) -> PolicyState:
    """Set ``announcementReview`` for the publication, or for one override scope (list, kind, channel; more than one narrows further). Admins who are people only:
    an agent is ``blocked`` and an editor ``not_authorized`` (``AgentPolicyStore``). Each change is a new version of the policy with who, when and why.

    ``none`` is the rung ``publish_auto``, and the ladder's hard floor refuses that rung until the gate that stops automatic publishing on doubt exists
    (``agent_policy.floors``, PPY-36e7c9); this refuses it in the same words, so a person is not told a fully automatic publication was set when the floor is not there."""
    from papyrus_content.agent_policy import floors

    if approval not in RUNG_OF:
        raise PolicyError("invalid_input", f"announcementReview is one of: {', '.join(RUNG_OF)}.")
    scope = _review_scope(scope)
    if approval == NONE:
        raise PolicyError("constraint_conflict", floors.publish_auto_refusal(RESPONSIBILITY))
    return policy.set_rung(tenant_id, caller, RESPONSIBILITY, RUNG_OF[approval], reason=reason, scope=scope)


def remove_override(policy: AgentPolicyStore, tenant_id: str, caller: Caller, scope: Mapping[str, str], *, reason: str) -> PolicyState:
    """Take an override away, so that scope follows the next wider one again."""
    return policy.remove_override(tenant_id, caller, RESPONSIBILITY, _review_scope(scope) or {}, reason=reason)


def _review_scope(scope: Mapping[str, str] | None) -> dict[str, str] | None:
    if not scope:
        return None
    extra = sorted(set(scope) - set(REVIEW_SCOPES))
    if extra:
        raise PolicyError("invalid_input", f"announcementReview is narrowed by {', '.join(REVIEW_SCOPES)}; not by {', '.join(extra)}.")
    return dict(scope)


def review_summary(state: PolicyState) -> dict[str, Any]:
    """The publication's review and every override, in the words a person reads."""
    entry = state.document.get("agents", {}).get(RESPONSIBILITY)
    if entry is None:
        return {"policyVersion": state.version, "approval": None, "rung": "off", "overrides": []}
    return {"policyVersion": state.version, "approval": APPROVAL_OF.get(entry["rung"]), "rung": entry["rung"], "paused": bool(entry.get("paused")),
            "overrides": [{"scope": scope_of(item), "approval": APPROVAL_OF.get(item["rung"]), "rung": item["rung"]} for item in entry.get("overrides", [])]}
