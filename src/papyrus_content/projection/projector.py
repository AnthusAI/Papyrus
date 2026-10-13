"""The site projector contract and the default Markus projector."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from ..markus_renderer.build import DEFAULT_THEME, render_fragment_text
from ..markus_renderer.citations import CitationRendering
from ..markus_renderer.content_markup import prepare_page
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
from ..renditions import (
    IMAGES_SETTINGS_KEY,
    RenditionCatalog,
    RenditionSettings,
    RenditionStore,
    StoredRenditionImageBuilder,
    settings_from_mapping as image_settings_from_mapping,
)
from .model import ItemSummary, ProjectedItem, SiteIndex
from .plugins import plugin_static_files
from .public_data import (
    PUBLIC_DATA_SETTINGS_KEY,
    PublicDataSettings,
    entry_for,
    hidden_from_public_data,
    owns_public_data_key,
    public_data_files,
    public_data_inputs,
    public_data_settings_from_mapping,
    public_static_files,
)
from .writers import request_paths_for_key

HOME_PAGE_PATH = "index.html"
PROJECTION_SETTINGS_FILE = "projection.json"
SITE_THEME_PATH = "css/site-theme.css"
VENDOR_CSS_PATH = "css/markus-vendor.css"
ASSETS_DIRECTORY = "assets"
PLACEHOLDER_SITE_THEME = "/* Site theme layer — unlayered so it wins over @layer markus */\n"
CHROME_FIELD_NAMES = {field.name for field in dataclasses.fields(SiteChrome)} - {"render_masthead", "render_body"}


class SiteProjector(Protocol):
    """What a site supplies to the projection engine.

    ``listing_inputs`` is the dependency rule of every page that is not an item
    page: for each such page it names the page and a digest of everything the
    page renders from (which items it lists, in which order, with which fields).
    The engine re-renders a page exactly when its digest differs between the
    site before a change and the site after it. ``shared_inputs`` is the same
    for what every item page depends on (navigation, the URL map).
    """

    def item_page_paths(self, summary: ItemSummary) -> tuple[str, ...]: ...

    def item_pages(self, item: ProjectedItem, site: SiteIndex) -> dict[str, bytes]: ...

    def listing_inputs(self, site: SiteIndex) -> dict[str, str]: ...

    def listing_pages(self, site: SiteIndex, keys: Collection[str] | None = None) -> dict[str, bytes]: ...

    def shared_inputs(self, site: SiteIndex) -> str: ...

    def owns_page_key(self, key: str) -> bool: ...

    def static_files(self) -> dict[str, bytes]: ...

    def redirects(self, site: SiteIndex) -> dict[str, str]: ...


def digest_of(value) -> str:
    """A short stable digest of JSON-able data; the unit of every ``listing_inputs`` value."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class MarkusProjectorSettings:
    theme: str | None = DEFAULT_THEME
    sections: tuple[str, ...] = ()
    citations: bool = False
    chrome: SiteChrome = DEFAULT_CHROME
    images: RenditionSettings | None = None
    public_data: PublicDataSettings | None = None
    plugins: tuple[str, ...] = ()


