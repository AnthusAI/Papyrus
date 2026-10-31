"""The ``home-page-snapshot`` projection task: read the References, write the public file when it changed, re-render what reads it.

``run_home_page_snapshot`` is also what ``papyrus home-page snapshot`` runs, against a local directory or a site bucket.
"""

from __future__ import annotations

import dataclasses
import os
from datetime import datetime, timezone
from typing import Any

from ..ids import knowledge_corpus_id
from ..publication import PUBLICATION_KEY_ENVIRONMENT
from .export import collect_references
from .settings import HomePageSettings
from .snapshot import (
    REFERENCES_FILE,
    THREADS_DIRECTORY,
    THREADS_FILE,
    build_snapshot,
    build_threads_snapshot,
    changed_without_generated_at,
    snapshot_bytes,
    thread_file,
)
from .threads import clean_text, collect_threads

TASK_NAME = "home-page-snapshot"


def site_key(projector: Any, key: str) -> str:
    """The object key under the site's URL policy (``urls.basePath``); a projector without a policy serves from the root."""
    policy = getattr(projector, "policy", None)
    return policy.key(key) if policy is not None else key


def corpus_id_for(settings: HomePageSettings, site: str | None = None) -> str:
    if settings.references.corpus:
        return settings.references.corpus
    key = (site or os.environ.get(PUBLICATION_KEY_ENVIRONMENT) or "").strip()
    if not key:
        raise ValueError(f"homePage.references.corpus is not set and {PUBLICATION_KEY_ENVIRONMENT} names no publication; pass --site KEY on the CLI.")
    return knowledge_corpus_id({"key": key})


def home_page_settings_of(projector: Any) -> HomePageSettings | None:
    return getattr(getattr(projector, "standard", None), "home_page", None)


def summary_characters_of(projector: Any) -> int | None:
    """``publicData.summaryCharacters`` of the site, which also limits the summaries the home page publishes."""
    public_data = getattr(getattr(projector, "_settings", None), "public_data", None)
    return getattr(public_data, "summary_characters", None)


def with_public_data_limits(settings: HomePageSettings, projector: Any) -> HomePageSettings:
    characters = summary_characters_of(projector)
    if not characters:
        return settings
    return dataclasses.replace(settings, references=dataclasses.replace(settings.references, summary_characters=characters))


def story_anchor_resolver(client: Any, projector: Any) -> Any:
    """A lookup from a Story's lineage id to ``{"url", "title"}`` when that Story is published and has a page; each Story is read once."""
    found: dict[str, dict[str, str] | None] = {}

    def resolve(lineage_id: str) -> dict[str, str] | None:
        if lineage_id not in found:
            found[lineage_id] = _published_story(client, projector, lineage_id)
        return found[lineage_id]

    return resolve


def _published_story(client: Any, projector: Any, lineage_id: str) -> dict[str, str] | None:
    from ..projection.source import is_projectable, summary_from_row
    from ..publishing import published_item_id_for

    policy = getattr(projector, "policy", None)
    if projector is None or policy is None:
        return None
    row = client.get_record("PublishedItem", published_item_id_for(lineage_id))
    if not row or not is_projectable(row, tuple(getattr(projector, "projectable_types", ()))):
        return None
    summary = summary_from_row(row)
    paths = projector.item_page_paths(summary)
    title = clean_text(row.get("headline") or row.get("title"))
    return {"url": policy.url_for_key(paths[0]), "title": title} if paths and title else None


def _thread_files(settings: HomePageSettings, client: Any, projector: Any, records: list[dict[str, Any]], now: datetime) -> tuple[dict[str, bytes], int]:
    """The thread files to write, by object key under the site's policy, and the number of public threads."""
    if not settings.threads.enabled:
        return {}, 0
    public_references = {record["key"]: str(record.get("title") or "Reference") for record in records}
    threads = collect_threads(client, public_references, settings, story_anchor=story_anchor_resolver(client, projector))
    index, documents = build_threads_snapshot(threads, now)
    files = {site_key(projector, THREADS_FILE): snapshot_bytes(index)}
    for key, document in documents.items():
        files[site_key(projector, thread_file(key))] = snapshot_bytes(document)
    return files, len(threads)


