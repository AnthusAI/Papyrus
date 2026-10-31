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
from .snapshot import REFERENCES_FILE, build_snapshot, changed_without_generated_at, snapshot_bytes

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
    """Report ``{written, unchanged, references, pagesRewritten, purged}``; a site without ``homePage`` settings has nothing to do."""
    if settings is None:
        return {"skipped": "this site has no homePage setting", "written": [], "unchanged": [], "references": 0, "pagesRewritten": 0, "purged": []}
    settings = with_public_data_limits(settings, context.projector)
    corpus_id = corpus_id_for(settings, site)
    records = collect_references(client, corpus_id, settings, client_factory=client_factory, workers=workers)
    document = build_snapshot(records, now or datetime.now(timezone.utc), corpus=corpus_id, fields=settings.references.fields)
    body = snapshot_bytes(document)
    key = site_key(context.projector, REFERENCES_FILE)
    report: dict[str, Any] = {"written": [], "unchanged": [], "references": len(records), "pagesRewritten": 0, "purged": [], "bytes": len(body)}
    with context.leased():
        if not changed_without_generated_at(context.writer.get(key), body):
            report["unchanged"].append(key)
            return report
        if dry_run:
            report["wouldWrite"] = [key]
            return report
        context.writer.put(key, body)
        report["written"].append(key)
        projected = _project_listings(context)
        report["pagesRewritten"] = len(projected.written)
        if settings.freshness.purge and context.invalidate is not None:
            report["purged"] = context.invalidate([key])
        if projected.errors:
            report["errors"] = list(projected.errors)
    return report


def _project_listings(context: Any) -> Any:
    from ..projection.engine import project_listings

    return project_listings(context)
