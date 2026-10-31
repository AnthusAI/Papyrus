"""``projection.json`` settings of the standard Markus front end.

A site opts in by having a top-level ``site`` object. Everything else here is
optional with a working default, so the smallest standard site is::

    {"site": {"name": "Example"}}

and it is a site without sections: articles live at the root, one flat listing
holds them all. Unknown keys are rejected so a typo never silently does nothing.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from ...home_page.settings import HomePageSettings, home_page_settings_from_mapping
from .grouping import valid_group_by
from .redirects import RedirectRule, rule_from_mapping
from .select import Selection, selection_from_mapping

STANDARD_KEYS = (
    "site", "urls", "nav", "footer", "seo", "sitemap", "robots", "feeds", "listings",
    "fonts", "icons", "environment", "hooks", "redirects", "pages", "components", "media", "showcase", "static", "forms", "agents", "pageActions",
    "values", "islands", "collections", "notFound", "wiki", "mermaid", "homePage",
)
URL_STYLES = ("html", "directory", "clean")
SITEMAP_STYLES = ("single", "index")
FEED_FORMATS = ("rss", "atom")
SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_/]*$")


def _only(mapping: Mapping, allowed: tuple[str, ...] | set[str], where: str) -> None:
    unknown = set(mapping) - set(allowed)
    if unknown:
        raise ValueError(f"Unknown {where} settings: {', '.join(sorted(unknown))}")


def _text(mapping: Mapping, name: str, default: str = "") -> str:
    value = mapping.get(name, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value.strip()


def _path_segment(value: str, where: str) -> str:
    value = value.strip("/")
    if value and not SLUG_PATTERN.match(value):
        raise ValueError(f"{where} must be a lowercase path such as 'commentary', got {value!r}")
    return value


RESERVED_PATH_PREFIXES = ("_data", "_plugins", "_papyrus", "_next", "api")


def _unreserved_segment(value: str, where: str) -> str:
    """A page path or listing base that is not one of the paths the platform serves itself.

    ``newsroom`` is also reserved on a site whose edge routes the CMS (``/newsroom*``); projection cannot see the edge, so it names the
    segment in the message and refuses only the prefixes it knows."""
    if str(value).strip("/") in RESERVED_PATH_PREFIXES:
        raise ValueError(
            f"{where} {str(value).strip('/')!r} is reserved: the platform serves {', '.join(RESERVED_PATH_PREFIXES)} itself "
            "(and 'newsroom' is reserved on sites whose edge routes the CMS); choose another path"
        )
    return _path_segment(value, where)


@dataclass(frozen=True)
class SiteIdentity:
    name: str
    short_name: str = ""
    publisher: str = ""
    tagline: str = ""
    description: str = ""
    language: str = "en"
    production_url: str | None = None
    author: str = ""
    date_format: str = ""             # strftime pattern for the dates the core components print ("%B %d, %Y"); empty: ISO dates
    lede_field: str = ""              # front matter field whose text is printed as the article's lede (standfirst) under its title


@dataclass(frozen=True)
class ArchiveConfig:
    """One listing page per month (or year) that has entries: ``<section base>/<archive base>/<YYYY-MM>/``."""

    by: str = "month"
    base: str = "archive"
    description: str = ""


@dataclass(frozen=True)
class SectionConfig:
    """One section; a site that declares none is a site without sections."""

    name: str
    base: str
    label: str
    pages: bool = True
    listing: bool = True              # the section's entries are listed: found by listings, tag pages, feeds and public data
    listing_page: bool = True         # the section has a listing page of its own (False: a collection or a page is its listing)
    feed: bool = True
    sitemap: bool = True
    link_field: str = "url"
    description: str = ""
    page_size: int | None = None      # None: the site's listings.pageSize
    list_empty: bool = False          # keep the listing page when the section has no entries
    group_by: str | None = None       # "week" (Monday start), "month" or "field:<name>": the listing view carries grouped entries
    archive: ArchiveConfig | None = None
    sort: str = "date"                # "date" (newest first) or "order" (front matter order, then title)


@dataclass(frozen=True)
class NotFoundSettings:
    """The 404 page: its title and description in the head, and whether it asks search engines to leave it out."""

    title: str = "Page not found"
    description: str = ""
    noindex: bool = True
    source: str | None = None         # a Markus page file in the static directory that is the body of the 404 page


@dataclass(frozen=True)
class CollectionConfig:
    """A listing defined by a selection (tags, sections) instead of by a CMS section: ``/<base>/``, then ``/<base>/page/N/``."""

    id: str
    base: str
    label: str
    select: Selection
    description: str = ""
    page_size: int | None = None      # None: the site's listings.pageSize
    featured_count: int | None = None # None: the site's listings.featuredCount
    sort: str = "date"                # "date" (newest first), "order" (front matter order, then title) or "title"
    ties: str = "slug-desc"           # sort "date" with equal dates: "slug-desc" or "slug-asc"
    drafts: bool = False              # the view of page 1 also carries the draft entries the selection matches
    sitemap: bool = True
    sitemap_pages: bool = False       # every page of the collection is in the sitemap, not only the first
    list_empty: bool = False


@dataclass(frozen=True)
class CustomPage:
    """A generated page whose body a hook composes (a tracker, a subscribe page), or an authored page file."""

    id: str
    path: str                         # "" is the home page
    title: str
    description: str = ""
    depends_on: tuple[str, ...] = ("*",)
    sitemap: bool = True
    noindex: bool = False
    form: str | None = None           # the id of a ``forms`` entry the default body shows
    source: str | None = None         # a Markus page file in the static directory; see ``includes.py``
    image: str | None = None          # the page's share image, a site path
    image_alt: str = ""               # og:image:alt / twitter:image:alt
    social_title: str = ""            # og:title / twitter:title when it differs from ``title``


@dataclass(frozen=True)
class NavLink:
    label: str
    href: str
    cta: bool = False
    external: bool = False                    # adds rel="noopener"; the target is not changed
    children: tuple["NavLink", ...] = ()      # nav only: a group rendered as <details class="markus-nav-group">


@dataclass(frozen=True)
class FooterColumn:
    title: str
    links: tuple[NavLink, ...]


@dataclass(frozen=True)
class FamilyFooter:
    """``footer.family``: the Anthus family footer (see ``family.py``). Empty strings fall back to the package's defaults."""

    site_id: str = ""
    name: str = ""
    tagline: str = ""
    description: str = ""
    byline: str = ""
    logo: str = ""        # a site path or https URL of an image shown beside the name and description
    logo_alt: str = ""
    contact_url: str = ""  # replaces the href of the registry's "Contact us" community link for this site