def run_home_page_snapshot(
    context: Any,
    client: Any,
    settings: HomePageSettings | None,
    *,
    site: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    client_factory: Any = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Report ``{written, unchanged, deleted, references, threads, pagesRewritten, rewritten, purged}``; a dry run adds ``wouldWrite``, ``wouldDelete`` and ``wouldRewrite``; a site without ``homePage`` settings has nothing to do.

    With ``homePage.threads.enabled`` the task also owns ``_data/home-page/threads.json`` and ``_data/home-page/threads/``: it writes
    the files whose content changed and deletes the per-thread files of threads that are no longer public.
    """
    if settings is None:
        return {"skipped": "this site has no homePage setting", "written": [], "unchanged": [], "deleted": [], "references": 0, "threads": 0, "pagesRewritten": 0, "purged": []}
    settings = with_public_data_limits(settings, context.projector)
    corpus_id = corpus_id_for(settings, site)
    stamp = now or datetime.now(timezone.utc)
    records = collect_references(client, corpus_id, settings, client_factory=client_factory, workers=workers)
    document = build_snapshot(records, stamp, corpus=corpus_id, fields=settings.references.fields)
    body = snapshot_bytes(document)
    key = site_key(context.projector, REFERENCES_FILE)
    thread_files, thread_count = _thread_files(settings, client, context.projector, records, stamp)
    report: dict[str, Any] = {"written": [], "unchanged": [], "deleted": [], "references": len(records), "threads": thread_count, "pagesRewritten": 0, "rewritten": [], "purged": [], "bytes": len(body)}
    readers = reader_pages_of(context.projector) if context.projector is not None else None
    if readers is not None:
        from ..projection.engine import check_rewrite_selection

        check_rewrite_selection(context, readers)  # the guard: abort before anything is written
    with context.leased():
        pending = {name: content for name, content in {key: body, **thread_files}.items() if changed_without_generated_at(context.writer.get(name), content)}
        report["unchanged"] = [name for name in (key, *thread_files) if name not in pending]
        stale = _stale_thread_files(context, settings, thread_files)
        stale_pages = _stale_thread_pages(context, stale)
        if not pending and not stale:
            return report
        if dry_run:
            report["wouldWrite"] = sorted(pending)
            report["wouldDelete"] = [*stale, *stale_pages]
            if readers is not None:
                report["wouldRewrite"] = sorted(readers)
            return report
        for name, content in pending.items():
            context.writer.put(name, content)
            report["written"].append(name)
        for name in [*stale, *stale_pages]:
            context.writer.delete(name)
            report["deleted"].append(name)
        if readers is not None:
            readers = reader_pages_of(context.projector)
        projected = _project_listings(context, readers)
        report["rewritten"] = list(projected.written)
        report["pagesRewritten"] = len(projected.written)
        if settings.freshness.purge and context.invalidate is not None:
            report["purged"] = context.invalidate([*report["written"], *report["deleted"]])
        if projected.errors:
            report["errors"] = list(projected.errors)
    return report


def _stale_thread_files(context: Any, settings: HomePageSettings, wanted: dict[str, bytes]) -> list[str]:
    """The stored per-thread files of threads that are no longer public; with threads switched off the task owns none."""
    if not settings.threads.enabled:
        return []
    prefix = site_key(context.projector, THREADS_DIRECTORY) + "/"
    return sorted(stored.key for stored in context.writer.list(prefix) if stored.key not in wanted and stored.key.endswith(".json"))


def _stale_thread_pages(context: Any, stale_files: list[str]) -> list[str]:
    """The stored pages (and Markdown twins) of the threads whose files are stale; a site without ``homePage.forum`` has none."""
    page_keys = getattr(context.projector, "thread_page_keys", None)
    if page_keys is None:
        return []
    found: list[str] = []
    for name in stale_files:
        thread_key = name.rsplit("/", 1)[-1].removesuffix(".json")
        found.extend(key for key in page_keys(thread_key) if context.writer.get(key) is not None)
    return sorted(found)


class ProjectorRefused(ValueError):
    """The projector is not one that knows which pages read the snapshot; the task writes nothing."""


def reader_pages_of(projector: Any) -> frozenset[str]:
    """The keys of the pages that place a home-page include. A projector that cannot say makes the task refuse; there is no fallback."""
    reader_keys = getattr(projector, "home_page_reader_keys", None)
    if reader_keys is None:
        raise ProjectorRefused(
            f"Refusing to write: {type(projector).__name__} cannot say which pages read the home-page snapshot. "
            "Only the standard front end (a 'site' object in projection.json) can; nothing was written."
        )
    return frozenset(reader_keys())


def _project_listings(context: Any, readers: frozenset[str]) -> Any:
    from ..projection.engine import project_stale_listings

    return project_stale_listings(context, readers)
