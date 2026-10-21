"""The standard Markus front end: ``MarkusSiteProjector`` configured by ``projection.json``.

A site that has a top-level ``site`` object in ``projection.json`` gets this
projector instead of the bare one. It adds, from settings alone: the extended
public entry model, a URL policy, the environment guard, the head builder, a
sitemap, robots.txt, a 404 page, RSS and Atom feeds, listings (flat or by
section, paginated, with tag pages), accessible components and named hooks.

Dependency rule (what the engine re-renders when something changes):

* an item page depends on its own content, the shared settings and, only if the
  site says so (``components.itemPagesDependOn``), on the entries of other sections;
* a listing page depends on the fingerprints of exactly the entries it shows, its
  page number and page count, and the shared settings;
* feeds and the sitemap depend on their own bytes, which are a function of the
  selection, so a change outside the selection writes nothing.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import math
import re
from collections.abc import Callable, Collection
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from ...markus_renderer.shell import BodyParts, PageContext, SiteChrome, render_page
from ...renditions import RenditionCatalog

from ..model import ItemSummary, ProjectedItem, SiteIndex
from ..plugins import plugin_static_files
from ..projector import (
    HOME_PAGE_PATH,
    PROJECTION_SETTINGS_FILE,
    MarkusProjectorSettings,
    MarkusSiteProjector,
    digest_of,
    read_static_files,
    settings_from_mapping,
)
from ..public_data import clipped, entry_for, hidden_from_public_data, owns_public_data_key, public_data_files, public_data_inputs, public_static_files
from ..writers import request_paths_for_key
import inspect

from . import blocks, components, includes
from .config import STANDARD_KEYS, CollectionConfig, CustomPage, SectionConfig, StandardSettings, standard_settings_from_mapping
from .entries import SUMMARY_FIELDS, StandardEntry, build_entries, entry_for_summary, entry_title, first_text, newest_first, order_of, sorted_by
from .environment import SiteEnvironment, resolve_environment
from .feeds import feed_files, feed_selection
from .head import HeadBuilder, PageHead
from .markdown import FRONT_MATTER, static_twin_key, LLMS_FULL_KEY, LLMS_KEY, body_of, item_markdown, listing_markdown, llms_full_txt, llms_txt, md_key, md_path
from .page_actions import SCRIPT_PATH as PAGE_ACTIONS_SCRIPT, render_page_actions
from .forms import FORM_SCRIPT_PATH, render_form
from .fragments import MARKUS_ARTICLE_CLOSE_PATTERN, first_image_of, lede_of, with_date_format, with_lede, with_listing
from .family import family_footer
from .grouping import group_entries, group_key, group_label
from .hooks import NO_HOOKS, HookSite, Hooks, load_hooks
from .page import ListingView, StandardPage
from .showcase import logo_wall, showcase_sites
from .sitemap import SITEMAP_KEYS, SitemapUrl, robots_text, sitemap_files
from .urls import NOT_FOUND_KEY, UrlPolicy, slugify_tag

def copy_directories(static_directory: Path | None, names, files: dict[str, bytes]) -> list[str]:
    """Add every file under the named directories of the static directory to ``files`` at its relative path."""
    added: list[str] = []
    if static_directory is None:
        return added
    for name in names:
        root = static_directory / name
        if not root.is_dir():
            raise ValueError(f"static.copy names {name!r}, which is not a directory of the static directory")
        for path in sorted(root.rglob("*")):
            key = path.relative_to(root).as_posix()
            if path.is_file() and key not in files:
                files[key] = path.read_bytes()
                added.append(key)
    return added


ARTICLE_OPEN_PATTERN = re.compile(r'^\s*<article class="markus-document"[^>]*>')
COMPONENTS_CSS_PATH = "css/markus-components.css"
NAV_SCRIPT_PATH = "_plugins/papyrus-nav-v1.js"
ISLANDS_RUNTIME_PATH = "_plugins/papyrus-islands-v1.js"
ASSET_DIRECTORY = Path(__file__).parent / "assets"
class StandardMarkusProjector(MarkusSiteProjector):
    def __init__(
        self,
        settings: MarkusProjectorSettings,
        static_files: dict[str, bytes],
        standard: StandardSettings,
        *,
        hooks: Hooks = NO_HOOKS,
        environment: SiteEnvironment | None = None,
        **kwargs,
    ) -> None:
        files = dict(static_files)
        static_directory = kwargs.pop("static_directory", None)
        if "css/markus-vendor.css" not in settings.chrome.stylesheets:
            files.pop("css/markus-vendor.css", None)  # a site that does not link Markus's stylesheet does not publish it
        self._passthrough = frozenset(copy_directories(static_directory, standard.static_copy, files))
        if standard.components_css:
            files[COMPONENTS_CSS_PATH] = (ASSET_DIRECTORY / "markus-components.css").read_bytes()
        if standard.nav_disclosure:
            files[NAV_SCRIPT_PATH] = (ASSET_DIRECTORY / "papyrus-nav.js").read_bytes()
        if standard.page_actions.enabled and standard.agents.markdown:
            files[PAGE_ACTIONS_SCRIPT] = (ASSET_DIRECTORY / "papyrus-page-actions.js").read_bytes()
        if any(form.endpoint for form in standard.forms):
            files[FORM_SCRIPT_PATH] = (ASSET_DIRECTORY / "papyrus-form.js").read_bytes()
        prerendered_bytes = b""
        if standard.islands is not None:
            files[ISLANDS_RUNTIME_PATH] = (ASSET_DIRECTORY / "papyrus-islands.js").read_bytes()
            for path in (standard.islands.script, standard.islands.stylesheet):
                if path and path not in files:
                    source = static_directory / path if static_directory is not None else None
                    if source is None or not source.is_file():
                        raise ValueError(f"islands names {path!r}, which is not a file of the static directory")
                    files[path] = source.read_bytes()
            if standard.islands.prerender:
                # Build input, not site content: read it, keep it out of the published files.
                path = standard.islands.prerender
                source = static_directory / path if static_directory is not None else None
                if path in files:
                    prerendered_bytes = files.pop(path)
                elif source is not None and source.is_file():
                    prerendered_bytes = source.read_bytes()
                else:
                    raise ValueError(f"islands.prerender names {path!r}, which is not a file of the static directory")
        super().__init__(settings, files, **kwargs)
        self._static_directory = static_directory
        self._hook_sites: list[HookSite] = []
        self._pipeline_cache = None
        self._page_text_cache: dict[str, str] = {}
        self._prerendered = blocks.parse_prerendered(prerendered_bytes) if prerendered_bytes else {}
        self.standard = standard
        self.hooks = hooks
        self.environment = environment or resolve_environment(standard)
        self.policy = UrlPolicy(standard)
        self.head = HeadBuilder(standard, self.environment)
        self._plan_cache: tuple[object, dict] | None = None
        self._shared_fingerprint = digest_of(
            [dataclasses.asdict(standard), self.environment.fingerprint(), repr(settings.chrome), hooks.fingerprint, self.version, prerendered_bytes.decode("utf-8", "replace")]
        )

    @classmethod
    def from_static_directory(cls, static_directory, *, renditions=None, plugins=(), environ=None):  # type: ignore[override]
        settings_path = static_directory / PROJECTION_SETTINGS_FILE if static_directory is not None else None
        raw = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path and settings_path.is_file() else {}
        if "site" not in raw:
            raise ValueError("projection.json has no 'site' object; the standard front end is opt-in by having one.")
        standard = standard_settings_from_mapping(raw)
        base_raw = {key: value for key, value in raw.items() if key not in STANDARD_KEYS}
        settings = dataclasses.replace(settings_from_mapping(base_raw), plugins=plugins)
        return cls(
            settings,
            read_static_files(static_directory, settings.theme),
            standard,
            static_directory=static_directory,
            hooks=load_hooks(static_directory, standard.hooks_path),
            environment=resolve_environment(standard, environ),
            renditions=renditions,
        )

    # ------------------------------------------------------------------ model

    def _entries(self, site: SiteIndex) -> list[StandardEntry]:
        return newest_first(build_entries(site.items, self.standard, self.policy, self.hooks.derive, self.hooks.item_filter))

    def _entry(self, summary: ItemSummary) -> StandardEntry | None:
        return entry_for_summary(summary, self.standard, self.policy, self.hooks.derive, self.hooks.item_filter)

    def _pipeline(self):
        pipeline = super()._pipeline()
        if pipeline is None or self.hooks.image_pipeline is None:
            return pipeline
        if self._pipeline_cache is None:
            self._pipeline_cache = self.hooks.image_pipeline(pipeline)
        return self._pipeline_cache

    def _rendition_records(self) -> list[dict]:
        """The rendition records of the site store, read afresh (images are uploaded while a projector is kept warm)."""
        pipeline = self._pipeline()
        if pipeline is None or self._renditions is None:
            return []
        return RenditionCatalog(self._renditions, pipeline).all_records()

    def _hook_site(self, site: SiteIndex) -> HookSite:
        for found in self._hook_sites:
            if found.items is site.items:
                return found
        found = HookSite(site.items, static_directory=self._static_directory, records=self._rendition_records)
        self._hook_sites.append(found)
        del self._hook_sites[:-4]
        return found

    @staticmethod
    def _authored_home(site: SiteIndex) -> bool:
        return any(MarkusSiteProjector._is_home_source(summary) and not PurePosixPath(summary.output_path).name.startswith(("_", ".")) for summary in site.items)

    def _full(self) -> bool:
        return self.hooks.renders_listings

    def _fingerprints(self, entries, *, full: bool | None = None) -> list:
        return [entry.fingerprint(full=self._full() if full is None else full) for entry in entries]

    # ------------------------------------------------------------------ page blocks

    def _fragment(self, text: str, depth: int, source: str = "", *, transform=None, trusted: bool = False, include=None) -> str:
        """Tokens and page blocks are handled before Markus; a page with none is converted exactly as before.

        ``trusted`` (a page file of the static directory) allows ``::raw``; ``include`` places ``::include`` blocks.
        """
        values = dict(self.standard.values)
        text = blocks.substitute(text, values, source)
        if not blocks.uses_blocks(text):
            return super()._fragment(text, depth, transform=transform)
        front = FRONT_MATTER.match(text)
        body = text[front.end():] if front else text

        def convert(markdown: str) -> str:
            fragment = super(StandardMarkusProjector, self)._fragment(markdown, depth, transform=transform)
            return MARKUS_ARTICLE_CLOSE_PATTERN.sub("", ARTICLE_OPEN_PATTERN.sub("", fragment, count=1), count=1).strip()

        return blocks.render(body, source, convert, include, trusted=trusted)

    def _twin(self, text: str, source: str) -> str:
        return blocks.twin(text, dict(self.standard.values), source)

    # ------------------------------------------------------------------ item pages

    def item_page_paths(self, summary: ItemSummary) -> tuple[str, ...]:
        if PurePosixPath(summary.output_path).name.startswith(("_", ".")):
            return ()
        if self._is_home_source(summary):
            return self._with_markdown((HOME_PAGE_PATH,), noindex=False)
        entry = self._entry(summary)
        return self._with_markdown((entry.key,), noindex=entry.noindex) if entry is not None and entry.key else ()

    def _with_markdown(self, keys: tuple[str, ...], *, noindex: bool) -> tuple[str, ...]:
        twin = md_key(keys[0]) if self.standard.agents.markdown and not noindex else None
        return keys + ((twin,) if twin else ())

    def item_pages(self, item: ProjectedItem, site: SiteIndex) -> dict[str, bytes]:
        summary = item.summary
        paths = self.item_page_paths(summary)
        if not paths:
            return {}
        key = paths[0]
        text = item.source_text if self.hooks.source is None else self.hooks.source(summary, item.source_text, self._hook_site(site))
        transform = self.hooks.item_transform(summary) if self.hooks.item_transform is not None else None
        fragment = self._fragment(text, key.count("/"), summary.output_path, transform=transform)
        if self.hooks.item_decorator is not None:
            fragment = self.hooks.item_decorator(fragment, summary)
        if self.standard.identity.lede_field:
            fragment = with_lede(fragment, summary.front_matter.get(self.standard.identity.lede_field))
        fragment = with_date_format(fragment, self.standard.identity.date_format)
        entries = tuple(self._entries(site)) if self._depends_on_entries() else ()
        if self._is_home_source(summary):
            title = entry_title(summary) if summary.front_matter.get("title") else (summary.page_title or summary.title or self.standard.identity.name)
            head = PageHead(
                title=title,
                path="/",
                description=clipped(first_text(summary.front_matter, self.standard.summary_fields or SUMMARY_FIELDS), 300) or lede_of(fragment) or self.standard.identity.description,
                image=first_image_of(fragment),
            )
            page = self._page("home", head, site, entries=entries, fragment=fragment)
            pages = {key: self._render(page)}
            if len(paths) > 1:
                pages[paths[1]] = self._home_markdown(title, head.description, self._twin(item.source_text, summary.output_path)).encode("utf-8")
            return pages
        entry = self._entry(summary)
        description = entry.summary_text or lede_of(fragment) or self.standard.identity.description
        article = entry.type in self.standard.listings.types or entry.type in self.standard.seo.article_types
        crumbs = self._breadcrumbs(entry)
        head = PageHead(
            title=entry.title,
            path=entry.url,
            description=description,
            og_type="article" if article else "website",
            image=entry.image or first_image_of(fragment),
            canonical=entry.canonical,
            published=entry.date,
            modified=entry.updated,
            authors=entry.authors,
            tags=entry.tags,
            noindex=entry.noindex,
            based_on=self._based_on(entry),
            json_ld_type=self._json_ld_type(entry) if article else None,
            breadcrumbs=crumbs,
        )
        page = self._page("item", head, site, entry=entry, entries=entries, fragment=fragment, crumbs=crumbs)
        pages = {key: self._render(page)}
        if len(paths) > 1:
            canonical = entry.canonical or self.head.absolute(entry.url)
            pages[paths[1]] = item_markdown(entry, self._twin(item.source_text, summary.output_path), canonical).encode("utf-8")
        return pages

    def _home_markdown(self, title: str, description: str, source_text: str) -> str:
        lines = [f"# {title}", ""] + ([f"> {description}", ""] if description else [])
        return "\n".join(lines + [body_of(source_text)]).rstrip() + "\n"

    def _based_on(self, entry: StandardEntry) -> str:
        """The original this page is based on: the URL in ``seo.isBasedOnField``, only when it is an absolute http(s) URL."""
        field = self.standard.seo.based_on_field
        value = entry.data.get(field) if field else None
        return value.strip() if isinstance(value, str) and value.strip().startswith(("http://", "https://")) else ""

    def _json_ld_type(self, entry: StandardEntry) -> str:
        mapping = dict(self.standard.seo.json_ld_types)
        section = entry.section.name if entry.section else None
        return mapping.get(section) or mapping.get(entry.type) or self.standard.seo.default_json_ld

    def _breadcrumbs(self, entry: StandardEntry) -> tuple[tuple[str, str], ...]:
        if not self.standard.breadcrumbs:
            return ()
        crumbs = [(self.standard.home_link_label, "/")]
        if entry.section is not None and entry.section.listing and entry.section.listing_page:
            crumbs.append((entry.section.label, f"/{entry.section.base}/"))
        crumbs.append((entry.title, entry.url))
        return tuple(crumbs) if len(crumbs) > 1 else ()

    def _dependencies(self, page_id: str = "item") -> tuple[str, ...]:
        """Which entries a page also depends on: ``*``, section names or ``@root``; empty for none.

        ``page_id`` is ``item``, ``home``, ``listing:<section>`` (``listing:flat`` for the flat listing), ``tags``,
        ``tag``, ``custom:<id>`` or ``not_found``. A hooks module's ``DEPENDS_ON`` is a list for all pages or a dict
        keyed by those ids (``"*"`` is the fallback key).
        """
        declared = self.hooks.depends_on
        if isinstance(declared, dict):
            declared = declared.get(page_id, declared.get("*", ("*",)))
            declared = (declared,) if isinstance(declared, str) else tuple(declared)
        if declared is None:
            declared = ("*",) if self.hooks.sees_the_site else ()
        return tuple(dict.fromkeys((*declared, *self.standard.item_depends_on)))

    def _depends_on_entries(self) -> bool:
        return bool(self._dependencies())

    def _dependency_digest(self, entries: list[StandardEntry], page_id: str = "item") -> list:
        wanted = self._dependencies(page_id)
        if not wanted:
            return []
        selected = [
            entry for entry in entries
            if "*" in wanted or (entry.section.name if entry.section else "@root") in wanted
        ]
        return self._fingerprints(selected, full=True)

    def _page_inputs(self, site: SiteIndex):
        return self.hooks.page_inputs(self._hook_site(site)) if self.hooks.page_inputs is not None else None

    def shared_inputs(self, site: SiteIndex) -> str:
        entries = self._entries(site) if self._depends_on_entries() else []
        inputs = self._page_inputs(site)
        return digest_of([self._shared_fingerprint, self._dependency_digest(entries), self._authored_home(site), inputs])

    # ------------------------------------------------------------------ generated pages

    def _plan(self, site: SiteIndex) -> dict[str, tuple[str, Callable[[], bytes]]]:
        """``key -> (input digest, renderer)`` for every generated page; cached per site index."""
        if self._plan_cache is not None and self._plan_cache[0] is site.items:
            return self._plan_cache[1]
        entries = self._entries(site)
        listed = [entry for entry in entries if entry.listed]
        summaries = site.items
        plan: dict[str, tuple[str, Callable[[], bytes]]] = {}
        shared = self._shared_fingerprint

        page_inputs = self._page_inputs(site)

        def add(key: str, page_id: str, digest_input, build_page: Callable[[], StandardPage], markdown: bool = True) -> None:
            dependency = self._dependency_digest(entries, page_id)
            digest = digest_of([shared, key, digest_input, dependency, page_inputs])
            plan[key] = (digest, lambda: self._render(build_page()))
            twin = md_key(key) if markdown and self.standard.agents.markdown else None
            if twin:
                plan[twin] = (digest_of([digest, "markdown"]), lambda: self._markdown_for(build_page()).encode("utf-8"))

        # home
        if not self._authored_home(site) and not any(custom.path == "" for custom in self.standard.pages):
            home_entries = tuple(listed[: self.standard.listings.home_count])
            add(
                HOME_PAGE_PATH,
                "home",
                [self._fingerprints(home_entries), self._section_links()],
                lambda: self._page(
                    "home",
                    PageHead(title=self.standard.identity.name, path="/", description=self.standard.identity.description, social_title=self.standard.seo.home_social_title),
                    site, entries=tuple(listed), listing=ListingView("", self.standard.home_link_label, home_entries, tuple(listed), 1, 1),
                ),
            )

        # listings: one flat listing, or one per section that has something to list
        for base, label, section_name, members in self._listing_groups(listed):
            for view in self._paginate(base, label, members, section_name):
                key = self.policy.listing_key(base, view.page)
                intro = self._intro(summaries, section_name) if view.page == 1 else None
                add(
                    key,
                    f"listing:{section_name or 'flat'}",
                    [self._fingerprints(view.entries), view.page, view.pages, len(view.featured), self._intro_fingerprint(intro)],
                    self._listing_builder("listing", view, site, listed, intro),
                )

        # collections: listings selected by tag or section, not by CMS section
        for collection in self.standard.collections:
            members = sorted_by(collection.select.select(entries), collection.sort, collection.ties)
            if not members and not collection.list_empty:
                continue
            drafts = tuple(sorted_by(collection.select.select(entries, drafts=True), collection.sort, collection.ties)) if collection.drafts else ()
            for view in self._paginate(collection.base, collection.label, members, None, collection=collection, drafts=drafts):
                add(
                    self.policy.listing_key(collection.base, view.page),
                    f"listing:{collection.id}",
                    [self._fingerprints(view.entries, full=True), view.page, view.pages, len(view.featured), self._fingerprints(view.drafts, full=True)],
                    self._listing_builder("listing", view, site, listed),
                )

        # archives: one page per month (or year) that has entries
        for section_config in self.standard.sections:
            archive = section_config.archive
            if archive is None or not section_config.listing:
                continue
            members = [entry for entry in listed if entry.section and entry.section.name == section_config.name]
            for view in self._archive_views(section_config, members):
                add(
                    self.policy.listing_key(view.base),
                    f"archive:{section_config.name}",
                    [self._fingerprints(view.entries), list(view.archive_keys), view.group],
                    lambda view=view, section_config=section_config: self._page(
                        "archive",
                        PageHead(
                            title=f"{view.label}: {self._archive_label(view.group, section_config.archive.by)}",
                            path=f"/{view.base}/",
                            description=section_config.archive.description or section_config.description or self.standard.identity.description,
                        ),
                        site, entries=tuple(listed), listing=view,
                    ),
                )

        # tags
        tags = self._tag_map(self._tag_entries(listed))
        if self.standard.listings.tags and tags:
            add(
                self.policy.listing_key(self.policy.tag_base()),
                "tags",
                [sorted((tag, len(found)) for tag, found in tags.items())],
                lambda: self._tag_index_page(tags, site, listed),
            )
            for tag, found in tags.items():
                slug = slugify_tag(tag)
                if not slug:
                    continue
                for view in self._paginate(self.policy.tag_base(slug), tag, found, None, tag=tag):
                    key = self.policy.listing_key(view.base, view.page)
                    add(key, "tag", [self._fingerprints(view.entries), view.page, view.pages], self._listing_builder("tag", view, site, listed))

        # showcase (logo wall)
        wall = self.standard.showcase
        if wall is not None:
            sites = showcase_sites(summaries, wall)
            add(
                self.policy.listing_key(wall.path),
                "showcase",
                [[site.fingerprint() for site in sites]],
                lambda: self._page(
                    "showcase",
                    PageHead(title=wall.title, path=f"/{wall.path}/", description=wall.description or self.standard.identity.description),
                    site, entries=tuple(listed), showcase=tuple(sites),
                ),
            )

        # custom pages, and authored page files
        for custom in self.standard.pages:
            selected = [entry for entry in entries if "*" in custom.depends_on or (entry.section and entry.section.name in custom.depends_on)]
            authored = self._page_includes(custom.source, f"pages.{custom.id}") if custom.source else None
            digest_input = [self._fingerprints(selected, full=True) if self.hooks.page_body else []]
            if authored is not None:
                text, found = authored
                digest_input = [hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], includes.include_inputs(found, entries, self.standard), self._showcase_inputs(summaries, found)]
            path = f"/{custom.path}/" if custom.path else "/"
            add(
                self.policy.listing_key(custom.path),
                f"custom:{custom.id}",
                digest_input,
                lambda custom=custom, path=path: self._custom_page(
                    custom, PageHead(title=custom.title, path=path, description=custom.description or self.standard.identity.description, noindex=custom.noindex, image=custom.image, image_alt=custom.image_alt, social_title=custom.social_title),
                    site, listed,
                ),
                markdown=not custom.noindex,
            )

        # 404
        not_found = self.standard.not_found
        not_found_input: list = []
        if not_found.source:
            text, found = self._page_includes(not_found.source, "notFound")
            not_found_input = [hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], includes.include_inputs(found, entries, self.standard), self._showcase_inputs(summaries, found)]
        add(
            NOT_FOUND_KEY,
            "not_found",
            not_found_input,
            lambda: self._not_found_page(
                PageHead(title=not_found.title, path="/404.html", description=not_found.description, noindex=not_found.noindex), site, listed,
            ),
        )

        # sitemap, feeds
        sitemap = sitemap_files(self.standard.sitemap_style, self.environment, self._sitemap_urls(site, entries, listed, plan), lastmod=self.standard.sitemap_lastmod)
        selection = feed_selection(entries, self.standard)
        for key, body in {**sitemap, **feed_files(selection, self.standard, self.environment)}.items():
            plan[key] = (hashlib.sha256(body).hexdigest()[:16], lambda body=body: body)
        self._add_llms_files(plan, site, entries, listed)
        self._plan_cache = (site.items, plan)
        return plan

    # ------------------------------------------------------------------ agent-readable files

    def _llms_groups(self, listed: list[StandardEntry], entries: list[StandardEntry]) -> list[tuple[str, list[StandardEntry]]]:
        limit = self.standard.agents.llms_max_links
        visible = [entry for entry in listed if (entry.key or entry.link) and not entry.noindex]
        if self.standard.sectioned:
            groups = [
                (section.label, [entry for entry in visible if entry.section and entry.section.name == section.name][:limit])
                for section in self.standard.sections
            ]
        else:
            groups = [("Articles", visible[:limit])]
        pages = [entry for entry in entries if not entry.listed and entry.key and not entry.noindex]
        pages += [
            SimpleNamespace(title=title, key=None, link=(self.environment.origin or "") + path, summary_text="", date="")
            for title, path, _text in self._static_twin_documents()
        ]
        return [*groups, ("Pages", pages[:limit])]

    def _static_twin_documents(self) -> list[tuple[str, str, str]]:
        """``(title, twin path, text)`` for each ``sitemap.extra`` route whose Markdown twin the site publishes by hand (``static.copy``)."""
        found = []
        for route in self.standard.sitemap_extra:
            key = static_twin_key(route)
            if key is None or key not in self._passthrough or key not in self._static_files:
                continue
            text = self._static_files[key].decode("utf-8")
            heading = re.search(r"^# (.+)$", text, re.M)
            found.append((heading.group(1).strip() if heading else route, "/" + key, text))
        return found

    def _llms_full_entries(self, entries: list[StandardEntry]) -> list[StandardEntry]:
        return [entry for entry in entries if entry.key and not entry.noindex]

    def _add_llms_files(self, plan, site: SiteIndex, entries, listed) -> None:
        agents = self.standard.agents
        if not agents.markdown or self.environment.guarded:
            return
        origin = self.environment.origin
        full_entries = self._llms_full_entries(entries)
        static_documents = self._static_twin_documents()
        full_enabled = agents.llms_full and 0 < len(full_entries) + len(static_documents) <= agents.llms_full_max_items
        if agents.llms_txt:
            optional = []
            if "rss" in self.standard.feeds.formats:
                optional.append(("RSS feed", "/" + self.standard.feeds.rss_path))
            if "atom" in self.standard.feeds.formats:
                optional.append(("Atom feed", "/" + self.standard.feeds.atom_path))
            optional.append(("Sitemap", "/sitemap-index.xml" if self.standard.sitemap_style == "index" else "/sitemap.xml"))
            if full_enabled:
                optional.append(("Full content of this site in one file", "/" + LLMS_FULL_KEY))
            body = llms_txt(self.standard.identity, self._llms_groups(listed, entries), optional, origin).encode("utf-8")
            plan[LLMS_KEY] = (hashlib.sha256(body).hexdigest()[:16], lambda body=body: body)
        if full_enabled:
            identity = self.standard.identity
            versions = [[entry.item_id, entry.summary.version_number] for entry in full_entries]
            digest = digest_of([self._shared_fingerprint, versions, agents.llms_full_max_bytes, [text for _title, _path, text in static_documents]])

            def render() -> bytes:
                documents = (
                    item_markdown(entry, self._twin(site.load_item(entry.item_id).source_text, entry.summary.output_path), entry.canonical or self.head.absolute(entry.url))
                    for entry in full_entries
                )
                return llms_full_txt(identity, itertools.chain(documents, (text for _title, _path, text in static_documents)), agents.llms_full_max_bytes).encode("utf-8")

            plan[LLMS_FULL_KEY] = (digest, render)

    def _markdown_for(self, page: StandardPage) -> str:
        identity = self.standard.identity
        origin = self.environment.origin
        description = page.description or identity.description
        view = page.listing
        if page.kind == "home" and view is not None:
            return listing_markdown(identity.name, description, view.entries, origin)
        if page.kind in ("listing", "tag", "archive") and view is not None:
            title = page.title
            return listing_markdown(
                title, description, view.entries, origin, page=view.page, pages=view.pages,
                page_md=lambda number: md_path(self.policy.listing_key(view.base, number)),
            )
        if page.kind == "tags":
            entries = [f"- [{tag}]({(origin or '') + md_path(self.policy.listing_key(self.policy.tag_base(slugify_tag(tag))))}) ({len(found)})" for tag, found in page.tags.items()]
            return "\n".join([f"# {page.title}", "", *entries]).rstrip() + "\n"
        if page.kind == "showcase":
            wall = [
                f"- [{site.name}]({site.url})" + (f" ({site.kind})" if site.kind else "") + (f": {site.description}" if site.description else "")
                for site in page.showcase
            ]
            return "\n".join([f"# {page.title}", "", *([f"> {description}", ""] if description else []), *wall]).rstrip() + "\n"
        return "\n".join([f"# {page.title}", "", *([f"> {description}", ""] if description else [])]).rstrip() + "\n"

    def _section_links(self) -> list:
        return [(section.label, section.base) for section in self.standard.sections if section.listing and section.listing_page]

    def _listing_groups(self, listed: list[StandardEntry]):
        if not self.standard.sectioned:
            if listed:
                yield self.standard.listings.flat_path, "Archive", None, listed
            return
        for section in self.standard.sections:
            if not section.listing or not section.listing_page:
                continue
            members = [entry for entry in listed if entry.section and entry.section.name == section.name]
            if section.sort == "order":
                members = sorted(members, key=order_of)
            if members or section.list_empty:
                yield section.base, section.label, section.name, members

    def _paginate(self, base: str, label: str, members: list[StandardEntry], section: str | None, *, tag: str | None = None, collection: CollectionConfig | None = None, drafts=()):
        settings = self.standard.listings
        configured = self.standard.section(section)
        size = configured.page_size if configured is not None and configured.page_size else settings.page_size
        featured_count = settings.featured_count
        if collection is not None:
            size = collection.page_size or size
            featured_count = collection.featured_count if collection.featured_count is not None else featured_count
        if tag is not None and settings.tag_page_size is not None:
            size, featured_count = settings.tag_page_size or max(len(members), 1), 0
        first = featured_count + size
        remaining = max(0, len(members) - first)
        pages = 1 + math.ceil(remaining / size)
        for number in range(1, pages + 1):
            if number == 1:
                shown = members[:first]
                featured = tuple(shown[:featured_count])
            else:
                start = first + (number - 2) * size
                shown = members[start : start + size]
                featured = ()
            by = configured.group_by if configured is not None else None
            groups = tuple(group_entries(shown, by)) if by else ()
            yield ListingView(
                base, label, tuple(shown), tuple(members), number, pages, featured, section, tag, groups,
                collection=collection.id if collection is not None else None, drafts=tuple(drafts) if number == 1 else (),
            )

    @staticmethod
    def _archive_label(key: str, by: str) -> str:
        return group_label(key, "month") if by == "month" else key

    def _archive_views(self, section: "SectionConfig", members: list[StandardEntry]):
        archive = section.archive
        width = 7 if archive.by == "month" else 4
        keys = sorted({entry.date[:width] for entry in members if len(entry.date) >= width}, reverse=True)
        for key in keys:
            found = tuple(entry for entry in members if entry.date[:width] == key)
            by = section.group_by
            groups = tuple(group_entries(found, by)) if by else ()
            yield ListingView(
                f"{section.base}/{archive.base}/{key}", section.label, found, tuple(members), 1, 1, (), section.name, None,
                groups, key, tuple(keys),
            )

    def _tag_entries(self, listed: list[StandardEntry]) -> list[StandardEntry]:
        """The entries the tag pages and the tag index cover: every listed entry unless ``listings.tagSelect`` narrows it."""
        select = self.standard.listings.tag_select
        return select.select(listed) if (select.sections or select.tags or select.all_tags or select.not_tags) else listed

    def _tag_map(self, listed: list[StandardEntry]) -> dict[str, list[StandardEntry]]:
        merged: dict[str, tuple[str, list[StandardEntry]]] = {}
        for entry in listed:
            for tag in entry.tags:
                slug = slugify_tag(tag)
                if not slug:
                    continue
                label, found = merged.setdefault(slug, (tag, []))
                found.append(entry)
        return {label: found for label, found in sorted(merged.values(), key=lambda pair: slugify_tag(pair[0]))}

    def _intro(self, summaries, section_name: str | None) -> ItemSummary | None:
        """The authored ``index`` item of a declared section: its body is shown above that section's listing."""
        if section_name is None:
            return None
        for summary in summaries:
            if summary.section == section_name and summary.slug == "index" and not PurePosixPath(summary.output_path).name.startswith(("_", ".")):
                return summary
        return None

    @staticmethod
    def _intro_fingerprint(intro: ItemSummary | None) -> list:
        return [] if intro is None else [intro.item_id, intro.version_number, intro.front_matter]

    def _listing_builder(self, kind: str, view: ListingView, site: SiteIndex, listed: list[StandardEntry], intro: ItemSummary | None = None):
        def build() -> StandardPage:
            suffix = self.standard.listings.page_suffix.format(page=view.page) if view.page > 1 else ""
            title = (self.standard.listings.tag_title.format(tag=view.label) if kind == "tag" else view.label) + suffix
            configured = self.standard.section(view.section)
            collection = self.standard.collection(view.collection)
            description = (collection.description if collection is not None else configured.description if configured is not None else "") or self.standard.identity.description
            fragment = ""
            if intro is not None:
                fragment = self._fragment(site.load_item(intro.item_id).source_text, view.url_for_page(view.page).count("/") - 1, intro.output_path)
                title = entry_title(intro)
                description = clipped(first_text(intro.front_matter, self.standard.summary_fields or SUMMARY_FIELDS), 300) or lede_of(fragment) or description
            head = PageHead(title=title, path=view.url_for_page(view.page), description=description)
            return self._page(kind, head, site, entries=tuple(listed), listing=view, fragment=fragment)

        return build

    def _tag_index_page(self, tags, site, listed) -> StandardPage:
        head = PageHead(title="Tags", path=f"/{self.policy.tag_base()}/", description=self.standard.identity.description)
        return self._page("tags", head, site, entries=tuple(listed), tags=tags)

    def _sitemap_urls(self, site, entries, listed, plan) -> list[SitemapUrl]:
        newest = max((entry.updated for entry in entries), default="")
        urls = [SitemapUrl("/", newest)]
        for entry in entries:
            if entry.in_sitemap:
                urls.append(SitemapUrl(entry.url, entry.updated))
        groups = list(self._listing_groups(listed))
        for base, _label, _section, members in groups:
            urls.append(SitemapUrl(f"/{base}/", max((entry.updated for entry in members), default="")))
        for collection in self.standard.collections:
            if not collection.sitemap:
                continue
            members = collection.select.select(entries)
            if not members and not collection.list_empty:
                continue
            updated = max((entry.updated for entry in members), default="")
            for view in self._paginate(collection.base, collection.label, sorted_by(members, collection.sort, collection.ties), None, collection=collection):
                if view.page == 1 or collection.sitemap_pages:
                    urls.append(SitemapUrl(view.url_for_page(view.page), updated))
        for section_config in self.standard.sections:
            if section_config.archive is not None and section_config.listing and section_config.sitemap:
                members = [entry for entry in listed if entry.section and entry.section.name == section_config.name]
                for view in self._archive_views(section_config, members):
                    urls.append(SitemapUrl(f"/{view.base}/", max(entry.updated for entry in view.entries)))
        if self.standard.sitemap_tags and self.standard.listings.tags:
            tags = self._tag_map(self._tag_entries(listed))
            if tags:
                urls.append(SitemapUrl(f"/{self.policy.tag_base()}/", ""))
                urls.extend(SitemapUrl(f"/{self.policy.tag_base(slugify_tag(tag))}/", max(entry.updated for entry in found)) for tag, found in tags.items() if slugify_tag(tag))
        if self.standard.showcase is not None:
            urls.append(SitemapUrl(f"/{self.standard.showcase.path}/", ""))
        for custom in self.standard.pages:
            if custom.sitemap and not custom.noindex:
                urls.append(SitemapUrl(f"/{custom.path}/" if custom.path else "/", ""))
        urls.extend(SitemapUrl(path, "") for path in self.standard.sitemap_extra)
        unique = {}
        for url in urls:
            unique.setdefault(url.path, url)
        return list(unique.values())

    def listing_inputs(self, site: SiteIndex) -> dict[str, str]:
        inputs = {key: digest for key, (digest, _render) in self._plan(site).items()}
        inputs.update(self._public_data_inputs(site))
        return inputs

    def listing_pages(self, site: SiteIndex, keys: Collection[str] | None = None) -> dict[str, bytes]:
        pages = {key: render() for key, (_digest, render) in self._plan(site).items() if keys is None or key in keys}
        pages.update(self._public_data_pages(site, keys))
        return pages

    def _public_data_entries(self, site: SiteIndex):
        settings = self._settings.public_data
        if settings is None:
            return []
        return [
            entry_for(entry.summary, entry.key, settings, date=entry.date)
            for entry in self._entries(site)
            if entry.listed and entry.key and not entry.noindex and not hidden_from_public_data(entry.summary)
        ]

    def _public_data_inputs(self, site):
        settings = self._settings.public_data
        return {} if settings is None else public_data_inputs(self._public_data_entries(site), settings)

    def _public_data_pages(self, site, keys):
        settings = self._settings.public_data
        if settings is None:
            return {}
        files = public_data_files(self._public_data_entries(site), settings)
        return files if keys is None else {key: body for key, body in files.items() if key in keys}

    # ------------------------------------------------------------------ ownership, static files, redirects

    def owns_page_key(self, key: str) -> bool:
        if key in self._passthrough:
            return False
        if key == HOME_PAGE_PATH or key in SITEMAP_KEYS or key in (self.standard.feeds.rss_path, self.standard.feeds.atom_path):
            return True
        if key in (LLMS_KEY, LLMS_FULL_KEY) or (key.endswith(".md") and not key.startswith(("css/", "assets/", "_"))):
            return True
        if owns_public_data_key(key):
            return True
        return key.endswith(".html") and not key.startswith(("css/", "assets/", "_"))

    def static_files(self) -> dict[str, bytes]:
        files = {**self._static_files, **public_static_files(self._settings.public_data), **plugin_static_files(self._settings.plugins)}
        files["robots.txt"] = robots_text(self.standard.sitemap_style, self.environment, self.standard.robots_extra).encode("utf-8")
        return files

    def canonical_path(self, key: str) -> str:
        """The public path of a page key (what rename redirects point at)."""
        return self.policy.url_for_key(key)

    def redirects(self, site: SiteIndex) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for summary in site.items:
            paths = self.item_page_paths(summary)
            for alias in summary.aliases if paths else ():
                source = alias if alias.startswith("/") else "/" + alias
                mapping[source] = self.policy.url_for_key(paths[0])
        if self.hooks.redirects is not None:
            mapping.update(self.hooks.redirects(self._hook_site(site)))
        for source, target in self.standard.exact_redirects:
            mapping[source] = target
        live = {path for key in self._plan(site) for path in request_paths_for_key(key)}
        live |= {path for summary in site.items for key in self.item_page_paths(summary) for path in (*request_paths_for_key(key), self.policy.url_for_key(key))}
        return {source: target for source, target in mapping.items() if source not in live and source != target}

    # ------------------------------------------------------------------ rendering

    def _page(self, kind: str, head: PageHead, site: SiteIndex, *, entries=(), **extra) -> StandardPage:
        crumbs = extra.pop("crumbs", ())
        page = StandardPage(
            kind=kind,
            path=head.path,
            title=head.title,
            description=head.description,
            settings=self.standard,
            environment=self.environment,
            head=head,
            entries=tuple(entries),
            summaries=site.items,
            breadcrumbs=crumbs,
            site=self._hook_site(site),
            **extra,
        )
        return dataclasses.replace(page, page_actions=self._page_actions(page)) if kind == "item" else page

    def _chrome(self, page: StandardPage) -> SiteChrome:
        base = self._settings.chrome
        extra = self.hooks.head_extra(page) if self.hooks.head_extra is not None else ""
        twin = None
        if self.standard.agents.markdown and not page.head.noindex:
            key = self.policy.key_for_path(page.path)
            twin = md_path(key) if md_key(key) else None
        described = self._described(page)
        head_html = self.head.build(dataclasses.replace(described, extra=extra, markdown_path=twin))
        if self.hooks.body_class is not None:
            base = dataclasses.replace(base, body_class=f"{base.body_class} {self.hooks.body_class(page)}".strip())
        sheets = list(base.stylesheets)
        if self.standard.components_css and COMPONENTS_CSS_PATH not in sheets:
            sheets.insert(1 if sheets and sheets[0] == "css/markus-vendor.css" else 0, COMPONENTS_CSS_PATH)
        if self.standard.islands is not None and self.standard.islands.stylesheet:
            sheets.append(self.standard.islands.stylesheet)
        if self.environment.guarded and (base.ga_measurement_id is not None or base.consent_mode is not None):
            base = dataclasses.replace(base, ga_measurement_id=None, ga_owner_opt_out=False, consent_mode=None)  # a guarded build never counts visits
        scripts = tuple(base.scripts) + ((NAV_SCRIPT_PATH,) if self.standard.nav_disclosure else ())
        if any(form.endpoint for form in self.standard.forms):
            scripts += (FORM_SCRIPT_PATH,)
        if self.standard.page_actions.enabled and self.standard.agents.markdown:
            scripts += (PAGE_ACTIONS_SCRIPT,)
        identity = self.standard.identity
        return dataclasses.replace(
            base,
            site_name=identity.name,
            lang=identity.language,
            stylesheets=tuple(sheets),
            scripts=scripts,
            head_html=base.head_html + head_html,
            asset_root="/",
            render_masthead=None,
            render_body=lambda context, parts: self._body(page, parts),
        )

    def _described(self, page: StandardPage) -> PageHead:
        """The page's head description after the site's ``page_head`` hook."""
        return self.hooks.page_head(page.head, page) if self.hooks.page_head is not None else page.head

    def _render(self, page: StandardPage) -> bytes:
        chrome = self._chrome(page)
        html_text = render_page(
            title=self._described(page).title, fragment="", active_href=page.path, nav_items=[], chrome=chrome, css_version=self.version
        )
        if self.hooks.page_finish is not None:
            html_text = self.hooks.page_finish(html_text, page)
        return html_text.encode("utf-8")

    def _body(self, page: StandardPage, parts: BodyParts) -> str:
        body = self._body_html(page, parts)
        islands = self.standard.islands
        if islands is not None and self._prerendered:
            body = blocks.fill_islands(body, self._prerendered)
        if islands is not None and 'data-island="' in body:
            suffix = f"?v={components.esc(self.version)}"
            body += (
                f'\n<script src="/{ISLANDS_RUNTIME_PATH}{suffix}"></script>'
                f'\n<script type="module" src="/{components.esc(islands.script)}{suffix}"></script>'
            )
        return body

    def _body_html(self, page: StandardPage, parts: BodyParts) -> str:
        if self.hooks.page_body is not None:
            custom = self.hooks.page_body(page)
            if custom is not None:
                return custom + parts.scripts
        identity = self.standard.identity
        masthead = (
            self.hooks.masthead(page)
            if self.hooks.masthead is not None
            else components.masthead(
                identity.name, self.standard.nav, page.path, tagline=identity.tagline,
                disclosure=self.standard.nav_disclosure, brand_html=self.standard.nav_brand_html,
            )
        )
        family = self.standard.footer_family
        footer_inner = (
            self.hooks.footer(page)
            if self.hooks.footer is not None
            else family_footer(family, identity.name, self.standard.footer_text, self.standard.footer_columns)
            if family is not None
            else (components.footer(self.standard.footer_columns, self.standard.footer_text) or self._settings.chrome.footer_html or f"<p>{components.esc(identity.name)}</p>")
        )
        main = "\n".join(part for part in (self._breadcrumbs_html(page), self._main_html(page)) if part)
        return (
            f"{components.skip_link()}\n{masthead}\n"
            f'  <main id="main">\n{main}\n  </main>\n'
            f'  <footer class="markus-site-footer">\n    {footer_inner}\n  </footer>{parts.scripts}'
        )

    def _breadcrumbs_html(self, page: StandardPage) -> str:
        return components.breadcrumbs(page.breadcrumbs) if page.kind == "item" else ""

    def _page_actions(self, page: StandardPage) -> str:
        """Copy / view / open-in actions on an article's page; only where the page has a Markdown twin."""
        settings = self.standard.page_actions
        entry = page.entry
        if not (settings.enabled and self.standard.agents.markdown) or entry is None or entry.noindex or not (entry.type in self.standard.listings.types or entry.type in (settings.types or ())):
            return ""
        twin = md_path(entry.key)
        if twin is None:
            return ""
        return render_page_actions(settings, markdown_path=twin, title=entry.title, canonical=entry.canonical or self.head.absolute(entry.url))

    def _grouped_html(self, page: StandardPage, view: ListingView, heading: str) -> str:
        groups = view.groups or ((view.group or "", heading, view.entries),)
        blocks = "".join(
            f'<section class="markus-group" aria-labelledby="group-{components.esc(key)}"><h2 id="group-{components.esc(key)}">{components.esc(label)}</h2>'
            f'<div class="markus-card-grid">{chr(10).join(self._card(entry, page) for entry in found)}</div></section>'
            for key, label, found in groups
        )
        pager = components.pager(view.page, view.pages, view.url_for_page) if view.pages > 1 else ""
        return f'<div class="markus-document"><h1>{components.esc(heading)}</h1>{blocks}{pager}</div>'

    def _card(self, entry: StandardEntry, page: StandardPage, variant: str | None = None, index: int = 0) -> str:
        """The site's ``card`` hook, given ``variant`` and ``index`` (the card's place in its list) when it takes them by name."""
        hook = self.hooks.card
        if hook is None:
            if variant is not None:
                raise ValueError(f"::include card={variant!r}: the site has no card hook")
            return components.card(entry, date_format=self.standard.identity.date_format)
        names = inspect.signature(hook).parameters
        keywords = {}
        if "variant" in names:
            keywords["variant"] = variant
        elif variant is not None:
            raise ValueError(f"::include card={variant!r}: the site's card hook takes no variant")
        if "index" in names:
            keywords["index"] = index
        return hook(entry, page, **keywords)

    # ------------------------------------------------------------------ authored pages and includes

    def _page_text(self, source: str, owner: str) -> str:
        if source not in self._page_text_cache:
            directory = self._static_directory
            path = (directory / source).resolve() if directory is not None else None
            if path is None or directory.resolve() not in path.parents or not path.is_file():
                raise ValueError(f"{owner}.source {source!r} is not a file inside the static directory")
            self._page_text_cache[source] = path.read_text(encoding="utf-8")
        return self._page_text_cache[source]

    def _page_includes(self, source: str, owner: str) -> tuple[str, list[dict]]:
        """The text of an authored page file and its validated ``::include`` attributes (a page's declared dependencies)."""
        text = blocks.substitute(self._page_text(source, owner), dict(self.standard.values), source)
        found = blocks.includes_in(text)
        for attributes in found:
            includes.check(attributes, self.standard, source)
        return text, found

    def _showcase_inputs(self, summaries, found: list[dict]) -> list:
        wall = self.standard.showcase
        if wall is None or not any(attributes.get("kind") == "showcase" for attributes in found):
            return []
        return [site.fingerprint() for site in showcase_sites(summaries, wall)]

    def _authored_fragment(self, source: str, owner: str, key: str, page: StandardPage) -> str:
        return self._fragment(
            self._page_text(source, owner), key.count("/"), source, trusted=True,
            include=lambda attributes: self._include(attributes, page, source),
        )

    def _custom_page(self, custom: CustomPage, head: PageHead, site: SiteIndex, listed) -> StandardPage:
        page = self._page("custom", head, site, entries=tuple(listed), custom_id=custom.id)
        if custom.source is None:
            return page
        return dataclasses.replace(page, fragment=self._authored_fragment(custom.source, f"pages.{custom.id}", self.policy.listing_key(custom.path), page))

    def _not_found_page(self, head: PageHead, site: SiteIndex, listed) -> StandardPage:
        page = self._page("not_found", head, site, entries=tuple(listed))
        source = self.standard.not_found.source
        if source is None:
            return page
        return dataclasses.replace(page, fragment=self._authored_fragment(source, "notFound", NOT_FOUND_KEY, page))

    def _include(self, attributes: dict, page: StandardPage, source: str) -> str:
        kind = includes.check(attributes, self.standard, source)
        if kind == "listing":
            chosen = includes.listing_entries(attributes, list(page.entries), self.standard)
            cards = [self._card(entry, page, attributes.get("card"), position) for position, entry in enumerate(chosen)]
            if "tag" in attributes:
                css = f' class="{components.esc(attributes["class"])}"' if "class" in attributes else ""
                return f'<{attributes["tag"]}{css}>' + "".join(cards) + f'</{attributes["tag"]}>' if cards else ""
            return "".join(cards) if attributes.get("layout") == "bare" else '<div class="markus-card-grid">' + "\n".join(cards) + "</div>"
        if kind == "showcase":
            wall = self.standard.showcase
            if wall is None:
                raise ValueError(f"{source}: ::include showcase needs a showcase in projection.json")
            return logo_wall(showcase_sites(page.summaries, wall), wall)
        if kind == "form":
            return render_form(next(spec for spec in self.standard.forms if spec.id == attributes["id"]))
        if self.hooks.block is None:
            raise ValueError(f"{source}: ::include block {attributes['name']!r}: the site has no block hook")
        passed = {key: value for key, value in attributes.items() if key not in ("kind", "name", "depends")}
        return self.hooks.block(attributes["name"], passed, page)

    def _main_html(self, page: StandardPage) -> str:
        identity = self.standard.identity
        if self.hooks.main is not None:
            custom = self.hooks.main(page)
            if custom is not None:
                return custom
        if page.kind == "item":
            entry = page.entry
            extras = []
            if entry is not None and self.standard.item_byline:
                extras.append(components.byline(entry, self.standard.identity.date_format))
            if entry is not None and entry.tags and self.standard.listings.tags:
                extras.append(components.tag_list(entry.tags, lambda tag: f"/{self.policy.tag_base(slugify_tag(tag))}/"))
            actions = self._page_actions(page)
            before, after = (actions, "") if self.standard.page_actions.placement == "header" else ("", actions)
            return before + page.fragment + after + ("\n" + "\n".join(extras) if extras else "")
        if page.kind in ("home", "custom") and page.fragment:
            return page.fragment
        if page.kind == "home":
            view = page.listing
            links = "".join(
                f'<li><a href="/{components.esc(base)}/">{components.esc(label)}</a></li>' for label, base in self._section_links()
            )
            more = (
                f'<ul class="markus-section-links">{links}</ul>'
                if links
                else (f'<p><a href="/{components.esc(self.standard.listings.flat_path)}/">All articles</a></p>' if page.entries and not self.standard.sectioned else "")
            )
            intro = f"<p>{components.esc(identity.description)}</p>" if identity.description else ""
            cards = "\n".join(self._card(entry, page) for entry in view.entries) if view else ""
            return f'<div class="markus-document"><h1>{components.esc(identity.name)}</h1>{intro}<div class="markus-card-grid">{cards}</div>{more}</div>'
        if page.kind == "archive":
            view = page.listing
            heading = f"{view.label}: {self._archive_label(view.group, self.standard.section(view.section).archive.by)}"
            return self._grouped_html(page, view, heading)
        if page.kind in ("listing", "tag"):
            view = page.listing
            if view.groups:
                return self._grouped_html(page, view, view.label)
            featured = "\n".join(self._card(entry, page) for entry in view.featured)
            rest = view.entries[len(view.featured):]
            grid = "\n".join(self._card(entry, page) for entry in rest)
            pager = components.pager(view.page, view.pages, view.url_for_page)
            heading = self.standard.listings.tag_title.format(tag=view.label) if page.kind == "tag" else view.label
            featured_html = f'<div class="markus-featured">{featured}</div>' if featured else ""
            if page.fragment:
                return with_listing(page.fragment, f'{featured_html}<div class="markus-card-grid">{grid}</div>{pager}')
            return f'<div class="markus-document"><h1>{components.esc(heading)}</h1>{featured_html}<div class="markus-card-grid">{grid}</div>{pager}</div>'
        if page.kind == "tags":
            items = "".join(
                f'<li><a href="/{components.esc(self.policy.tag_base(slugify_tag(tag)))}/">{components.esc(tag)}</a> ({len(found)})</li>'
                for tag, found in page.tags.items()
            )
            return f'<div class="markus-document"><h1>Tags</h1><ul class="markus-tag-cloud">{items}</ul></div>'
        if page.kind == "showcase":
            wall = self.standard.showcase
            intro = f"<p>{components.esc(wall.description)}</p>" if wall.description else ""
            return f'<div class="markus-document"><h1>{components.esc(wall.title)}</h1>{intro}{logo_wall(page.showcase, wall)}</div>'
        if page.kind == "not_found" and page.fragment:
            return page.fragment
        if page.kind == "not_found":
            return (
                '<div class="markus-document"><h1>Page not found</h1>'
                "<p>That page is not here. It may have moved, or the address may be mistyped.</p>"
                '<p><a href="/">Back to the home page</a></p></div>'
            )
        form = next((spec for spec in self.standard.forms if page.kind == "custom" and spec.id == self._custom_form(page)), None)
        return (
            f'<div class="markus-document"><h1>{components.esc(page.title)}</h1>'
            + (f"<p>{components.esc(page.description)}</p>" if page.description else "")
            + (render_form(form) if form is not None else "")
            + "</div>"
        )

    def _custom_form(self, page: StandardPage) -> str | None:
        custom = next((c for c in self.standard.pages if c.id == page.custom_id), None)
        return custom.form if custom is not None else None
