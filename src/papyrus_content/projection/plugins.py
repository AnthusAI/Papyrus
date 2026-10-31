"""Static files that Papyrus plugins ship to a site that enables them (docs/plugins.md).

The backend tells the projection which plugins a site enables through ``PAPYRUS_PLUGINS``
(comma separated, set by ``defineSiteBackend``). A site with its own projector calls
``plugin_static_files`` with the same names.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from ..home_page.snapshot import HOME_PAGE_DATA_DIRECTORY
from ..reader_steering.proposals import PROPOSALS_DATA_DIRECTORY
from ..reader_steering.snapshot import READER_DATA_DIRECTORY

PLUGINS_ENV = "PAPYRUS_PLUGINS"
PLUGIN_ASSET_DIRECTORY = Path(__file__).parent / "plugin_assets"
PLUGIN_STATIC_ASSETS: dict[str, dict[str, str]] = {
    "reader-steering": {"_plugins/papyrus-reader@1.js": "papyrus-reader.js", "_plugins/papyrus-reader@1.css": "papyrus-reader.css"},
    "newsletter": {"_plugins/papyrus-newsletter@1.js": "papyrus-newsletter.js", "_plugins/papyrus-newsletter-pages@1.js": "papyrus-newsletter-pages.js"},
    "signup": {"_plugins/papyrus-signup@1.js": "papyrus-signup.js"},
}
# The site-relative key prefixes of the pages a plugin projects. A reconcile never deletes a key under one of them unless the plugin
# is known to be disabled for the site (``standard/newsletter_pages.site_key`` writes ``newsletter/<name>/index.html``).
PLUGIN_PAGE_PREFIXES: dict[str, tuple[str, ...]] = {"newsletter": ("newsletter/",)}


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


KNOWLEDGE_DATA_DIRECTORY = "_data/knowledge"
PLUGIN_RUNTIME_DIRECTORIES = (READER_DATA_DIRECTORY + "/", PROPOSALS_DATA_DIRECTORY + "/", KNOWLEDGE_DATA_DIRECTORY + "/", HOME_PAGE_DATA_DIRECTORY + "/")


def is_plugin_runtime_key(key: str) -> bool:
    """A file a task writes (the reader snapshot, its proposals, the knowledge snapshot, the home-page snapshot), at the site root or under ``urls.basePath``.

    The projector's page reconcile must never call such a file an orphan: no page expects it, a task owns it.
    """
    padded = "/" + key
    return any("/" + directory in padded for directory in PLUGIN_RUNTIME_DIRECTORIES)


def plugin_names_from_outputs(outputs_path: Path) -> tuple[str, ...] | None:
    """The plugins the deployed backend enables: the keys of ``custom.papyrusPlugins`` in ``amplify_outputs.json``.

    ``defineSiteBackend`` publishes that object when, and only when, the site enables a plugin, so a readable file without it means
    "none". ``None`` means the file is missing or unreadable, which is not the same as "none".
    """
    try:
        parsed = json.loads(Path(outputs_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    custom = parsed.get("custom")
    published = custom.get("papyrusPlugins") if isinstance(custom, dict) else None
    return tuple(published) if isinstance(published, dict) else ()
