"""The attempt log of a Delivery, and the one consumer that writes it (docs/announcement-records.md, "Attempts").

**A retry is an attempt.** The log on a Delivery only grows. Attempt N is one Caducus event, ``delivery:<deliveryId>:a<N>``, so a retry is a new event and the same
attempt handed over twice posts once. Nothing counts attempts or stops after some number of them: a sequence ends on a clear answer from the provider (sent,
refused) or, after an unknown outcome, on the read that shows whether the post exists.

**An attempt is written before the call.** It opens ``started`` in the same conditional write that moves the Delivery to ``sending``, and only then is the
provider called. It closes ``sent``, ``refused`` or ``unknown``. An entry left ``started`` or ``unknown`` is settled by reading what Caducus recorded for that
event id, never by a timeout and never by guessing: if Caducus has no record the same event id is handed over again, and Caducus dedupes on it.

**A wait ends an attempt.** A pause, a budget stop or a rate limit closes the attempt ``refused`` with its code, puts ``nextAttemptAt`` and ``waitingFor`` on the
Delivery (so ``dueAt`` follows), and the next try is the next attempt.

**An attempt opens only on a Delivery that may be sent.** The Delivery must be the highest generation for its Announcement, channel and account, must not be
superseded, and its words file must exist and match the row's content hash. Otherwise nothing is sent and one flag is raised. Closing an attempt never changes the
state of a superseded Delivery: the outcome goes in the log and the state stays ``superseded``.

**One worker for each channel account.** Every attempt for one channel account passes through one ``AccountWorker``. It refuses a Delivery of another account.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlsplit
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..run_outcomes import OUTCOME_SHOWN
from .channel import attempt_event_id
from .counts import DeliveryCounts
from .deliveries import Conflict, Deliveries, OpenAttempt, content_hash
from .delivery_lock import WAITING_FOR_PERSON, decide, raise_flag
from .delivery_text import sendable_number
from .records import (
    EMAIL, ATTEMPT_REFUSED, ATTEMPT_SENT, BLOCKED, BUDGET_CYCLE, BUDGET_REACHED_CODE, FAILED, MANUAL, PAUSED_CODE, RATE_LIMIT, RATE_LIMIT_CODE, READY, SENDING, SENT, STARTED, SUPERSEDED,
    UNKNOWN, POST_SPACING, RecordError, account_key, attempt_log, now_iso, open_attempt_of, utc,
)

FLAG_RAISER = "announce"
FLAG_SUBJECT = "delivery"

# Caducus's answers for one event (its delivery log).
QUEUED, ANSWER_SENT, ANSWER_FAILED, ANSWER_REFUSED = "queued", "sent", "failed", "refused"


class NotReleasable(RecordError):
    """The Delivery may not go yet. ``reason`` says why in plain words. Nothing was written and no flag is raised: waiting is normal."""

    def __init__(self, delivery: str, reason: str):
        super().__init__(f"{delivery} is not sent: {reason}.")
        self.reason = reason


class AttemptRefused(RecordError):
    """The Delivery must not be sent at all: a newer generation exists, it is superseded, or its words file is missing or does not match. Nothing was sent and one flag
    was raised (``flag`` is its request id)."""

    def __init__(self, delivery: str, reason: str, flag: str):
        super().__init__(f"{delivery} is not sent: {reason}.")
        self.reason, self.flag = reason, flag


class ManualDelivery(RecordError):
    """The Delivery is in manual mode: a person posts it by hand, so no worker and no channel ever sends it. Nothing was written and no flag is raised."""

    def __init__(self, delivery: str):
        super().__init__(f"{delivery} is not sent: it is a manual Delivery, so a person posts it and records the address (record_manual).")


class AttemptClosed(RecordError):
    """The attempt already has a clear answer. An earlier entry never changes."""


class WrongConsumer(RecordError):
    """The Delivery belongs to another channel account. All attempts for one account pass through that account's worker."""


