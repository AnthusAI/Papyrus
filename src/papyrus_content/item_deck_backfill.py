"""`papyrus stories decks`: bring every Item's and PublishedItem's ``deck`` column to the dek its own front matter holds.

An Item's ``deck`` column is derived from its front matter by one rule (``item_front_matter.dek_from_front_matter``: ``dek``, then ``deck``, then
``standfirst``, then ``description``, first non-blank). Until that rule accepted ``dek`` (the canonical spelling, and the one the console editor and the
guides use), a version saved with a ``dek`` kept an older ``deck`` value, or none, so feeds, the newsroom context pack, announcements, reference curation
and the published row served a dek the story no longer had. This command re-derives the column for every row whose stored value differs.

* It reads the rows through the version-state index, state by state (no table scan; a named sweep), and every published row by its id (one point read per
  lineage). The client's tenant only.
* An Item row is re-derived from its own front matter (``metadata.frontMatterYaml``); a published row from the front matter it carries, the version that is
  served. A row with no front matter (a checklist step, a guideline document, a machine idea) has nothing to derive from and is left alone.
* It writes only the derived ``deck`` column, never front matter, and only on rows that differ, keeping each row's own ``updatedAt`` (a backfill is not a
  change of the Story). A second run writes nothing, so its dry run is the health check.

Writes by default; ``--dry-run`` prints what it would write. **At deploy** (:func:`ensure_item_decks`) the same code runs inside the post-deploy render before
anything reads a deck, once per site (a clean run leaves a marker in the site store); a run that fails part-way raises, fails the deploy before the render and
leaves no marker, and the next deploy finishes it.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .item_front_matter import dek_from_front_matter, parse_object
from .item_language_backfill import VERSION_STATES, read_published_rows
from .publishing import _load_front_matter
from .story_head_index import DEFAULT_RATE
from .tenancy import rows_for_tenant

SWEEP_NAME = "stories-decks"


@dataclass
class DeckPlan:
    rows: int = 0
    already_right: int = 0
    no_front_matter: int = 0
    writes: list[dict[str, Any]] = field(default_factory=list)   # {id, lineageId, deck (new value or None), was, updatedAt}
    published: "DeckPlan | None" = None

    def counts(self) -> dict[str, int]:
        return {"rows read": self.rows, "rows to write": len(self.writes), "already right": self.already_right, "without front matter": self.no_front_matter}


def plan_decks(rows: Iterable[dict[str, Any]]) -> DeckPlan:
    """The writes that make each row's ``deck`` the dek of its own front matter."""
    rows = list(rows)
    plan = DeckPlan(rows=len(rows))
    for row in sorted(rows, key=lambda r: (str(r.get("lineageId") or r.get("itemLineageId") or r["id"]), int(r.get("versionNumber") or 0), str(r["id"]))):
        text = parse_object(row.get("metadata")).get("frontMatterYaml")
        if not isinstance(text, str) or not text.strip():
            plan.no_front_matter += 1
            continue
        derived = dek_from_front_matter(_load_front_matter(text))
        stored = (row.get("deck") or "").strip() or None
        if stored == derived and (row.get("deck") or None) == derived:
            plan.already_right += 1
            continue
        plan.writes.append({"id": row["id"], "lineageId": str(row.get("lineageId") or row.get("itemLineageId") or row["id"]), "deck": derived,
                            "was": row.get("deck"), "updatedAt": row.get("updatedAt")})
    return plan


def read_rows(client: Any, states: Iterable[str] = VERSION_STATES) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state in states:
        rows += client.list_by_index("itemDeckFieldsByVersionState", state)
    return rows_for_tenant("Item", getattr(client, "tenant_id", None), rows)


def _line(change: dict[str, Any], state: str, model: str) -> str:
    return "\t".join(["stories", "decks", model, change["lineageId"], change["id"], f"deck={change['deck']!r}", state])


def run_decks(client: Any, *, dry_run: bool = False, rate: float = DEFAULT_RATE, sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic, echo: Callable[[str], None] = print) -> DeckPlan:
    """Plan, print and (unless ``dry_run``) write, no faster than ``rate`` writes a second."""
    from . import request_meter

    with request_meter.sweep(SWEEP_NAME):
        item_rows = read_rows(client)
        plan = plan_decks(item_rows)
        published = plan_decks(read_published_rows(client, item_rows))
    models = (("Item", plan), ("PublishedItem", published))
    if dry_run:
        for model, found in models:
            for change in found.writes:
                echo(_line(change, "would write", model))
    else:
        interval = 1.0 / rate if rate and rate > 0 else 0.0
        next_at = clock()
        with request_meter.sweep(SWEEP_NAME):
            for model, found in models:
                for change in found.writes:
                    wait = next_at - clock()
                    if wait > 0:
                        sleep(wait)
                    update = {"id": change["id"], "deck": change["deck"]}
                    if change.get("updatedAt"):
                        update["updatedAt"] = change["updatedAt"]
                    client.update_record(model, update)
                    next_at = max(next_at, clock()) + interval
                    echo(_line(change, "written", model))
    for model, found in models:
        summary = "\t".join(f"{name} {value}" for name, value in found.counts().items())
        echo(f"stories\tdecks\t{model}\t{'dry run' if dry_run else 'write'}\t{summary}")
    plan.published = published
    return plan


#: Where the deploy records that every row of the site has the deck its front matter holds (the site store's state, beside the language marker).
DEPLOY_MARKER_KEY = "_papyrus/migrations/item-decks.json"


def ensure_item_decks(client: Any, store: Any, *, now: Callable[[], str], echo: Callable[[str], None] = print) -> dict[str, Any]:
    """The deploy's step: re-derive the deck of every Item and published row that differs from its front matter's dek, once per site, before the render.
    Writes are not paced (a deploy is short); a failure raises and the next deploy finishes it."""
    import json

    if store.get(DEPLOY_MARKER_KEY) is not None:
        return {"itemDecks": "already written"}
    plan = run_decks(client, rate=0, echo=echo)
    result = {"itemDecks": "written", "items": len(plan.writes), "publishedItems": len(plan.published.writes)}
    store.put(DEPLOY_MARKER_KEY, json.dumps({**result, "at": now()}).encode("utf-8"))
    return result
