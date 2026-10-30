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

import functools
import logging
import re
from contextlib import contextmanager
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Callable

from .lease import ProjectionLease
from .item_state import (
    ITEM_STATE_PREFIX,
    ItemState,
    item_id_from_state_key,
    item_state_key,
    read_item_state,
    write_item_state,
)
from .model import ItemSummary, ProjectionReport, SiteIndex, site_signature
from .plugins import PLUGIN_PAGE_PREFIXES, is_plugin_runtime_key
from .projector import SiteProjector, normalized_redirect_source
from .source import ProjectionSourceError, PublishedContentSource, replace_item
from .writers import STATE_PREFIX, PageWriter, RedirectStore, StoredObject, body_etag, request_paths_for_key

LOGGER = logging.getLogger("papyrus.projection")
MAXIMUM_ROUNDS = 3
REPROJECT_ALL_THRESHOLD = 20


@dataclass(frozen=True)
class DeletionGuard:
    """When a bulk projection refuses to delete: more than ``share_limit`` of the stored pages (and more than ``floor``), or any page of an item that stays published."""

    share_limit: float = 0.1
    floor: int = 20


MESSAGE_ITEM_LIMIT = 20
MESSAGE_KEY_LIMIT = 50


class DeletionRefused(ValueError):
    """A projection planned deletions the guard does not allow; no page was written."""

    def __init__(self, keys, dropped_items, stored_pages: int) -> None:
        self.keys = tuple(sorted(keys))
        self.dropped_items = tuple(sorted(dropped_items))
        self.stored_pages = stored_pages
        super().__init__(self._describe())

    def _describe(self) -> str:
        groups: dict[str, int] = {}
        for key in self.keys:
            head = key.split("/", 1)[0] + "/" if "/" in key else "(top level)"
            groups[head] = groups.get(head, 0) + 1
        lines = [
            f"Refusing to delete {len(self.keys)} of {self.stored_pages} stored pages; no page was written.",
            "By first path segment: " + ", ".join(f"{head} {count}" for head, count in sorted(groups.items())),
        ]
        if self.dropped_items:
            shown = ", ".join(self.dropped_items[:MESSAGE_ITEM_LIMIT])
            more = len(self.dropped_items) - MESSAGE_ITEM_LIMIT
            lines.append(
                f"{len(self.dropped_items)} published items would be left with no pages: {shown}"
                + (f" and {more} more" if more > 0 else "")
            )
        more_keys = len(self.keys) - MESSAGE_KEY_LIMIT
        lines.append("Pages: " + ", ".join(self.keys[:MESSAGE_KEY_LIMIT]) + (f" and {more_keys} more" if more_keys > 0 else ""))
        lines.append(
            "Check that --static-dir is a current checkout of the site, or pass --allow-deletions if the deletions are intended."
        )
        return "\n".join(lines)


class PluginPagesRefused(ValueError):
    """A reconcile would delete pages a plugin projects, and the plugin is not known to be disabled; no page was written."""

    def __init__(self, keys) -> None:
        self.keys = tuple(sorted(keys))
        shown = ", ".join(self.keys[:MESSAGE_KEY_LIMIT])
        more = len(self.keys) - MESSAGE_KEY_LIMIT
        super().__init__(
            f"Refusing to delete {len(self.keys)} pages that a plugin projects; no page was written.\n"
            f"Pages: {shown}" + (f" and {more} more" if more > 0 else "") + "\n"
            "The plugin list this run used does not include the plugin that writes them. Run from the site directory so "
            "amplify_outputs.json (custom.papyrusPlugins) is read, or set PAPYRUS_PLUGINS to the deployed list."
        )


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
    deletion_guard: DeletionGuard | None = None
    lease: ProjectionLease | None = None
    disabled_plugins: frozenset[str] = frozenset()  # plugins known to be disabled for the site; only their pages may be reconciled away

    @contextmanager
    def leased(self):
        """Hold the publication's projection lease, if it has one. Nested uses share one hold."""
        if self.lease is None:
            yield
        else:
            with self.lease.held():
                yield

    def renew_lease(self) -> None:
        if self.lease is not None:
            self.lease.renew()

    def __post_init__(self) -> None:
        types = tuple(getattr(self.projector, "projectable_types", ()))
        if types and hasattr(self.source, "extra_types"):
            self.source.extra_types = types
        attach = getattr(self.projector, "attach_store", None)
        if attach is not None:
            attach(self.writer)


def _leased(function):
    """Run a public entry point under the context's projection lease (released on any exit, including errors)."""

    @functools.wraps(function)
    def wrapper(context: ProjectionContext, *args, **kwargs):
        with context.leased():
            return function(context, *args, **kwargs)

    return wrapper


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
        context.renew_lease()
        context.writer.put(key, pages[key], version=versions.get(key))
        report.written.append(key)


