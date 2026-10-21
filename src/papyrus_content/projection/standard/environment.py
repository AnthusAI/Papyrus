"""The environment guard: a non-production site must never ask to be indexed.

Production is decided in Papyrus config, not in site code. ``site.productionUrl``
names the one origin that is production. The projector resolves its own origin
from ``PAPYRUS_SITE_PUBLIC_URL`` and is production only when that is the production
origin; ``PAPYRUS_SITE_ENV=production`` (or any other value) overrides the guess.
A guarded environment emits ``noindex``, ``Disallow: /`` and its own origin in
canonical links, and fails safe: an origin that is not production is guarded.

A site that declares no ``productionUrl`` and sets no ``PAPYRUS_SITE_ENV`` has
nothing to guard against and behaves as production.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .config import StandardSettings

PUBLIC_URL_ENV = "PAPYRUS_SITE_PUBLIC_URL"
SITE_ENV_ENV = "PAPYRUS_SITE_ENV"


def _normalised_origin(value: str | None) -> str | None:
    value = (value or "").strip().rstrip("/")
    if not value:
        return None
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


@dataclass(frozen=True)
class SiteEnvironment:
    production: bool
    origin: str | None

    @property
    def guarded(self) -> bool:
        return not self.production

    def fingerprint(self) -> list:
        return [self.production, self.origin]


def resolve_environment(settings: StandardSettings, environ: Mapping[str, str] | None = None) -> SiteEnvironment:
    environment = os.environ if environ is None else environ
    production_url = _normalised_origin(settings.identity.production_url)
    origin = _normalised_origin(environment.get(PUBLIC_URL_ENV)) or production_url
    explicit = (environment.get(SITE_ENV_ENV) or "").strip().lower()
    if not settings.guard:
        return SiteEnvironment(production=True, origin=origin)
    if explicit:
        return SiteEnvironment(production=explicit == "production", origin=origin)
    if production_url is None:
        return SiteEnvironment(production=True, origin=origin)
    return SiteEnvironment(production=origin == production_url, origin=origin)
