"""The render task of a site served from the public index (``homePage.references.source: "index"``): decide which blocks a change touched, ask the index for those
blocks alone, and write the pages whose blocks changed. There is no ``references.json``.

``run_home_page_snapshot`` (``task.py``) reads the table; this reads what pages show. It uses the lock table for two small records only: the list of changes the
stream trigger recorded (coordinates, ``routing.py``) and what each block remembered of its last render (``indexed.Block.state``). With no usable record, or after
a mass import, every block is asked once, which for the two live sites is a few dozen requests and not a read of the corpus.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..publication import PUBLICATION_KEY_ENVIRONMENT  # noqa: F401 - the corpus id is found as the snapshot task finds it
from .incremental import fingerprint_of
from .indexed import IndexAnchors, IndexReader, block_key
from .routing import STATE_FORMAT, Coordinate, touched_blocks
from .settings import HomePageSettings
from .snapshot import THREADS_FILE, build_threads_snapshot, changed_without_generated_at, snapshot_bytes, thread_file
from .state_store import DirtyBatch
from .task import (
    ProjectorRefused,  # noqa: F401
    _project_listings,
    _stale_list_files,
    _stale_thread_files,
    _stale_thread_pages,
    corpus_id_for,
    reader_pages_of,
    site_key,
    story_anchor_resolver,
    with_public_data_limits,
)
from .threads import collect_threads


def _coordinates(batch: DirtyBatch | None) -> list[Coordinate] | None:
    """The changes the trigger recorded, or ``None`` when they cannot be trusted (no batch, a mass import, or ids that came with no coordinate)."""
    if batch is None or batch.full:
        return None
    parsed = [Coordinate.from_json(json.loads(entry)) for entry in sorted(batch.coords)]
    if {coordinate.identifier for coordinate in parsed} != set(batch.ids):
        return None   # an id with no coordinate came from a trigger that records none: it could be anything
    return parsed


def _selection(projector: Any, readers: frozenset[str], touched_pages: set[str], everything: bool) -> frozenset[str]:
    """The pages to render: all readers, or the touched pages with their Markdown twins (and ``llms-full.txt``, which carries the twins)."""
    if everything:
        return readers
    from ..projection.standard.markdown import LLMS_FULL_KEY, md_key

    chosen = set(touched_pages)
    if getattr(getattr(projector, "standard", None), "agents", None) is not None and projector.standard.agents.markdown:
        chosen.update(twin for twin in (md_key(key) for key in list(chosen)) if twin)
        if chosen and projector.standard.agents.llms_full:
            chosen.add(projector.policy.key(LLMS_FULL_KEY))
    return frozenset(chosen & readers)


def run_home_page_render(
    context: Any,
    client: Any,
    settings: HomePageSettings | None,
    *,
    site: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    block_store: Any = None,
    dirty: DirtyBatch | None = None,
    reader: IndexReader | None = None,
) -> dict[str, Any]:
    """Report ``{mode, blocks, touchedBlocks, pagesTouched, pagesRewritten, rewritten, threads, requests, written, deleted, purged}``.

    ``mode`` is ``incremental`` when the trigger's coordinates and the remembered blocks decided what to render, and ``full`` when every block was asked."""
    if settings is None or not settings.references.indexed:
        return {"skipped": "this site is not served from the public index", "written": [], "deleted": [], "pagesRewritten": 0, "rewritten": [], "purged": []}
    settings = with_public_data_limits(settings, context.projector)
    corpus_id = corpus_id_for(settings, site)
    stamp = now or datetime.now(timezone.utc)
    projector = context.projector
    as_of = projector._day()
    by_page = projector.home_page_blocks_by_page()
    wanted = {block_key(attributes, as_of) for blocks in by_page.values() for attributes in blocks}
    fingerprint = fingerprint_of(settings, corpus_id)
    stored = block_store.load() if block_store is not None else None
    usable = isinstance(stored, dict) and stored.get("format") == STATE_FORMAT and stored.get("fingerprint") == fingerprint
    states = dict(stored.get("blocks") or {}) if usable else {}
    coordinates = _coordinates(dirty) if usable else None
    mode = "incremental" if coordinates is not None else "full"
    read_threads = settings.threads.enabled and (mode == "full" or bool(dirty and dirty.messages) or any((c.feed0 is None) != (c.feed1 is None) for c in coordinates or []))
    everything = mode == "full" or read_threads   # a thread page and the files that list it are written with the pages, so every page is asked once
    touched = set(wanted) if everything else touched_blocks(states, wanted, coordinates or [], as_of=as_of)
    paged = {block_key(attributes, as_of) for blocks in by_page.values() for attributes in blocks if attributes.get("paged") == "true"}
    if paged and (touched or everything):
        touched |= paged   # a paged list is the whole selection, and the files of every chunk are named from it: all of them are asked together or not at all
    index = reader or IndexReader(client, corpus_id, settings)
    if not touched and not read_threads:   # nothing a block shows changed: no block is asked, and the pages that name the chunk files of a paged list are not even worked out
        _remember(block_store, fingerprint, states, index, wanted, dry_run)
        return {"mode": mode, "blocks": len(wanted), "touchedBlocks": 0, "pagesTouched": 0, "pagesRewritten": 0, "rewritten": [], "threads": 0, "threadsRead": False, "written": [],
                "deleted": [], "purged": [], "unchanged": [], "requests": {}}
    projector.use_home_page_index(index, frozenset(touched))
    readers = reader_pages_of(projector)   # after the index is attached: the chunk files of a paged list are named from the list
    touched_pages = {page for page, blocks in by_page.items() if any(block_key(attributes, as_of) in touched for attributes in blocks)}
    thread_files: dict[str, bytes] = {}
    thread_count = 0
    if read_threads:
        thread_files, thread_count = _thread_files(settings, client, projector, index, stamp)
    report: dict[str, Any] = {"mode": mode, "blocks": len(wanted), "touchedBlocks": len(touched), "pagesTouched": len(touched_pages), "pagesRewritten": 0, "rewritten": [],
                              "threads": thread_count, "threadsRead": read_threads, "written": [], "deleted": [], "purged": [], "unchanged": []}
    selection = _selection(projector, readers, touched_pages, everything=everything)
    if paged & touched and not everything:
        selection |= frozenset(projector.reference_list_keys())   # the files of the chunks are written with the page that places the list
    if not selection and not read_threads:
        report["requests"] = dict(index.requests)
        _remember(block_store, fingerprint, states, index, wanted, dry_run)
        return report
    from ..projection.engine import check_rewrite_selection

    list_keys = getattr(projector, "reference_list_keys", None)
    check_rewrite_selection(context, selection - (list_keys() if list_keys is not None else frozenset()))
    with context.leased():
        pending = {name: content for name, content in thread_files.items() if changed_without_generated_at(context.writer.get(name), content)}
        report["unchanged"] = [name for name in thread_files if name not in pending]
        stale = _stale_thread_files(context, settings, thread_files) if read_threads else []
        stale_pages = _stale_thread_pages(context, stale)
        if dry_run:
            report["wouldWrite"] = sorted(pending)
            report["wouldDelete"] = [*stale, *stale_pages]
            report["wouldRewrite"] = sorted(selection)
            report["requests"] = dict(index.requests)
            return report
        for name, content in pending.items():
            context.writer.put(name, content)
            report["written"].append(name)
        for name in [*stale, *stale_pages]:
            context.writer.delete(name)
            report["deleted"].append(name)
        projected = _project_listings(context, selection)
        if paged & touched:
            for name in _stale_list_files(context):   # the chunk files of a paged list that the cuts no longer make
                context.writer.delete(name)
                report["deleted"].append(name)
        report["rewritten"] = list(projected.written)
        report["pagesRewritten"] = len(projected.written)
        if settings.freshness.purge and context.invalidate is not None:
            report["purged"] = context.invalidate([*report["written"], *report["deleted"], *report["rewritten"]])
        if projected.errors:
            report["errors"] = list(projected.errors)
    report["requests"] = dict(index.requests)
    if not report.get("errors"):
        _remember(block_store, fingerprint, states, index, wanted, dry_run)
    return report


def _thread_files(settings: HomePageSettings, client: Any, projector: Any, index: IndexReader, now: datetime) -> tuple[dict[str, bytes], int]:
    """The thread files to write by object key, and the number of public threads; a Reference anchor is public when its row is in the public index."""
    threads = collect_threads(client, IndexAnchors(index), settings, story_anchor=story_anchor_resolver(client, projector))
    listing, documents = build_threads_snapshot(threads, now)
    files = {site_key(projector, THREADS_FILE): snapshot_bytes(listing)}
    for key, document in documents.items():
        files[site_key(projector, thread_file(key))] = snapshot_bytes(document)
    return files, len(threads)


def _remember(block_store: Any, fingerprint: str, states: dict[str, Any], index: IndexReader, wanted: set[str], dry_run: bool) -> None:
    """Keep what the blocks of this run remember, and what the other blocks remembered before; blocks no page places any more are forgotten."""
    if block_store is None or dry_run:
        return
    merged = {**states, **index.block_states()}
    block_store.save({"format": STATE_FORMAT, "fingerprint": fingerprint, "blocks": {key: state for key, state in merged.items() if key in wanted}})
