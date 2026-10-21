"""Named hooks: the only places site code runs inside the standard front end.

A site's ``projection.json`` names a module (``"hooks": "hooks.py"``, relative to
the static directory). The module may define any of these functions and nothing
else is called; an unknown public function is an error, so a typo cannot silently
do nothing. Anything that needs more than a slot is a signal to add a core option.

``masthead(page) -> str``           the header block
``footer(page) -> str``             the inside of the footer element
``card(entry, page) -> str``        one entry in a listing
``head_extra(page) -> str``         raw markup appended to ``<head>``
``body_class(page) -> str``         classes added to ``<body>`` after the site's ``chrome.body_class``
``item_decorator(html, summary) -> str``   the converted article fragment, before it is placed in the page
``page_body(page) -> str | None``   the whole body of a page (everything between ``<body>`` and the scripts);
                                    ``None`` keeps the default. ``page.kind`` says which page it is.

``derive(summary) -> dict``         fields computed from an item's summary (a tier, a week); they appear as ``entry.derived``,
                                    are part of every fingerprint, and are how a site's row or card component is chosen
``page`` is a :class:`papyrus_content.projection.standard.page.StandardPage`.

A hook that takes ``page`` can read any entry, so by default every page depends on all of them. A module may narrow
that with ``DEPENDS_ON = ["essays", "@root"]`` (section names; ``@root`` is the items with no section) or ``[]`` for
"nothing beyond the page's own entry and the listing slice". It may also be a dict keyed by page id (``home``,
``item``, ``listing:<section>``, ``listing:flat``, ``tags``, ``tag``, ``custom:<id>``, ``not_found``; ``"*"`` is the
fallback) for pages that each depend on less. Editing a hooks module always re-renders.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

HOOK_NAMES = ("masthead", "footer", "card", "head_extra", "body_class", "item_decorator", "page_body", "derive")


@dataclass(frozen=True)
class Hooks:
    masthead: object = None
    footer: object = None
    card: object = None
    head_extra: object = None
    body_class: object = None
    item_decorator: object = None
    page_body: object = None
    derive: object = None
    fingerprint: str = ""
    depends_on: tuple[str, ...] | dict | None = None

    @property
    def sees_the_site(self) -> bool:
        """True when a hook is handed ``page`` (and so every entry and summary of the site)."""
        return any(hook is not None for hook in (self.masthead, self.footer, self.card, self.head_extra, self.body_class, self.page_body))

    @property
    def renders_listings(self) -> bool:
        """True when a hook may read any entry field, so listings depend on all of them."""
        return any(hook is not None for hook in (self.card, self.page_body))


NO_HOOKS = Hooks()


def load_hooks(static_directory: Path | None, relative_path: str | None) -> Hooks:
    if not relative_path:
        return NO_HOOKS
    if static_directory is None:
        raise ValueError(f"hooks {relative_path!r} is configured but the site has no static directory")
    path = (static_directory / relative_path).resolve()
    if static_directory.resolve() not in path.parents or not path.is_file():
        raise ValueError(f"hooks module {relative_path!r} is not a file inside the static directory")
    directory = str(path.parent)
    if directory not in sys.path:
        sys.path.insert(0, directory)  # lets a hooks module import its sibling modules
    spec = importlib.util.spec_from_file_location(f"papyrus_site_hooks_{hashlib.sha1(str(path).encode()).hexdigest()[:8]}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    public = {
        name for name, value in vars(module).items()
        if callable(value) and not name.startswith("_") and getattr(value, "__module__", None) == module.__name__
    }
    unknown = public - set(HOOK_NAMES)
    if unknown:
        raise ValueError(f"{relative_path} defines unknown hooks: {', '.join(sorted(unknown))}. Named hooks are {', '.join(HOOK_NAMES)}.")
    digest = hashlib.sha256()
    for sibling in sorted([*path.parent.glob("*.py"), *path.parent.glob("*.json")]):  # modules and data files the hooks read must re-render too
        digest.update(sibling.name.encode())
        digest.update(sibling.read_bytes())
    fingerprint = digest.hexdigest()[:16]
    declared = getattr(module, "DEPENDS_ON", None)
    return Hooks(
        **{name: getattr(module, name) for name in public},
        fingerprint=fingerprint,
        depends_on=declared if isinstance(declared, dict) or declared is None else tuple(declared),
    )
