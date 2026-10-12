"""Project published content onto a site store.

Every function renders first and writes after, so a rendering failure leaves
the site untouched. Writes follow one order so a reader never meets a link to
a page that does not exist yet or no longer exists:

* published item: its pages, then the listing pages that changed, then the
  pages that went away, then redirects, then the item's state;
* unpublished item: the listing pages that changed, then the item's pages are
  deleted, then its redirects, then its state.

A listing page is re-rendered when, and only when, the inputs the projector
declares for it differ between the site as it was projected before this change
and the site now (membership, order, pagination, the fields shown). After the
writes the published versions are read again; if another publish moved them,
the pages that depend on the difference are rendered again, so concurrent
publishes converge.

``project``, ``project_listings``, ``project_all`` and ``reconcile`` are
idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .item_state import (
    ITEM_STATE_PREFIX,
    ItemState,
    item_id_from_state_key,
    item_state_key,
    read_item_state,
    write_item_state,
)
from .model import ItemSummary, ProjectionReport, SiteIndex, site_signature
from .projector import SiteProjector, normalized_redirect_source
from .source import ProjectionSourceError, PublishedContentSource, replace_item
from .writers import STATE_PREFIX, PageWriter, RedirectStore, StoredObject, body_etag, request_paths_for_key

LOGGER = logging.getLogger("papyrus.projection")
MAXIMUM_ROUNDS = 3
REPROJECT_ALL_THRESHOLD = 20


@dataclass
class ProjectionContext:
    source: PublishedContentSource
    projector: SiteProjector
    writer: PageWriter
    invalidate: Callable[[list[str]], list[str]] | None = None
    redirect_store: RedirectStore | None = None
    keep_state: bool = True
    maximum_rounds: int = MAXIMUM_ROUNDS
    defer_follow_up: bool = False


def _page_order(keys) -> list[str]:
    return sorted(keys, key=lambda key: (key.endswith(".xml"), key))


def _versions_by_page(context: ProjectionContext, site: SiteIndex) -> dict[str, int | None]:
    versions: dict[str, int | None] = {}
    for summary in site.items:
        for path in context.projector.item_page_paths(summary):
            versions[path] = summary.version_number
    return versions


def _write_item_pages(
    context: ProjectionContext, report: ProjectionReport, pages: dict[str, bytes], versions: dict[str, int | None]
) -> None:
    for key in _page_order(pages):
        context.writer.put(key, pages[key], version=versions.get(key))
        report.written.append(key)


def _write_listing_pages(
    context: ProjectionContext, report: ProjectionReport, pages: dict[str, bytes], inputs: dict[str, str]
) -> None:
    for key in _page_order(pages):
        context.writer.put(key, pages[key], inputs=inputs.get(key))
        report.written.append(key)


def _write_static(context: ProjectionContext, report: ProjectionReport, pages: dict[str, bytes]) -> None:
    for key in sorted(pages):
        context.writer.put(key, pages[key])
        report.written.append(key)


def _delete_pages(context: ProjectionContext, report: ProjectionReport, keys) -> None:
    for key in sorted(keys):
        context.writer.delete(key)
        report.deleted.append(key)


def _item_keys(context: ProjectionContext, site: SiteIndex) -> set[str]:
    return {key for summary in site.items for key in context.projector.item_page_paths(summary)}


def _moved_redirects(state: ItemState | None, live_keys: set[str]) -> dict[str, str]:
    if state is None or not state.page_keys or not state.former_page_keys:
        return {}
    target = request_paths_for_key(state.page_keys[0])[0]
    moved: dict[str, str] = {}
    for former in state.former_page_keys:
        if former in live_keys:
            continue
        for source in request_paths_for_key(former):
            moved[source] = target
    return moved


def _redirects_for(context: ProjectionContext, site: SiteIndex, state: ItemState | None) -> dict[str, str]:
    live_keys = _item_keys(context, site)
    return {**context.projector.redirects(site), **_moved_redirects(state, live_keys)}


def _apply_redirect_difference(
    context: ProjectionContext, report: ProjectionReport, old: dict[str, str], new: dict[str, str]
) -> None:
    if context.redirect_store is None:
        return
    puts = {source: target for source, target in new.items() if old.get(source) != target}
    deletes = sorted(set(old) - set(new))
    if puts:
        context.redirect_store.put_all(puts)
        report.redirects_written += len(puts)
    if deletes:
        context.redirect_store.delete_all(deletes)
        report.redirects_deleted += len(deletes)


def _run_follow_up(context: ProjectionContext, report: ProjectionReport, item_id: str) -> None:
    unchanged_since_read = None if report.rounds > 1 else item_id
    follow_up = project_item_pages(context, except_item_id=unchanged_since_read, finish=False)
    report.written.extend(follow_up.written)
    report.skipped.extend(follow_up.skipped)
    report.errors.extend(follow_up.errors)
    report.follow_up_item_pages = False


def _release_redirects_for_new_pages(context: ProjectionContext, report: ProjectionReport, new_keys) -> None:
    """A page that takes over a path an earlier rename redirected away must not stay shadowed by that redirect."""
    store = context.redirect_store
    if store is None:
        return
    shadowing = [
        source for key in sorted(new_keys) for source in request_paths_for_key(key) if store.get(source) is not None
    ]
    if shadowing:
        store.delete_all(shadowing)
        report.redirects_deleted += len(shadowing)


def _finish(context: ProjectionContext, report: ProjectionReport) -> ProjectionReport:
    touched = [key for key in [*report.written, *report.deleted] if not key.startswith(STATE_PREFIX)]
    if context.invalidate is not None and touched:
        try:
            report.invalidated = context.invalidate(touched)
        except Exception as error:  # noqa: BLE001 - reported in the result, the pages are already written
            report.errors.append(f"invalidation failed: {type(error).__name__}: {error}")
    return report


def _listing_difference(
    projector: SiteProjector, before: SiteIndex, after: SiteIndex
) -> tuple[set[str], set[str], dict[str, str]]:
    inputs_before = projector.listing_inputs(before)
    inputs_after = projector.listing_inputs(after)
    changed = {key for key, digest in inputs_after.items() if inputs_before.get(key) != digest}
    return changed, set(inputs_before) - set(inputs_after), inputs_after


def _updated_state(previous: ItemState | None, current: ItemSummary, page_keys: tuple[str, ...]) -> ItemState:
    former: list[str] = list(previous.former_page_keys) if previous else []
    if previous is not None:
        former.extend(key for key in previous.page_keys if key not in page_keys)
    return ItemState(
        summary=current,
        page_keys=page_keys,
        former_page_keys=tuple(dict.fromkeys(key for key in former if key not in page_keys)),
    )


def _log(item_id: str, report: ProjectionReport) -> None:
    LOGGER.info(
        "projection item=%s written=%s deleted=%s redirects=%s/%s rounds=%s followUp=%s",
        item_id,
        report.written,
        report.deleted,
        report.redirects_written,
        report.redirects_deleted,
        report.rounds,
        report.follow_up_item_pages,
    )


def project(context: ProjectionContext, item_id: str, *, unpublished: bool = False) -> ProjectionReport:
    """Project one item and the pages that depend on it.

    The stored data decides what happens: an item with a published version is
    projected, anything else is removed. ``unpublished`` is only a hint kept for
    callers that know the item was just unpublished.
    """
    report = ProjectionReport()
    previous_state = read_item_state(context.writer, item_id) if context.keep_state else None
    site = context.source.site_index()
    item = context.source.published_item(item_id)
    if item is None:
        _project_removal(context, report, item_id, previous_state, site)
    else:
        _project_publication(context, report, item, previous_state, site)
    if report.follow_up_item_pages and not context.defer_follow_up:
        _run_follow_up(context, report, item_id)
    _finish(context, report)
    _log(item_id, report)
    return report


def _project_publication(
    context: ProjectionContext, report: ProjectionReport, item, previous_state: ItemState | None, site: SiteIndex
) -> None:
    projector = context.projector
    current = item.summary
    previous = previous_state.summary if previous_state is not None and previous_state.projected else None
    site_before = replace_item(site, current.item_id, previous)
    dirty, removed, inputs = _listing_difference(projector, site_before, site)
    report.follow_up_item_pages = projector.shared_inputs(site_before) != projector.shared_inputs(site)
    item_pages = projector.item_pages(item, site)
    listing_pages = projector.listing_pages(site, dirty) if dirty else {}
    page_keys = tuple(sorted(item_pages))
    state = _updated_state(previous_state, current, page_keys)
    old_redirects = _redirects_for(context, site_before, previous_state)
    new_redirects = _redirects_for(context, site, state)

    _write_item_pages(context, report, item_pages, {key: current.version_number for key in item_pages})
    report.item_paths = list(page_keys)
    _write_listing_pages(context, report, listing_pages, inputs)
    if previous_state is not None:
        _delete_pages(context, report, set(previous_state.page_keys) - set(page_keys) - set(inputs))
    _delete_pages(context, report, removed - _item_keys(context, site))
    _apply_redirect_difference(context, report, old_redirects, new_redirects)
    _release_redirects_for_new_pages(
        context, report, set(page_keys) - (set(previous_state.page_keys) if previous_state else set())
    )
    if report.follow_up_item_pages and not context.defer_follow_up:
        _run_follow_up(context, report, current.item_id)
    if context.keep_state:
        write_item_state(context.writer, state)
    _converge(context, report, site, current.item_id, state)


def _project_removal(
    context: ProjectionContext, report: ProjectionReport, item_id: str, previous_state: ItemState | None, site: SiteIndex
) -> None:
    projector = context.projector
    if previous_state is not None and previous_state.projected:
        previous = previous_state.summary
        page_keys = previous_state.page_keys
    elif previous_state is not None:
        return
    else:
        try:
            previous = context.source.item_summary(item_id)
        except ProjectionSourceError:
            return
        page_keys = projector.item_page_paths(previous)
    site_before = replace_item(site, item_id, previous)
    dirty, removed, inputs = _listing_difference(projector, site_before, site)
    report.follow_up_item_pages = projector.shared_inputs(site_before) != projector.shared_inputs(site)
    listing_pages = projector.listing_pages(site, dirty) if dirty else {}
    old_redirects = _redirects_for(context, site_before, previous_state)
    new_redirects = _redirects_for(context, site, None)

    _write_listing_pages(context, report, listing_pages, inputs)
    if report.follow_up_item_pages and not context.defer_follow_up:
        _run_follow_up(context, report, item_id)
    _delete_pages(context, report, set(page_keys) - set(inputs))
    report.item_paths = list(page_keys)
    _delete_pages(context, report, removed - _item_keys(context, site))
    _apply_redirect_difference(context, report, old_redirects, new_redirects)
    tombstone = ItemState(
        summary=previous,
        page_keys=(),
        former_page_keys=tuple(dict.fromkeys([*(previous_state.former_page_keys if previous_state else ()), *page_keys])),
    )
    if context.keep_state:
        write_item_state(context.writer, tombstone)
    _converge(context, report, site, item_id, tombstone)


def _converge(
    context: ProjectionContext, report: ProjectionReport, site_used: SiteIndex, item_id: str, state: ItemState | None
) -> None:
    """Read the published versions again; render again what a concurrent publish changed.

    The state is written before this re-read, and again whenever the re-read
    finds the item itself moved, so the last state written is the one of the
    last pages written.
    """
    projector = context.projector
    for _round in range(context.maximum_rounds - 1):
        fresh = context.source.site_index()
        if site_signature(fresh) == site_signature(site_used):
            return
        report.rounds += 1
        dirty, removed, inputs = _listing_difference(projector, site_used, fresh)
        if projector.shared_inputs(site_used) != projector.shared_inputs(fresh):
            report.follow_up_item_pages = True
        used_item = next((summary for summary in site_used.items if summary.item_id == item_id), None)
        fresh_item = next((summary for summary in fresh.items if summary.item_id == item_id), None)
        if fresh_item is not None and (used_item is None or used_item.version_number != fresh_item.version_number):
            item = context.source.published_item(item_id)
            if item is not None:
                pages = projector.item_pages(item, fresh)
                _write_item_pages(context, report, pages, {key: item.summary.version_number for key in pages})
                report.item_paths = sorted(pages)
                state = _updated_state(state, item.summary, tuple(sorted(pages)))
                if context.keep_state:
                    write_item_state(context.writer, state)
        elif fresh_item is None and used_item is not None:
            _delete_pages(context, report, set(projector.item_page_paths(used_item)) - set(projector.listing_inputs(fresh)))
            if state is not None and context.keep_state:
                state = ItemState(
                    summary=state.summary,
                    page_keys=(),
                    former_page_keys=tuple(dict.fromkeys([*state.former_page_keys, *state.page_keys])),
                )
                write_item_state(context.writer, state)
        if dirty:
            _write_listing_pages(context, report, projector.listing_pages(fresh, dirty), inputs)
        _delete_pages(context, report, removed - _item_keys(context, fresh))
        site_used = fresh
    final = context.source.site_index()
    if site_signature(final) != site_signature(site_used):
        report.errors.append("published items kept changing during projection; retry")


def project_static(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    _write_static(context, report, context.projector.static_files())
    return _finish(context, report)


def project_listings(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    site = context.source.site_index()
    inputs = context.projector.listing_inputs(site)
    _write_listing_pages(context, report, context.projector.listing_pages(site, None), inputs)
    return _finish(context, report)


def project_all(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    projector = context.projector
    items = context.source.all_published_items()
    site = SiteIndex(items=tuple(item.summary for item in items), load_item=context.source.load_item)
    rendered: dict[str, bytes] = {}
    states: list[ItemState] = []
    for item in items:
        pages = projector.item_pages(item, site)
        rendered.update(pages)
        remembered = read_item_state(context.writer, item.summary.item_id) if context.keep_state else None
        states.append(_updated_state(remembered, item.summary, tuple(sorted(pages))))
    inputs = projector.listing_inputs(site)
    listings = projector.listing_pages(site, None)
    live_keys = _item_keys(context, site)
    redirects = dict(projector.redirects(site))
    for state in states:
        redirects.update(_moved_redirects(state, live_keys))
    _write_static(context, report, projector.static_files())
    _write_item_pages(context, report, rendered, _versions_by_page(context, site))
    _write_listing_pages(context, report, listings, inputs)
    if context.redirect_store is not None and redirects:
        context.redirect_store.put_all(redirects)
        report.redirects_written = len(redirects)
    if context.keep_state:
        for state in states:
            write_item_state(context.writer, state)
    return _finish(context, report)


def project_item_pages(
    context: ProjectionContext, *, except_item_id: str | None = None, finish: bool = True
) -> ProjectionReport:
    """Render every item page again; write only those whose bytes differ from what the store holds.

    The follow-up of a change that moved something every item page depends on
    (the URL map, navigation): usually a few seconds, run after the response.
    """
    report = ProjectionReport()
    projector = context.projector
    stored = {entry.key: entry.etag for entry in context.writer.list()}
    items = context.source.all_published_items()
    site = SiteIndex(items=tuple(item.summary for item in items), load_item=context.source.load_item)
    for item in items:
        if item.summary.item_id == except_item_id:
            continue
        pages = projector.item_pages(item, site)
        different = {key: body for key, body in pages.items() if stored.get(key) != body_etag(body)}
        _write_item_pages(context, report, different, {key: item.summary.version_number for key in different})
    return _finish(context, report) if finish else report


@dataclass
class ReconcileReport:
    stale_items: list[str] = field(default_factory=list)
    removed_items: list[str] = field(default_factory=list)
    stale_listings: list[str] = field(default_factory=list)
    orphan_pages: list[str] = field(default_factory=list)
    redirects_repaired: int = 0
    redirects_unexpected: int = 0
    projected_everything: bool = False
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def drift(self) -> bool:
        return bool(
            self.stale_items
            or self.removed_items
            or self.stale_listings
            or self.orphan_pages
            or self.redirects_repaired
        )

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "drift": self.drift,
            "dryRun": self.dry_run,
            "staleItems": list(self.stale_items),
            "removedItems": list(self.removed_items),
            "staleListings": list(self.stale_listings),
            "orphanPages": list(self.orphan_pages),
            "redirectsRepaired": self.redirects_repaired,
            "redirectsUnexpected": self.redirects_unexpected,
            "projectedEverything": self.projected_everything,
            "errors": list(self.errors),
        }


def _head_many(writer: PageWriter, keys: list[str]) -> dict[str, StoredObject | None]:
    many = getattr(writer, "head_many", None)
    if many is not None:
        return many(keys)
    return {key: writer.head(key) for key in keys}


def _stale_listing_keys(context: ProjectionContext, site: SiteIndex) -> list[str]:
    inputs = context.projector.listing_inputs(site)
    heads = _head_many(context.writer, sorted(inputs))
    return sorted(key for key, digest in inputs.items() if heads[key] is None or heads[key].inputs != digest)


def reconcile(context: ProjectionContext, *, dry_run: bool = False) -> ReconcileReport:
    """Find drift between the published data and the site store, and repair it.

    Drift is any item page whose ``papyrus-version`` is not the published version
    (or that is missing), any state or page of an item that is no longer
    published, any listing page whose ``papyrus-inputs`` digest is not the one the
    data now yields, and any page the projector owns that nothing expects. Theme
    and code changes are not drift; ``project_all`` applies those.
    """
    report = ReconcileReport(dry_run=dry_run)
    projector = context.projector
    site = context.source.site_index()
    objects = {entry.key: entry for entry in context.writer.list()}
    states = sorted(item_id_from_state_key(key) for key in objects if key.startswith(ITEM_STATE_PREFIX))

    expected_item_keys: dict[str, ItemSummary] = {}
    for summary in site.items:
        for key in projector.item_page_paths(summary):
            expected_item_keys[key] = summary
    present = sorted(key for key in expected_item_keys if key in objects)
    heads = _head_many(context.writer, present)
    published_ids = {summary.item_id for summary in site.items}
    stale: set[str] = set()
    for key, summary in expected_item_keys.items():
        head = heads.get(key)
        if head is None or head.version != summary.version_number:
            stale.add(summary.item_id)
    for summary in site.items:
        if projector.item_page_paths(summary) and context.keep_state and item_state_key(summary.item_id) not in objects:
            stale.add(summary.item_id)
    report.stale_items = sorted(stale)
    report.removed_items = sorted(
        item_id
        for item_id in states
        if item_id not in published_ids
        and (remembered := read_item_state(context.writer, item_id)) is not None
        and remembered.projected
    )
    report.stale_listings = _stale_listing_keys(context, site)

    if not dry_run and len(report.stale_items) > REPROJECT_ALL_THRESHOLD:
        project_all(context)
        report.projected_everything = True
    elif not dry_run:
        for item_id in report.stale_items:
            project(context, item_id)

    if not dry_run:
        fresh = context.source.site_index()
        stale_now = _stale_listing_keys(context, fresh)
        if stale_now:
            listing_report = ProjectionReport()
            _write_listing_pages(
                context, listing_report, projector.listing_pages(fresh, set(stale_now)), projector.listing_inputs(fresh)
            )
            _finish(context, listing_report)
        if report.removed_items:
            _remove_items(context, report.removed_items, fresh)

    expected = set(expected_item_keys) | set(projector.listing_inputs(site))
    report.orphan_pages = sorted(
        key for key in objects if not key.startswith(STATE_PREFIX) and projector.owns_page_key(key) and key not in expected
    )
    if not dry_run and report.orphan_pages:
        cleanup = ProjectionReport()
        _delete_pages(context, cleanup, report.orphan_pages)
        _finish(context, cleanup)

    _reconcile_redirects(context, report, site, dry_run)
    return report


def _remove_items(context: ProjectionContext, item_ids: list[str], site: SiteIndex) -> None:
    """Remove the pages, redirects and state of items that are no longer published, in one pass.

    The listing pages were already repaired against ``site``, so nothing links to
    these items by the time their pages are deleted.
    """
    cleanup = ProjectionReport()
    keep = _item_keys(context, site) | set(context.projector.listing_inputs(site))
    stale_redirects: set[str] = set()
    for item_id in item_ids:
        state = read_item_state(context.writer, item_id)
        if state is None or not state.projected:
            continue
        _delete_pages(context, cleanup, set(state.page_keys) - keep)
        stale_redirects.update(normalized_redirect_source(alias) for alias in state.summary.aliases)
        stale_redirects.update(_moved_redirects(state, set()))
        if context.keep_state:
            write_item_state(
                context.writer,
                ItemState(
                    summary=state.summary,
                    page_keys=(),
                    former_page_keys=tuple(dict.fromkeys([*state.former_page_keys, *state.page_keys])),
                ),
            )
    if context.redirect_store is not None and stale_redirects:
        present = set(context.redirect_store.list_all())
        gone = sorted(stale_redirects & present)
        if gone:
            context.redirect_store.delete_all(gone)
    cleanup.written.extend(project_item_pages(context, finish=False).written)
    _finish(context, cleanup)


def _reconcile_redirects(context: ProjectionContext, report: ReconcileReport, site: SiteIndex, dry_run: bool) -> None:
    store = context.redirect_store
    if store is None:
        return
    expected = dict(context.projector.redirects(site))
    live_keys = _item_keys(context, site)
    for summary in site.items:
        state = read_item_state(context.writer, summary.item_id) if context.keep_state else None
        expected.update(_moved_redirects(state, live_keys))
    current = store.list_all()
    missing = {source: target for source, target in expected.items() if current.get(source) != target}
    report.redirects_unexpected = len(set(current) - set(expected))
    report.redirects_repaired = len(missing)
    if missing and not dry_run:
        store.put_all(missing)
