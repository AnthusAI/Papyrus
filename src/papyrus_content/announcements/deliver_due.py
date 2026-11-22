"""The scheduled send: the engine's run when a Delivery's time comes (PPY-e2829f).

A Delivery is drafted with an edit window (``edit_windows.py``): ``releaseAt`` is when it may go and ``lockAt`` when it locks for the send. Its earliest pending time is ``dueAt``, which
has a follow-up timer (``delivery_timers.py``). When the timer fires, the runner starts the procedure ``deliver_due`` with no adopted agent (``engine_follow_ups.py``; only the site's
pause stops it), and the procedure calls ``deliver_due_run``:

1. **Read the Delivery again** and check that it still waits for the time the wake names (``follow_up_timers.check_wake``). A time that moved has its own wake; a Delivery that went,
   was withdrawn or was stopped waits for nothing. Either way the run does nothing (``nothing``, ``not_waiting``).
2. **Raise the lock if its time has come** (``delivery_lock.lock_at_time``). Under ``soft`` review a Delivery nobody acted on is approved by the policy (``approvedBy`` ``system``) and
   locked; a person's approval or edit is what is locked when there is one. Under ``hard`` review with no approval nothing is locked or sent, one flag is raised for a person, and the run
   ends ``asked`` (``waiting_for_person``).
3. **Send what is due** through the same steps the announce agent uses after it decides (``story_wake.deliver_steps``: ``x_delivery.send_due`` and ``email_delivery.send_due_email``),
   with the same guards: the site's mode, the X account, the pause and the budget (Caducus's guard, asked before every post). A Delivery locked before its release time is not sent; the
   lock moved its timer to the release time, whose wake sends it.

It ends ``acted`` with ``sent`` (something was handed to its channel) or ``locked`` (locked, not yet released), or ``nothing`` with the reason. It calls no model and decides nothing
about what is announced: that is the announce agent's.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .. import follow_up_timers
from .deliveries import Deliveries
from .delivery_lock import APPROVED_AND_LOCKED, LOCKED, WAITING_FOR_PERSON, lock_at_time
from .delivery_timers import OWNER
from .records import OPEN_OUTCOMES, now_iso, open_attempt_of, utc

BY = "deliver"
SENT, LOCKED_REASON, NOT_WAITING, ASKED_REASON, NOT_SENT, NOT_RELEASABLE = "sent", "locked", "not_waiting", "waiting_for_person", "not_sent", "not_releasable"

Sender = Callable[[str | None], list[dict[str, Any]]]


@dataclass
class DeliverServices:
    """What the run reaches outside itself for: the site's Deliveries (holding its timers) and the deliver steps, X then email (``now -> the Deliveries handed over``). A test
    replaces each one."""

    deliveries: Deliveries
    send_x: Sender | None = None
    send_email: Sender | None = None


def deliver_due_run(services: DeliverServices, delivery_id: str, due_at: str, *, now: str | None = None) -> dict[str, Any]:
    """The ``deliver_due`` procedure's one step for the wake of ``delivery_id`` at ``due_at``, with the outcome the runner records."""
    now = utc(now or now_iso())
    deliveries = services.deliveries
    answer = follow_up_timers.check_wake(follow_up_timers.follow_up_key(OWNER, delivery_id, due_at), deliveries.get(delivery_id))
    if not answer["waiting"]:
        return _ended(answer["reason"], "nothing", NOT_WAITING, delivery_id)
    lock = lock_at_time(deliveries, delivery_id, now=now, by=BY)
    if lock.action == WAITING_FOR_PERSON:
        return _ended(f"Delivery {delivery_id} reached its lock time with no approval: nothing is locked or sent, and a person is asked to look at it ({lock.reason}).",
                      "asked", ASKED_REASON, delivery_id, lock=lock.action, flag=lock.flag)
    handed = [*(services.send_x(now) if services.send_x else []), *(services.send_email(now) if services.send_email else [])]
    went = [row["id"] for row in handed if _handed_over(row, now)]
    lock_words = f"{lock.action}: {lock.reason}" if lock.reason else lock.action
    if went:
        return _ended(f"Handed {len(went)} Delivery(ies) to their channel at {now}: {', '.join(went)} (the lock: {lock_words}).", "acted", SENT, delivery_id, lock=lock.action, sent=went)
    if lock.action in (LOCKED, APPROVED_AND_LOCKED):
        row = deliveries.get(delivery_id) or lock.row
        ok, why = deliveries.releasable(row, now)
        return _ended(f"Delivery {delivery_id} is locked with version {row.get('lockedVersion')}; it is not sent yet ({why or 'its channel did not take it'}).", "acted",
                      LOCKED_REASON, delivery_id, lock=lock.action, releasable=ok)
    row = deliveries.get(delivery_id) or lock.row
    ok, why = deliveries.releasable(row, now)
    reason = (lock.action if lock.reason else NOT_RELEASABLE) if not ok else NOT_SENT
    words = why if not ok else "it may go, but its channel did not take it (announcements are not on, the account needs connecting, or the budget is not set)"
    return _ended(f"Nothing was sent for Delivery {delivery_id}: {words}.", "nothing", reason, delivery_id, lock=lock.action, releasable=ok)


def _handed_over(row: Mapping[str, Any], now: str) -> bool:
    """The step opened an attempt on this Delivery now (it is with its channel), as against writing a wait or a refusal on it."""
    attempt = open_attempt_of(row)
    return (attempt is not None and attempt.get("outcome") in OPEN_OUTCOMES and attempt.get("at") == now) or (row.get("state") == SENT and row.get("updatedAt") == now)


def _ended(summary: str, outcome: str, reason: str, delivery_id: str, **result: Any) -> dict[str, Any]:
    return {"summary": summary, "result": {"deliveryId": delivery_id, **result}, "run_outcome": outcome, "run_outcome_reason": reason}


def default_services(environ: Mapping[str, str]) -> DeliverServices:
    """The services of a real run in the procedure runner: the site's Deliveries with its timers (the lock moves the timer to the release time) and the announce agent's deliver steps."""
    import boto3

    from papyrus_content.agent_policy.run_gate import SiteCatalogue
    from papyrus_content.announcements.decisions import Announcements
    from papyrus_content.graphql_authoring import create_authoring_client
    from papyrus_content.list_cadence.store import ListSettingsStore
    from papyrus_content.list_cadence.story_wake import BUCKET_ENVIRONMENT, TENANT_ENVIRONMENT, deliver_steps, site_delivery_timers
    from papyrus_content.site_store import SiteStore

    client, _ = create_authoring_client()
    deliveries = Deliveries(client, timers=site_delivery_timers(environ, client))
    tenant, bucket = (environ.get(TENANT_ENVIRONMENT) or "").strip(), (environ.get(BUCKET_ENVIRONMENT) or "").strip()

    def lists() -> Mapping[str, Any]:
        return ListSettingsStore(SiteStore(boto3.client("s3"), bucket, SiteCatalogue(client))).read(tenant).document["lists"]

    send_x, send_email = deliver_steps(client, environ, deliveries, Announcements(client, deliveries), lists=lists)
    return DeliverServices(deliveries=deliveries, send_x=send_x, send_email=send_email)


def deliver_due(delivery_id: str, due_at: str, environ: Mapping[str, str] | None = None, services: DeliverServices | None = None, now: str | None = None) -> dict[str, Any]:
    """The procedure's work for one wake."""
    import os

    return deliver_due_run(services or default_services(os.environ if environ is None else environ), delivery_id, due_at, now=now)
