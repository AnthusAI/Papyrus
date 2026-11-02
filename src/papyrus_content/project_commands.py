"""CLI entry for ``papyrus ops content project``: re-project published content onto the site store."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .env import amplify_outputs_path
from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options
from .projection.engine import (
    DeletionGuard,
    ProjectionContext,
    project,
    project_all,
    project_item_pages,
    project_listings,
    project_removals,
    reconcile,
)
from .projection.runtime import (
    SITE_BUCKET_ENV,
    SITE_STATIC_DIRECTORY_ENV,
    context_from_environment,
    load_projector,
)
from .projection.plugins import PLUGIN_PAGE_PREFIXES, PLUGINS_ENV, plugin_names_from_environment, plugin_names_from_outputs
from .projection.checkout import warn_if_checkout_is_behind
from .projection.directory_source import DirectoryContentSource
from .projection.source import PublishedContentSource
from .projection.writers import LocalDirectoryWriter


@dataclass(frozen=True)
class PluginResolution:
    """Which plugins this run projects with, and which the deployed backend enables (``None``: not known)."""

    local: tuple[str, ...] | None
    deployed: tuple[str, ...] | None
    overridden: bool
    source: str

    @property
    def verified(self) -> bool:
        return self.local is not None and self.deployed is not None and set(self.local) == set(self.deployed)

    def problem(self) -> str | None:
        if self.verified:
            return None
        if self.deployed is None:
            return (
                f"Cannot tell which plugins the deployed site enables: {self.source} is missing or unreadable, so the plugin list "
                "cannot be checked. Run from the site directory, set PAPYRUS_SITE_ROOT, or pass --amplify-outputs PATH."
            )
        return (
            f"The plugin list for this run ({', '.join(self.local or ()) or 'none'}, from {PLUGINS_ENV}) differs from the deployed one "
            f"({', '.join(self.deployed) or 'none'}, from {self.source}). Unset {PLUGINS_ENV} to use the deployed list."
        )


def _resolve_plugins(options: dict, environment: dict[str, str]) -> PluginResolution:
    """The way the deployed backend does it: ``custom.papyrusPlugins`` in amplify_outputs.json, with an explicit PAPYRUS_PLUGINS override."""
    outputs = normalize_string(options.get("amplify-outputs"))
    path = Path(outputs) if outputs else amplify_outputs_path()
    deployed = plugin_names_from_outputs(path)
    if PLUGINS_ENV in environment:
        return PluginResolution(plugin_names_from_environment(environment), deployed, True, str(path))
    return PluginResolution(deployed, deployed, False, str(path))


def _projection_environment(options: dict) -> dict[str, str]:
    environment = dict(os.environ)
    resolution = _resolve_plugins(options, environment)
    if not resolution.overridden and resolution.local is not None:
        environment[PLUGINS_ENV] = ",".join(resolution.local)
    bucket = normalize_string(options.get("bucket"))
    if bucket:
        environment[SITE_BUCKET_ENV] = bucket
    static_directory = normalize_string(options.get("static-dir"))
    if static_directory:
        environment[SITE_STATIC_DIRECTORY_ENV] = static_directory
        warn_if_checkout_is_behind(static_directory)
    return environment


def _context_for(client, options: dict) -> ProjectionContext:
    context = _build_context(client, options)
    resolution = _resolve_plugins(options, dict(os.environ))
    if resolution.verified:
        context.disabled_plugins = frozenset(PLUGIN_PAGE_PREFIXES) - frozenset(resolution.local or ())
    if not options.get("allow-deletions"):
        context.deletion_guard = DeletionGuard()
    return context


def _build_context(client, options: dict) -> ProjectionContext:
    environment = _projection_environment(options)
    output_directory = normalize_string(options.get("out"))
    from_directory = normalize_string(options.get("from-dir"))
    if from_directory:
        if not output_directory:
            raise ValueError("--from-dir needs --out DIR.")
        return ProjectionContext(
            source=DirectoryContentSource(Path(from_directory)),
            projector=load_projector(environment),
            writer=LocalDirectoryWriter(Path(output_directory)),
            keep_state=False,
        )
    if output_directory:
        return ProjectionContext(
            source=PublishedContentSource(client),
            projector=load_projector(environment),
            writer=LocalDirectoryWriter(Path(output_directory)),
            keep_state=False,
        )
    return context_from_environment(client, environment)


def _item_ids_of(path: str | None) -> list[str]:
    """The ids in a JSON file holding a list of item ids (``--unpublished-items``)."""
    if not path:
        raise ValueError("--unpublished-items needs a JSON file holding a list of item ids.")
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not all(isinstance(entry, str) and entry for entry in loaded):
        raise ValueError(f"{path} must hold a JSON list of item ids.")
    return loaded


def content_project(flags: list[str]) -> None:
    options = parse_options(flags)
    item_id = normalize_string(options.get("item"))
    modes = [
        bool(options.get("all")),
        bool(options.get("listings")),
        bool(options.get("reconcile")),
        bool(options.get("item-pages")),
        bool(item_id),
        bool(options.get("unpublished-items")),
    ]
    if sum(modes) != 1:
        raise ValueError("Pass exactly one of --all, --listings, --reconcile, --item-pages, --item <item-id> or --unpublished-items FILE.")
    if options.get("from-dir"):
        if not options.get("all"):
            raise ValueError("--from-dir supports --all only.")
        client = None
    else:
        if options.get("reconcile") and not options.get("dry-run") and not options.get("out"):
            problem = _resolve_plugins(options, dict(os.environ)).problem()
            if problem:
                raise ValueError(f"Refusing to reconcile: {problem}")
        client, _claims = create_authoring_client()
    context = _context_for(client, options)
    knowledge_directory = normalize_string(options.get("knowledge-dir"))
    if knowledge_directory:
        use = getattr(context.projector, "use_knowledge_directory", None)
        if use is None:
            raise ValueError("--knowledge-dir needs a site that uses the standard front end.")
        use(Path(knowledge_directory))
    if options.get("reconcile"):
        _run_reconcile(context, options)
        return
    if options.get("all"):
        report = project_all(context)
    elif options.get("item-pages"):
        report = project_item_pages(context)
    elif options.get("listings"):
        report = project_listings(context)
    elif options.get("unpublished-items"):
        report = project_removals(context, _item_ids_of(normalize_string(options.get("unpublished-items"))))
    else:
        report = project(context, item_id, unpublished=bool(options.get("unpublished")))
    payload = report.to_dict()
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        print(
            f"Projected: {payload['written']} written, {payload['deleted']} deleted, "
            f"{payload['redirectsWritten']} redirects, {payload['invalidated']} invalidation paths"
        )
        for error in report.errors:
            print(f"error: {error}")
    if not report.ok:
        raise SystemExit(1)


def _run_reconcile(context: ProjectionContext, options: dict) -> None:
    if options.get("only") is True:
        raise ValueError("--only needs a site-relative path prefix, for example --only wiki/page/.")
    report = reconcile(context, dry_run=bool(options.get("dry-run")), only=normalize_string(options.get("only")) or None)
    payload = report.to_dict()
    if options.get("json"):
        print(json.dumps(payload, indent=2))
    else:
        verb = "Found" if report.dry_run else "Repaired"
        print(
            f"{verb}: {len(report.stale_items)} stale items, {len(report.removed_items)} removed items, "
            f"{len(report.stale_listings)} stale listings, {len(report.orphan_pages)} orphan pages, "
            f"{report.redirects_repaired} redirects"
        )
        if report.protected_pages:
            print(f"Kept {len(report.protected_pages)} plugin pages that nothing here expects: {', '.join(report.protected_pages[:10])}")
        for error in report.errors:
            print(f"error: {error}")
    if not report.ok or (report.dry_run and report.drift):
        raise SystemExit(1)
