"""In-memory stand-ins for the specs and tests: Story fixtures over the records backend, a Caducus ``x`` channel that behaves as its contract documents, and the settings document.
No network, no AWS, and never a real post.
"""
from __future__ import annotations

import copy
from typing import Any

from .channel import FAILED, QUEUED, REFUSED, SENT, WITHDRAWN, DeliveryView
from .records_fakes import RecordsBackend


class StoryFixtures:
    """Story versions and their published copies, for a backend whose ``items`` and ``published`` are the ``Item`` and ``PublishedItem`` tables."""

    items: dict[str, dict]
    published: dict[str, dict]

    def add_story(self, lineage: str, *, stars: int | None = None, published: bool = True, story_type: str = "article", section: str | None = None,
                  title: str = "Can a system keep a secret from itself?", deck: str = "A look at non-interference.", body: str = "A system can keep a secret.",
                  summary: str = "") -> None:
        metadata = f"{{\"frontMatterYaml\": \"summary: {summary}\\n\"}}" if summary else "{}"
        row = {"id": f"{lineage}-v1", "lineageId": lineage, "versionNumber": 1, "versionState": "current", "type": story_type, "section": section, "slug": lineage,
               "title": title, "deck": deck, "bodyMarkus": body, "status": "published" if published else "draft", "stage": "published" if published else "draft",
               "starRating": stars, "metadata": metadata}
        self.items[row["id"]] = row
        if published:
            self.published[f"published-{lineage}"] = {**row, "id": f"published-{lineage}", "sourceItemId": row["id"]}

    def rate(self, lineage: str, stars: int | None, by: str | None = None) -> None:
        self.items[f"{lineage}-v1"]["starRating"] = stars
        if by is not None:
            self.items[f"{lineage}-v1"]["starRatedBy"] = by

    def retire(self, lineage: str) -> None:
        self.items[f"{lineage}-v1"].update(stage="retired", metadata='{"retiredInto": {"toLineageId": "other"}}')
        self.published.pop(f"published-{lineage}", None)


class StoryRecordsBackend(StoryFixtures, RecordsBackend):
    """The Announcement, Delivery and relation tables of ``RecordsBackend``, and Story versions so a Story can be read as the announcement code reads it."""

    tenant_id = "alpha"

    def __init__(self) -> None:
        super().__init__()
        self.items = self.records.setdefault("Item", {})
        self.published = self.records.setdefault("PublishedItem", {})

    def list_by_index(self, index: str, key: str, **options: Any) -> list[dict[str, Any]]:
        if index == "itemsByLineageAndVersion":
            self.reads.append((index, key))
            return copy.deepcopy([row for row in self.items.values() if row["lineageId"] == key])
        if index == "knowledgeCorporaByRoleAndName":
            return [{"id": "knowledge-corpus-mom", "name": "Machines on Machines", "role": "canonical"}]
        if index in ("itemBySlug", "modelAttachmentsByOwnerRoleAndSortKey"):
            return []
        return super().list_by_index(index, key, **options)


class _Account:
    def __init__(self, account_id: str) -> None:
        self.key = f"CHANNELACCT#x#{account_id}"


class _Price:
    def __init__(self, amount: str) -> None:
        self.amount = amount


class FakeX:
    """Caducus's x channel as its contract documents it. ``submit`` queues; ``deliver`` is the x queue running: it asks the Guard (``guard.SpendGuard``, when one is set) before the
    post and tells it what was charged after, then posts, or refuses, or fails, and charges the price. ``withdraw`` deletes the post and charges the deletion. ``log`` is every
    hand-over and every deletion in the order they happened."""

    def __init__(self, post_price: str = "0.200", delete_price: str = "0.010") -> None:
        self.events: dict[str, dict] = {}
        self.deliveries: dict[str, dict] = {}
        self.submissions: list[str] = []
        self.withdrawals: list[str] = []
        self.next_post = 1000
        self.post_price = post_price
        self.delete_price = delete_price
        self.fail_with: str | None = None
        self.guard: Any = None
        self.log: list[tuple[str, str]] = []

    def submit(self, *, account_id: str, event_id: str, text: str, url: str) -> None:
        self.submissions.append(event_id)
        self.log.append(("submit", event_id))
        if event_id in self.events:
            return
        self.events[event_id] = {"account": account_id, "text": text, "url": url}
        self.deliveries[event_id] = {"status": QUEUED, "attempts": 0}

    def deliver(self, event_id: str, *, refusal: str | None = None) -> None:
        delivery = self.deliveries[event_id]
        delivery["attempts"] += 1
        account = self.events[event_id]["account"]
        if not refusal and self.guard is not None and not self.fail_with:
            refusal = self.guard.refusal(_Account(account), _Price(self.post_price))
        if refusal:
            delivery.update(status=REFUSED, reason=refusal)
        elif self.fail_with:
            delivery.update(status=FAILED, reason=self.fail_with)
        else:
            self.next_post += 1
            delivery.update(status=SENT, providerMessageId=str(self.next_post), cost=self.post_price)
            if self.guard is not None:
                self.guard.charged(_Account(account), _Price(self.post_price))

    def delivery(self, event_id: str) -> DeliveryView | None:
        d = self.deliveries.get(event_id)
        if d is None:
            return None
        return DeliveryView(status=d["status"], post_id=d.get("providerMessageId"), cost=d.get("cost"), reason=d.get("reason"), attempts=d["attempts"],
                            withdrawn_by=d.get("withdrawnBy"), withdrawn_at=d.get("withdrawnAt"))

    def withdraw(self, event_id: str, *, by: str) -> DeliveryView:
        d = self.deliveries[event_id]
        self.withdrawals.append(event_id)
        self.log.append(("withdraw", event_id))
        total = f"{float(d.get('cost') or 0) + float(self.delete_price):.3f}"
        d.update(status=WITHDRAWN, withdrawnBy=by, withdrawnAt="2026-11-13T12:00:00Z", cost=total)
        return self.delivery(event_id)


class MemoryDocument:
    """The settings document store (``stores.DynamoSettings`` in the function): ``get`` and ``put`` of one JSON document."""

    def __init__(self) -> None:
        self.document: dict | None = None

    def get(self) -> dict | None:
        return copy.deepcopy(self.document)

    def put(self, settings: dict) -> None:
        self.document = copy.deepcopy(settings)


class FakeFunctions:
    """What ``handlers.Functions`` is, for the specs: the settings class of the ``announcements`` function over an in-memory document, and a connection status that a
    spec changes. Same methods, so the announcement code and the commands cannot tell the difference."""

    def __init__(self, clock: Any) -> None:
        from .settings import AnnouncementSettings

        self.clock = clock
        self.settings = AnnouncementSettings(MemoryDocument(), clock)
        self.connected = {"connection": "connected", "accountId": "mom", "handle": "@mom_test"}

    def read(self) -> dict:
        return self.settings.read()

    def save(self, proposed: dict, connection_status: str) -> dict:
        return self.settings.save(proposed, connection_status)

    def manual_pause(self, paused: bool, by: str) -> dict:
        return self.settings.manual_pause(paused, by)

    def pause(self, reason: str, detail: str, by: str, at: str) -> None:
        self.settings.pause(reason, detail, by, at)

    def resume(self) -> None:
        self.settings.resume()

    def resume_if(self, reason: str) -> None:
        self.settings.resume_if(reason)

    def status(self) -> dict:
        return dict(self.connected)
