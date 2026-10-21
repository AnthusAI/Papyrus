"""``projection.json`` settings of the standard Markus front end.

A site opts in by having a top-level ``site`` object. Everything else here is
optional with a working default, so the smallest standard site is::

    {"site": {"name": "Example"}}

and it is a site without sections: articles live at the root, one flat listing
holds them all. Unknown keys are rejected so a typo never silently does nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from .redirects import RedirectRule, rule_from_mapping

STANDARD_KEYS = (
    "site", "urls", "nav", "footer", "seo", "sitemap", "robots", "feeds", "listings",
    "fonts", "icons", "environment", "hooks", "redirects", "pages", "components", "media", "showcase", "static", "forms", "agents", "pageActions",
)
URL_STYLES = ("html", "directory")
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
    listing: bool = True
    feed: bool = True
    sitemap: bool = True
    link_field: str = "url"
    description: str = ""
    page_size: int | None = None      # None: the site's listings.pageSize
    list_empty: bool = False          # keep the listing page when the section has no entries
    group_by: str | None = None       # "week" (Monday start) or "month": the listing view carries grouped entries
    archive: ArchiveConfig | None = None
    sort: str = "date"                # "date" (newest first) or "order" (front matter order, then title)


@dataclass(frozen=True)
class CustomPage:
    """A generated page whose body a hook composes (a tracker, a subscribe page)."""

    id: str
    path: str
    title: str
    description: str = ""
    depends_on: tuple[str, ...] = ("*",)
    sitemap: bool = True
    noindex: bool = False
    form: str | None = None           # the id of a ``forms`` entry the default body shows


@dataclass(frozen=True)
class NavLink:
    label: str
    href: str
    cta: bool = False


@dataclass(frozen=True)
class FooterColumn:
    title: str
    links: tuple[NavLink, ...]


@dataclass(frozen=True)
class SeoSettings:
    default_image: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    twitter_site: str = ""
    twitter_creator: str = ""
    json_ld_types: tuple[tuple[str, str], ...] = ()
    default_json_ld: str = "Article"
    publisher_name: str = ""
    breadcrumbs_json_ld: bool = True


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


FORM_FIELD_TYPES = ("text", "email", "textarea", "select")


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


@dataclass(frozen=True)
class StandardSettings:
    identity: SiteIdentity
    url_style: str = "html"
    sections: tuple[SectionConfig, ...] = ()
    exact_redirects: tuple[tuple[str, str], ...] = ()
    pattern_redirects: tuple[RedirectRule, ...] = ()
    nav: tuple[NavLink, ...] = ()
    nav_disclosure: bool = False
    footer_columns: tuple[FooterColumn, ...] = ()
    footer_text: str = ""
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

    @property
    def sectioned(self) -> bool:
        return bool(self.sections)

    def section(self, name: str | None) -> SectionConfig | None:
        return next((section for section in self.sections if section.name == name), None)

    def edge_rules(self) -> tuple[RedirectRule, ...]:
        """Pattern rules plus, for directory URLs, ``/x.html`` to ``/x/``; compiled into the edge function."""
        rules = list(self.pattern_redirects)
        if self.url_style == "directory":
            rules.append(RedirectRule(pattern=r"^/(.+)\.html$", to="/$1/", status=301, except_paths=("/404.html",)))
        return tuple(rules)


def _links(raw, where: str) -> tuple[NavLink, ...]:
    links = []
    for entry in raw or ():
        _only(entry, {"label", "href", "cta"}, where)
        if not entry.get("label") or not entry.get("href"):
            raise ValueError(f"{where} entries need label and href")
        links.append(NavLink(str(entry["label"]), str(entry["href"]), bool(entry.get("cta", False))))
    return tuple(links)


def standard_settings_from_mapping(raw: Mapping) -> StandardSettings:
    site = raw["site"]
    _only(site, {"name", "shortName", "publisher", "tagline", "description", "language", "productionUrl", "author", "componentsCss", "summaryFields"}, "site")
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
    )

    urls = dict(raw.get("urls") or {})
    _only(urls, {"style", "sections"}, "urls")
    style = urls.get("style", "html")
    if style not in URL_STYLES:
        raise ValueError(f"urls.style must be one of {URL_STYLES}")
    sections = []
    for section_name, entry in dict(urls.get("sections") or {}).items():
        entry = dict(entry or {})
        _only(entry, {"base", "label", "pages", "listing", "feed", "sitemap", "linkField", "description", "pageSize", "listEmpty", "groupBy", "archive", "sort"}, f"urls.sections.{section_name}")
        if entry.get("sort", "date") not in ("date", "order"):
            raise ValueError(f"urls.sections.{section_name}.sort must be 'date' or 'order'")
        group_by = entry.get("groupBy")
        if group_by not in (None, "week", "month"):
            raise ValueError(f"urls.sections.{section_name}.groupBy must be 'week' or 'month'")
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
                base=_path_segment(entry.get("base", section_name), f"urls.sections.{section_name}.base"),
                label=str(entry.get("label") or section_name.replace("-", " ").title()),
                pages=bool(entry.get("pages", True)),
                listing=bool(entry.get("listing", True)),
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
    _only(nav, {"links", "disclosure", "homeLabel"}, "nav")
    footer = dict(raw.get("footer") or {})
    _only(footer, {"columns", "text"}, "footer")
    columns = []
    for column in footer.get("columns") or ():
        _only(column, {"title", "links"}, "footer.columns")
        columns.append(FooterColumn(str(column.get("title", "")), _links(column.get("links"), "footer.columns.links")))

    seo = dict(raw.get("seo") or {})
    _only(seo, {"defaultImage", "imageSize", "twitterSite", "twitterCreator", "jsonLdTypes", "defaultJsonLd", "publisherName", "breadcrumbs"}, "seo")
    size = seo.get("imageSize")
    if size is not None and (len(size) != 2 or not all(isinstance(number, int) for number in size)):
        raise ValueError("seo.imageSize must be [width, height]")
    seo_settings = SeoSettings(
        default_image=seo.get("defaultImage"),
        image_width=size[0] if size else None,
        image_height=size[1] if size else None,
        twitter_site=_text(seo, "twitterSite"),
        twitter_creator=_text(seo, "twitterCreator"),
        json_ld_types=tuple(sorted(dict(seo.get("jsonLdTypes") or {}).items())),
        default_json_ld=_text(seo, "defaultJsonLd", "Article"),
        publisher_name=_text(seo, "publisherName") or identity.publisher or identity.name,
        breadcrumbs_json_ld=bool(seo.get("breadcrumbs", True)),
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
    _only(listings, {"pageSize", "featuredCount", "path", "homeCount", "tags", "tagBase", "types"}, "listings")
    listing_defaults = ListingSettings()
    listing_settings = ListingSettings(
        page_size=int(listings.get("pageSize", listing_defaults.page_size)),
        featured_count=int(listings.get("featuredCount", 0)),
        flat_path=_path_segment(str(listings.get("path", listing_defaults.flat_path)), "listings.path"),
        home_count=int(listings.get("homeCount", listing_defaults.home_count)),
        tags=bool(listings.get("tags", True)),
        tag_base=_path_segment(str(listings.get("tagBase", "tags")), "listings.tagBase"),
        types=tuple(listings.get("types", listing_defaults.types)),
    )
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

    custom = []
    for entry in raw.get("pages") or ():
        _only(entry, {"id", "path", "title", "description", "dependsOn", "sitemap", "noindex", "form"}, "pages")
        custom.append(
            CustomPage(
                id=str(entry["id"]),
                path=_path_segment(str(entry["path"]), "pages.path"),
                title=str(entry["title"]),
                description=str(entry.get("description", "")),
                depends_on=tuple(entry.get("dependsOn", ("*",))),
                sitemap=bool(entry.get("sitemap", True)),
                noindex=bool(entry.get("noindex", False)),
                form=entry.get("form"),
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
        _only(spec, {"title", "fields", "endpoint", "submitLabel", "honeypot", "closedNotice", "successText", "failureText"}, f"forms.{form_id}")
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
    _only(actions_raw, {"enabled", "placement", "actions", "ai", "prompt"}, "pageActions")
    action_defaults = PageActionSettings()
    page_actions = PageActionSettings(
        enabled=bool(actions_raw.get("enabled", True)),
        placement=str(actions_raw.get("placement", action_defaults.placement)),
        actions=tuple(actions_raw.get("actions", action_defaults.actions)),
        ai=tuple(actions_raw.get("ai", ())),
        prompt=str(actions_raw.get("prompt", action_defaults.prompt)),
    )
    if page_actions.placement not in ("header", "aside"):
        raise ValueError("pageActions.placement must be 'header' or 'aside'")
    if not set(page_actions.actions) <= {"copy", "view"}:
        raise ValueError("pageActions.actions must be a subset of ['copy', 'view']")
    if not set(page_actions.ai) <= set(AI_DESTINATIONS):
        raise ValueError(f"pageActions.ai must be a subset of {sorted(AI_DESTINATIONS)}")
    if "{url}" not in page_actions.prompt or len(page_actions.prompt) > 200:
        raise ValueError("pageActions.prompt must contain {url} and stay short: the page body is never sent")
    return StandardSettings(
        identity=identity,
        url_style=style,
        sections=tuple(sections),
        exact_redirects=tuple(sorted(exact)),
        pattern_redirects=patterns,
        nav=_links(nav.get("links"), "nav.links"),
        nav_disclosure=bool(nav.get("disclosure", False)),
        footer_columns=tuple(columns),
        footer_text=_text(footer, "text"),
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
    )
