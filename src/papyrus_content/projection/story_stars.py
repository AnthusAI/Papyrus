"""The editors' private star ratings of Stories, kept where a projection can read them in one request.

A Story's rating lives on its newest ``Item`` version (``item_stars.py``). A projection that ranks listings needs the rating of every published Story,
and reading each Story's versions on every run would cost a request per Story. So the ratings are kept in the projection lock table (hash key
``publication``, the table every projection lease already uses, so a site needs no new table, no index and no permission beyond the ``GetItem`` and
``UpdateItem`` its content-actions function already has):

* ``story-stars#<scope>``: a map ``stars`` of ``{lineage id: stars}``, where 1 to 5 is a rating and 0 means "looked, nobody rated it". A Story missing
  from the map is simply not known yet: the next projection reads it once from its ``Item`` rows and records the answer, so a site starts with an empty
  map and a newly published Story is picked up without any extra step.

The map lives in the lock table and never beside the pages, because the site bucket is public and a rating is private. A rating change is one
``story-stars`` task (``amplify/functions/content-actions/handler.py``): it reads the one Item row that changed, sets its entry and re-renders the listing
pages whose order changed. Each entry is its own map key, so two ratings landing together never overwrite each other.

The size is the one real limit, DynamoDB's 400 KB for an item: about 6,000 Stories at roughly 60 bytes an entry. Past it the write fails loudly (the task
goes to the dead letter queue) and ratings stop reaching the pages; they never reach a public file.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ..item_stars import item_stars
from ..story_reporting import _current_of, story_versions
from .lease import lock_table_from_environment

STATE_PREFIX = "story-stars#"
UNRATED = 0
SCOPE_CHARACTERS = 8
FUNCTION_NAME_ENVIRONMENT = "AWS_LAMBDA_FUNCTION_NAME"
CONTENT_ACTIONS_FUNCTION_ENVIRONMENT = "PAPYRUS_CONTENT_ACTIONS_FUNCTION"
SCOPE_FIELD = "scope"


def scope_of(function_name: str) -> str:
    """The short stable name of a site's backend (the same hash the home-page task uses), so sites sharing an account never share an entry."""
    return hashlib.sha256(function_name.encode("utf-8")).hexdigest()[:SCOPE_CHARACTERS]


def state_key(scope: str) -> str:
    return f"{STATE_PREFIX}{scope}"


class MemoryStarStore:
    """The ratings in memory: what a test uses."""

    def __init__(self, stars: Mapping[str, int] | None = None) -> None:
        self.stars: dict[str, int] = dict(stars or {})
        self.reads = 0
        self.writes = 0

    def load(self) -> dict[str, int]:
        self.reads += 1
        return dict(self.stars)

    def record(self, entries: Mapping[str, int]) -> None:
        if entries:
            self.writes += 1
            self.stars.update(entries)


LOGGER = logging.getLogger("papyrus.projection")
RECORD_CHUNK = 50


class DynamoStarStore:
    """The ratings in the projection lock table: one consistent read to load them, two updates to record entries."""

    def __init__(self, table: Any, scope: str) -> None:
        self.table, self.scope = table, scope

    def load(self) -> dict[str, int]:
        item = self.table.get_item(Key={"publication": state_key(self.scope)}, ConsistentRead=True).get("Item") or {}
        return {str(lineage): int(value) for lineage, value in dict(item.get("stars") or {}).items()}

    def record(self, entries: Mapping[str, int]) -> None:
        if not entries:
            return
        key = {"publication": state_key(self.scope)}
        self.table.update_item(Key=key, UpdateExpression="SET stars = if_not_exists(stars, :empty)", ExpressionAttributeValues={":empty": {}})
        # One request holds only so much: DynamoDB refuses an update expression over 4 KB, and a site's first render records every Story at once.
        pairs = list(entries.items())
        for start in range(0, len(pairs), RECORD_CHUNK):
            chunk = pairs[start:start + RECORD_CHUNK]
            names = {f"#l{position}": lineage for position, (lineage, _) in enumerate(chunk)}
            values = {f":v{position}": int(value) for position, (_, value) in enumerate(chunk)}
            assignments = ", ".join(f"stars.#l{position} = :v{position}" for position in range(len(chunk)))
            self.table.update_item(Key=key, UpdateExpression=f"SET {assignments}", ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def content_actions_function_name(environment: Mapping[str, str]) -> str:
    """The name of the site's content-actions function: the running Lambda itself, the operator's override, or (on a laptop) the site's ``amplify_outputs.json``."""
    for name in (FUNCTION_NAME_ENVIRONMENT, CONTENT_ACTIONS_FUNCTION_ENVIRONMENT):
        if (environment.get(name) or "").strip():
            return environment[name].strip()
    if environment is os.environ:
        from ..projection_trigger import content_actions_function

        return content_actions_function()
    return ""


def star_store_from_environment(environ: Mapping[str, str] | None = None, *, scope: str | None = None, table: Any = None) -> DynamoStarStore | None:
    """The store of the running backend, or None when there is no lock table or no function name to scope it by.

    With none, listings keep their newest-first order: a local run that cannot find the ratings must not be used to write a site's pages.
    """
    environment = os.environ if environ is None else environ
    function_name = "" if scope else content_actions_function_name(environment)
    name = scope or (scope_of(function_name) if function_name else "")
    found = table if table is not None else (lock_table_from_environment(environment) if name else None)
    return DynamoStarStore(found, name) if name and found is not None else None


def stars_of_lineage(client: Any, lineage_id: str) -> int:
    """The rating on the Story's current Item version (``UNRATED`` when there is none): one request."""
    versions = story_versions(client, lineage_id)
    return (item_stars(_current_of(versions)) or UNRATED) if versions else UNRATED


def known_stars(store: Any, lineages: Iterable[str], read: Callable[[str], int]) -> dict[str, int]:
    """``{lineage: stars}`` for the rated Stories among ``lineages``. A lineage the store has not seen is read once with ``read`` and recorded."""
    wanted = list(dict.fromkeys(lineage for lineage in lineages if lineage))
    stored = store.load()
    fresh = {lineage: read(lineage) for lineage in wanted if lineage not in stored}
    if fresh:
        try:
            store.record(fresh)
        except Exception:  # noqa: BLE001 - remembering is a saving: the ratings were read, this render uses them, and the next one reads them again
            LOGGER.warning("could not remember %d Story ratings; they will be read again next time", len(fresh), exc_info=True)
        stored = {**stored, **fresh}
    return {lineage: stored[lineage] for lineage in wanted if stored.get(lineage, UNRATED) > UNRATED}
