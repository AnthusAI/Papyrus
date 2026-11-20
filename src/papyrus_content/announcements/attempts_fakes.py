"""A stand-in for Caducus's channel for the attempt specs. It behaves as the contract documents: it dedupes on the event id (an event handed over twice posts once),
posts nothing until an event is handed over, and answers only what its delivery log recorded. A spec scripts what happens to the next new event. No network, no AWS.
"""
from __future__ import annotations

from typing import Any, Mapping

from .attempts import ANSWER_FAILED, ANSWER_REFUSED, ANSWER_SENT, QUEUED, Answer, RateLimited
from .deliveries import Deliveries
from .records import attempt_log


class FakeChannel:
    def __init__(self, deliveries: Deliveries) -> None:
        self.deliveries = deliveries
        self.log: dict[str, Answer] = {}          # Caducus's delivery log, by event id
        self.posts: list[str] = []                 # the event ids that were posted at the provider, one entry for each real post
        self.submissions: list[str] = []           # every hand-over, repeats included
        self.texts: dict[str, str] = {}
        self.started_when_called: list[tuple[str, str | None]] = []   # (event id, outcome of that attempt in the Delivery's log at the moment of the call)
        self._script: list[tuple[str, Any]] = []

    # --- what a spec scripts for the next new event -----------------------------------------------------------------------------------------------

    def next_event(self, what: str, detail: Any = None) -> None:
        """``sent``, ``failed`` (detail: the provider's code), ``refused`` (detail: (code, wait until)), ``queued`` (in flight), ``rate limit`` (detail: the time),
        ``lands but the answer is lost`` (the event reaches Caducus and is posted, but the call raises), ``lost`` (the call raises before Caducus has it)."""
        self._script.append((what, detail))

    # --- the Transport ----------------------------------------------------------------------------------------------------------------------------

    def submit(self, row: Mapping[str, Any], text: str, event_id: str) -> None:
        self.submissions.append(event_id)
        attempt = next((entry for entry in attempt_log(self.deliveries.get(row["id"]) or {}) if entry["eventId"] == event_id), None)
        self.started_when_called.append((event_id, attempt["outcome"] if attempt else None))
        if event_id in self.log:
            return   # deduped: nothing new happens
        what, detail = self._script.pop(0) if self._script else ("sent", None)
        if what == "lost":
            raise ConnectionError("the connection dropped before the event arrived")
        if what == "rate limit":
            raise RateLimited(detail)
        self.texts[event_id] = text
        if what in ("sent", "lands but the answer is lost"):
            self.posts.append(event_id)
            self.log[event_id] = Answer(ANSWER_SENT, provider_id=f"post-{len(self.posts)}", cost="0.200")
        elif what == "failed":
            self.log[event_id] = Answer(ANSWER_FAILED, code=detail or "refused by the provider")
        elif what == "refused":
            code, until = detail
            self.log[event_id] = Answer(ANSWER_REFUSED, code=code, wait_until=until)
        elif what == "queued":
            self.log[event_id] = Answer(QUEUED)
        else:
            raise AssertionError(what)
        if what == "lands but the answer is lost":
            raise TimeoutError("no answer from the router")

    def delivery(self, event_id: str) -> Answer | None:
        return self.log.get(event_id)

    def finish(self, event_id: str, answer: Answer) -> None:
        """Caducus records an answer for an event that was in flight."""
        self.log[event_id] = answer
        if answer.status == ANSWER_SENT:
            self.posts.append(event_id)
