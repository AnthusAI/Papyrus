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
import json
import math
import re
from collections.abc import Callable, Collection
from pathlib import Path, PurePosixPath

from ...markus_renderer.shell import BodyParts, PageContext, SiteChrome, render_page

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
from ..public_data import entry_for, hidden_from_public_data, owns_public_data_key, public_data_files, public_data_inputs, public_static_files
from ..writers import request_paths_for_key
from . import components
from .config import STANDARD_KEYS, StandardSettings, standard_settings_from_mapping
from .entries import StandardEntry, build_entries, entry_for_summary, entry_title, newest_first
from .environment import SiteEnvironment, resolve_environment
from .feeds import feed_files, feed_selection
from .head import HeadBuilder, PageHead
from .fragments import first_image_of, lede_of
from .hooks import NO_HOOKS, Hooks, load_hooks
from .page import ListingView, StandardPage
from .showcase import logo_wall, showcase_sites
from .sitemap import SITEMAP_KEYS, SitemapUrl, robots_text, sitemap_files
from .urls import NOT_FOUND_KEY, UrlPolicy, slugify_tag

COMPONENTS_CSS_PATH = "css/markus-components.css"
NAV_SCRIPT_PATH = "_plugins/papyrus-nav-v1.js"
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
        if standard.components_css:
            files[COMPONENTS_CSS_PATH] = (ASSET_DIRECTORY / "markus-components.css").read_bytes()
        if standard.nav_disclosure:
            files[NAV_SCRIPT_PATH] = (ASSET_DIRECTORY / "papyrus-nav.js").read_bytes()
        super().__init__(settings, files, **kwargs)
        self.standard = standard
        self.hooks = hooks
        self.environment = environment or resolve_environment(standard)
        self.policy = UrlPolicy(standard)
        self.head = HeadBuilder(standard, self.environment)
        self._plan_cache: tuple[object, dict] | None = None
        self._shared_fingerprint = digest_of(
            [dataclasses.asdict(standard), self.environment.fingerprint(), repr(settings.chrome), hooks.fingerprint, self.version]
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
            hooks=load_hooks(static_directory, standard.hooks_path),
            environment=resolve_environment(standard, environ),
            renditions=renditions,
        )

    # ------------------------------------------------------------------ model

    def _entries(self, site: SiteIndex) -> list[StandardEntry]:
        return newest_first(build_entries(site.items, self.standard, self.policy))

    @staticmethod
    def _authored_home(site: SiteIndex) -> bool:
        return any(MarkusSiteProjector._is_home_source(summary) and not PurePosixPath(summary.output_path).name.startswith(("_", ".")) for summary in site.items)

    def _full(self) -> bool:
        return self.hooks.renders_listings

    def _fingerprints(self, entries, *, full: bool | None = None) -> list:
        return [entry.fingerprint(full=self._full() if full is None else full) for entry in entries]

    # ------------------------------------------------------------------ item pages

    def item_page_paths(self, summary: ItemSummary) -> tuple[str, ...]:
        if PurePosixPath(summary.output_path).name.startswith(("_", ".")):
            return ()
        if self._is_home_source(summary):
            return (HOME_PAGE_PATH,)
        entry = entry_for_summary(summary, self.standard, self.policy)
        return (entry.key,) if entry is not None and entry.key else ()

    def item_pages(self, item: ProjectedItem, site: SiteIndex) -> dict[str, bytes]:
        summary = item.summary
        paths = self.item_page_paths(summary)
        if not paths:
            return {}
        key = paths[0]
        fragment = self._fragment(item.source_text, key.count("/"))
        if self.hooks.item_decorator is not None:
            fragment = self.hooks.item_decorator(fragment, summary)
        entries = tuple(self._entries(site)) if self._depends_on_entries() else ()
        if self._is_home_source(summary):
            title = entry_title(summary) if summary.front_matter.get("title") else (summary.page_title or summary.title or self.standard.identity.name)
            head = PageHead(
                title=title,
                path="/",
                description=lede_of(fragment) or self.standard.identity.description,
                image=first_image_of(fragment),
            )
            page = self._page("home", head, site, entries=entries, fragment=fragment)
            return {key: self._render(page)}
        entry = entry_for_summary(summary, self.standard, self.policy)
        description = entry.summary_text or lede_of(fragment) or self.standard.identity.description
        article = entry.type in self.standard.listings.types
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
            json_ld_type=self._json_ld_type(entry) if article else None,
            breadcrumbs=crumbs,
        )
        page = self._page("item", head, site, entry=entry, entries=entries, fragment=fragment, crumbs=crumbs)
        return {key: self._render(page)}

    def _json_ld_type(self, entry: StandardEntry) -> str:
        mapping = dict(self.standard.seo.json_ld_types)
        section = entry.section.name if entry.section else None
        return mapping.get(section) or mapping.get(entry.type) or self.standard.seo.default_json_ld

    def _breadcrumbs(self, entry: StandardEntry) -> tuple[tuple[str, str], ...]:
        if not self.standard.breadcrumbs:
            return ()
        crumbs = [(self.standard.home_link_label, "/")]
        if entry.section is not None and entry.section.listing:
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

    def shared_inputs(self, site: SiteIndex) -> str:
        entries = self._entries(site) if self._depends_on_entries() else []
        return digest_of([self._shared_fingerprint, self._dependency_digest(entries), self._authored_home(site)])

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

        def add(key: str, page_id: str, digest_input, build_page: Callable[[], StandardPage]) -> None:
            dependency = self._dependency_digest(entries, page_id)
            plan[key] = (digest_of([shared, key, digest_input, dependency]), lambda: self._render(build_page()))

        # home
        if not self._authored_home(site):
            home_entries = tuple(listed[: self.standard.listings.home_count])
            add(
                HOME_PAGE_PATH,
                "home",
                [self._fingerprints(home_entries), self._section_links()],
                lambda: self._page(
                    "home",
                    PageHead(title=self.standard.identity.name, path="/", description=self.standard.identity.description),
                    site, entries=tuple(listed), listing=ListingView("", self.standard.home_link_label, home_entries, tuple(listed), 1, 1),
                ),
            )

        # listings: one flat listing, or one per section that has something to list
        for base, label, section_name, members in self._listing_groups(listed):
            for view in self._paginate(base, label, members, section_name):
                key = self.policy.listing_key(base, view.page)
                add(key, f"listing:{section_name or 'flat'}", [self._fingerprints(view.entries), view.page, view.pages, len(view.featured)], self._listing_builder("listing", view, site, listed))

        # tags
        tags = self._tag_map(listed)
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

        # custom pages
        for custom in self.standard.pages:
            selected = [entry for entry in entries if "*" in custom.depends_on or (entry.section and entry.section.name in custom.depends_on)]
            add(
                self.policy.listing_key(custom.path),
                f"custom:{custom.id}",
                [self._fingerprints(selected, full=True) if self.hooks.page_body else []],
                lambda custom=custom: self._page(
                    "custom",
                    PageHead(title=custom.title, path=f"/{custom.path}/", description=custom.description or self.standard.identity.description, noindex=custom.noindex),
                    site, entries=tuple(listed), custom_id=custom.id,
                ),
            )

        # 404
        add(
            NOT_FOUND_KEY,
            "not_found",
            [],
            lambda: self._page("not_found", PageHead(title="Page not found", path="/404.html", description="", noindex=True), site, entries=tuple(listed)),
        )

        # sitemap, feeds
        sitemap = sitemap_files(self.standard.sitemap_style, self.environment, self._sitemap_urls(site, entries, listed, plan), lastmod=self.standard.sitemap_lastmod)
        selection = feed_selection(entries, self.standard)
        for key, body in {**sitemap, **feed_files(selection, self.standard, self.environment)}.items():
            plan[key] = (hashlib.sha256(body).hexdigest()[:16], lambda body=body: body)
        self._plan_cache = (site.items, plan)
        return plan

    def _section_links(self) -> list:
        return [(section.label, section.base) for section in self.standard.sections if section.listing]

    def _listing_groups(self, listed: list[StandardEntry]):
        if not self.standard.sectioned:
            if listed:
                yield self.standard.listings.flat_path, "Archive", None, listed
            return
        for section in self.standard.sections:
            if not section.listing:
                continue
            members = [entry for entry in listed if entry.section and entry.section.name == section.name]
            if members or section.list_empty:
                yield section.base, section.label, section.name, members

    def _paginate(self, base: str, label: str, members: list[StandardEntry], section: str | None, *, tag: str | None = None):
        settings = self.standard.listings
        configured = self.standard.section(section)
        size = configured.page_size if configured is not None and configured.page_size else settings.page_size
        first = settings.featured_count + size
        remaining = max(0, len(members) - first)
        pages = 1 + math.ceil(remaining / size)
        for number in range(1, pages + 1):
            if number == 1:
                shown = members[:first]
                featured = tuple(shown[: settings.featured_count])
            else:
                start = first + (number - 2) * size
                shown = members[start : start + size]
                featured = ()
            yield ListingView(base, label, tuple(shown), tuple(members), number, pages, featured, section, tag)

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

    def _listing_builder(self, kind: str, view: ListingView, site: SiteIndex, listed: list[StandardEntry]):
        def build() -> StandardPage:
            suffix = f" — page {view.page}" if view.page > 1 else ""
            title = (f"Tagged {view.label}" if kind == "tag" else view.label) + suffix
            configured = self.standard.section(view.section)
            head = PageHead(
                title=title,
                path=view.url_for_page(view.page),
                description=(configured.description if configured is not None else "") or self.standard.identity.description,
            )
            return self._page(kind, head, site, entries=tuple(listed), listing=view)

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
        if self.standard.sitemap_tags and self.standard.listings.tags:
            tags = self._tag_map(listed)
            if tags:
                urls.append(SitemapUrl(f"/{self.policy.tag_base()}/", ""))
                urls.extend(SitemapUrl(f"/{self.policy.tag_base(slugify_tag(tag))}/", max(entry.updated for entry in found)) for tag, found in tags.items() if slugify_tag(tag))
        if self.standard.showcase is not None:
            urls.append(SitemapUrl(f"/{self.standard.showcase.path}/", ""))
        for custom in self.standard.pages:
            if custom.sitemap and not custom.noindex:
                urls.append(SitemapUrl(f"/{custom.path}/", ""))
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
        if key == HOME_PAGE_PATH or key in SITEMAP_KEYS or key in (self.standard.feeds.rss_path, self.standard.feeds.atom_path):
            return True
        if owns_public_data_key(key):
            return True
        return key.endswith(".html") and not key.startswith(("css/", "assets/", "_"))

    def static_files(self) -> dict[str, bytes]:
        files = {**self._static_files, **public_static_files(self._settings.public_data), **plugin_static_files(self._settings.plugins)}
        files["robots.txt"] = robots_text(self.standard.sitemap_style, self.environment, self.standard.robots_extra).encode("utf-8")
        return files

    def redirects(self, site: SiteIndex) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for summary in site.items:
            paths = self.item_page_paths(summary)
            for alias in summary.aliases if paths else ():
                source = alias if alias.startswith("/") else "/" + alias
                mapping[source] = request_paths_for_key(paths[0])[0]
        for source, target in self.standard.exact_redirects:
            mapping[source] = target
        live = {path for key in self._plan(site) for path in request_paths_for_key(key)}
        live |= {path for summary in site.items for key in self.item_page_paths(summary) for path in request_paths_for_key(key)}
        return {source: target for source, target in mapping.items() if source not in live and source != target}

    # ------------------------------------------------------------------ rendering

    def _page(self, kind: str, head: PageHead, site: SiteIndex, *, entries=(), **extra) -> StandardPage:
        crumbs = extra.pop("crumbs", ())
        return StandardPage(
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
            **extra,
        )

    def _chrome(self, page: StandardPage) -> SiteChrome:
        base = self._settings.chrome
        extra = self.hooks.head_extra(page) if self.hooks.head_extra is not None else ""
        head_html = self.head.build(dataclasses.replace(page.head, extra=extra))
        sheets = list(base.stylesheets)
        if self.standard.components_css and COMPONENTS_CSS_PATH not in sheets:
            sheets.insert(1 if sheets and sheets[0] == "css/markus-vendor.css" else 0, COMPONENTS_CSS_PATH)
        scripts = tuple(base.scripts) + ((NAV_SCRIPT_PATH,) if self.standard.nav_disclosure else ())
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

    def _render(self, page: StandardPage) -> bytes:
        chrome = self._chrome(page)
        html_text = render_page(
            title=page.title, fragment="", active_href=page.path, nav_items=[], chrome=chrome, css_version=self.version
        )
        return html_text.encode("utf-8")

    def _body(self, page: StandardPage, parts: BodyParts) -> str:
        if self.hooks.page_body is not None:
            custom = self.hooks.page_body(page)
            if custom is not None:
                return custom + parts.scripts
        identity = self.standard.identity
        masthead = (
            self.hooks.masthead(page)
            if self.hooks.masthead is not None
            else components.masthead(identity.name, self.standard.nav, page.path, tagline=identity.tagline, disclosure=self.standard.nav_disclosure)
        )
        footer_inner = (
            self.hooks.footer(page)
            if self.hooks.footer is not None
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

    def _card(self, entry: StandardEntry, page: StandardPage) -> str:
        return self.hooks.card(entry, page) if self.hooks.card is not None else components.card(entry)

    def _main_html(self, page: StandardPage) -> str:
        identity = self.standard.identity
        if page.kind == "item":
            entry = page.entry
            extras = []
            if entry is not None and self.standard.item_byline:
                extras.append(components.byline(entry))
            if entry is not None and entry.tags and self.standard.listings.tags:
                extras.append(components.tag_list(entry.tags, lambda tag: f"/{self.policy.tag_base(slugify_tag(tag))}/"))
            return page.fragment + ("\n" + "\n".join(extras) if extras else "")
        if page.kind == "home" and page.fragment:
            return page.fragment
        if page.kind == "home":
            view = page.listing
            links = "".join(
                f'<li><a href="/{components.esc(base)}/">{components.esc(label)}</a></li>' for label, base in self._section_links()
            )
            more = (
                f'<ul class="markus-section-links">{links}</ul>'
                if links
                else (f'<p><a href="/{components.esc(self.standard.listings.flat_path)}/">All articles</a></p>' if page.entries else "")
            )
            intro = f"<p>{components.esc(identity.description)}</p>" if identity.description else ""
            cards = "\n".join(self._card(entry, page) for entry in view.entries) if view else ""
            return f'<div class="markus-document"><h1>{components.esc(identity.name)}</h1>{intro}<div class="markus-card-grid">{cards}</div>{more}</div>'
        if page.kind in ("listing", "tag"):
            view = page.listing
            featured = "\n".join(self._card(entry, page) for entry in view.featured)
            rest = view.entries[len(view.featured):]
            grid = "\n".join(self._card(entry, page) for entry in rest)
            pager = components.pager(view.page, view.pages, view.url_for_page)
            heading = f"Tagged {view.label}" if page.kind == "tag" else view.label
            featured_html = f'<div class="markus-featured">{featured}</div>' if featured else ""
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
        if page.kind == "not_found":
            return (
                '<div class="markus-document"><h1>Page not found</h1>'
                "<p>That page is not here. It may have moved, or the address may be mistyped.</p>"
                '<p><a href="/">Back to the home page</a></p></div>'
            )
        return f'<div class="markus-document"><h1>{components.esc(page.title)}</h1>' + (f"<p>{components.esc(page.description)}</p>" if page.description else "") + "</div>"
