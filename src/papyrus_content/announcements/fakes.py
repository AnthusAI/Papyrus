"""In-memory stand-ins for the specs and tests: a backend holding only the rows announcements touch, a document store, and a Caducus x channel that behaves as its
contract documents. No network, no AWS, and never a real post.
"""
from __future__ import annotations

import copy
from typing import Any

from .channel import FAILED, QUEUED, REFUSED, SENT, WITHDRAWN, DeliveryView
from .store import INDEX


class FakeBackend:
    """Items (Story versions), PublishedItems, and the announcement models. Only the calls the announcements make are answered; anything else fails."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.published: dict[str, dict] = {}
        self.records: dict[str, dict[str, dict]] = {}
        self.reads: list[tuple[str, str]] = []

    def list_by_index(self, index: str, key: str, **_: Any) -> list[dict]:
        self.reads.append((index, key))
        if index == "itemsByLineageAndVersion":
            return copy.deepcopy([row for row in self.items.values() if row["lineageId"] == key])
        raise AssertionError(f"unexpected index {index}")

    def get_record(self, model: str, record_id: str) -> dict | None:
        if model == "PublishedItem":
            return copy.deepcopy(self.published.get(record_id))
        return copy.deepcopy(self.records.get(model, {}).get(record_id))

    def create_record(self, model: str, record: dict) -> None:
        table = self.records.setdefault(model, {})
        if record["id"] in table:
            raise RuntimeError("GraphQL request failed: The conditional request failed")
        table[record["id"]] = copy.deepcopy(record)

    def update_record(self, model: str, record: dict) -> None:
        self.records[model][record["id"]].update(copy.deepcopy(record))

    def iterate_newest_first(self, index: str, key: str, **_: Any):
        assert index == INDEX
        self.reads.append((index, key))
        rows = [row for row in self.records.get("Announcement", {}).values() if row["accountId"] == key]
        yield from copy.deepcopy(sorted(rows, key=lambda row: row["createdAt"], reverse=True))

    # --- fixtures ---------------------------------------------------------------------------------------------------------------------------------

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

    def rate(self, lineage: str, stars: int | None) -> None:
        self.items[f"{lineage}-v1"]["starRating"] = stars

    def retire(self, lineage: str) -> None:
        self.items[f"{lineage}-v1"].update(stage="retired", metadata='{"retiredInto": {"toLineageId": "other"}}')
        self.published.pop(f"published-{lineage}", None)


class MemoryFiles:
    def __init__(self) -> None:
        self.documents: dict[str, dict] = {}

    def put(self, row_id: str, document: Any, *, now: str) -> None:
        self.documents[row_id] = copy.deepcopy(dict(document))

    def get(self, row_id: str) -> dict | None:
        return copy.deepcopy(self.documents.get(row_id))


class FakeX:
    """Caducus's x channel as its contract documents it. ``submit`` queues; ``deliver`` is the x queue running: it posts, or refuses, or fails, and charges the price."""

    def __init__(self, post_price: str = "0.200") -> None:
        self.events: dict[str, dict] = {}
        self.deliveries: dict[str, dict] = {}
        self.submissions: list[str] = []
        self.next_post = 1000
        self.post_price = post_price
        self.fail_with: str | None = None

    def submit(self, *, account_id: str, event_id: str, text: str, url: str) -> None:
        self.submissions.append(event_id)
        if event_id in self.events:
            return
        self.events[event_id] = {"account": account_id, "text": text, "url": url}
        self.deliveries[event_id] = {"status": QUEUED, "attempts": 0}

    def deliver(self, event_id: str, *, refusal: str | None = None) -> None:
        delivery = self.deliveries[event_id]
        delivery["attempts"] += 1
        if refusal:
            delivery.update(status=REFUSED, reason=refusal)
        elif self.fail_with:
            delivery.update(status=FAILED, reason=self.fail_with)
        else:
            self.next_post += 1
            delivery.update(status=SENT, providerMessageId=str(self.next_post), cost=self.post_price)

    def delivery(self, event_id: str) -> DeliveryView | None:
        d = self.deliveries.get(event_id)
        if d is None:
            return None
        return DeliveryView(status=d["status"], post_id=d.get("providerMessageId"), cost=d.get("cost"), reason=d.get("reason"), attempts=d["attempts"],
                            withdrawn_by=d.get("withdrawnBy"), withdrawn_at=d.get("withdrawnAt"))

    def withdraw(self, event_id: str, *, by: str) -> DeliveryView:
        d = self.deliveries[event_id]
        d.update(status=WITHDRAWN, withdrawnBy=by, withdrawnAt="2026-11-13T12:00:00Z")
        return self.delivery(event_id)
