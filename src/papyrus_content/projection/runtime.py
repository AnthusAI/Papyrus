"""Build a projection context from the deployment environment (content-actions Lambda and the ops CLI)."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .engine import ProjectionContext
from .lease import lease_from_environment
from .plugins import plugin_names_from_environment
from .projector import MarkusSiteProjector, SiteProjector
from ..renditions import S3RenditionStore
from .source import PublishedContentSource
from .story_stars import star_store_from_environment
from .writers import (
    DEFAULT_HTML_S_MAXAGE_SECONDS,
    FALLBACK_HTML_S_MAXAGE_SECONDS,
    CloudFrontInvalidator,
    KeyValueStoreRedirects,
    S3PageWriter,
    TargetedCloudFrontInvalidator,
)
from ..page_refresh.budget import budget_from_environment

PUBLICATION_KIND_ENV = "PAPYRUS_PUBLICATION_KIND"
SITE_BUCKET_ENV = "PAPYRUS_SITE_BUCKET"
EDGE_DISTRIBUTION_ENV = "PAPYRUS_EDGE_DISTRIBUTION_ID"
REDIRECTS_KVS_ENV = "PAPYRUS_REDIRECTS_KVS_ARN"
DEAD_LETTER_QUEUE_ENV = "PAPYRUS_PROJECTION_DLQ_URL"
HTML_S_MAXAGE_ENV = "PAPYRUS_HTML_S_MAXAGE_SECONDS"
EDGE_INVALIDATION_ENV = "PAPYRUS_EDGE_INVALIDATION"
EDGE_INVALIDATION_OFF = "off"
EDGE_INVALIDATION_TARGETED = "targeted"
PUBLIC_URL_ENV = "PAPYRUS_SITE_PUBLIC_URL"
SITE_PROJECTOR_ENV = "PAPYRUS_SITE_PROJECTOR"
SITE_STATIC_DIRECTORY_ENV = "PAPYRUS_SITE_STATIC_DIR"
S3_PROJECTION_KIND = "s3-projection"
SITE_PROJECTOR_FACTORY = "create_projector"

_projector_by_configuration: dict[tuple[str, str, tuple[str, ...]], SiteProjector] = {}


def projection_configured(environ: Mapping[str, str] | None = None) -> bool:
    environment = os.environ if environ is None else environ
    return (environment.get(PUBLICATION_KIND_ENV) or "").strip() == S3_PROJECTION_KIND


def load_projector(environ: Mapping[str, str] | None = None, *, renditions: Any = None) -> SiteProjector:
    """The site projector of the environment. ``renditions`` (a rendition store) replaces the site bucket's, for a local projection; such a projector is not kept."""
    environment = os.environ if environ is None else environ
    module_name = (environment.get(SITE_PROJECTOR_ENV) or "").strip()
    static_directory = (environment.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
    plugins = plugin_names_from_environment(environment)
    cache_key = (module_name, static_directory, plugins)
    cached = _projector_by_configuration.get(cache_key) if renditions is None else None
    if cached is not None:
        return cached
    if module_name:
        projector = getattr(importlib.import_module(module_name), SITE_PROJECTOR_FACTORY)()
    else:
        bucket = (environment.get(SITE_BUCKET_ENV) or "").strip()
        projector = MarkusSiteProjector.from_static_directory(
            Path(static_directory) if static_directory else None,
            renditions=renditions if renditions is not None else S3RenditionStore(bucket) if bucket else None,
            plugins=plugins,
        )
    if renditions is None:
        _projector_by_configuration[cache_key] = projector
    return projector


def site_body_features(environ: Mapping[str, str] | None = None):
    """What a body may contain on the site this environment projects (see ``markus_renderer.body_features``).

    Save validates with this, so it reads the same projector, settings and media store the page is rendered with. An
    environment that does not project, or a custom projector that does not say, gets the defaults."""
    from ..markus_renderer.body_features import DEFAULT_FEATURES

    if not projection_configured(environ):
        return DEFAULT_FEATURES
    features = getattr(load_projector(environ), "body_features", None)
    return features() if callable(features) else DEFAULT_FEATURES


def render_preflight(client, item_id: str, environ: Mapping[str, str] | None = None) -> None:
    """Refuse a publish whose page the site could not render, before anything is written (``PublishError``, code ``page-not-renderable``).

    Save checks what a body may contain (``site_body_features``); this renders the body as the projector will, which also finds
    what only the site's store knows (a picture whose renditions were never made). Only a problem of the content stops a
    publish; a failure of the platform here is left for the projection itself to report."""
    if not projection_configured(environ):
        return
    row = client.get_record("Item", item_id)
    if row is None:
        return
    front_matter = row.get("metadata")
    if isinstance(front_matter, str):
        try:
            front_matter = json.loads(front_matter)
        except ValueError:
            front_matter = {}
    render_body_preflight((front_matter or {}).get("frontMatterYaml"), row.get("bodyMarkus") or "", environ, page=str(row.get("slug") or row.get("title") or item_id), item_type=str(row.get("type") or ""))


def render_body_preflight(front_matter_yaml: str | None, body_markus: str, environ: Mapping[str, str] | None = None, *, page: str = "", item_type: str = "") -> None:
    """``render_preflight`` for a body that is not stored yet (an edit that would go live as it is saved)."""
    if not projection_configured(environ):
        return
    projector = load_projector(environ)
    fragment = getattr(projector, "preflight_fragment", None)
    if callable(fragment):
        render = lambda source: fragment(source, 1, page, item_type)  # noqa: E731
    elif callable(getattr(projector, "_fragment", None)):
        render = lambda source: projector._fragment(source, 1)  # noqa: E731
    else:
        return
    from ..markus_renderer.derive import compose_source
    from ..publishing import PublishError

    name = f" {page!r}" if page else ""
    try:
        render(compose_source(front_matter_yaml, body_markus))
    except Exception as error:  # noqa: BLE001 - any render error is a refusal that names the page, never a crash of the function
        raise PublishError(
            "page-not-renderable",
            f"The page{name} cannot be published because it cannot be rendered ({type(error).__name__}): {error}. Nothing was published; fix the page and publish it again.",
        ) from error


def invalidation_enabled(environment: Mapping[str, str]) -> bool:
    return (environment.get(EDGE_INVALIDATION_ENV) or "").strip().lower() != EDGE_INVALIDATION_OFF


def targeted_invalidation(environment: Mapping[str, str]) -> bool:
    """``publication.cache.invalidation: "targeted"``: a single-story publish or save purges exactly what it wrote; a deploy never purges (PPY-2745c1)."""
    return (environment.get(EDGE_INVALIDATION_ENV) or "").strip().lower() == EDGE_INVALIDATION_TARGETED


def html_s_maxage_seconds(environment: Mapping[str, str]) -> int:
    configured = (environment.get(HTML_S_MAXAGE_ENV) or "").strip()
    if configured:
        return int(configured)
    return DEFAULT_HTML_S_MAXAGE_SECONDS if invalidation_enabled(environment) else FALLBACK_HTML_S_MAXAGE_SECONDS


def context_from_environment(
    client: Any,
    environ: Mapping[str, str] | None = None,
    *,
    s3_client: Any = None,
    cloudfront_client: Any = None,
    kvs_client: Any = None,
    force_invalidation: bool = False,
) -> ProjectionContext:
    """``force_invalidation`` keeps the edge invalidator even when the site's ``cache.invalidation`` is ``off``: an explicit refresh purges what it wrote."""
    environment = os.environ if environ is None else environ
    bucket = (environment.get(SITE_BUCKET_ENV) or "").strip()
    if not bucket:
        raise ValueError(f"{SITE_BUCKET_ENV} is not set; this site has no s3-projection publication.")
    distribution_id = (environment.get(EDGE_DISTRIBUTION_ENV) or "").strip()
    kvs_arn = (environment.get(REDIRECTS_KVS_ENV) or "").strip()
    if distribution_id and targeted_invalidation(environment):
        invalidator = TargetedCloudFrontInvalidator(distribution_id, budget_from_environment(environment).path_cap, cloudfront_client)
    elif distribution_id and (force_invalidation or invalidation_enabled(environment)):
        invalidator = CloudFrontInvalidator(distribution_id, cloudfront_client)
    else:
        invalidator = None
    source = PublishedContentSource(client)
    source.star_store = star_store_from_environment(environment)
    return ProjectionContext(
        source=source,
        projector=load_projector(environment),
        writer=S3PageWriter(bucket, s3_client, html_s_maxage_seconds(environment)),
        invalidate=invalidator.invalidate if invalidator else None,
        redirect_store=KeyValueStoreRedirects(kvs_arn, kvs_client) if kvs_arn else None,
        lease=lease_from_environment(environment, bucket),
    )


def public_item_url(environ: Mapping[str, str], item_paths: list[str]) -> str | None:
    base = (environ.get(PUBLIC_URL_ENV) or "").strip().rstrip("/")
    if not base or not item_paths:
        return None
    path = item_paths[0]
    return f"{base}/" if path == "index.html" else f"{base}/{path}"