class RateLimited(Exception):
    """The provider asked to wait. ``until`` is when it may be tried again (UTC)."""

    def __init__(self, until: str):
        super().__init__(f"rate limited until {until}")
        self.until = utc(until)


@dataclass(frozen=True)
class Answer:
    """What the provider's record says about one event. ``code`` is the provider's code or reason; ``wait_until`` is when a refused wait (budget cycle, pause with a
    known end) may be tried again."""

    status: str
    provider_id: str | None = None
    cost: str | None = None
    code: str | None = None
    wait_until: str | None = None


@dataclass(frozen=True)
class Wait:
    """What an attempt that ended on a wait is waiting for, and until when."""

    for_what: str
    until: str | None = None


class Transport(Protocol):
    """The channel as Papyrus sees it. ``submit`` hands the event to the provider's router and returns before anything is posted. Handing over an event id twice does
    nothing the second time. ``delivery`` reads the provider's record of one event, or None when it has none."""

    def submit(self, row: Mapping[str, Any], text: str, event_id: str) -> None: ...

    def delivery(self, event_id: str) -> Answer | None: ...


# How an attempt entry is shown. The mark never carries the meaning alone: the words are always shown with it. An entry with no answer yet (``started`` or
# ``unknown``) reads "Outcome unknown", the same words as a run that started and recorded no result.
ATTEMPT_SHOWN: dict[str, tuple[str, str]] = {
    STARTED: OUTCOME_SHOWN[UNKNOWN],
    UNKNOWN: OUTCOME_SHOWN[UNKNOWN],
    ATTEMPT_SENT: ("✓", "Sent"),
    ATTEMPT_REFUSED: ("✗", "Refused"),
}


def shown(entry: Mapping[str, Any]) -> tuple[str, str]:
    """(mark, words) for one attempt entry."""
    return ATTEMPT_SHOWN[entry["outcome"]]


def manual_address(url: str) -> str:
    """The address of a post made by hand: an http or https URL with a host and no spaces, or a refusal in plain words."""
    address = (url or "").strip()
    try:
        parts = urlsplit(address)
        valid = parts.scheme in ("http", "https") and bool(parts.hostname) and not any(ch.isspace() for ch in address)
    except ValueError:
        valid = False
    if not valid:
        raise RecordError(f"The address of the post is a web address that starts with http:// or https://; not {url!r}.")
    return address


def flag_id(delivery: str, reason: str) -> str:
    """One flag for one Delivery and one reason, so raising it again finds the first."""
    return "attempt-" + hashlib.sha256(f"{delivery}\n{reason}".encode("utf-8")).hexdigest()[:24]