@dataclass(frozen=True)
class IslandSettings:
    script: str                # path of the site's island bundle in the static directory, e.g. "assets/islands.js"
    stylesheet: str | None = None
    prerender: str | None = None   # a JSON file of server-rendered island HTML, read at build time and never published


@dataclass(frozen=True)
class SeoSettings:
    default_image: str | None = None
    default_image_alt: str = ""
    home_social_title: str = ""
    image_width: int | None = None
    image_height: int | None = None
    twitter_site: str = ""
    twitter_creator: str = ""
    json_ld_types: tuple[tuple[str, str], ...] = ()
    default_json_ld: str = "Article"
    publisher_name: str = ""
    breadcrumbs_json_ld: bool = True
    based_on_field: str = ""          # front matter field with the URL of the original this page is based on (JSON-LD isBasedOn)
    article_types: tuple[str, ...] = ()   # entry types that are not listed but still report og:type article and Article JSON-LD


@dataclass(frozen=True)
class FeedSettings:
    formats: tuple[str, ...] = ("rss", "atom")
    count: int = 30
    rss_path: str = "feed.xml"
    atom_path: str = "atom.xml"
    title: str = ""


@dataclass(frozen=True)
class ListingSettings:
    page_size: int = 10
    featured_count: int = 0
    flat_path: str = "archive"
    home_count: int = 10
    tags: bool = True
    tag_base: str = "tags"
    types: tuple[str, ...] = ("article",)
    tag_select: Selection = field(default_factory=Selection)  # which entries the tag pages and the tag index cover
    tag_page_size: int | None = None  # None: pageSize and featuredCount; 0: every entry of a tag on one page
    page_suffix: str = " — page {page}"   # appended to the title of page 2 and later of a listing
    tag_title: str = "Tagged {tag}"       # the title and heading of a tag page
    draft_field: str = ""             # a front matter field whose value (draft_values) marks an item as a draft
    draft_values: tuple[str, ...] = ("draft",)


@dataclass(frozen=True)
class FontSettings:
    stylesheet: str | None = None
    preconnect: tuple[str, ...] = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")


@dataclass(frozen=True)
class IconSettings:
    icon: str | None = None
    icon_type: str = "image/svg+xml"
    apple_touch: str | None = None
    manifest: str | None = None
    theme_color: str | None = None
    theme_color_dark: str | None = None


@dataclass(frozen=True)
class ShowcaseSettings:
    """A logo wall fed from published items: every item of ``section`` is one site (front matter: name, logo, url, kind, order)."""

    section: str
    path: str = "built-with"
    title: str = "Built with Papyrus"
    description: str = ""
    kinds: tuple[tuple[str, str], ...] = (("anthus", "Built by Anthus"), ("design-partner", "Design partners"), ("customer", "Customers"))


@dataclass(frozen=True)
class FormField:
    name: str
    label: str
    type: str = "text"                      # text, email, textarea, select
    required: bool = False
    options: tuple[tuple[str, str], ...] = ()   # select: (value, label)
    autocomplete: str = ""
    help: str = ""


@dataclass(frozen=True)
class FormSpec:
    """A public form defined as data. ``endpoint`` is ``None`` until the receiving endpoint exists: the form then
    says it is not open yet and cannot be submitted. It never shows success it did not get from the endpoint."""

    id: str
    title: str
    fields: tuple[FormField, ...]
    endpoint: str | None = None
    submit_label: str = "Send"
    honeypot: str = "website"
    closed_notice: str = "This form is not open yet. Please check back soon."
    success_text: str = "Thank you. Your message was sent."
    failure_text: str = "Your message could not be sent. Please try again later."
    conversion_event: str | None = None
    """``"generate_lead"`` reports that GA4 event, once, when the endpoint answers 2xx (never on submit). None reports nothing."""