def _write_listing_pages(
    context: ProjectionContext, report: ProjectionReport, pages: dict[str, bytes], inputs: dict[str, str]
) -> None:
    for key in _page_order(pages):
        context.renew_lease()
        context.writer.put(key, pages[key], inputs=inputs.get(key))
        report.written.append(key)


def _write_static(context: ProjectionContext, report: ProjectionReport, pages: dict[str, bytes]) -> None:
    for key in sorted(pages):
        context.renew_lease()
        context.writer.put(key, pages[key])
        report.written.append(key)


def _delete_pages(context: ProjectionContext, report: ProjectionReport, keys) -> None:
    for key in sorted(keys):
        context.renew_lease()
        context.writer.delete(key)
        report.deleted.append(key)


def _guard_deletions(context: ProjectionContext, keys, dropped_items) -> None:
    """Refuse, before any page is written, deletions that look like a wrong site configuration rather than an edit."""
    guard = context.deletion_guard
    keys = set(keys)
    dropped = sorted(set(dropped_items))
    if guard is None or not (keys or dropped):
        return
    projector = context.projector
    stored = sum(
        1
        for entry in context.writer.list()
        if not entry.key.startswith(STATE_PREFIX) and not is_plugin_runtime_key(entry.key) and projector.owns_page_key(entry.key)
    )
    if dropped or len(keys) > max(guard.floor, guard.share_limit * stored):
        raise DeletionRefused(keys, dropped, stored)


def _item_keys(context: ProjectionContext, site: SiteIndex) -> set[str]:
    return {key for summary in site.items for key in context.projector.item_page_paths(summary)}


def _canonical_path(projector, key: str) -> str:
    """The public path of a page: the projector's own (``urls.style: clean`` serves ``x.html`` at ``/x``), else the stored key's."""
    canonical = getattr(projector, "canonical_path", None)
    return canonical(key) if canonical is not None else request_paths_for_key(key)[0]


def _request_paths(projector, key: str) -> tuple[str, ...]:
    """Every path a request for the page can use: the canonical one first, then the stored key's own paths."""
    return tuple(dict.fromkeys((_canonical_path(projector, key), *request_paths_for_key(key))))


def _moved_redirects(projector, state: ItemState | None, live_keys: set[str]) -> dict[str, str]:
    if state is None or not state.page_keys or not state.former_page_keys:
        return {}
    target = _canonical_path(projector, state.page_keys[0])
    moved: dict[str, str] = {}
    for former in state.former_page_keys:
        if former in live_keys:
            continue
        for source in _request_paths(projector, former):
            if source != target:
                moved[source] = target
    return moved


def _redirects_for(context: ProjectionContext, site: SiteIndex, state: ItemState | None) -> dict[str, str]:
    live_keys = _item_keys(context, site)
    return {**context.projector.redirects(site), **_moved_redirects(context.projector, state, live_keys)}


REDIRECT_LOOKUP_LIMIT = 10


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
    candidates = [source for key in sorted(new_keys) for source in _request_paths(context.projector, key)]
    if len(candidates) > REDIRECT_LOOKUP_LIMIT:
        present = store.list_all()  # a few list calls cost less than a billed read per path
        shadowing = [source for source in candidates if source in present]
    else:
        shadowing = [source for source in candidates if store.get(source) is not None]
    if shadowing:
        store.delete_all(shadowing)
        report.redirects_deleted += len(shadowing)


def _finish(context: ProjectionContext, report: ProjectionReport) -> ProjectionReport:
    touched = [key for key in [*report.written, *report.deleted] if not key.startswith(STATE_PREFIX)]
    if context.invalidate is not None and touched:
        try:
            report.invalidated = context.invalidate(touched)
        except Exception as error:  # noqa: BLE001 - the pages are written and live at the origin; the purge is retried
            report.unpurged = touched
            LOGGER.warning("edge invalidation failed for %s paths: %s: %s", len(touched), type(error).__name__, error)
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


VERSION_SUFFIX = re.compile(r"-v\d+$")


def _lineage_of_state_id(item_id: str) -> str:
    return VERSION_SUFFIX.sub("", item_id)


def _merge_sibling_states(own: ItemState | None, siblings: list[ItemState]) -> ItemState | None:
    """One state for an item and the other versions of its lineage.

    Publishing a different version of a story (``<lineage>-v<n>``) changes the published row's source item, so pages
    written while another version was published stay remembered under that version's id, in states nothing reads
    again. Merging them lets the pages those states own be deleted and their addresses redirected. The merged
    ``page_keys`` are every page any version left in the store, the item's own first.
    """
    if not siblings:
        return own
    states = ([own] if own is not None else []) + siblings
    projected = [state for state in states if state.projected]
    base = own if own is not None and own.projected else (projected[0] if projected else states[0])
    return ItemState(
        summary=base.summary,
        page_keys=tuple(dict.fromkeys(key for state in projected for key in state.page_keys)),
        former_page_keys=tuple(dict.fromkeys(key for state in states for key in state.former_page_keys)),
    )


