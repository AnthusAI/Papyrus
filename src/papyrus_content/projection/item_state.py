"""What the projection remembers about each item it wrote, in the site store beside the pages.

One small JSON object per item under ``_papyrus/items/``. Two items never share
a state object, so concurrent projections of different items never race on it.
The state is written last, so a projection that fails halfway is simply redone
from the old state: the retry recomputes the same plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

from .model import ItemSummary
from .writers import STATE_PREFIX, PageWriter

ITEM_STATE_PREFIX = STATE_PREFIX + "items/"


@dataclass(frozen=True)
class ItemState:
    summary: ItemSummary
    page_keys: tuple[str, ...]
    former_page_keys: tuple[str, ...] = ()

    @property
    def projected(self) -> bool:
        """False for the tombstone left when an item is unpublished: it only remembers where the item used to live."""
        return bool(self.page_keys)


def item_state_key(item_id: str) -> str:
    return f"{ITEM_STATE_PREFIX}{quote(item_id, safe='')}.json"


def summary_to_json(summary: ItemSummary) -> dict:
    return {
        "itemId": summary.item_id,
        "type": summary.type,
        "section": summary.section,
        "slug": summary.slug,
        "outputPath": summary.output_path,
        "versionNumber": summary.version_number,
        "title": summary.title,
        "pageTitle": summary.page_title,
        "frontMatter": summary.front_matter,
        "aliases": list(summary.aliases),
        "publishedAt": summary.published_at,
    }


def summary_from_json(raw: dict) -> ItemSummary:
    return ItemSummary(
        item_id=raw["itemId"],
        type=raw["type"],
        section=raw["section"],
        slug=raw["slug"],
        output_path=raw["outputPath"],
        version_number=raw["versionNumber"],
        title=raw["title"],
        page_title=raw["pageTitle"],
        front_matter=dict(raw["frontMatter"]),
        aliases=tuple(raw["aliases"]),
        published_at=raw["publishedAt"],
    )


def read_item_state(store: PageWriter, item_id: str) -> ItemState | None:
    body = store.get(item_state_key(item_id))
    if body is None:
        return None
    raw = json.loads(body.decode("utf-8"))
    return ItemState(
        summary=summary_from_json(raw["summary"]),
        page_keys=tuple(raw["pageKeys"]),
        former_page_keys=tuple(raw.get("formerPageKeys", ())),
    )


def write_item_state(store: PageWriter, state: ItemState) -> None:
    body = json.dumps(
        {
            "summary": summary_to_json(state.summary),
            "pageKeys": list(state.page_keys),
            "formerPageKeys": list(state.former_page_keys),
        },
        sort_keys=True,
    ).encode("utf-8")
    store.put(item_state_key(state.summary.item_id), body)


def item_id_from_state_key(key: str) -> str:
    from urllib.parse import unquote

    return unquote(key[len(ITEM_STATE_PREFIX) : -len(".json")])