FORM_FIELD_TYPES = ("text", "email", "textarea", "select")


def _conversion_event(value, form_id: str) -> str | None:
    if value is None:
        return None
    if value != "generate_lead":
        raise ValueError(f"forms.{form_id}.conversionEvent must be 'generate_lead' when set")
    return value


@dataclass(frozen=True)
class WikiSettings:
    """Public wiki pages: the entry types that carry a review stamp and, optionally, the ``forms`` entry that lets a reader
    suggest an edit. ``data_link`` adds a link to the entity's graph JSON when the knowledge snapshot has that entity."""

    types: tuple[str, ...] = ("wiki_page",)
    suggest_form: str | None = None
    data_link: bool = True


@dataclass(frozen=True)
class AgentSettings:
    """Agent-readable representations (see ``markdown.py``); all on by default."""

    markdown: bool = True            # a .md twin of every page, advertised in the head and served on Accept: text/markdown
    llms_txt: bool = True
    llms_full: bool = True           # omitted when the site has more than llms_full_max_items pages
    llms_full_max_items: int = 200
    llms_full_max_bytes: int = 1_000_000
    llms_max_links: int = 200


AI_DESTINATIONS = {
    "chatgpt": ("Open in ChatGPT", "https://chatgpt.com/?q="),
    "claude": ("Open in Claude", "https://claude.ai/new?q="),
    "perplexity": ("Open in Perplexity", "https://www.perplexity.ai/search?q="),
}


@dataclass(frozen=True)
class PageActionSettings:
    """Copy-as-Markdown and related actions on article pages (see ``page_actions.py``)."""

    enabled: bool = True
    placement: str = "header"                 # header (above the article) or aside (after it)
    actions: tuple[str, ...] = ("copy", "view")
    ai: tuple[str, ...] = ()                  # subset of AI_DESTINATIONS; none by default
    prompt: str = "Read {url} and help me with it."
    types: tuple[str, ...] | None = None      # extra entry types that get actions (guides, docs); None = the listed types only


#: The canonical-URL rules of a directory-style site; the TypeScript mirror is in amplify/publication/redirect-rules.ts.
DIRECTORY_HTML_PATTERN = r"^/(?!(?:.*/)?index\.html$)(.+)\.html$"
DIRECTORY_SLASH_PATTERN = r"^/((?:[^/]+/)*[^/.]+)$"


@dataclass(frozen=True)
class StandardSettings:
    identity: SiteIdentity
    url_style: str = "html"
    base_path: str = ""     # urls.basePath without slashes: every generated key and URL lives under it ("" is the root)
    sections: tuple[SectionConfig, ...] = ()
    collections: tuple[CollectionConfig, ...] = ()
    not_found: NotFoundSettings = field(default_factory=NotFoundSettings)
    exact_redirects: tuple[tuple[str, str], ...] = ()
    pattern_redirects: tuple[RedirectRule, ...] = ()
    nav: tuple[NavLink, ...] = ()
    nav_disclosure: bool = False
    nav_brand_html: str = ""
    footer_columns: tuple[FooterColumn, ...] = ()
    footer_text: str = ""
    footer_family: FamilyFooter | None = None
    values: tuple[tuple[str, str], ...] = ()    # {{name}} tokens for page blocks
    islands: IslandSettings | None = None
    seo: SeoSettings = field(default_factory=SeoSettings)
    sitemap_style: str = "single"
    sitemap_lastmod: bool = True
    sitemap_tags: bool = True
    sitemap_extra: tuple[str, ...] = ()   # site paths listed in the sitemap that core does not generate (static.copy routes)
    robots_extra: tuple[str, ...] = ()
    feeds: FeedSettings = field(default_factory=FeedSettings)
    listings: ListingSettings = field(default_factory=ListingSettings)
    fonts: FontSettings = field(default_factory=FontSettings)
    icons: IconSettings = field(default_factory=IconSettings)
    guard: bool = True
    hooks_path: str | None = None
    pages: tuple[CustomPage, ...] = ()
    item_depends_on: tuple[str, ...] = ()
    static_copy: tuple[str, ...] = ()   # directories of the static directory published verbatim at the site root
    components_css: bool = True
    item_byline: bool = False
    breadcrumbs: bool = True
    home_link_label: str = "Home"
    summary_fields: tuple[str, ...] = ()
    showcase: ShowcaseSettings | None = None
    forms: tuple[FormSpec, ...] = ()
    agents: AgentSettings = field(default_factory=AgentSettings)
    page_actions: PageActionSettings = field(default_factory=PageActionSettings)
    mermaid: bool = True                      # ```mermaid blocks render as diagrams (self-hosted script, loaded only on pages that have one)
    wiki: WikiSettings = field(default_factory=WikiSettings)
    home_page: HomePageSettings | None = None   # the ``homePage`` key; None means the site has no home-page behaviour

    @property
    def sectioned(self) -> bool:
        return bool(self.sections)

    def section(self, name: str | None) -> SectionConfig | None:
        return next((section for section in self.sections if section.name == name), None)

    def collection(self, collection_id: str | None) -> CollectionConfig | None:
        return next((collection for collection in self.collections if collection.id == collection_id), None)

    def edge_rules(self) -> tuple[RedirectRule, ...]:
        """Pattern rules plus, for directory URLs, ``/x.html`` to ``/x/``; compiled into the edge function."""
        rules = list(self.pattern_redirects)
        if self.url_style == "directory":
            # /x.html to /x/ (a directory index file such as /x/index.html is served as it is), then /x to /x/.
            rules.append(RedirectRule(pattern=DIRECTORY_HTML_PATTERN, to="/$1/", status=301, except_paths=("/404.html",)))
            rules.append(RedirectRule(pattern=DIRECTORY_SLASH_PATTERN, to="/$1/", status=301, except_paths=("/404",)))
        return tuple(rules)


