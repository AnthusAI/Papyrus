"""Static files that Papyrus plugins ship to a site that enables them (docs/plugins.md).

The backend tells the projection which plugins a site enables through ``PAPYRUS_PLUGINS``
(comma separated, set by ``defineSiteBackend``). A site with its own projector calls
``plugin_static_files`` with the same names.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from ..reader_steering.snapshot import READER_DATA_DIRECTORY

PLUGINS_ENV = "PAPYRUS_PLUGINS"
PLUGIN_ASSET_DIRECTORY = Path(__file__).parent / "plugin_assets"
PLUGIN_STATIC_ASSETS: dict[str, dict[str, str]] = {
    "reader-steering": {"_plugins/papyrus-reader@1.js": "papyrus-reader.js", "_plugins/papyrus-reader@1.css": "papyrus-reader.css"},
    "newsletter": {"_plugins/papyrus-newsletter@1.js": "papyrus-newsletter.js"},
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


PLUGIN_RUNTIME_DIRECTORIES = (READER_DATA_DIRECTORY + "/",)


def is_plugin_runtime_key(key: str) -> bool:
    """A file a plugin's own task writes (the reader snapshot), at the site root or under ``urls.basePath``.

    The projector's page reconcile must never call such a file an orphan: no page expects it, a task owns it.
    """
    padded = "/" + key
    return any("/" + directory in padded for directory in PLUGIN_RUNTIME_DIRECTORIES)