class Attempts:
    def __init__(self, deliveries: Deliveries):
        self.deliveries = deliveries

    # --- the guard --------------------------------------------------------------------------------------------------------------------------------

    def structural_refusal(self, row: Mapping[str, Any]) -> str | None:
        """Why this Delivery is not the one to send: it was superseded, or a newer generation of its Announcement, channel and account exists (a correction that was
        started and not finished). One index read of the Announcement's Deliveries."""
        if row.get("state") == SUPERSEDED or row.get("supersededBy"):
            return "it was superseded by a correction"
        newer = [other for other in self.deliveries.for_announcement(row["announcementId"])
                 if (other["channel"], other["accountId"]) == (row["channel"], row["accountId"]) and int(other["generation"]) > int(row["generation"])]
        return f"a newer generation exists ({newer[0]['id']})" if newer else None

    def words_refusal(self, row: Mapping[str, Any]) -> str | None:
        """Why the words cannot go out: the file is missing, or it is not the file the row's content hash names."""
        entry = self.deliveries.sendable(row)
        text = self.deliveries.sent_text(row)
        if text is None:
            return "its words file is missing"
        if not text.strip():
            return "it has no words"
        described = self.deliveries.files.describe(row["id"], text, entry["file"])
        if content_hash(described["sha256"], entry.get("imageKey")) != entry.get("contentHash"):
            return "its words file does not match the row's content hash"
        return None

    def refusal(self, row: Mapping[str, Any]) -> str | None:
        """Why this Delivery must not be sent at all, or None. A Delivery that is merely not due yet is not in this list (``releasable`` says that)."""
        return self.structural_refusal(row) or self.words_refusal(row)

    def _flag(self, row: Mapping[str, Any], reason: str, now: str) -> str:
        from ..review_requests import raise_review

        request = raise_review(
            self.deliveries.client, subject={"type": FLAG_SUBJECT, "id": row["id"]}, mode="flag", raised_by=FLAG_RAISER, request_id=flag_id(row["id"], reason),
            reason=f"Not sent: {reason}.", ask=f"{row['channel']} {row['accountId']}: nothing was sent for this Delivery. Look at it and decide what should go out.",
        )
        return request["id"]

    # --- open -------------------------------------------------------------------------------------------------------------------------------------

    def open(self, delivery: str, *, by: str, now: str | None = None, spacing_minutes: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        """Open the next attempt, or say why not. Returns the Delivery as written and the new entry.

        The entry is written, and the Delivery moves to ``sending``, in one conditional write on the row's revision: if the row changed since it was read (a correction
        marked it superseded, someone else opened an attempt) nothing is written and ``Conflict`` is raised. Only after this returns may the provider be called.

        ``spacing_minutes`` is the owner's post spacing for this account (None: none). While the account's last post is closer than that, the Delivery waits: it keeps its
        place, ``waitingFor`` says ``post spacing``, ``nextAttemptAt`` names when the spacing ends, and no attempt is opened. It goes like any wait, once the time has come."""
        now = now or now_iso()
        row = self.deliveries.get(delivery)
        if row is None:
            raise RecordError(f"There is no Delivery {delivery}.")
        if row.get("mode") == MANUAL:
            raise ManualDelivery(delivery)
        refused = self.structural_refusal(row)
        if refused:
            raise AttemptRefused(delivery, refused, self._flag(row, refused, now))
        pending = open_attempt_of(row)
        if pending:
            raise OpenAttempt(f"{delivery} has attempt {pending['number']} with no answer yet ({pending['outcome']}); settle it before another attempt opens.")
        # The sender reads only the locked version: a Delivery whose lock time has come is locked by the same write that opens the attempt (delivery_lock.decide).
        lock = decide(self.deliveries, row, utc(now)) if not row.get("lockedAt") else None
        locking = dict(lock.changes) if lock and lock.changes else {}
        if lock and lock.action == WAITING_FOR_PERSON:
            raise_flag(self.deliveries, row, lock.reason or "")
        seen = {**row, **locking}
        ok, why = self.deliveries.releasable(seen, now)
        if not ok:
            raise NotReleasable(delivery, why or "not releasable")
        refused = self.words_refusal(seen)
        if refused:
            raise AttemptRefused(delivery, refused, self._flag(row, refused, now))
        if spacing_minutes:
            until = self.deliveries.spacing_until(row, spacing_minutes)
            if until and utc(now) < until:
                if row.get("nextAttemptAt") != until or row.get("waitingFor") != POST_SPACING:
                    self.deliveries._change(row, {"waitingFor": POST_SPACING, "nextAttemptAt": until}, by=by, note=f"held by post spacing until {until}", now=now)
                raise NotReleasable(delivery, f"waiting for {POST_SPACING} until {until}")
        log = attempt_log(row)
        number = len(log) + 1
        entry = {"number": number, "at": now, "eventId": attempt_event_id(delivery, number), "outcome": STARTED, "by": by, "version": sendable_number(seen)}
        written = self.deliveries._change(
            row, {**locking, "attempts": [*log, entry], "state": SENDING, "blockedReason": None, "nextAttemptAt": None, "waitingFor": None},
            by=by, note=f"attempt {number} started" + (f"; {lock.note}" if locking and lock else ""), now=now)
        return written, entry

    # --- close ------------------------------------------------------------------------------------------------------------------------------------

    def close(self, delivery: str, number: int, outcome: str, *, by: str, now: str | None = None, code: str | None = None, provider_id: str | None = None,
              cost: str | None = None, wait: Wait | None = None) -> dict[str, Any]:
        """Close attempt ``number`` as ``sent``, ``refused`` or ``unknown``.

        ``started`` closes to any of the three; ``unknown`` closes to ``sent`` or ``refused`` once the provider's record says which; a ``sent`` or ``refused`` entry
        never changes. A ``refused`` attempt whose code is a pause, a budget stop or a rate limit is a wait: it puts ``nextAttemptAt`` and ``waitingFor`` on the
        Delivery. Closing never changes the state of a superseded Delivery: the outcome goes in the log only.

        The write is conditional on the row's revision. When the row changed since it was read (it was superseded while the attempt was open, say) the row is read
        again and the close is applied to what is there now; a close never overwrites a change it has not seen."""
        if outcome not in (ATTEMPT_SENT, ATTEMPT_REFUSED, UNKNOWN):
            raise RecordError(f"An attempt closes as sent, refused or unknown; not {outcome!r}.")
        if outcome == ATTEMPT_REFUSED and code == RATE_LIMIT_CODE and not (wait and wait.until):
            raise RecordError("A rate limit names the time to try again.")
        now = now or now_iso()
        while True:
            row = self.deliveries.get(delivery)
            if row is None:
                raise RecordError(f"There is no Delivery {delivery}.")
            log = attempt_log(row)
            index = next((i for i, entry in enumerate(log) if int(entry["number"]) == int(number)), None)
            if index is None:
                raise RecordError(f"{delivery} has no attempt {number}.")
            entry = dict(log[index])
            if entry["outcome"] == outcome:
                return row
            if entry["outcome"] in (ATTEMPT_SENT, ATTEMPT_REFUSED):
                raise AttemptClosed(f"Attempt {number} of {delivery} was already closed as {entry['outcome']}; an earlier entry never changes.")
            entry["outcome"] = outcome
            if code:
                entry["code"] = code
            if outcome != UNKNOWN:
                entry["closedAt"] = now
            entry["by"] = by
            closed = [*log[:index], entry, *log[index + 1:]]
            changes = {"attempts": closed, **self._after(row, outcome, code, provider_id, cost, wait)}
            try:
                return self.deliveries._change(row, changes, by=by, note=f"attempt {number} {outcome}" + (f" ({code})" if code else ""), now=now)
            except Conflict:
                continue

    def _after(self, row: Mapping[str, Any], outcome: str, code: str | None, provider_id: str | None, cost: str | None, wait: Wait | None) -> dict[str, Any]:
        """What the Delivery itself becomes when an attempt closes. A superseded Delivery keeps its state: only the facts the provider recorded are written."""
        facts: dict[str, Any] = {}
        if provider_id:
            facts["providerId"] = provider_id
        if cost is not None:
            facts["cost"] = cost
        if row.get("state") != SENDING or outcome == UNKNOWN:
            return facts   # superseded, withdrawn or already moved on: the log is the record. An unknown outcome leaves the Delivery sending.
        if outcome == ATTEMPT_SENT:
            return {**facts, "state": SENT, "blockedReason": None, "nextAttemptAt": None, "waitingFor": None}
        if code == PAUSED_CODE:
            return {**facts, "state": BLOCKED, "blockedReason": PAUSED_CODE, "nextAttemptAt": None, "waitingFor": None}
        if code == BUDGET_REACHED_CODE:
            return {**facts, "state": BLOCKED, "blockedReason": BUDGET_REACHED_CODE, "waitingFor": BUDGET_CYCLE if wait and wait.until else None,
                    "nextAttemptAt": utc(wait.until) if wait and wait.until else None}
        if code == RATE_LIMIT_CODE:
            return {**facts, "state": READY, "blockedReason": None, "waitingFor": RATE_LIMIT, "nextAttemptAt": utc(wait.until)}
        return {**facts, "state": FAILED, "blockedReason": None, "nextAttemptAt": None, "waitingFor": None}

    # --- manual mode ------------------------------------------------------------------------------------------------------------------------------

    def record_manual(self, delivery: str, url: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """A person posted a manual Delivery's words by hand and pastes the address of the post: the Delivery becomes ``sent`` and the attempt log names that person.

        Only a manual Delivery that is ``ready`` (its words are drafted and checked: a draft, a blocked draft, a sending, sent, failed or superseded Delivery is
        refused), is the highest generation, and whose words file is the one its content hash names. The address is an http or https URL. It is one conditional
        write on the row's revision (the attempt, the state and ``resultUrl`` together), so recording twice, or two people recording at once, gives one entry and the
        second is refused. Nothing is handed to a provider; the attempt has no event id because there is no provider event."""
        now = now or now_iso()
        row = self.deliveries.get(delivery)
        if row is None:
            raise RecordError(f"There is no Delivery {delivery}.")
        if not (by or "").strip():
            raise RecordError("A manual post is recorded by a person: say who posted it.")
        if row.get("mode") != MANUAL:
            raise RecordError(f"{delivery} is an automatic Delivery: only a manual Delivery is recorded by hand.")
        if row.get("state") == SENT:
            raise RecordError(f"{delivery} is already sent (address {row.get('resultUrl')}); an earlier record is never changed.")
        if row.get("state") != READY:
            raise RecordError(f"{delivery} is {row.get('state')}; only a ready Delivery, whose words are drafted and checked, is recorded as posted.")
        address = manual_address(url)
        refused = self.refusal(row)
        if refused:
            raise RecordError(f"{delivery} is not recorded: {refused}.")
        log = attempt_log(row)
        number = len(log) + 1
        entry = {"number": number, "at": now, "outcome": ATTEMPT_SENT, "closedAt": now, "by": by, "url": address, "version": sendable_number(row)}
        return self.deliveries._change(
            row, {"attempts": [*log, entry], "state": SENT, "resultUrl": address, "blockedReason": None, "nextAttemptAt": None, "waitingFor": None},
            by=by, note=f"posted by hand by {by}: {address}", now=now)

    # --- settle -----------------------------------------------------------------------------------------------------------------------------------

    def read(self, delivery: str, entry: Mapping[str, Any], transport: Transport, *, by: str, now: str) -> dict[str, Any]:
        """Close the open attempt if the provider's record says how it ended; otherwise leave it open. Reads only; hands nothing over."""
        return self.apply(delivery, entry, transport.delivery(entry["eventId"]), by=by, now=now)

    def apply(self, delivery: str, entry: Mapping[str, Any], answer: Answer | None, *, by: str, now: str) -> dict[str, Any]:
        if answer is None or answer.status == QUEUED:
            return self.deliveries.get(delivery) or {}
        number = entry["number"]
        if answer.status == ANSWER_SENT:
            return self.close(delivery, number, ATTEMPT_SENT, by=by, now=now, provider_id=answer.provider_id, cost=answer.cost)
        if answer.status == ANSWER_REFUSED:
            wait = Wait(BUDGET_CYCLE if answer.code == BUDGET_REACHED_CODE else RATE_LIMIT, answer.wait_until) if answer.code in (BUDGET_REACHED_CODE, RATE_LIMIT_CODE) else None
            return self.close(delivery, number, ATTEMPT_REFUSED, by=by, now=now, code=answer.code, cost=answer.cost, wait=wait)
        if answer.status == ANSWER_FAILED:
            return self.close(delivery, number, ATTEMPT_REFUSED, by=by, now=now, code=answer.code or "refused by the provider", cost=answer.cost)
        raise RecordError(f"The channel's record has the status {answer.status!r}.")

    def settle(self, delivery: str, transport: Transport, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Settle an attempt left ``started`` or ``unknown`` without a second post.

        It reads what Caducus recorded for the entry's event id. A record that says how it ended closes the entry. When Caducus has no record, the event may never have
        been handed over (the worker died after writing ``started``), so the same event id is handed over again: Caducus dedupes on it, so a post that did land is not
        made twice. No time decides anything: an entry with no record yet simply stays open."""
        now = now or now_iso()
        row = self.deliveries.get(delivery)
        entry = open_attempt_of(row) if row else None
        if row is None or entry is None:
            return row or {}
        answer = transport.delivery(entry["eventId"])
        if answer is not None:
            return self.apply(delivery, entry, answer, by=by, now=now)
        refused = self.refusal(row)
        if refused:
            self._flag(row, refused, now)
            return row
        self.hand_over(row, entry, transport, by=by, now=now)
        return self.read(delivery, entry, transport, by=by, now=now)

    def hand_over(self, row: Mapping[str, Any], entry: Mapping[str, Any], transport: Transport, *, by: str, now: str) -> None:
        """Call the provider for an attempt that is already written. A rate limit ends the attempt; any other failure leaves its outcome ``unknown`` and is raised.
        A manual Delivery is never handed to a provider."""
        if row.get("mode") == MANUAL:
            raise ManualDelivery(row["id"])
        text = self.deliveries.sent_text(row)
        try:
            transport.submit(row, text or "", entry["eventId"])
        except RateLimited as limited:
            self.close(row["id"], entry["number"], ATTEMPT_REFUSED, by=by, now=now, code=RATE_LIMIT_CODE, wait=Wait(RATE_LIMIT, limited.until))
        except Exception:
            self.close(row["id"], entry["number"], UNKNOWN, by=by, now=now, code="no answer to the hand-over")
            raise


class AccountWorker:
    """The one consumer for one channel account. Every attempt for the account passes through it, one at a time, so two attempts for one account never race. A
    Delivery of another account is refused. (The queue that gives the worker its single consumer belongs to the channel's infrastructure; this is the rule it keeps.)"""

    def __init__(self, deliveries: Deliveries, transport: Transport, channel: str, account_id: str, *, spacing_minutes: int | None = None):
        self.spacing_minutes = spacing_minutes   # the owner's post spacing for this account (``settings.spacing_minutes``); None means none
        self.attempts = Attempts(deliveries)
        self.deliveries = deliveries
        self.transport = transport
        self.channel, self.account_id = channel, account_id
        self.key = account_key(channel, account_id)
        self.handled: list[str] = []

    def _mine(self, delivery: str) -> dict[str, Any]:
        row = self.deliveries.get(delivery)
        if row is None:
            raise RecordError(f"There is no Delivery {delivery}.")
        if row["accountKey"] != self.key:
            raise WrongConsumer(f"{delivery} is for {row['accountKey']}; this worker is the only consumer of {self.key}.")
        return row

    def send(self, delivery: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Open the next attempt, hand it to the channel, and read what the channel recorded. Nothing is sent when the attempt does not open."""
        now = now or now_iso()
        self._mine(delivery)
        self.handled.append(delivery)
        row, entry = self.attempts.open(delivery, by=by, now=now, spacing_minutes=self.spacing_minutes)
        self.attempts.hand_over(row, entry, self.transport, by=by, now=now)
        return self._counted(self.attempts.read(delivery, entry, self.transport, by=by, now=now), by=by, now=now)

    def settle(self, delivery: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        self._mine(delivery)
        self.handled.append(delivery)
        return self._counted(self.attempts.settle(delivery, self.transport, by=by, now=now), by=by, now=now)

    def refresh_counts(self, delivery: str, *, by: str, now: str | None = None) -> dict[str, Any]:
        """Read Caducus's records of the Delivery again and write its counts. The provider reports deliveries, bounces and complaints after the send, so whatever
        wakes the Delivery later (the due check, a provider event) calls this."""
        self._mine(delivery)
        return DeliveryCounts(self.deliveries).refresh(delivery, self.transport, by=by, now=now)  # type: ignore[arg-type]

    def _counted(self, row: dict[str, Any], *, by: str, now: str | None) -> dict[str, Any]:
        """An email Delivery's counts follow its attempt: they are read from Caducus's records every time the worker has touched the Delivery."""
        return self.refresh_counts(row["id"], by=by, now=now) if row.get("channel") == EMAIL else row
