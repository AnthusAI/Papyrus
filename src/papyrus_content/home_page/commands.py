"""CLI: ``papyrus home-page snapshot``."""

from __future__ import annotations

import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from ..options import normalize_string, parse_options, resolve_mutation_apply
from ..projection.projector import PROJECTION_SETTINGS_FILE
from .settings import HomePageSettings
from .task import home_page_settings_of, reader_pages_of, run_home_page_snapshot

CLI_WORKERS = 8
SITE_STATIC_DIRECTORY_ENV = "PAPYRUS_SITE_STATIC_DIR"
SITE_PROJECTOR_ENV = "PAPYRUS_SITE_PROJECTOR"


class _NoStore:
    """A dry run with no destination: nothing to compare with, nothing to write."""

    class _Writer:
        def get(self, key: str) -> None:
            return None

        def list(self, prefix: str = "") -> list:
            return []

    projector = None
    invalidate = None
    writer = _Writer()

    def leased(self) -> Any:
        return nullcontext()


def require_standard_site(options: dict, environment: Any = None) -> None:
    """Refuse, before a projector is built, unless the site's own settings (the ones the deploy projection uses) can be found.

    ``load_projector`` quietly builds the plain Markus projector when ``projection.json`` is missing; for a write that projector
    would render another site's pages, so the snapshot never gets that far. Relative paths resolve against the current directory.
    """
    environment = os.environ if environment is None else environment
    configured = normalize_string(options.get("static-dir")) or (environment.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
    module = (environment.get(SITE_PROJECTOR_ENV) or "").strip()
    if module and not normalize_string(options.get("static-dir")):
        return  # the deployed projector module decides; the standard check below runs on the projector itself
    if not configured:
        raise ValueError(
            "Refusing to write: the site's projector cannot be built because no static directory is set. "
            f"Pass --static-dir DIR (the directory that holds projection.json) or set {SITE_STATIC_DIRECTORY_ENV}."
        )
    settings = Path(configured).expanduser().resolve() / PROJECTION_SETTINGS_FILE
    if not settings.is_file():
        raise ValueError(
            f"Refusing to write: {settings} does not exist, so the site's projector cannot be built "
            f"(--static-dir {configured!r} is resolved against {Path.cwd()}). Run from the site's checkout or pass an absolute path."
        )
    try:
        has_site = "site" in json.loads(settings.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Refusing to write: {settings} cannot be read as JSON ({error}).") from error
    if not has_site:
        raise ValueError(f"Refusing to write: {settings} has no 'site' object, so it does not use the standard front end the site's deploy projection uses.")


def home_page_snapshot(flags: list[str]) -> None:
    """``papyrus home-page snapshot [--site KEY] [--site-bucket B | --out DIR] [--static-dir DIR] [--dry-run] [--json]``.

    Writes ``_data/home-page/references.json`` of the site's accepted and recommended References when it changed, then re-renders
    the pages that read it. ``--site KEY`` names the publication when ``homePage.references.corpus`` is not set. ``--dry-run`` writes
    nothing: it prints the counts, the size of the file and the exact keys a real run would write, delete and rewrite.
    A write needs the site's own settings: it refuses unless ``--static-dir`` holds a ``projection.json`` with a ``site`` object.
    """
    from ..graphql_authoring import create_authoring_client
    from ..knowledge_snapshot.commands import authoring_client

    options = parse_options(flags)
    write = resolve_mutation_apply(options, "home-page snapshot")
    site = normalize_string(options.get("site"))
    if options.get("out") and options.get("site-bucket"):
        raise ValueError("Pass --out or --site-bucket, not both.")
    has_store = bool(options.get("out") or options.get("site-bucket"))
    if write and not has_store:
        raise ValueError("Pass --out DIR (a local directory) or --site-bucket NAME (the site store), or --dry-run.")
    if has_store:
        require_standard_site(options)  # before any sign-in: a refusal needs no credentials
    client = authoring_client(options)
    if options.get("site-bucket"):
        options["bucket"] = options["site-bucket"]
    if has_store:
        from ..project_commands import _context_for

        context = _context_for(client, options)
        reader_pages_of(context.projector)  # never a fallback projector: refuse unless it can name the pages that read the snapshot
    else:
        context = _NoStore()
    settings = home_page_settings_of(context.projector) or HomePageSettings()
    report = run_home_page_snapshot(
        context,
        client,
        settings,
        site=site,
        dry_run=not write,
        client_factory=lambda: create_authoring_client()[0],
        workers=CLI_WORKERS,
    )
    if options.get("json"):
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"home-page\tsnapshot\t{report['references']} references\t{report['threads']} threads\t{report['bytes']} bytes")
        print(
            f"home-page\tsnapshot\t{len(report['written'])} written\t{len(report['unchanged'])} unchanged\t{len(report['deleted'])} deleted\t"
            f"{report['pagesRewritten']} pages rewritten\t{len(report['purged'])} purged"
        )
    for key in report.get("wouldWrite", ()):
        print(f"home-page\twould write\t{key}")
    for key in report.get("wouldDelete", ()):
        print(f"home-page\twould delete\t{key}")
    for key in report.get("wouldRewrite", ()):
        print(f"home-page\twould rewrite\t{key}")
    for key in report.get("rewritten", ()):
        print(f"home-page\trewrote\t{key}")
    for error in report.get("errors", ()):
        print(f"error: {error}", file=sys.stderr)
    if report.get("errors"):
        raise SystemExit(1)


HOME_PAGE_COMMANDS = {"snapshot": home_page_snapshot}
