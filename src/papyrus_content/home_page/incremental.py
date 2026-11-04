"""Keep the public snapshot current from the Reference rows that changed, not from the whole corpus.

Reading a corpus costs requests in proportion to its size (a page of 100 rows for each list, then a relations request and an attachments request for
every row). A snapshot kept that way costs the same again at every change, so a busy site paid for its entire corpus several times an hour. The rule
is that derived work runs once when something changes: this module turns the ids of the rows that changed into the new snapshot, and the number of
requests depends on how many rows changed and not on how many there are.

What carries over from one run to the next:

* the previous ``references.json``, which holds every public record as it was last built;
* a private state, one ``Standing`` per public record: an editor's stars, the live confidence the shared order reads (a record an editor accepted
  does not publish it), the arrival time, the Reference version and the section. It cannot sit beside the pages, because the bucket is public and
  the stars must never be, so it lives in the projection lock table (``state_store.py``).

A change to one row is read again (the row, its decision, and when it will show, its preview); nothing else is. The rank is a position among all the
records, so it is recomputed from the standings in memory. A state that cannot be trusted (none yet, written for other settings or another build of
the fields, or not the one that goes with the file in the bucket) is not repaired: the task reads the whole corpus once and starts a new one.

A decision written for a Reference that did not change in any field the page reads is not seen until that Reference changes: the first decision of a
Reference always writes onto its row (``record_original_prediction``), and that write is a change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..knowledge_snapshot.parallel import map_with_clients
from .export import PUBLIC_REFERENCE_FIELDS, PublicEntry, Standing, entry_for_row, ranked_records, scrub, section_labels_of

#: Bumped whenever the shape of a stored record or a Standing changes, so state written by an older build is replaced and never read.
STATE_FORMAT = 1
CREATED_FIELD = "createdAt"


class StateRefused(Exception):
    """The stored state cannot be used for this run; the whole corpus is read once to replace it."""


@dataclass(frozen=True)
class StoredState:
    """The private state: which settings it was built for, the file it goes with, and the standing of every public record."""

    fingerprint: str
    snapshot_sha: str
    entries: dict[str, Standing]


@dataclass
class Changes:
    """What one incremental pass produced."""

    records: list[dict[str, Any]]
    entries: dict[str, Standing]
    examined: int
    anchors_changed: bool = False
    touched: set[str] = field(default_factory=set)


def fingerprint_of(settings: Any, corpus_id: str) -> str:
    """Everything a stored record depends on besides the row: the corpus, the published fields, the threshold, the summary length and the build."""
    material = {
        "format": STATE_FORMAT,
        "corpus": corpus_id,
        "fields": list(settings.references.fields),
        "threshold": settings.references.recommended_threshold,
        "summary": settings.references.summary_characters,
        "public": list(PUBLIC_REFERENCE_FIELDS),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def sha_of(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def state_for(entries: Iterable[PublicEntry], *, fingerprint: str, snapshot: bytes) -> StoredState:
    return StoredState(fingerprint=fingerprint, snapshot_sha=sha_of(snapshot), entries={entry.key: entry.standing for entry in entries})


def usable_state(state: StoredState | None, *, fingerprint: str, snapshot: bytes | None) -> dict[str, dict[str, Any]]:
    """The previous records by key when ``state`` goes with ``snapshot`` and with these settings; ``StateRefused`` otherwise."""
    if state is None:
        raise StateRefused("there is no state yet")
    if state.fingerprint != fingerprint:
        raise StateRefused("the settings or the build of the fields changed")
    if snapshot is None or sha_of(snapshot) != state.snapshot_sha:
        raise StateRefused("the file in the bucket is not the one the state was built with")
    try:
        previous = {str(record["key"]): record for record in json.loads(snapshot)["references"]}
    except (ValueError, KeyError, TypeError) as error:
        raise StateRefused("the file in the bucket cannot be read") from error
    if set(previous) != set(state.entries):
        raise StateRefused("the file and the state hold different References")
    return previous


@dataclass(frozen=True)
class _Outcome:
    identifier: str
    entry: PublicEntry | None = None
    drop_key: str | None = None
    fresh: bool = False


def _outcome(worker: Any, identifier: str, corpus_id: str, settings: Any, labels: Mapping[str, str], since: str) -> _Outcome:
    from .export import public_key

    row = worker.get_record("Reference", identifier)
    if not row:
        return _Outcome(identifier)
    if row.get("versionState", "current") != "current" or not row.get("lineageId"):
        return _Outcome(identifier)
    key = public_key(str(row["lineageId"]))
    created = str(row.get(CREATED_FIELD) or "")
    fresh = bool(since and created and created >= since)
    entry = entry_for_row(worker, row, corpus_id, settings, labels)
    if entry is None:
        return _Outcome(identifier, drop_key=key, fresh=fresh)
    return _Outcome(identifier, entry=entry, fresh=fresh)


def apply_changes(
    client: Any,
    corpus_id: str,
    settings: Any,
    previous: Mapping[str, Mapping[str, Any]],
    entries: Mapping[str, Standing],
    identifiers: Iterable[str],
    *,
    since: str = "",
    client_factory: Callable[[], Any] | None = None,
    workers: int = 1,
) -> Changes:
    """The records after ``identifiers`` (ids of Reference rows that changed) are read again.

    ``since`` is when the previous snapshot was generated: a row created after it cannot have had a thread yet, so it is not a reason to read the
    threads again. The requests are one section list, then for each id the row, and for a row that is public or might be, its decision and its preview.
    """
    chosen = sorted({identifier for identifier in identifiers if identifier})
    records: dict[str, dict[str, Any]] = {key: dict(record) for key, record in previous.items()}
    standings: dict[str, Standing] = dict(entries)
    if not chosen:
        return Changes(records=ranked_records_of(records, standings), entries=standings, examined=0)
    labels = section_labels_of(client)
    outcomes = map_with_clients(
        chosen, lambda worker, identifier: _outcome(worker, identifier, corpus_id, settings, labels, since), client=client, client_factory=client_factory, workers=workers
    )
    by_id = {standing.id: key for key, standing in standings.items()}
    touched: set[str] = set()
    anchors_changed = False
    for outcome in outcomes:
        before = None
        key = None
        if outcome.entry is not None:
            key = outcome.entry.key
            before = records.get(key)
            records[key] = dict(outcome.entry.record)
            standings[key] = outcome.entry.standing
        elif outcome.drop_key is not None:
            key = outcome.drop_key
            before = records.pop(key, None)
            standings.pop(key, None)
        else:
            key = by_id.get(outcome.identifier)
            if key is not None and standings[key].id == outcome.identifier:
                before = records.pop(key, None)
                standings.pop(key, None)
            else:
                key = None
        if key is None:
            continue
        touched.add(key)
        after = records.get(key)
        if not outcome.fresh and ((before is None) != (after is None) or (before is not None and after is not None and before.get("title") != after.get("title"))):
            anchors_changed = True
    relabel(records, standings, labels)
    ordered = ranked_records_of(records, standings)
    return Changes(records=ordered, entries=standings, examined=len(chosen), anchors_changed=anchors_changed, touched=touched)


def relabel(records: dict[str, dict[str, Any]], standings: Mapping[str, Standing], labels: Mapping[str, str]) -> None:
    """The section label of every record, from the section list read this run, so a renamed section reaches every record that carries it."""
    for key, record in records.items():
        if "section" in record:
            record["section"] = scrub(labels.get(str(standings[key].section or "")))


def ranked_records_of(records: Mapping[str, Mapping[str, Any]], standings: Mapping[str, Standing]) -> list[dict[str, Any]]:
    """The records with fresh ranks. Each stored record is turned back into an entry (without its old rank), so the ranking is the one the full read uses."""
    entries = [PublicEntry(key, {name: value for name, value in record.items() if name != "rank"}, standings[key]) for key, record in records.items()]
    return ranked_records(entries)


__all__ = ["Changes", "StateRefused", "StoredState", "apply_changes", "fingerprint_of", "sha_of", "state_for", "usable_state"]
