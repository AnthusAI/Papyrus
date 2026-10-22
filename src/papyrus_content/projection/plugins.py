"""Static files that Papyrus plugins ship to a site that enables them (docs/plugins.md).

The backend tells the projection which plugins a site enables through ``PAPYRUS_PLUGINS``
(comma separated, set by ``defineSiteBackend``). A site with its own projector calls
``plugin_static_files`` with the same names.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

PLUGINS_ENV = "PAPYRUS_PLUGINS"
PLUGIN_ASSET_DIRECTORY = Path(__file__).parent / "plugin_assets"
PLUGIN_STATIC_ASSETS: dict[str, dict[str, str]] = {
    "reader-steering": {},
    "signup": {"_plugins/papyrus-signup@1.js": "papyrus-signup.js"},
}


def plugin_names_from_environment(environ: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(name.strip() for name in (environ.get(PLUGINS_ENV) or "").split(",") if name.strip())


def plugin_static_files(names: Iterable[str]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for name in names:
        if name not in PLUGIN_STATIC_ASSETS:
            raise ValueError(f"Unknown plugin {name!r}; known plugins: {', '.join(sorted(PLUGIN_STATIC_ASSETS))}")
        for key, filename in PLUGIN_STATIC_ASSETS[name].items():
            files[key] = (PLUGIN_ASSET_DIRECTORY / filename).read_bytes()
    return files
