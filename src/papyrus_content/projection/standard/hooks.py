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

``card`` may also take ``variant`` (what an ``::include{kind="listing" card="..."}`` asks for) and ``index`` (the card's place in
its list, from 0), by those names; a hook without ``variant`` rejects an include that names one.

The hooks that shape an item page before and after it is converted (a site whose content needs more than Markus):

``item_filter(summary) -> bool``    ``False`` leaves an item out of the site: no page, no listing, no sitemap entry
``source(summary, text, site) -> str``      the Markus source that is converted; the item's own text unless the site stages it
                                    (lifts legacy markup, adds a heading block). ``site`` is a :class:`HookSite`.
``item_transform(summary) -> FragmentTransform | None``    applied to the converted fragment (class vocabulary, block passthrough)
``image_pipeline(pipeline) -> ImagePipeline``   the site's image pipeline from ``projection.json`` ``images``, with the
                                    callbacks that are not data (``wrap``) set; the renditions are unchanged
``page_head(head, page) -> PageHead``   the description of the page's ``<head>`` (title, description, image, dates, JSON-LD) before it is built;
                                    return ``dataclasses.replace(head, ...)``
``page_finish(html, page) -> str``  the finished page, as text, before it is written (canonical links, a head tag); it is the last step
``item_inputs(site) -> object``     JSON-able data that every item page also renders from (a table of the site's URLs a page rewrites
                                    its links with); with ``DEPENDS_ON`` declaring ``[]`` for item pages, saving an article
                                    re-renders the others only when this data changes
``redirects(site) -> dict``         exact redirects (``{"/old/": "/new/"}``) a site derives from its items, on top of the items' ``aliases``;
                                    ``projection.json`` ``redirects.exact`` wins over it, and a path that is a page is never redirected
``block(name, attributes, page) -> str``    the markup of ``::include{kind="block" name="..."}`` in an authored page; the include's
                                    ``depends`` attribute names the sections it reads (see ``includes.py``)

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

HOOK_NAMES = (
    "masthead", "footer", "card", "head_extra", "body_class", "item_decorator", "page_body", "derive",
    "item_filter", "source", "item_transform", "image_pipeline", "page_finish", "block", "item_inputs", "redirects", "page_head",
)


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
    item_filter: object = None
    source: object = None
    item_transform: object = None
    image_pipeline: object = None
    page_finish: object = None
    block: object = None
    item_inputs: object = None
    redirects: object = None
    page_head: object = None
    fingerprint: str = ""
    depends_on: tuple[str, ...] | dict | None = None

    @property
    def sees_the_site(self) -> bool:
        """True when a hook is handed ``page`` (and so every entry and summary of the site)."""
        return any(hook is not None for hook in (self.masthead, self.footer, self.card, self.head_extra, self.body_class, self.page_body, self.block, self.page_finish, self.page_head))

    @property
    def renders_listings(self) -> bool:
        """True when a hook may read any entry field, so listings depend on all of them."""
        return any(hook is not None for hook in (self.card, self.page_body, self.block))


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


class HookSite:
    """What the item-level hooks may know about the whole site: the items, the site's image renditions and a memo.

    One instance belongs to one version of the site (the same ``items``); a hook that derives something from the whole
    site (a table of every page, the images the site has) builds it once with :meth:`memo`.
    """

    def __init__(self, items, *, static_directory: Path | None, records) -> None:
        self.items = items
        self.static_directory = static_directory
        self._records = records
        self._memo: dict = {}

    def memo(self, name, build):
        if name not in self._memo:
            self._memo[name] = build()
        return self._memo[name]

    def rendition_records(self) -> list[dict]:
        """The ``meta.json`` records of the site store: the images the site has (empty when the site has no ``images`` settings)."""
        if "records" not in self._memo:
            self._memo["records"] = self._records()
        return self._memo["records"]