def _sibling_states(context: ProjectionContext, item_id: str) -> list[tuple[str, ItemState]]:
    """The states, other than the item's own, that belong to the same lineage (`<lineage>` or `<lineage>-v<n>`)."""
    lineage_id_of = getattr(context.source, "lineage_id_of", None)
    lineage_id = lineage_id_of(item_id) if lineage_id_of is not None else _lineage_of_state_id(item_id)
    sibling = re.compile(rf"^{re.escape(lineage_id)}(-v\d+)?$")
    own_key = item_state_key(item_id)
    found: list[tuple[str, ItemState]] = []
    for entry in context.writer.list(ITEM_STATE_PREFIX + quote(lineage_id, safe="")):
        sibling_id = item_id_from_state_key(entry.key)
        if entry.key == own_key or not sibling.match(sibling_id):
            continue
        state = read_item_state(context.writer, sibling_id)
        if state is not None:
            found.append((entry.key, state))
    return found


@_leased
def project(context: ProjectionContext, item_id: str, *, unpublished: bool = False) -> ProjectionReport:
    """Project one item and the pages that depend on it.

    The stored data decides what happens: an item with a published version is
    projected, anything else is removed. ``unpublished`` is only a hint kept for
    callers that know the item was just unpublished.
    """
    report = ProjectionReport()
    previous_state = read_item_state(context.writer, item_id) if context.keep_state else None
    adopted_keys: list[str] = []
    if context.keep_state:
        siblings = _sibling_states(context, item_id)
        adopted_keys = [key for key, _state in siblings]
        previous_state = _merge_sibling_states(previous_state, [state for _key, state in siblings])
    site = context.source.site_index()
    item = context.source.published_item(item_id)
    if item is None:
        _project_removal(context, report, item_id, previous_state, site)
    else:
        _project_publication(context, report, item, previous_state, site)
    if report.follow_up_item_pages and not context.defer_follow_up:
        _run_follow_up(context, report, item_id)
    for key in adopted_keys:
        if key != item_state_key(item_id):
            context.writer.delete(key)
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


