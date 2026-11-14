"""Which votes on a proposal count, and which proposals an editor should look at.

Both are deterministic: the same rows and the same clock give the same answer, and nothing here calls a model.

**Exclusions.** An editor can exclude a batch of votes on one proposal with a named rule (``EXCLUSION_RULES``, for example
accounts that were under 24 hours old when they voted), and can undo it. The batch covers the votes already cast when the
exclusion was made. Independently, the votes of a reader whose account is limited or banned (the ``spam`` case of moderation)
never count on a proposal. Excluded votes are dropped before any tally, so ``votes``, the community result and the ranking
all see only counted votes, and the public files say how many were left out and why.

**Needs a look.** :func:`needs_a_look` lists the reasons an editor should open a proposal: a spike of votes, a surge of votes from
new accounts, or a community that disagrees with the AI that proposed it. It is editor-only: the snapshot task stores it on the
private ``Proposal`` row and no public file carries it.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

PROPOSAL_SUBJECT_PREFIX = "proposal:"
UP = "up"
LIMITED_OR_SPAM = "limited-or-spam"
LIMITED_OR_SPAM_LABEL = "limited or spam accounts"
RESTRICTED_READER_STATES = ("limited", "banned")
#: Must match ``EXCLUSION_RULES`` in ``amplify/plugins/reader-steering/function/proposals.py``, which validates the rule an editor names.
EXCLUSION_RULES: dict[str, dict[str, Any]] = {
    "new-accounts-24h": {"hours": 24, "label": "accounts under 24 h"},
}

SECONDS_PER_HOUR = 3600
#: At least this many counted votes in the last hour, and at least three times the hourly pace of the 23 hours before.
SPIKE_MINIMUM = 10
SPIKE_FACTOR = 3
#: At least this many counted votes in the last 24 hours from accounts under 24 hours old at the time, and at least this share of them.
SURGE_MINIMUM = 5
SURGE_SHARE = 0.4
SURGE_ACCOUNT_HOURS = 24
#: A community against its AI proposer: at least this many counted votes, down ahead of up by this much and at this share.
DISAGREEMENT_MINIMUM = 5
DISAGREEMENT_LEAD = 3
DISAGREEMENT_SHARE = 0.6
LOOKED_AT_STATES = ("draft", "in_steering", "editor_review")

VOTE_SPIKE, NEW_ACCOUNT_SURGE, COMMUNITY_AI_DISAGREEMENT = "vote_spike", "new_account_surge", "community_ai_disagreement"
REASON_LABELS = {VOTE_SPIKE: "Vote spike", NEW_ACCOUNT_SURGE: "New-account surge", COMMUNITY_AI_DISAGREEMENT: "Community and AI disagree"}


def seconds_of(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()


def parsed(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return fallback if value is None else value


def proposal_id_of(vote: Mapping) -> str | None:
    key = vote.get("subjectKey")
    return key[len(PROPOSAL_SUBJECT_PREFIX) :] if isinstance(key, str) and key.startswith(PROPOSAL_SUBJECT_PREFIX) else None


def active_exclusions(row: Mapping) -> list[dict]:
    """The proposal's exclusions that have not been undone and name a known rule, oldest first."""
    found = [entry for entry in parsed(row.get("exclusions"), []) if isinstance(entry, dict) and not entry.get("undoneAt") and entry.get("rule") in EXCLUSION_RULES and entry.get("at")]
    return sorted(found, key=lambda entry: (entry["at"], entry.get("id") or ""))


def excluded_by(vote: Mapping, exclusions: list[dict], restricted: bool, age_hours: float | None) -> str | None:
    """The exclusion id (or ``limited-or-spam``) that keeps a vote out of the count, or ``None``.

    An account whose age is unknown (no profile row) is not held against the vote. A batch only covers votes cast up to the moment it was made.
    """
    cast = vote.get("createdAt")
    for entry in exclusions:
        hours = EXCLUSION_RULES[entry["rule"]]["hours"]
        if age_hours is not None and age_hours < hours and cast and cast <= entry["at"]:
            return entry["id"]
    return LIMITED_OR_SPAM if restricted else None


