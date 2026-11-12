"""The contract with Caducus's ``x`` channel (AnthusAI/Caducus PR #13, kanbus-ea2644), as Papyrus uses it.

Caducus owns the transport. Papyrus hands it one ``story.announce`` event per announcement (class ``broadcast``: the event's ``audience`` is the account key
``CHANNELACCT#x#<accountId>``, ``facts.text`` is the drafted post and ``facts.url`` its link) and Caducus posts it from its ``x`` queue: it dedupes on the event id,
claims the delivery before the request, never repeats a request whose outcome is unknown without reading the account's recent posts first, waits out X's rate
limits and records the post id and what each call cost. Papyrus learns the result by reading the delivery, never from the call that handed the event over.

Papyrus supplies to Caducus: the token provider (the account connection, PPY-2deb63, keeps the rotating refresh token), the ``Guard`` (``guard.SpendGuard``: pause and
budget), the price table (copied from X's list with its date in each note: ``prices_from_settings``), ``Directory.account`` and the ``story.announce`` kind. Those
wiring pieces ship with the Caducus release; until it is out nothing here posts, and a site set to On refuses to run (``ChannelNotAvailable``).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol

EVENT_PREFIX = "story.announce:"
KIND = "story.announce"
AUDIENCE_PREFIX = "CHANNELACCT#x#"

# Delivery statuses Papyrus acts on (Caducus delivery log).
QUEUED, SENT, FAILED, REFUSED, WITHDRAWN = "queued", "sent", "failed", "refused", "withdrawn"


def event_id(account_id: str, lineage_id: str, round_number: int = 1) -> str:
    """The Caducus event id: it dedupes in the site's table, so one account never gets two posts for one Story lineage. A guard refusal is final for its event id, so
    the announcement made after the guard lifted is round 2, 3, ... and carries the round in its id."""
    base = f"{EVENT_PREFIX}{account_id}:{lineage_id}"
    return base if round_number == 1 else f"{base}:r{round_number}"


def audience(account_id: str) -> str:
    return AUDIENCE_PREFIX + account_id


class ChannelNotAvailable(RuntimeError):
    """The site is set to post but no Broadcaster is wired (the Caducus ``x`` channel is not released or not deployed on this site)."""


@dataclass(frozen=True)
class DeliveryView:
    """One delivery as the Caducus log records it."""

    status: str
    post_id: str | None = None
    cost: str | None = None  # decimal string: the running total Caducus charged on this delivery
    reason: str | None = None
    attempts: int = 0
    withdrawn_by: str | None = None
    withdrawn_at: str | None = None


def view_of(item: Mapping[str, Any]) -> DeliveryView:
    """A Caducus delivery-log item as a view."""
    return DeliveryView(status=str(item["status"]), post_id=item.get("providerMessageId"), cost=item.get("cost"), reason=item.get("reason"),
                        attempts=int(item.get("attempts") or 0), withdrawn_by=item.get("withdrawnBy"), withdrawn_at=item.get("withdrawnAt"))


class Broadcaster(Protocol):
    def submit(self, *, account_id: str, event_id: str, text: str, url: str) -> None:
        """Hand the event to Caducus's router (it returns before anything is posted). Submitting the same event id again does nothing."""
        ...

    def delivery(self, event_id: str) -> DeliveryView | None:
        """The event's delivery, or None when Caducus has not recorded one yet."""
        ...

    def withdraw(self, event_id: str, *, by: str) -> DeliveryView:
        """Delete the post at X (never blocked by pause or budget) and return the delivery afterwards."""
        ...


def prices_from_settings(settings: Mapping[str, Any]) -> dict[str, tuple[Decimal, str]]:
    """The site's X price table as ``{name: (amount, note)}`` for Caducus's ``PriceTable``; each note names X's list and the date it was copied."""
    note = f"X API price list (docs.x.com/x-api/getting-started/pricing), copied {settings.get('pricesAsOf')}"
    return {name: (Decimal(str(amount)), note) for name, amount in (settings.get("prices") or {}).items()}
