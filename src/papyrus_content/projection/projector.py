"""The site projector contract and the default Markus projector."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from ..markus_renderer.build import DEFAULT_THEME, render_fragment_text
from ..markus_renderer.citations import CitationRendering
from ..markus_renderer.convert import convert_text_in_process
from ..markus_renderer.pages import (
    ARTICLES_INDEX_SLUG,
    ARTICLES_SECTION,
    build_nav_items,
    generated_home_fragment,
    read_title,
    render_content_page,
    render_home_page,
    title_from_slug,
    version_token,
)
from ..markus_renderer.shell import DEFAULT_CHROME, SiteChrome
from ..markus_renderer.vendor_css import vendor_markus_css_text
from .model import ItemChange, ItemSummary, ProjectedItem, SiteIndex

HOME_PAGE_PATH = "index.html"
PROJECTION_SETTINGS_FILE = "projection.json"
SITE_THEME_PATH = "css/site-theme.css"
VENDOR_CSS_PATH = "css/markus-vendor.css"
ASSETS_DIRECTORY = "assets"
PLACEHOLDER_SITE_THEME = "/* Site theme layer — unlayered so it wins over @layer markus */\n"
CHROME_FIELD_NAMES = {field.name for field in dataclasses.fields(SiteChrome)} - {"render_masthead", "render_body"}


class SiteProjector(Protocol):
    def item_page_paths(self, summary: ItemSummary) -> tuple[str, ...]: ...

    def item_pages(self, item: ProjectedItem, site: SiteIndex) -> dict[str, bytes]: ...

    def dependent_pages(self, change: ItemChange, site: SiteIndex) -> dict[str, bytes]: ...

    def listing_pages(self, site: SiteIndex) -> dict[str, bytes]: ...

    def static_files(self) -> dict[str, bytes]: ...

    def redirects(self, site: SiteIndex) -> dict[str, str]: ...


@dataclass(frozen=True)
class MarkusProjectorSettings:
    theme: str | None = DEFAULT_THEME
    sections: tuple[str, ...] = ()
    citations: bool = False
    chrome: SiteChrome = DEFAULT_CHROME


def settings_from_mapping(raw: dict) -> MarkusProjectorSettings:
    unknown = set(raw) - {"theme", "sections", "citations", "chrome"}
    if unknown:
        raise ValueError(f"Unknown projection settings: {', '.join(sorted(unknown))}")
    chrome_raw = dict(raw.get("chrome") or {})
    unknown_chrome = set(chrome_raw) - CHROME_FIELD_NAMES
    if unknown_chrome:
        raise ValueError(f"Unknown chrome settings: {', '.join(sorted(unknown_chrome))}")
    for list_field in ("scripts", "stylesheets"):
        if list_field in chrome_raw:
            chrome_raw[list_field] = tuple(chrome_raw[list_field])
    return MarkusProjectorSettings(
        theme=raw["theme"] if "theme" in raw else DEFAULT_THEME,
        sections=tuple(raw.get("sections") or ()),
        citations=bool(raw.get("citations", False)),
        chrome=SiteChrome(**chrome_raw),
    )


def read_static_files(static_directory: Path | None, theme: str | None) -> dict[str, bytes]:
    files: dict[str, bytes] = {VENDOR_CSS_PATH: vendor_markus_css_text(theme=theme).encode("utf-8")}
    site_theme = static_directory / SITE_THEME_PATH if static_directory is not None else None
    files[SITE_THEME_PATH] = (
        site_theme.read_bytes()
        if site_theme is not None and site_theme.is_file()
        else PLACEHOLDER_SITE_THEME.encode("utf-8")
    )
    assets = static_directory / ASSETS_DIRECTORY if static_directory is not None else None
    if assets is not None and assets.is_dir():
        for path in sorted(assets.rglob("*")):
            if path.is_file():
                files[f"{ASSETS_DIRECTORY}/{path.relative_to(assets).as_posix()}"] = path.read_bytes()
    return files


def static_version(static_files: dict[str, bytes]) -> str:
    stylesheets = [
        (PurePosixPath(path).name, content)
        for path, content in static_files.items()
        if PurePosixPath(path).parent == PurePosixPath("css") and path.endswith(".css")
    ]
    assets = [
        (path[len(ASSETS_DIRECTORY) + 1 :], content)
        for path, content in static_files.items()
        if path.startswith(ASSETS_DIRECTORY + "/")
    ]
    return version_token(stylesheets, assets)


def normalized_redirect_source(alias: str) -> str:
    return alias if alias.startswith("/") else "/" + alias


class MarkusSiteProjector:
    """Projects a Markus site laid out like ``build_markus_site``: articles, sections, a home page."""

    def __init__(
        self,
        settings: MarkusProjectorSettings,
        static_files: dict[str, bytes],
        *,
        convert_text: Callable[[str], str] | None = None,
    ) -> None:
        self._settings = settings
        self._static_files = dict(static_files)
        self.version = static_version(self._static_files)
        self._convert_text = convert_text or (lambda text: convert_text_in_process(text, theme=settings.theme))
        self._citations = CitationRendering() if settings.citations else None

    @classmethod
    def from_static_directory(cls, static_directory: Path | None) -> "MarkusSiteProjector":
        settings_path = static_directory / PROJECTION_SETTINGS_FILE if static_directory is not None else None
        raw = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path and settings_path.is_file() else {}
        settings = settings_from_mapping(raw)
        return cls(settings, read_static_files(static_directory, settings.theme))

    def _content_sections(self) -> tuple[str, ...]:
        return (ARTICLES_SECTION, *self._settings.sections)

    def _is_page_source(self, summary: ItemSummary) -> bool:
        if PurePosixPath(summary.output_path).name.startswith(("_", ".")):
            return False
        if summary.section is None:
            return summary.slug == ARTICLES_INDEX_SLUG
        return summary.section in self._content_sections()

    @staticmethod
    def _is_home_source(summary: ItemSummary) -> bool:
        return summary.section is None and summary.slug == ARTICLES_INDEX_SLUG

    @staticmethod
    def _articles(site: SiteIndex) -> list[ItemSummary]:
        articles = [summary for summary in site.items if summary.section == ARTICLES_SECTION]
        return sorted(articles, key=lambda summary: PurePosixPath(summary.output_path).name)

    def _nav_items(self, site: SiteIndex):
        return build_nav_items([(summary.slug, summary.page_title) for summary in self._articles(site)])

    def _fragment(self, text: str, depth: int) -> str:
        return render_fragment_text(
            text, convert=self._convert_text, depth=depth, citations=self._citations
        )

    def item_page_paths(self, summary: ItemSummary) -> tuple[str, ...]:
        if not self._is_page_source(summary):
            return ()
        if self._is_home_source(summary):
            return (HOME_PAGE_PATH,)
        return (f"{summary.section}/{summary.slug}.html",)

    def item_pages(self, item: ProjectedItem, site: SiteIndex) -> dict[str, bytes]:
        summary = item.summary
        if not self._is_page_source(summary):
            return {}
        nav_items = self._nav_items(site)
        chrome = self._settings.chrome
        if self._is_home_source(summary):
            page_html = render_home_page(
                fragment=self._fragment(item.source_text, 0),
                title=read_title(item.source_text, "Home"),
                nav_items=nav_items,
                chrome=chrome,
                css_version=self.version,
            )
            return {HOME_PAGE_PATH: page_html.encode("utf-8")}
        href, page_html = render_content_page(
            section=summary.section,
            slug=summary.slug,
            text=item.source_text,
            fragment=self._fragment(item.source_text, 1),
            nav_items=nav_items,
            chrome=chrome,
            css_version=self.version,
        )
        return {href: page_html.encode("utf-8")}

    def listing_pages(self, site: SiteIndex) -> dict[str, bytes]:
        if any(self._is_home_source(summary) for summary in site.items):
            return {}
        articles = [
            (summary.slug, summary.page_title or title_from_slug(summary.slug))
            for summary in self._articles(site)
            if self._is_page_source(summary)
        ]
        page_html = render_home_page(
            fragment=generated_home_fragment(articles),
            title="Home",
            nav_items=self._nav_items(site),
            chrome=self._settings.chrome,
            css_version=self.version,
        )
        return {HOME_PAGE_PATH: page_html.encode("utf-8")}

    def dependent_pages(self, change: ItemChange, site: SiteIndex) -> dict[str, bytes]:
        pages = dict(self.listing_pages(site))
        if not self._navigation_may_have_changed(change, site):
            return pages
        for summary in site.items:
            if summary.item_id == change.summary.item_id or not self._is_page_source(summary):
                continue
            pages.update(self.item_pages(site.load_item(summary.item_id), site))
        return pages

    def _navigation_may_have_changed(self, change: ItemChange, site: SiteIndex) -> bool:
        if change.summary.section != ARTICLES_SECTION:
            return False
        if change.summary.slug == ARTICLES_INDEX_SLUG:
            return True
        return not any(
            summary.slug == ARTICLES_INDEX_SLUG for summary in site.items if summary.section == ARTICLES_SECTION
        )

    def static_files(self) -> dict[str, bytes]:
        return dict(self._static_files)

    def redirects(self, site: SiteIndex) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for summary in site.items:
            paths = self.item_page_paths(summary)
            if not paths:
                continue
            for alias in summary.aliases:
                mapping[normalized_redirect_source(alias)] = "/" + paths[0]
        return mapping