def partition_votes(
    votes: Iterable[Mapping], profiles: Iterable[Mapping], proposals: Iterable[Mapping], age_of: Callable[[Mapping], float | None]
) -> tuple[list[Mapping], dict[str, dict[str, int]]]:
    """``(counted votes, excluded)``: every vote that is not excluded, and per proposal the number of up/down votes left out per reason.

    Only votes on proposals the caller passed are looked at; every other vote is returned untouched.
    """
    exclusions = {row["id"]: active_exclusions(row) for row in proposals}
    restricted = {profile["readerId"] for profile in profiles if profile.get("state") in RESTRICTED_READER_STATES}
    kept: list[Mapping] = []
    excluded: dict[str, dict[str, int]] = {}
    for vote in votes:
        proposal = proposal_id_of(vote)
        if proposal is None or proposal not in exclusions:
            kept.append(vote)
            continue
        reason = excluded_by(vote, exclusions[proposal], vote.get("readerId") in restricted, age_of(vote))
        if reason is None:
            kept.append(vote)
        elif vote.get("dimension") == UP and vote.get("value") in (1, -1):
            counts = excluded.setdefault(proposal, {})
            counts[reason] = counts.get(reason, 0) + 1
    return kept, excluded


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def public_exclusions(row: Mapping, counts: Mapping[str, int] | None) -> dict[str, Any]:
    """``{votes, rules: [{id, rule, label, votes, at}], note}`` for a proposal; no actor, and nothing for an undone exclusion.

    ``votes`` is the total left out, ``note`` the sentence a site shows ("Excluded 7 votes from accounts under 24 h"), or ``None``.
    """
    counts = counts or {}
    rules = []
    for entry in active_exclusions(row):
        rules.append({"id": entry["id"], "rule": entry["rule"], "label": EXCLUSION_RULES[entry["rule"]]["label"], "votes": counts.get(entry["id"], 0), "at": entry["at"]})
    if counts.get(LIMITED_OR_SPAM):
        rules.append({"id": None, "rule": LIMITED_OR_SPAM, "label": LIMITED_OR_SPAM_LABEL, "votes": counts[LIMITED_OR_SPAM], "at": None})
    rules = [rule for rule in rules if rule["votes"] > 0]
    total = sum(rule["votes"] for rule in rules)
    parts = [f"{plural(rule['votes'], 'vote')} from {rule['label']}" for rule in rules]
    return {"votes": total, "rules": rules, "note": f"Excluded {' and '.join(parts)}" if parts else None}


def reason(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "label": REASON_LABELS[code], "detail": detail}


def needs_a_look(row: Mapping, votes: Iterable[Mapping], age_of: Callable[[Mapping], float | None], now_seconds: float) -> list[dict[str, str]]:
    """The reasons an editor should open this proposal, as ``{code, label, detail}``; empty when it needs none.

    ``votes`` are the counted votes on this proposal (excluded ones are already gone, so excluding a batch clears its reason). A proposal
    that is decided is never listed.
    """
    if row.get("state") not in LOOKED_AT_STATES:
        return []
    counted = [vote for vote in votes if vote.get("dimension") == UP and vote.get("value") in (1, -1) and vote.get("createdAt")]
    reasons: list[dict[str, str]] = []
    ages = [(now_seconds - seconds_of(vote["createdAt"])) / SECONDS_PER_HOUR for vote in counted]
    last_hour = sum(1 for age in ages if age <= 1)
    before = sum(1 for age in ages if 1 < age <= 24)
    pace = max(1.0, before / 23)
    if last_hour >= SPIKE_MINIMUM and last_hour >= SPIKE_FACTOR * pace:
        reasons.append(reason(VOTE_SPIKE, f"{plural(last_hour, 'vote')} in the last hour, against {plural(before, 'vote')} in the 23 hours before"))
    day = [vote for vote, age in zip(counted, ages) if age <= 24]
    new = sum(1 for vote in day if (age_of(vote) is not None and age_of(vote) < SURGE_ACCOUNT_HOURS))
    if new >= SURGE_MINIMUM and new >= SURGE_SHARE * len(day):
        reasons.append(reason(NEW_ACCOUNT_SURGE, f"{new} of {plural(len(day), 'vote')} in the last 24 hours came from accounts under {SURGE_ACCOUNT_HOURS} h old"))
    up = sum(1 for vote in counted if vote["value"] == 1)
    down = len(counted) - up
    if row.get("proposer") == "ai" and row.get("state") != "draft" and up + down >= DISAGREEMENT_MINIMUM and down - up >= DISAGREEMENT_LEAD and down / (up + down) >= DISAGREEMENT_SHARE:
        reasons.append(reason(COMMUNITY_AI_DISAGREEMENT, f"The AI proposed it; readers voted {up} up and {down} down"))
    return reasons


def attention_by_proposal(
    proposals: Iterable[Mapping], votes: Iterable[Mapping], age_of: Callable[[Mapping], float | None], now_seconds: float
) -> dict[str, list[dict[str, str]]]:
    """Proposal id to its reasons, for the proposals that have any."""
    grouped: dict[str, list[Mapping]] = defaultdict(list)
    for vote in votes:
        proposal = proposal_id_of(vote)
        if proposal is not None:
            grouped[proposal].append(vote)
    found = {row["id"]: needs_a_look(row, grouped.get(row["id"], ()), age_of, now_seconds) for row in proposals}
    return {identifier: reasons for identifier, reasons in found.items() if reasons}
