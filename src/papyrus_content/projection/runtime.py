"""Build a projection context from the deployment environment (content-actions Lambda and the ops CLI)."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .engine import ProjectionContext
from .projector import MarkusSiteProjector, SiteProjector
from .source import PublishedContentSource
from .writers import CloudFrontInvalidator, KeyValueStoreRedirects, S3PageWriter

PUBLICATION_KIND_ENV = "PAPYRUS_PUBLICATION_KIND"
SITE_BUCKET_ENV = "PAPYRUS_SITE_BUCKET"
EDGE_DISTRIBUTION_ENV = "PAPYRUS_EDGE_DISTRIBUTION_ID"
REDIRECTS_KVS_ENV = "PAPYRUS_REDIRECTS_KVS_ARN"
DEAD_LETTER_QUEUE_ENV = "PAPYRUS_PROJECTION_DLQ_URL"
PUBLIC_URL_ENV = "PAPYRUS_SITE_PUBLIC_URL"
SITE_PROJECTOR_ENV = "PAPYRUS_SITE_PROJECTOR"
SITE_STATIC_DIRECTORY_ENV = "PAPYRUS_SITE_STATIC_DIR"
S3_PROJECTION_KIND = "s3-projection"
SITE_PROJECTOR_FACTORY = "create_projector"

_projector_by_configuration: dict[tuple[str, str], SiteProjector] = {}


def projection_configured(environ: Mapping[str, str] | None = None) -> bool:
    environment = os.environ if environ is None else environ
    return (environment.get(PUBLICATION_KIND_ENV) or "").strip() == S3_PROJECTION_KIND


def load_projector(environ: Mapping[str, str] | None = None) -> SiteProjector:
    environment = os.environ if environ is None else environ
    module_name = (environment.get(SITE_PROJECTOR_ENV) or "").strip()
    static_directory = (environment.get(SITE_STATIC_DIRECTORY_ENV) or "").strip()
    cache_key = (module_name, static_directory)
    cached = _projector_by_configuration.get(cache_key)
    if cached is not None:
        return cached
    if module_name:
        projector = getattr(importlib.import_module(module_name), SITE_PROJECTOR_FACTORY)()
    else:
        projector = MarkusSiteProjector.from_static_directory(Path(static_directory) if static_directory else None)
    _projector_by_configuration[cache_key] = projector
    return projector


def context_from_environment(
    client: Any,
    environ: Mapping[str, str] | None = None,
    *,
    s3_client: Any = None,
    cloudfront_client: Any = None,
    kvs_client: Any = None,
) -> ProjectionContext:
    environment = os.environ if environ is None else environ
    bucket = (environment.get(SITE_BUCKET_ENV) or "").strip()
    if not bucket:
        raise ValueError(f"{SITE_BUCKET_ENV} is not set; this site has no s3-projection publication.")
    distribution_id = (environment.get(EDGE_DISTRIBUTION_ENV) or "").strip()
    kvs_arn = (environment.get(REDIRECTS_KVS_ENV) or "").strip()
    invalidator = CloudFrontInvalidator(distribution_id, cloudfront_client) if distribution_id else None
    return ProjectionContext(
        source=PublishedContentSource(client),
        projector=load_projector(environment),
        writer=S3PageWriter(bucket, s3_client),
        invalidate=invalidator.invalidate if invalidator else None,
        redirect_store=KeyValueStoreRedirects(kvs_arn, kvs_client) if kvs_arn else None,
    )


def public_item_url(environ: Mapping[str, str], item_paths: list[str]) -> str | None:
    base = (environ.get(PUBLIC_URL_ENV) or "").strip().rstrip("/")
    if not base or not item_paths:
        return None
    path = item_paths[0]
    return f"{base}/" if path == "index.html" else f"{base}/{path}"
