"""The real binding to Caducus's ``x`` channel: a ``channel.Broadcaster`` over Caducus's own router, delivery log and ``XChannel``, and the directory that names the site's account.

``CaducusBroadcaster`` is what ``x_channel.XChannel`` (the attempt log's adapter) is built over in production. It is the same three calls the in-memory ``fakes.FakeX`` answers:

* ``submit`` hands the router one ``story.announce`` event of class ``broadcast``: ``audience`` is the account key ``CHANNELACCT#x#<accountId>``, ``facts.text`` the post exactly as drafted
  and ``facts.url`` its link. The router dedupes on the event id and queues one delivery on the ``x`` queue; nothing is posted by this call. An event the router refuses (no such account, no text)
  is raised here in words, because Caducus would record it against no recipient and there would be no delivery to read.
* ``delivery`` reads the delivery log's row for the event (``channel.view_of``): its status, the post id, the cost so far and the reason a post was refused or failed.
* ``withdraw`` is Caducus's ``XChannel.delete``: it deletes the post at X, is never blocked by a pause or the budget, and records who and when.

``SiteAccounts`` is Caducus's ``Directory`` for a site with one connected X account: ``account(key)`` answers the connection's account (the account connection, ``x_account``) and nothing else,
so an event naming any other account is refused as "no audience". Nothing here reads a token: the channel asks ``channel.CaducusTokens`` when it posts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from caducus.notify.directory import ChannelAccount, Directory, account_key
from caducus.notify.prices import Price

from .channel import KIND, DeliveryView, prices_from_settings, view_of
from .records import RecordError

CHANNEL = "x"
PRODUCT = "papyrus"
#: How many of the account's latest posts Caducus reads before it would post again after an unknown outcome. X's smallest page: the post in doubt was made moments ago by this same worker, and
#: X charges for every post read.
RECENT_POSTS_READ = 5


class SubmitRefused(RecordError):
    """Caducus's router refused the event (for instance the account is not connected), so no delivery was made."""


class SettingsPrices:
    """Caducus's ``PriceTable`` read from the settings document each time a price is asked for, so a price list the owner updates applies to the next post of a container that is still running."""

    def __init__(self, read: Callable[[], Mapping[str, Any]]):
        self._read = read

    def _price(self, name: str) -> Price:
        amount, note = prices_from_settings(self._read())[name]
        return Price(str(amount), "USD", note)

    post = property(lambda self: self._price("post"))
    post_with_url = property(lambda self: self._price("post_with_url"))
    delete = property(lambda self: self._price("delete"))
    read_per_post = property(lambda self: self._price("read_per_post"))


class SiteAccounts(Directory):
    """``connection`` is the account connection's status (``x_account.XAccounts.status``: ``connection``, ``accountId``, ``handle``). The one account is the site's connected one."""

    def __init__(self, connection: Callable[[], Mapping[str, Any]], base: Directory | None = None):
        self._connection, self._base = connection, base

    def operators(self):  # type: ignore[no-untyped-def]
        return self._base.operators() if self._base else []

    def get(self, key: str):  # type: ignore[no-untyped-def]
        return self._base.get(key) if self._base else None

    def probe(self):  # type: ignore[no-untyped-def]
        return self._base.probe() if self._base else None

    def account(self, key: str) -> Optional[ChannelAccount]:
        status = self._connection()
        account_id = status.get("accountId")
        if status.get("connection") != "connected" or not account_id or key != account_key(CHANNEL, str(account_id)):
            return None
        return ChannelAccount(key=key, address=str(status.get("handle") or ""), channel=CHANNEL, external_id=str(account_id))


class CaducusBroadcaster:
    """``router`` is Caducus's ``Router``, ``log`` its ``DeliveryLog``, ``channel`` its ``XChannel`` (the one that holds the token provider, the guard and the price table)."""

    def __init__(self, router: Any, log: Any, channel: Any, site_id: str, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.router, self.log, self.channel, self.site_id, self.clock = router, log, channel, site_id, clock

    def submit(self, *, account_id: str, event_id: str, text: str, url: str) -> None:
        result = self.router.handle_detail({
            "schema": 1, "eventId": event_id, "kind": KIND, "product": PRODUCT, "site": self.site_id, "severity": "info",
            "occurredAt": self.clock().strftime("%Y-%m-%dT%H:%M:%SZ"), "audience": account_key(CHANNEL, account_id), "facts": {"title": "Story announcement", "text": text, "url": url},
        })
        if result.outcome == "refused":
            raise SubmitRefused(f"Caducus refused the announcement {event_id}: {result.reason}.")

    def _row(self, event_id: str) -> Mapping[str, Any] | None:
        rows = [row for row in self.log.for_event(event_id) if row.get("channel") == CHANNEL]
        return rows[0] if rows else None

    def delivery(self, event_id: str) -> DeliveryView | None:
        row = self._row(event_id)
        return view_of(row) if row is not None else None

    def withdraw(self, event_id: str, *, by: str) -> DeliveryView:
        row = self._row(event_id)
        if row is None:
            raise RecordError(f"Caducus has no delivery for {event_id}, so there is no post to delete.")
        outcome = self.channel.delete(row, by=by)
        if outcome.status == "failed":
            raise RecordError(f"The post of {event_id} was not deleted: {outcome.reason}.")
        return view_of(self._row(event_id) or row)