def _links(raw, where: str, *, groups: bool = False) -> tuple[NavLink, ...]:
    links = []
    for entry in raw or ():
        _only(entry, {"label", "href", "cta", "external", *({"children"} if groups else set())}, where)
        children = entry.get("children")
        if not entry.get("label") or (not entry.get("href") and not children):
            raise ValueError(f"{where} entries need label and href")
        if children and entry.get("href"):
            raise ValueError(f"{where} entry {entry['label']!r} has children, so it takes no href")
        links.append(
            NavLink(
                str(entry["label"]), str(entry.get("href", "")), bool(entry.get("cta", False)), bool(entry.get("external", False)),
                _links(children, f"{where}.children") if children else (),
            )
        )
    return tuple(links)


def standard_settings_from_mapping(raw: Mapping) -> StandardSettings:
    site = raw["site"]
    _only(site, {"name", "shortName", "publisher", "tagline", "description", "language", "productionUrl", "author", "componentsCss", "summaryFields", "dateFormat", "ledeField"}, "site")
    name = _text(site, "name")
    if not name:
        raise ValueError("site.name is required")
    identity = SiteIdentity(
        name=name,
        short_name=_text(site, "shortName"),
        publisher=_text(site, "publisher"),
        tagline=_text(site, "tagline"),
        description=_text(site, "description"),
        language=_text(site, "language", "en"),
        production_url=_text(site, "productionUrl").rstrip("/") or None,
        author=_text(site, "author"),
        date_format=_text(site, "dateFormat"),
        lede_field=_text(site, "ledeField"),
    )
    if identity.date_format:
        try:
            dt.date(2026, 1, 2).strftime(identity.date_format)
        except ValueError as error:
            raise ValueError(f"site.dateFormat is not a valid strftime pattern: {error}") from error

    urls = dict(raw.get("urls") or {})
    _only(urls, {"style", "sections", "basePath"}, "urls")
    style = urls.get("style", "html")
    if style not in URL_STYLES:
        raise ValueError(f"urls.style must be one of {URL_STYLES}")
    base_path = _path_segment(str(urls.get("basePath") or ""), "urls.basePath")
    if base_path and ("images" in raw or "media" in raw):
        raise ValueError("urls.basePath does not work with images or media yet: their renditions are written at the bucket root")
    sections = []
    for section_name, entry in dict(urls.get("sections") or {}).items():
        entry = dict(entry or {})
        _only(entry, {"base", "label", "pages", "listing", "listingPage", "feed", "sitemap", "linkField", "description", "pageSize", "listEmpty", "groupBy", "archive", "sort"}, f"urls.sections.{section_name}")
        if entry.get("sort", "date") not in ("date", "order"):
            raise ValueError(f"urls.sections.{section_name}.sort must be 'date' or 'order'")
        group_by = entry.get("groupBy")
        if group_by is not None and not valid_group_by(group_by):
            raise ValueError(f"urls.sections.{section_name}.groupBy must be 'week', 'month' or 'field:<front matter field>'")
        archive_raw = entry.get("archive")
        archive = None
        if archive_raw is not None:
            _only(archive_raw, {"by", "base", "description"}, f"urls.sections.{section_name}.archive")
            if archive_raw.get("by", "month") not in ("month", "year"):
                raise ValueError("archive.by must be 'month' or 'year'")
            archive = ArchiveConfig(
                by=archive_raw.get("by", "month"),
                base=_path_segment(str(archive_raw.get("base", "archive")), f"urls.sections.{section_name}.archive.base"),
                description=str(archive_raw.get("description", "")),
            )
        sections.append(
            SectionConfig(
                name=section_name,
                base=_unreserved_segment(entry.get("base", section_name), f"urls.sections.{section_name}.base"),
                label=str(entry.get("label") or section_name.replace("-", " ").title()),
                pages=bool(entry.get("pages", True)),
                listing=bool(entry.get("listing", True)),
                listing_page=bool(entry.get("listingPage", True)),
                feed=bool(entry.get("feed", True)),
                sitemap=bool(entry.get("sitemap", True)),
                link_field=str(entry.get("linkField", "url")),
                description=str(entry.get("description", "")),
                page_size=int(entry["pageSize"]) if entry.get("pageSize") is not None else None,
                list_empty=bool(entry.get("listEmpty", False)),
                group_by=group_by,
                archive=archive,
                sort=str(entry.get("sort", "date")),
            )
        )

    static = dict(raw.get("static") or {})
    _only(static, {"copy"}, "static")
    static_copy = tuple(str(name) for name in static.get("copy", ()))
    for name in static_copy:
        if not name or name.startswith("/") or ".." in name.split("/") or name in ("css", "assets"):
            raise ValueError(f"static.copy entries must be relative directories other than css and assets, not {name!r}")

    redirects = dict(raw.get("redirects") or {})
    _only(redirects, {"exact", "patterns"}, "redirects")
    exact = []
    for source, target in dict(redirects.get("exact") or {}).items():
        if not str(source).startswith("/") or not str(target).startswith(("/", "http")):
            raise ValueError(f"redirects.exact needs absolute paths, got {source!r} -> {target!r}")
        exact.append((str(source), str(target)))
    patterns = tuple(rule_from_mapping(entry) for entry in redirects.get("patterns") or ())

    nav = dict(raw.get("nav") or {})
    _only(nav, {"links", "disclosure", "homeLabel", "brandHtml"}, "nav")
    footer = dict(raw.get("footer") or {})
    _only(footer, {"columns", "text", "family"}, "footer")
    family_raw = footer.get("family")
    family = None
    if family_raw is not None:
        _only(family_raw, {"siteId", "name", "tagline", "description", "byline", "logo", "logoAlt", "contactUrl"}, "footer.family")
        family = FamilyFooter(*(_text(family_raw, key) for key in ("siteId", "name", "tagline", "description", "byline", "logo", "logoAlt", "contactUrl")))
    values = []
    for key, value in dict(raw.get("values") or {}).items():
        if not re.fullmatch(r"\w+", key) or isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"values.{key} must be a string or a number, with a name of letters, digits and underscores")
        values.append((key, str(value)))
    islands_raw = raw.get("islands")
    islands = None
    if islands_raw is not None:
        _only(islands_raw, {"script", "stylesheet", "prerender"}, "islands")
        if not islands_raw.get("script"):
            raise ValueError("islands.script is required")
        islands = IslandSettings(
            str(islands_raw["script"]).lstrip("/"),
            str(islands_raw["stylesheet"]).lstrip("/") if islands_raw.get("stylesheet") else None,
            str(islands_raw["prerender"]).lstrip("/") if islands_raw.get("prerender") else None,
        )
    columns = []
    for column in footer.get("columns") or ():
        _only(column, {"title", "links"}, "footer.columns")
        columns.append(FooterColumn(str(column.get("title", "")), _links(column.get("links"), "footer.columns.links")))

    seo = dict(raw.get("seo") or {})
    _only(seo, {"defaultImage", "defaultImageAlt", "homeSocialTitle", "imageSize", "twitterSite", "twitterCreator", "jsonLdTypes", "defaultJsonLd", "publisherName", "breadcrumbs", "isBasedOnField", "articleTypes"}, "seo")
    size = seo.get("imageSize")
    if size is not None and (len(size) != 2 or not all(isinstance(number, int) for number in size)):
        raise ValueError("seo.imageSize must be [width, height]")
    seo_settings = SeoSettings(
        default_image=seo.get("defaultImage"),
        default_image_alt=str(seo.get("defaultImageAlt", "")),
        home_social_title=str(seo.get("homeSocialTitle", "")),
        image_width=size[0] if size else None,
        image_height=size[1] if size else None,
        twitter_site=_text(seo, "twitterSite"),
        twitter_creator=_text(seo, "twitterCreator"),
        json_ld_types=tuple(sorted(dict(seo.get("jsonLdTypes") or {}).items())),
        default_json_ld=_text(seo, "defaultJsonLd", "Article"),
        publisher_name=_text(seo, "publisherName") or identity.publisher or identity.name,
        breadcrumbs_json_ld=bool(seo.get("breadcrumbs", True)),
        based_on_field=_text(seo, "isBasedOnField"),
        article_types=tuple(str(name) for name in (seo.get("articleTypes") or ())),
    )

    sitemap = dict(raw.get("sitemap") or {})
    _only(sitemap, {"style", "lastmod", "tags", "extra"}, "sitemap")
    sitemap_extra = tuple(str(path) for path in sitemap.get("extra", ()))
    for path in sitemap_extra:
        if not path.startswith("/"):
            raise ValueError(f"sitemap.extra paths start with /, not {path!r}")
    sitemap_style = sitemap.get("style", "single")
    if sitemap_style not in SITEMAP_STYLES:
        raise ValueError(f"sitemap.style must be one of {SITEMAP_STYLES}")
    robots = dict(raw.get("robots") or {})
    _only(robots, {"extra"}, "robots")

    feeds = dict(raw.get("feeds") or {})
    _only(feeds, {"formats", "count", "rssPath", "atomPath", "title"}, "feeds")
    formats = tuple(feeds.get("formats", FEED_FORMATS))
    if not set(formats) <= set(FEED_FORMATS):
        raise ValueError(f"feeds.formats must be a subset of {FEED_FORMATS}")
    feed_defaults = FeedSettings()
    feed_settings = FeedSettings(
        formats=formats,
        count=int(feeds.get("count", feed_defaults.count)),
        rss_path=_text(feeds, "rssPath", feed_defaults.rss_path),
        atom_path=_text(feeds, "atomPath", feed_defaults.atom_path),
        title=_text(feeds, "title") or identity.name,
    )
    if feed_settings.count < 1:
        raise ValueError("feeds.count must be positive")

    listings = dict(raw.get("listings") or {})
    _only(listings, {"pageSize", "featuredCount", "path", "homeCount", "tags", "tagBase", "types", "tagSelect", "tagPageSize", "draft", "pageSuffix", "tagTitle"}, "listings")
    draft_raw = dict(listings.get("draft") or {})
    _only(draft_raw, {"field", "values"}, "listings.draft")
    listing_defaults = ListingSettings()
    listing_settings = ListingSettings(
        page_size=int(listings.get("pageSize", listing_defaults.page_size)),
        featured_count=int(listings.get("featuredCount", 0)),
        flat_path=_path_segment(str(listings.get("path", listing_defaults.flat_path)), "listings.path"),
        home_count=int(listings.get("homeCount", listing_defaults.home_count)),
        tags=bool(listings.get("tags", True)),
        tag_base=_path_segment(str(listings.get("tagBase", "tags")), "listings.tagBase"),
        types=tuple(listings.get("types", listing_defaults.types)),
        tag_select=selection_from_mapping(listings.get("tagSelect"), "listings.tagSelect"),
        tag_page_size=int(listings["tagPageSize"]) if listings.get("tagPageSize") is not None else None,
        page_suffix=str(listings.get("pageSuffix", listing_defaults.page_suffix)),
        tag_title=str(listings.get("tagTitle", listing_defaults.tag_title)),
        draft_field=str(draft_raw.get("field", "")),
        draft_values=tuple(str(value) for value in draft_raw.get("values", listing_defaults.draft_values)),
    )
    if listing_settings.tag_page_size is not None and listing_settings.tag_page_size < 0:
        raise ValueError("listings.tagPageSize must not be negative (0 puts every entry of a tag on one page)")
    if listing_settings.page_size < 1 or listing_settings.featured_count < 0:
        raise ValueError("listings.pageSize must be positive and featuredCount must not be negative")
    if any(section.page_size is not None and section.page_size < 1 for section in sections):
        raise ValueError("urls.sections.*.pageSize must be positive")

    fonts = dict(raw.get("fonts") or {})
    _only(fonts, {"stylesheet", "preconnect"}, "fonts")
    font_defaults = FontSettings()
    icons = dict(raw.get("icons") or {})
    _only(icons, {"icon", "iconType", "appleTouch", "manifest", "themeColor", "themeColorDark"}, "icons")
    environment = dict(raw.get("environment") or {})
    _only(environment, {"guard"}, "environment")

    collections = []
    for entry in raw.get("collections") or ():
        _only(entry, {"id", "base", "label", "select", "description", "pageSize", "featuredCount", "sort", "ties", "drafts", "sitemap", "sitemapPages", "listEmpty"}, "collections")
        collection_id = str(entry.get("id", ""))
        if not re.fullmatch(r"[a-z][a-z0-9-]*", collection_id) or any(c.id == collection_id for c in collections):
            raise ValueError(f"collections need a unique lowercase id, got {collection_id!r}")
        base = _unreserved_segment(str(entry.get("base", collection_id)), f"collections.{collection_id}.base")
        if not base or any(base == section.base and section.listing_page for section in sections):
            raise ValueError(f"collections.{collection_id}.base must be a path that no section with a listing page uses")
        if any(base == other.base for other in collections):
            raise ValueError(f"collections.{collection_id}.base {base!r} is already the base of another collection")
        if base == str(raw.get("listings", {}).get("tagBase", "tags")).strip("/") and raw.get("listings", {}).get("tags", True):
            raise ValueError(f"collections.{collection_id}.base {base!r} is the tag pages' base")
        if str(entry.get("sort", "date")) not in ("date", "order", "title") or str(entry.get("ties", "slug-desc")) not in ("slug-desc", "slug-asc"):
            raise ValueError(f"collections.{collection_id}: sort is date, order or title; ties is slug-desc or slug-asc")
        collection = CollectionConfig(
            id=collection_id,
            base=base,
            label=str(entry.get("label") or collection_id.replace("-", " ").title()),
            select=selection_from_mapping(entry.get("select"), f"collections.{collection_id}.select"),
            description=str(entry.get("description", "")),
            page_size=int(entry["pageSize"]) if entry.get("pageSize") is not None else None,
            featured_count=int(entry["featuredCount"]) if entry.get("featuredCount") is not None else None,
            sort=str(entry.get("sort", "date")),
            ties=str(entry.get("ties", "slug-desc")),
            drafts=bool(entry.get("drafts", False)),
            sitemap=bool(entry.get("sitemap", True)),
            sitemap_pages=bool(entry.get("sitemapPages", False)),
            list_empty=bool(entry.get("listEmpty", False)),
        )
        if (collection.page_size is not None and collection.page_size < 1) or (collection.featured_count is not None and collection.featured_count < 0):
            raise ValueError(f"collections.{collection_id}: pageSize must be positive and featuredCount must not be negative")
        collections.append(collection)
    not_found_raw = dict(raw.get("notFound") or {})
    _only(not_found_raw, {"title", "description", "noindex", "source"}, "notFound")
    not_found_defaults = NotFoundSettings()
    not_found = NotFoundSettings(
        title=_text(not_found_raw, "title", not_found_defaults.title),
        description=_text(not_found_raw, "description"),
        noindex=bool(not_found_raw.get("noindex", True)),
        source=_text(not_found_raw, "source") or None,
    )
    custom = []
    for entry in raw.get("pages") or ():
        _only(entry, {"id", "path", "title", "description", "dependsOn", "sitemap", "noindex", "form", "source", "image", "imageAlt", "socialTitle"}, "pages")
        custom.append(
            CustomPage(
                id=str(entry["id"]),
                path=_unreserved_segment(str(entry["path"]), "pages.path"),
                title=str(entry["title"]),
                description=str(entry.get("description", "")),
                depends_on=tuple(entry.get("dependsOn", ("*",))),
                sitemap=bool(entry.get("sitemap", True)),
                noindex=bool(entry.get("noindex", False)),
                form=entry.get("form"),
                source=str(entry["source"]) if entry.get("source") else None,
                image=str(entry["image"]) if entry.get("image") else None,
                image_alt=str(entry.get("imageAlt", "")),
                social_title=str(entry.get("socialTitle", "")),
            )
        )
    components = dict(raw.get("components") or {})
    _only(components, {"itemByline", "breadcrumbs", "itemPagesDependOn"}, "components")

    showcase_raw = raw.get("showcase")
    showcase = None
    if showcase_raw is not None:
        _only(showcase_raw, {"section", "path", "title", "description", "kinds"}, "showcase")
        defaults = ShowcaseSettings(section="x")
        showcase = ShowcaseSettings(
            section=_path_segment(str(showcase_raw["section"]), "showcase.section"),
            path=_path_segment(str(showcase_raw.get("path", defaults.path)), "showcase.path"),
            title=_text(showcase_raw, "title", defaults.title),
            description=_text(showcase_raw, "description"),
            kinds=tuple((str(key), str(label)) for key, label in dict(showcase_raw.get("kinds") or dict(defaults.kinds)).items()),
        )
        if any(section.name == showcase.section for section in sections):
            raise ValueError("showcase.section must not also be declared in urls.sections")
    forms = []
    for form_id, spec in dict(raw.get("forms") or {}).items():
        _only(spec, {"title", "fields", "endpoint", "submitLabel", "honeypot", "closedNotice", "successText", "failureText", "conversionEvent"}, f"forms.{form_id}")
        fields = []
        for field_raw in spec.get("fields") or ():
            _only(field_raw, {"name", "label", "type", "required", "options", "autocomplete", "help"}, f"forms.{form_id}.fields")
            kind = field_raw.get("type", "text")
            if kind not in FORM_FIELD_TYPES:
                raise ValueError(f"forms.{form_id}.fields type must be one of {FORM_FIELD_TYPES}")
            if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]*", str(field_raw.get("name", ""))):
                raise ValueError(f"forms.{form_id}.fields needs a simple name")
            fields.append(
                FormField(
                    name=field_raw["name"], label=str(field_raw.get("label", field_raw["name"])), type=kind,
                    required=bool(field_raw.get("required", False)),
                    options=tuple((str(o["value"]), str(o.get("label", o["value"]))) for o in field_raw.get("options") or ()),
                    autocomplete=str(field_raw.get("autocomplete", "")), help=str(field_raw.get("help", "")),
                )
            )
        endpoint = spec.get("endpoint")
        if endpoint is not None and not str(endpoint).startswith(("https://", "/")):
            raise ValueError(f"forms.{form_id}.endpoint must be https or a site path")
        defaults = FormSpec(form_id, "", ())
        forms.append(
            FormSpec(
                id=form_id, title=str(spec.get("title", "")), fields=tuple(fields), endpoint=endpoint,
                submit_label=str(spec.get("submitLabel", defaults.submit_label)), honeypot=str(spec.get("honeypot", defaults.honeypot)),
                closed_notice=str(spec.get("closedNotice", defaults.closed_notice)),
                success_text=str(spec.get("successText", defaults.success_text)), failure_text=str(spec.get("failureText", defaults.failure_text)),
                conversion_event=_conversion_event(spec.get("conversionEvent"), form_id),
            )
        )
        if any(field.name == forms[-1].honeypot for field in forms[-1].fields):
            raise ValueError(f"forms.{form_id}.honeypot collides with a field name")
    known_forms = {form.id for form in forms}
    for custom_page in custom:
        if custom_page.form is not None and custom_page.form not in known_forms:
            raise ValueError(f"pages.{custom_page.id}.form names an unknown form {custom_page.form!r}")
    agents_raw = dict(raw.get("agents") or {})
    _only(agents_raw, {"markdown", "llmsTxt", "llmsFull", "llmsFullMaxItems", "llmsFullMaxBytes", "llmsMaxLinks"}, "agents")
    agent_defaults = AgentSettings()
    agents = AgentSettings(
        markdown=bool(agents_raw.get("markdown", agent_defaults.markdown)),
        llms_txt=bool(agents_raw.get("llmsTxt", agent_defaults.llms_txt)),
        llms_full=bool(agents_raw.get("llmsFull", agent_defaults.llms_full)),
        llms_full_max_items=int(agents_raw.get("llmsFullMaxItems", agent_defaults.llms_full_max_items)),
        llms_full_max_bytes=int(agents_raw.get("llmsFullMaxBytes", agent_defaults.llms_full_max_bytes)),
        llms_max_links=int(agents_raw.get("llmsMaxLinks", agent_defaults.llms_max_links)),
    )
    if (agents.llms_txt or agents.llms_full) and not agents.markdown:
        raise ValueError("agents.llmsTxt and agents.llmsFull link to the Markdown twins; turn agents.markdown on")
    actions_raw = dict(raw.get("pageActions") or {})
    _only(actions_raw, {"enabled", "placement", "actions", "ai", "prompt", "types"}, "pageActions")
    action_defaults = PageActionSettings()
    page_actions = PageActionSettings(
        enabled=bool(actions_raw.get("enabled", True)),
        placement=str(actions_raw.get("placement", action_defaults.placement)),
        actions=tuple(actions_raw.get("actions", action_defaults.actions)),
        ai=tuple(actions_raw.get("ai", ())),
        prompt=str(actions_raw.get("prompt", action_defaults.prompt)),
        types=tuple(str(name) for name in actions_raw["types"]) if actions_raw.get("types") is not None else None,
    )
    if page_actions.types is not None and not all(page_actions.types):
        raise ValueError("pageActions.types lists entry type names")
    if page_actions.placement not in ("header", "aside"):
        raise ValueError("pageActions.placement must be 'header' or 'aside'")
    if not set(page_actions.actions) <= {"copy", "view"}:
        raise ValueError("pageActions.actions must be a subset of ['copy', 'view']")
    if not set(page_actions.ai) <= set(AI_DESTINATIONS):
        raise ValueError(f"pageActions.ai must be a subset of {sorted(AI_DESTINATIONS)}")
    if "{url}" not in page_actions.prompt or len(page_actions.prompt) > 200:
        raise ValueError("pageActions.prompt must contain {url} and stay short: the page body is never sent")
    mermaid_raw = dict(raw.get("mermaid") or {})
    _only(mermaid_raw, {"enabled"}, "mermaid")
    wiki_raw = dict(raw.get("wiki") or {})
    _only(wiki_raw, {"types", "suggestForm", "dataLink"}, "wiki")
    wiki_defaults = WikiSettings()
    wiki = WikiSettings(
        types=tuple(str(name) for name in wiki_raw.get("types", wiki_defaults.types)),
        suggest_form=str(wiki_raw["suggestForm"]) if wiki_raw.get("suggestForm") else None,
        data_link=bool(wiki_raw.get("dataLink", wiki_defaults.data_link)),
    )
    if not all(wiki.types):
        raise ValueError("wiki.types lists entry type names")
    if wiki.suggest_form is not None and wiki.suggest_form not in known_forms:
        raise ValueError(f"wiki.suggestForm names an unknown form {wiki.suggest_form!r}")
    return StandardSettings(
        identity=identity,
        url_style=style,
        base_path=base_path,
        sections=tuple(sections),
        collections=tuple(collections),
        not_found=not_found,
        exact_redirects=tuple(sorted(exact)),
        pattern_redirects=patterns,
        nav=_links(nav.get("links"), "nav.links", groups=True),
        nav_disclosure=bool(nav.get("disclosure", False)),
        nav_brand_html=str(nav.get("brandHtml") or ""),
        footer_columns=tuple(columns),
        footer_text=_text(footer, "text"),
        footer_family=family,
        values=tuple(values),
        islands=islands,
        seo=seo_settings,
        sitemap_style=sitemap_style,
        sitemap_lastmod=bool(sitemap.get("lastmod", True)),
        sitemap_tags=bool(sitemap.get("tags", True)),
        sitemap_extra=sitemap_extra,
        robots_extra=tuple(robots.get("extra") or ()),
        feeds=feed_settings,
        listings=listing_settings,
        fonts=FontSettings(stylesheet=fonts.get("stylesheet"), preconnect=tuple(fonts.get("preconnect", font_defaults.preconnect if fonts.get("stylesheet") else ()))),
        icons=IconSettings(
            icon=icons.get("icon"),
            icon_type=str(icons.get("iconType", "image/svg+xml")),
            apple_touch=icons.get("appleTouch"),
            manifest=icons.get("manifest"),
            theme_color=icons.get("themeColor"),
            theme_color_dark=icons.get("themeColorDark"),
        ),
        guard=bool(environment.get("guard", True)),
        hooks_path=_text(raw, "hooks") or None,
        pages=tuple(custom),
        item_depends_on=tuple(components.get("itemPagesDependOn", ())),
        static_copy=static_copy,
        components_css=bool(site.get("componentsCss", True)),
        item_byline=bool(components.get("itemByline", False)),
        breadcrumbs=bool(components.get("breadcrumbs", True)),
        home_link_label=_text(nav, "homeLabel", "Home"),
        summary_fields=tuple(site.get("summaryFields") or ()),
        showcase=showcase,
        forms=tuple(forms),
        agents=agents,
        page_actions=page_actions,
        mermaid=bool(mermaid_raw.get("enabled", True)),
        wiki=wiki,
        home_page=home_page_settings_from_mapping(raw["homePage"]) if raw.get("homePage") is not None else None,
    )