@_leased
def project_static(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    _write_static(context, report, context.projector.static_files())
    return _finish(context, report)


@_leased
def project_listings(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    site = context.source.site_index()
    inputs = context.projector.listing_inputs(site)
    _write_listing_pages(context, report, context.projector.listing_pages(site, None), inputs)
    return _finish(context, report)


@_leased
def project_all(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    projector = context.projector
    items = context.source.all_published_items()
    site = SiteIndex(items=tuple(item.summary for item in items), load_item=context.source.load_item)
    rendered: dict[str, bytes] = {}
    states: list[ItemState] = []
    sibling_keys: set[str] = set()
    leftovers: set[str] = set()
    dropped: list[str] = []
    for item in items:
        pages = projector.item_pages(item, site)
        rendered.update(pages)
        remembered = read_item_state(context.writer, item.summary.item_id) if context.keep_state else None
        if context.keep_state:
            siblings = _sibling_states(context, item.summary.item_id)
            sibling_keys.update(key for key, _state in siblings)
            remembered = _merge_sibling_states(remembered, [state for _key, state in siblings])
        if remembered is not None:
            leftovers.update(set(remembered.page_keys) - set(pages))
            if remembered.page_keys and not pages:
                dropped.append(item.summary.item_id)
        states.append(_updated_state(remembered, item.summary, tuple(sorted(pages))))
    inputs = projector.listing_inputs(site)
    listings = projector.listing_pages(site, None)
    live_keys = _item_keys(context, site)
    redirects = dict(projector.redirects(site))
    for state in states:
        redirects.update(_moved_redirects(context.projector, state, live_keys))
    planned = leftovers - live_keys - set(inputs)
    _guard_deletions(context, planned, dropped)
    _write_static(context, report, projector.static_files())
    _write_item_pages(context, report, rendered, _versions_by_page(context, site))
    _write_listing_pages(context, report, listings, inputs)
    _delete_pages(context, report, planned)
    if context.redirect_store is not None:
        current = context.redirect_store.list_all()
        changed = {source: target for source, target in redirects.items() if current.get(source) != target}
        if changed:
            context.redirect_store.put_all(changed)
        report.redirects_written = len(changed)
        # A path that is a page now never stays a redirect: an entry left by an earlier layout (a basePath that moved
        # back and forth) would otherwise loop with the redirect that points at the page.
        served = {path for key in (*rendered, *listings) for path in _request_paths(projector, key)}
        shadowing = sorted(source for source in current if source in served and source not in redirects)
        if shadowing:
            context.redirect_store.delete_all(shadowing)
            report.redirects_deleted += len(shadowing)
    if context.keep_state:
        for state in states:
            write_item_state(context.writer, state)
        for key in sibling_keys:
            context.writer.delete(key)
    return _finish(context, report)


@_leased
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
    protected_pages: list[str] = field(default_factory=list)  # plugin pages nothing here expects; never deleted, never counted as drift
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
            "protectedPluginPages": list(self.protected_pages),
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


def reconcile(context: ProjectionContext, *, dry_run: bool = False, only: str | None = None) -> ReconcileReport:
    """``only`` is a site-relative key prefix (``wiki/page/``); orphans outside it, under the site's base path, are not considered."""
    if dry_run:
        return _reconcile(context, dry_run=True, only=only)  # read-only: no lease
    with context.leased():
        return _reconcile(context, dry_run=False, only=only)


def _only_prefix(projector, only: str | None) -> str | None:
    if not only or not only.strip("/"):
        return None
    policy = getattr(projector, "policy", None)
    prefix = only.lstrip("/")
    return policy.key(prefix) if policy is not None else prefix


def _plugin_page_keys(context: ProjectionContext, keys) -> list[str]:
    """The keys among ``keys`` that sit under the page prefix of a plugin that is not known to be disabled."""
    policy = getattr(context.projector, "policy", None)
    protected = [
        prefix
        for plugin, prefixes in PLUGIN_PAGE_PREFIXES.items()
        if plugin not in context.disabled_plugins
        for prefix in prefixes
    ]
    found = []
    for key in keys:
        relative = policy.relative_key(key) if policy is not None else key
        if relative is not None and relative.startswith(tuple(protected)):
            found.append(key)
    return found


def _reconcile(context: ProjectionContext, *, dry_run: bool, only: str | None = None) -> ReconcileReport:
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
    if context.keep_state:
        published_lineages = {_lineage_of_state_id(item_id) for item_id in published_ids}
        for state_id in states:
            lineage = _lineage_of_state_id(state_id)
            if state_id not in published_ids and lineage in published_lineages:
                stale.update(item_id for item_id in published_ids if _lineage_of_state_id(item_id) == lineage)
    report.stale_items = sorted(stale)
    report.removed_items = sorted(
        item_id
        for item_id in states
        if item_id not in published_ids
        and (remembered := read_item_state(context.writer, item_id)) is not None
        and remembered.projected
    )
    report.stale_listings = _stale_listing_keys(context, site)

    expected = set(expected_item_keys) | set(projector.listing_inputs(site))
    report.orphan_pages = sorted(
        key
        for key in objects
        if not key.startswith(STATE_PREFIX) and not is_plugin_runtime_key(key) and projector.owns_page_key(key) and key not in expected
    )
    prefix = _only_prefix(projector, only)
    if prefix is not None:
        report.orphan_pages = [key for key in report.orphan_pages if key.startswith(prefix)]
    report.protected_pages = _plugin_page_keys(context, report.orphan_pages)
    if report.protected_pages:
        report.orphan_pages = [key for key in report.orphan_pages if key not in set(report.protected_pages)]
        if not dry_run:
            raise PluginPagesRefused(report.protected_pages)
    if not dry_run:
        _guard_reconcile(context, report, site, objects, expected)

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

    if not dry_run and report.orphan_pages:
        cleanup = ProjectionReport()
        _delete_pages(context, cleanup, report.orphan_pages)
        _finish(context, cleanup)

    _reconcile_redirects(context, report, site, dry_run)
    return report


def _guard_reconcile(
    context: ProjectionContext, report: ReconcileReport, site: SiteIndex, objects: dict[str, StoredObject], expected: set[str]
) -> None:
    if context.deletion_guard is None:
        return
    planned = set(report.orphan_pages)
    for item_id in report.removed_items:
        state = read_item_state(context.writer, item_id)
        if state is not None:
            planned.update(set(state.page_keys) - expected)
    dropped: list[str] = []
    if context.keep_state:
        for summary in site.items:
            if context.projector.item_page_paths(summary) or item_state_key(summary.item_id) not in objects:
                continue
            state = read_item_state(context.writer, summary.item_id)
            if state is not None and state.page_keys:
                dropped.append(summary.item_id)
    _guard_deletions(context, planned, dropped)


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
        stale_redirects.update(_moved_redirects(context.projector, state, set()))
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
        expected.update(_moved_redirects(context.projector, state, live_keys))
    current = store.list_all()
    missing = {source: target for source, target in expected.items() if current.get(source) != target}
    report.redirects_unexpected = len(set(current) - set(expected))
    report.redirects_repaired = len(missing)
    if missing and not dry_run:
        store.put_all(missing)