def settings_from_mapping(raw: dict) -> MarkusProjectorSettings:
    unknown = set(raw) - {"theme", "sections", "citations", "chrome", IMAGES_SETTINGS_KEY, PUBLIC_DATA_SETTINGS_KEY}
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
        images=image_settings_from_mapping(raw[IMAGES_SETTINGS_KEY]) if IMAGES_SETTINGS_KEY in raw else None,
        public_data=public_data_settings_from_mapping(raw[PUBLIC_DATA_SETTINGS_KEY]) if PUBLIC_DATA_SETTINGS_KEY in raw else None,
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
        renditions: RenditionStore | None = None,
    ) -> None:
        self._settings = settings
        self._static_files = dict(static_files)
        self.version = static_version(self._static_files)
        self._convert_text = convert_text or (lambda text: convert_text_in_process(text, theme=settings.theme))
        self._citations = CitationRendering() if settings.citations else None
        self._renditions = renditions

    @classmethod
    def from_static_directory(
        cls,
        static_directory: Path | None,
        *,
        renditions: RenditionStore | None = None,
        plugins: tuple[str, ...] = (),
    ) -> "MarkusSiteProjector":
        settings_path = static_directory / PROJECTION_SETTINGS_FILE if static_directory is not None else None
        raw = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path and settings_path.is_file() else {}
        settings = dataclasses.replace(settings_from_mapping(raw), plugins=plugins)
        return cls(settings, read_static_files(static_directory, settings.theme), renditions=renditions)

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

    def _image_builder(self, text: str) -> StoredRenditionImageBuilder | None:
        images = self._settings.images
        if images is None:
            return None
        if self._renditions is None:
            raise ValueError("This site configures images but the projector has no rendition store.")
        catalog = RenditionCatalog(self._renditions, images.pipeline)
        catalog.prefetch(request.src for request in prepare_page(text, images=images.pipeline, citations=None).images.values())
        return StoredRenditionImageBuilder(images.pipeline, catalog)

    def _fragment(self, text: str, depth: int) -> str:
        images = self._settings.images
        return render_fragment_text(
            text,
            convert=self._convert_text,
            depth=depth,
            images=images.pipeline if images is not None else None,
            image_builder=self._image_builder(text),
            citations=self._citations,
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

    def _generated_home(self, site: SiteIndex) -> bool:
        return not any(self._is_home_source(summary) for summary in site.items)

    def _listed_articles(self, site: SiteIndex) -> list[tuple[str, str]]:
        return [
            (summary.slug, summary.page_title or title_from_slug(summary.slug))
            for summary in self._articles(site)
            if self._is_page_source(summary)
        ]

    def public_data_entries(self, site: SiteIndex):
        settings = self._settings.public_data
        if settings is None:
            return []
        return [
            entry_for(summary, paths[0], settings)
            for summary in site.items
            if (paths := self.item_page_paths(summary)) and not self._is_home_source(summary) and not hidden_from_public_data(summary)
        ]

    def public_data_inputs(self, site: SiteIndex) -> dict[str, str]:
        settings = self._settings.public_data
        return {} if settings is None else public_data_inputs(self.public_data_entries(site), settings)

    def public_data_pages(self, site: SiteIndex, keys: Collection[str] | None = None) -> dict[str, bytes]:
        settings = self._settings.public_data
        if settings is None:
            return {}
        files = public_data_files(self.public_data_entries(site), settings)
        return files if keys is None else {key: body for key, body in files.items() if key in keys}

    def listing_inputs(self, site: SiteIndex) -> dict[str, str]:
        inputs = self.public_data_inputs(site)
        if self._generated_home(site):
            inputs[HOME_PAGE_PATH] = digest_of([self._listed_articles(site), self.shared_inputs(site)])
        return inputs

    def listing_pages(self, site: SiteIndex, keys: Collection[str] | None = None) -> dict[str, bytes]:
        pages = self.public_data_pages(site, keys)
        if not self._generated_home(site) or (keys is not None and HOME_PAGE_PATH not in keys):
            return pages
        page_html = render_home_page(
            fragment=generated_home_fragment(self._listed_articles(site)),
            title="Home",
            nav_items=self._nav_items(site),
            chrome=self._settings.chrome,
            css_version=self.version,
        )
        pages[HOME_PAGE_PATH] = page_html.encode("utf-8")
        return pages

    def shared_inputs(self, site: SiteIndex) -> str:
        return digest_of([[item.label, item.href] for item in self._nav_items(site)])

    def owns_page_key(self, key: str) -> bool:
        if key == HOME_PAGE_PATH or owns_public_data_key(key):
            return True
        return key.endswith(".html") and key.split("/", 1)[0] in self._content_sections()

    def static_files(self) -> dict[str, bytes]:
        return {**self._static_files, **public_static_files(self._settings.public_data), **plugin_static_files(self._settings.plugins)}

    def redirects(self, site: SiteIndex) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for summary in site.items:
            paths = self.item_page_paths(summary)
            if not paths:
                continue
            for alias in summary.aliases:
                mapping[normalized_redirect_source(alias)] = request_paths_for_key(paths[0])[0]
        return mapping
