"""Project published content onto a site store.

Every function renders first and writes after, so a rendering failure leaves
the site untouched. Writes follow one order so a reader never meets a link to
a page that does not exist yet or no longer exists:

* published item: its pages, then the pages that depend on it, then redirects;
* unpublished item: the dependent pages, then the item's pages are deleted,
  then its redirects.

``project``, ``project_listings`` and ``project_all`` are idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .model import ItemChange, ProjectionReport, SiteIndex
from .projector import SiteProjector, normalized_redirect_source
from .source import ProjectionSourceError, PublishedContentSource, with_change
from .writers import PageWriter, RedirectStore


@dataclass
class ProjectionContext:
    source: PublishedContentSource
    projector: SiteProjector
    writer: PageWriter
    invalidate: Callable[[list[str]], list[str]] | None = None
    redirect_store: RedirectStore | None = None


def _versions_by_page(context: ProjectionContext, site: SiteIndex) -> dict[str, int | None]:
    versions: dict[str, int | None] = {}
    for summary in site.items:
        for path in context.projector.item_page_paths(summary):
            versions[path] = summary.version_number
    return versions


def _write_pages(
    context: ProjectionContext,
    report: ProjectionReport,
    pages: dict[str, bytes],
    versions: dict[str, int | None],
) -> None:
    for key in sorted(pages):
        context.writer.put(key, pages[key], version=versions.get(key))
        report.written.append(key)


def _delete_pages(context: ProjectionContext, report: ProjectionReport, keys: tuple[str, ...]) -> None:
    for key in keys:
        context.writer.delete(key)
        report.deleted.append(key)


def _finish(context: ProjectionContext, report: ProjectionReport) -> ProjectionReport:
    touched = [*report.written, *report.deleted]
    if context.invalidate is not None and touched:
        try:
            report.invalidated = context.invalidate(touched)
        except Exception as error:  # noqa: BLE001 - reported in the result, the pages are already written
            report.errors.append(f"invalidation failed: {type(error).__name__}: {error}")
    return report


def project(context: ProjectionContext, item_id: str, *, unpublished: bool = False) -> ProjectionReport:
    report = ProjectionReport()
    site = context.source.site_index()
    if unpublished:
        change = ItemChange("unpublished", context.source.item_summary(item_id))
        site = with_change(site, change, context.source.load_item)
        dependent = context.projector.dependent_pages(change, site)
        _write_pages(context, report, dependent, _versions_by_page(context, site))
        _delete_pages(context, report, context.projector.item_page_paths(change.summary))
        report.item_paths = list(context.projector.item_page_paths(change.summary))
        if context.redirect_store is not None and change.summary.aliases:
            sources = [normalized_redirect_source(alias) for alias in change.summary.aliases]
            context.redirect_store.delete_all(sources)
            report.redirects_deleted = len(sources)
        return _finish(context, report)

    item = context.source.published_item(item_id)
    if item is None:
        raise ProjectionSourceError(f"Item {item_id} has no published version to project")
    change = ItemChange("published", item.summary)
    site = with_change(site, change, context.source.load_item)
    item_pages = context.projector.item_pages(item, site)
    dependent = context.projector.dependent_pages(change, site)
    redirects = {
        source: target
        for source, target in context.projector.redirects(site).items()
        if source in {normalized_redirect_source(alias) for alias in item.summary.aliases}
    }
    versions = _versions_by_page(context, site)
    _write_pages(context, report, item_pages, versions)
    report.item_paths = sorted(item_pages)
    _write_pages(context, report, {key: value for key, value in dependent.items() if key not in item_pages}, versions)
    if context.redirect_store is not None and redirects:
        context.redirect_store.put_all(redirects)
        report.redirects_written = len(redirects)
    return _finish(context, report)


def project_static(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    _write_pages(context, report, context.projector.static_files(), {})
    return _finish(context, report)


def project_listings(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    site = context.source.site_index()
    _write_pages(context, report, context.projector.listing_pages(site), _versions_by_page(context, site))
    return _finish(context, report)


def project_all(context: ProjectionContext) -> ProjectionReport:
    report = ProjectionReport()
    items = context.source.all_published_items()
    site = SiteIndex(items=tuple(item.summary for item in items), load_item=context.source.load_item)
    versions = _versions_by_page(context, site)
    rendered: dict[str, bytes] = {}
    for item in items:
        rendered.update(context.projector.item_pages(item, site))
    rendered.update(context.projector.listing_pages(site))
    redirects = context.projector.redirects(site)
    _write_pages(context, report, context.projector.static_files(), {})
    _write_pages(context, report, rendered, versions)
    if context.redirect_store is not None and redirects:
        context.redirect_store.put_all(redirects)
        report.redirects_written = len(redirects)
    return _finish(context, report)
