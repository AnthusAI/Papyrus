"""The wake gate: what stands between a change feed and the wake queue (PPY-67e3cd, slice B5, and PPY-4e7e8b, slice B7).

A change feed (``item_change_feed.handle``) turns each change into one wake request per listening agent. The gate decides, for each, whether it goes on the
queue now, waits for quiet, or is stopped.

**The loop guard** (B7). Agents wake each other by changing records, so two agents could pass a Story back and forth. The guard counts the wakes caused by an
agent's change on a Story since a person last acted on it (``Item.metadata.botChain.hops``, the counter the Stage Bots already keep, so the old guard becomes
this one). At the owner's limit (``agents.<responsibility>.loopLimit`` in the agent policy, starting at 5, decision 8) nothing more starts for that Story and
ONE hard-gate review request says so. A person's change to the Story resets the count and opens the next round, so a later loop raises its own gate. An agent
never wakes itself: its own new version wakes the other agents' free and paid steps, and never the same step (``item_change_feed.is_own_change``).

**The coalescing window** (B5). A step marked paid does not start at once. Each change sets or replaces ONE follow-up timer for that subject and step
(``follow_up_timers``: one entry per record, named from the step and the Story), due when the subject has been quiet for the site's window: ``site.coalescing.
windowSeconds`` after an agent's change, ``afterPersonSeconds`` after a person's (Ryan's ruling of 2026-11-06: 30 minutes to 24 hours, about 5 minutes after a
person's own action; the starting values are the ruling's shortest). The timer's wake key leaves out the version (``<agent>|<Story>|<due time>|due``) and the request
leaves it out too, so the run takes the version that is current when it fires. A free step is put on the queue at once, on every change. A window changed in the
policy changes only the waits set after it: a timer already pending keeps its time until the next change moves it.

Nothing here sweeps: the timer is the only thing that waits, and the counter is one point read and write on the Story.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol

from . import agent_wakes, follow_up_timers

DEFAULT_WINDOW_SECONDS = 30 * 60      # Ryan 2026-11-06: the shortest window of the ruling, until the owner sets one
DEFAULT_AFTER_PERSON_SECONDS = 5 * 60
DEFAULT_LOOP_LIMIT = 5                # decision 8: today's default, as the starting owner setting
COALESCE_RECORD_PREFIX = "quiet:"     # a timer's record kind: one entry per step (agent) and subject
WAITING_FOR = "quiet window"
AGENT, PERSON = "agent", "person"
CHAIN_KEY = "botChain"


class Chain(Protocol):
    """The count of agent-caused wakes on a subject since a person last acted, and the round it belongs to."""

    def read(self, subject: str) -> Mapping[str, int]: ...          # {"hops", "round"}
    def write(self, subject: str, hops: int) -> None: ...
    def reset(self, subject: str, version: str | None) -> bool: ...  # True when there was a count to clear


class StoryChain:
    """The counter on the Story's current version: ``metadata.botChain`` (``hops``, and ``round`` which grows each time a person's action clears a count)."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _row(self, story: str) -> dict[str, Any]:
        from .story_reporting import current_story_version

        return current_story_version(self.client, story)

    @staticmethod
    def _chain(row: Mapping[str, Any]) -> dict[str, int]:
        from .story_triggers import chain_of

        chain = chain_of(dict(row))
        rounds = chain.get("round")
        return {"hops": chain["hops"], "round": rounds if isinstance(rounds, int) and not isinstance(rounds, bool) and rounds >= 0 else 0}

    def _put(self, row: Mapping[str, Any], **fields: int) -> None:
        from .story_triggers import _write_metadata, chain_of

        _write_metadata(self.client, dict(row), **{CHAIN_KEY: {**chain_of(dict(row)), **fields}})

    def read(self, story: str) -> dict[str, int]:
        return self._chain(self._row(story))

    def write(self, story: str, hops: int) -> None:
        self._put(self._row(story), hops=hops)

    def reset(self, story: str, version: str | None) -> bool:
        """Clear the count on the current version and on the version the person's change made, which a new version's insert can precede the current mark of."""
        current = self._row(story)
        rows = [current]
        if version and version != current.get("id"):
            made = self.client.get_record("Item", version)
            if made:
                rows.append(made)
        cleared = False
        for row in rows:
            chain = self._chain(row)
            if chain["hops"] > 0:
                self._put(row, hops=0, round=chain["round"] + 1)
                cleared = True
        return cleared


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _time_of(value: Any, fallback: datetime) -> datetime:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class WakeGate:
    """``person_acted`` for each change a person made, ``release`` for each wake request a change makes. ``policy`` returns the live agent policy document.

    ``review`` raises the hard gate: ``review(story=, agent=, hops=, limit=, round=)``. ``timers`` is a ``FollowUpTimers``."""

    def __init__(self, *, policy: Callable[[], Mapping[str, Any]], timers: Any, chain: Chain, review: Callable[..., Any],
                 clock: Callable[[], datetime] | None = None) -> None:
        self._policy, self.timers, self.chain, self.review = policy, timers, chain, review
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._document: Mapping[str, Any] | None = None

    @property
    def document(self) -> Mapping[str, Any]:
        if self._document is None:    # read once per gate, which lives for one batch
            self._document = self._policy()
        return self._document

    # --- the settings the owner holds ---------------------------------------------------------------------------------------------

    def window_seconds(self, actor_kind: str | None) -> int:
        coalescing = (self.document.get("site") or {}).get("coalescing") or {}
        if actor_kind == PERSON:
            return _positive_int(coalescing.get("afterPersonSeconds")) or DEFAULT_AFTER_PERSON_SECONDS
        return _positive_int(coalescing.get("windowSeconds")) or DEFAULT_WINDOW_SECONDS

    def loop_limit(self, responsibility: str | None) -> int:
        entry = (self.document.get("agents") or {}).get(responsibility) or {}
        return _positive_int(entry.get("loopLimit")) or DEFAULT_LOOP_LIMIT

    # --- a person acted -------------------------------------------------------------------------------------------------------------

    def person_acted(self, *, subject: str, version: str | None) -> bool:
        """A person's change to a Story clears the count of agent runs on it."""
        return self.chain.reset(subject, version)

    # --- one wake request -----------------------------------------------------------------------------------------------------------

    def release(self, request: dict[str, Any], send: Callable[[dict], Any]) -> dict[str, Any]:
        """Send, delay or stop one wake. Returns ``{"status": "sent" | "waiting" | "stopped", ...}``."""
        trigger = request.get("trigger") or {}
        agent, story = trigger.get("automationId"), trigger.get("story")
        counted = trigger.get("actorKind") == AGENT and bool(story)
        if counted:
            hops, limit = self.chain.read(story), self.loop_limit(trigger.get("responsibility"))
            if hops["hops"] >= limit:
                self.review(story=story, agent=agent, hops=hops["hops"], limit=limit, round=hops["round"])
                return {"status": "stopped", "reason": f"loop limit reached ({hops['hops']} of {limit})", "agent": agent, "story": story}
        if trigger.get("paid"):
            outcome = self._delay(request, trigger)
        else:
            send(request)
            outcome = {"status": "sent"}
        if counted:
            self.chain.write(story, hops["hops"] + 1)
        return outcome

    def _delay(self, request: dict[str, Any], trigger: Mapping[str, Any]) -> dict[str, Any]:
        subject = trigger.get("story") or (trigger.get("subject") or {}).get("id")
        if not subject:
            raise ValueError("a paid wake waits for quiet on a subject, and this one names none")
        wake = agent_wakes.wake_of(request)
        now = self._clock()
        seconds = self.window_seconds(trigger.get("actorKind"))
        due = (_time_of(trigger.get("at"), now) + timedelta(seconds=seconds)).replace(microsecond=0)
        due_at = due.strftime(follow_up_timers.TIME_FORMAT)
        base = {name: value for name, value in request.items() if name != "wakeKey"}
        base["input"] = {name: value for name, value in (base.get("input") or {}).items() if name != "version"}
        base["trigger"] = {name: value for name, value in trigger.items() if name != "version"}
        self.timers.sync(COALESCE_RECORD_PREFIX + wake["agent"], subject, due_at, owner=wake["agent"], base=base, waiting_for=WAITING_FOR)
        return {"status": "waiting", "dueAt": due_at, "agent": wake["agent"], "subject": subject, "windowSeconds": seconds}


def raise_loop_review(client: Any, *, story: str, agent: str, hops: int, limit: int, round: int = 0) -> dict[str, Any]:
    """ONE hard-gate review request for a Story whose agents reached the loop limit. The id carries the round, so the same stop is raised once and a
    later loop, after a person acted, raises its own."""
    from .review_requests import raise_review
    from .story_triggers import _safe, bot_label

    return raise_review(
        client, subject={"type": "story", "id": story}, mode="hard_gate", raised_by=bot_label(agent),
        reason=f"agent loop limit reached: agents ran {hops} times on this story since a person last acted (limit {limit}); {agent} did not start",
        ask="Read the latest version and decide what happens next. Any change you make lets the agents continue; the owner sets the limit in the agent policy.",
        request_id=f"rr-agent-loop-{_safe(story, 90)}-{limit}-{round}")
