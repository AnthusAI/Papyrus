"""Build a documentation site from a repository's ``docs/`` Markdown.

One builder for every Anthus docs site. A repository supplies a
:class:`DocsSiteConfig`; the builder stages its Markdown into the Papyrus
content layout (``index.md`` plus a flat ``articles/`` directory), rewrites
the links between pages and the image paths to match, and renders the result
with :func:`build_markus_site` and a masthead carrying the site's name.
"""

from __future__ import annotations

import argparse
import fnmatch
import html
import posixpath
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .build import BuildResult, build_markus_site
from .docs_markdown import convert_markdown_dialects
from .consent import ConsentModeSettings
from .shell import SiteChrome

DIRECTORY_LINK_PATTERN = re.compile(r"\]\(((?!https?:|mailto:|#|/)[^)\s#]*/)(#[^)\s]*)?\)")
IMAGE_REFERENCE_PATTERN = re.compile(r"(!\[[^\]]*\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")
DIRECTORY_INDEX_NAMES = ("README.md", "readme.md", "index.md", "INDEX.md")
LIGHT_THEME_FOR_DARK_THEME = {"catppuccin": "catppuccin-latte"}
RELATIVE_LINK_PATTERN = re.compile(r"\]\((?!https?:|mailto:|#|/)([^)\s#]+)(#[^)\s]*)?\)")
MARKDOWN_LINK_PATTERN = re.compile(r"\]\(([^)\s#]+\.(?:md|html))(#[^)\s]*)?\)")
IMAGE_DIRECTORY_NAME = "images"
PUBLISHED_ASSET_DIRECTORY_NAME = "assets"
INDEX_PAGE_PATH = "index.md"
DEFAULT_SITE_STYLESHEET = Path(__file__).with_name("docs_site.css")
DEFAULT_PRIVACY_POLICY_URL = "https://anth.us/privacy/"
COOKIE_SETTINGS_LINK = '<p class="site-cookie-settings"><a href="#" data-papyrus-consent-reopen hidden>Cookie settings</a></p>'


@dataclass(frozen=True)
class DocsSiteConfig:
    """What differs between one documentation site and the next."""

    site_name: str
    tagline: str
    documentation_directory: Path
    source_repository_url: str
    theme: str = "catppuccin"
    navigation: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    """Sidebar groups as (group label, ((published .html path, label), ...)); empty keeps the flat page list."""
    site_stylesheet: Path | None = None
    redirect_former_directory_urls: bool = False
    """Write an index.html redirect at each page's former directory URL (for example from MkDocs)."""
    excluded_page_patterns: tuple[str, ...] = ()
    """Glob patterns matched against each page's path under the docs directory; matching pages are never published."""
    published_site_url: str = ""
    """The site's public address ending in a slash; when set, the build also writes ``sitemap.xml`` and ``404.html``."""
    contact_url: str = ""
    """Where the family footer's "Contact us" link points; empty keeps the registry's ``contactUrl``."""
    ga_measurement_id: str = ""
    """Google Analytics 4 measurement id. Empty (the default) keeps analytics off; set, the pages load Consent Mode v2
    (regional defaults, the first-party banner, a "Cookie settings" footer link) and the privacy-safe events."""
    privacy_policy_url: str = DEFAULT_PRIVACY_POLICY_URL
    """Where the consent banner's privacy link points; only used with ``ga_measurement_id``."""


def source_documentation_pages(config: DocsSiteConfig) -> list[Path]:
    """Every Markdown page that may be published, without the excluded ones."""
    return [
        page
        for page in sorted(config.documentation_directory.rglob("*.md"))
        if not any(
            fnmatch.fnmatchcase(page.relative_to(config.documentation_directory).as_posix(), pattern)
            for pattern in config.excluded_page_patterns
        )
    ]


def published_page_path(documentation_relative_path: str) -> str:
    """Where a documentation page lands in the staged Papyrus content layout."""
    if documentation_relative_path == INDEX_PAGE_PATH:
        return INDEX_PAGE_PATH
    return f"articles/{published_page_slug(documentation_relative_path)}.md"


def published_page_slug(documentation_relative_path: str) -> str:
    """The page's published file stem: lowercase words joined by hyphens, as the build names its pages."""
    stem = documentation_relative_path.removesuffix(".md").replace("/", "-")
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def rewrite_links_between_pages(
    page_text: str, documentation_relative_path: str, known_pages: set[str]
) -> str:
    """Point ``](other.md)`` links at the published ``.html`` of the same page."""
    source_directory = posixpath.dirname(documentation_relative_path)
    published_directory = posixpath.dirname(published_page_path(documentation_relative_path))

    def rewrite(match: re.Match[str]) -> str:
        target_path = posixpath.normpath(posixpath.join(source_directory, match.group(1)))
        if target_path.endswith(".html"):
            target_path = target_path.removesuffix(".html") + ".md"
        if target_path not in known_pages:
            return match.group(0)
        published_target = published_page_path(target_path).removesuffix(".md") + ".html"
        relative_target = posixpath.relpath(published_target, published_directory or ".")
        return f"]({relative_target}{match.group(2) or ''})"

    def rewrite_directory(match: re.Match[str]) -> str:
        directory_path = posixpath.normpath(posixpath.join(source_directory, match.group(1)))
        for index_name in DIRECTORY_INDEX_NAMES:
            candidate = posixpath.join(directory_path, index_name)
            if candidate in known_pages:
                published_target = published_page_path(candidate).removesuffix(".md") + ".html"
                relative_target = posixpath.relpath(published_target, published_directory or ".")
                return f"]({relative_target}{match.group(2) or ''})"
        return match.group(0)

    page_text = MARKDOWN_LINK_PATTERN.sub(rewrite, page_text)
    return DIRECTORY_LINK_PATTERN.sub(rewrite_directory, page_text)


def asset_path_for_documentation_file(documentation_relative_path: str) -> str:
    """Where a documentation file lands under the published ``assets/`` directory (the ``images/`` folder is flattened)."""
    prefix = f"{IMAGE_DIRECTORY_NAME}/"
    return documentation_relative_path.removeprefix(prefix)


def rewrite_image_references(
    page_text: str, documentation_relative_path: str, documentation_directory: Path
) -> tuple[str, set[str]]:
    """Point Markdown images at the published ``assets/`` copy of the file they name, wherever the page sits.

    Returns the rewritten text and the documentation-relative paths of the image files it now needs copied.
    """
    source_directory = posixpath.dirname(documentation_relative_path)
    published_directory = posixpath.dirname(published_page_path(documentation_relative_path))
    needed_files: set[str] = set()

    def rewrite(match: re.Match[str]) -> str:
        target = match.group(2)
        if re.match(r"(?:[a-z][a-z0-9+.-]*:|//|/|#)", target, re.IGNORECASE):
            return match.group(0)
        resolved = posixpath.normpath(posixpath.join(source_directory, target))
        if resolved.startswith("..") or not (documentation_directory / resolved).is_file():
            return match.group(0)
        needed_files.add(resolved)
        published = posixpath.join(PUBLISHED_ASSET_DIRECTORY_NAME, asset_path_for_documentation_file(resolved))
        relative = posixpath.relpath(published, published_directory or ".")
        return f"{match.group(1)}{relative}{match.group(3)}"

    return IMAGE_REFERENCE_PATTERN.sub(rewrite, page_text), needed_files


def rewrite_repository_links(page_text: str, documentation_relative_path: str, config: DocsSiteConfig) -> str:
    """Point relative links to files in the repository (source, README, diagrams) at their GitHub pages."""
    source_directory = posixpath.dirname(documentation_relative_path)
    repository_root = config.documentation_directory.parent

    def rewrite(match: re.Match[str]) -> str:
        target = match.group(1)
        if target.startswith(("articles/", "../assets/", "assets/")) or target.endswith(".html"):
            return match.group(0)
        docs_relative = posixpath.normpath(posixpath.join(source_directory, target))
        documentation_target = config.documentation_directory / docs_relative
        repository_relative = posixpath.normpath(posixpath.join(config.documentation_directory.name, docs_relative))
        repository_target = repository_root / repository_relative
        if documentation_target.exists() and docs_relative.endswith(".md") and not docs_relative.startswith(".."):
            return match.group(0)
        if repository_target.exists():
            kind = "tree" if repository_target.is_dir() else "blob"
            return f"]({config.source_repository_url}/{kind}/HEAD/{repository_relative}{match.group(2) or ''})"
        return match.group(0)

    return RELATIVE_LINK_PATTERN.sub(rewrite, page_text)


def stage_docs_content(config: DocsSiteConfig, staging_directory: Path) -> int:
    """Write the staged content layout and return the number of pages staged."""
    (staging_directory / "articles").mkdir()
    source_pages = source_documentation_pages(config)
    known_pages = {
        page.relative_to(config.documentation_directory).as_posix() for page in source_pages
    }
    needed_image_files: set[str] = set()
    for source_page in source_pages:
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        page_text = convert_markdown_dialects(source_page.read_text(encoding="utf-8"))
        page_text = rewrite_links_between_pages(page_text, relative_path, known_pages)
        page_text, needed_files = rewrite_image_references(
            page_text, relative_path, config.documentation_directory
        )
        needed_image_files |= needed_files
        page_text = rewrite_repository_links(page_text, relative_path, config)
        (staging_directory / published_page_path(relative_path)).write_text(
            page_text, encoding="utf-8"
        )
    image_directory = config.documentation_directory / IMAGE_DIRECTORY_NAME
    if image_directory.is_dir():
        shutil.copytree(image_directory, staging_directory / PUBLISHED_ASSET_DIRECTORY_NAME)
    for needed_file in sorted(needed_image_files):
        published_file = staging_directory / PUBLISHED_ASSET_DIRECTORY_NAME / asset_path_for_documentation_file(needed_file)
        published_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(config.documentation_directory / needed_file, published_file)
    if config.published_site_url:
        stage_generated_pages(staging_directory)
    return len(source_pages)


GENERATED_ARTICLES_INDEX_NAME = "index"
GENERATED_NOT_FOUND_NAME = "not-found"


def stage_generated_pages(staging_directory: Path) -> None:
    """Add an index of every article and a page-not-found page beside the pages the author wrote."""
    articles_directory = staging_directory / "articles"
    article_lines = [
        f"- [{page_title(article)}]({article.stem}.html)"
        for article in sorted(articles_directory.glob("*.md"))
        if article.stem not in (GENERATED_ARTICLES_INDEX_NAME, GENERATED_NOT_FOUND_NAME)
    ]
    articles_index = articles_directory / f"{GENERATED_ARTICLES_INDEX_NAME}.md"
    if not articles_index.exists():
        articles_index.write_text("# All articles\n\n" + "\n".join(article_lines) + "\n", encoding="utf-8")
    (articles_directory / f"{GENERATED_NOT_FOUND_NAME}.md").write_text(
        "# Page not found\n\nThat page does not exist. Try [all articles](index.html) or the [home page](../index.html).\n",
        encoding="utf-8",
    )


LLMS_FULL_MAX_PAGES = 200
LLMS_FULL_MAX_BYTES = 1_000_000


def git_commit_date(directory: Path, relative_path: str | None = None) -> str | None:
    """The ISO date of the last commit touching a path (or the whole checkout), or None outside git."""
    command = ["git", "-C", str(directory), "log", "-1", "--format=%cs"]
    if relative_path is not None:
        command += ["--", relative_path]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return None
    date = completed.stdout.strip()
    return date if completed.returncode == 0 and date else None


def default_last_modified(config: DocsSiteConfig) -> str:
    return git_commit_date(config.documentation_directory) or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def published_pages(output_directory: Path) -> list[str]:
    return sorted(
        page.relative_to(output_directory).as_posix()
        for page in output_directory.rglob("*.html")
        if page.name not in ("404.html", f"{GENERATED_NOT_FOUND_NAME}.html") and not is_redirect_stub(page)
    )


def write_sitemap_and_not_found_page(
    config: DocsSiteConfig,
    output_directory: Path,
    content_directory: Path | None = None,
    last_modified_by_address: dict[str, str] | None = None,
) -> None:
    """Write ``sitemap.xml`` (with ``lastmod``), a root ``404.html`` whose relative links resolve from any address, and,
    when the staged content directory is given, the agent-readable outputs (Markdown twins, ``llms.txt``, ``llms-full.txt``, ``robots.txt``)."""
    site_url = config.published_site_url
    page_addresses = published_pages(output_directory)
    fallback_date = default_last_modified(config)
    dates = last_modified_by_address or {}
    sitemap_entries = "".join(
        f"<url><loc>{html.escape(site_url + address)}</loc><lastmod>{dates.get(address, fallback_date)}</lastmod></url>"
        for address in page_addresses
    )
    (output_directory / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sitemap_entries}</urlset>',
        encoding="utf-8",
    )
    not_found_page = output_directory / "articles" / f"{GENERATED_NOT_FOUND_NAME}.html"
    base_element = f'<base href="{html.escape(site_url)}articles/">'
    (output_directory / "404.html").write_text(
        not_found_page.read_text(encoding="utf-8").replace("<head>", f"<head>{base_element}", 1),
        encoding="utf-8",
    )
    not_found_page.unlink()
    if content_directory is not None:
        write_agent_outputs(config, output_directory, content_directory, page_addresses)


def twin_text(staged_page: Path) -> tuple[str, str]:
    """The Markdown twin's text (with a title heading) and the page title."""
    text = staged_page.read_text(encoding="utf-8").strip()
    title = next((line[2:].strip() for line in text.splitlines() if line.startswith("# ")), None)
    if title is None:
        title = staged_page.stem.replace("_", " ").replace("-", " ").title()
        text = f"# {title}\n\n{text}"
    return text + "\n", title


PAGE_ACTIONS_STYLESHEET = "_plugins/papyrus-page-actions.css"


def page_actions_stylesheet() -> str:
    """The page-actions rules of the standard front end's component stylesheet (they use the ``--papyrus-*`` tokens)."""
    from papyrus_content.projection.standard.projector import ASSET_DIRECTORY

    lines = (ASSET_DIRECTORY / "markus-components.css").read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if "markus-page-actions" in line or "markus-actions-" in line or "markus-copy-md" in line) + "\n"


def add_page_actions(page_html: str, *, address: str, title: str, canonical: str) -> str:
    """Page actions at the top of a docs page that has a Markdown twin: a head link to the twin, the actions group,
    the shared stylesheet and the enhancing script. The links work without JavaScript."""
    from papyrus_content.projection.standard.config import AI_DESTINATIONS, PageActionSettings
    from papyrus_content.projection.standard.page_actions import SCRIPT_PATH, render_page_actions

    prefix = "../" * address.count("/")
    twin = address.rsplit("/", 1)[-1].removesuffix(".html") + ".md"
    actions = render_page_actions(PageActionSettings(ai=tuple(AI_DESTINATIONS)), markdown_path=twin, title=title, canonical=canonical)
    head = (
        f'<link rel="alternate" type="text/markdown" href="{html.escape(twin)}">'
        f'<link rel="stylesheet" href="{prefix}{PAGE_ACTIONS_STYLESHEET}">'
    )
    script = f'<script src="{prefix}{SCRIPT_PATH}" defer></script>'
    if "<main>" not in page_html or "</head>" not in page_html or "</body>" not in page_html:
        return page_html
    page_html = page_html.replace("</head>", head + "</head>", 1).replace("<main>", "<main>\n" + actions, 1)
    return page_html.replace("</body>", script + "</body>", 1)


def write_agent_outputs(
    config: DocsSiteConfig, output_directory: Path, content_directory: Path, page_addresses: list[str]
) -> None:
    """Markdown twins beside the pages, ``/llms.txt``, ``/llms-full.txt`` and ``/robots.txt`` (kept when the site wrote one)."""
    site_url = config.published_site_url
    entries: list[tuple[str, str, str]] = []
    wrote_actions = False
    for address in page_addresses:
        twin_address = address.removesuffix(".html") + ".md"
        staged_page = content_directory / twin_address
        if not staged_page.is_file():
            continue
        text, title = twin_text(staged_page)
        (output_directory / twin_address).write_text(text, encoding="utf-8")
        page_file = output_directory / address
        page_file.write_text(
            add_page_actions(page_file.read_text(encoding="utf-8"), address=address, title=title, canonical=site_url + address),
            encoding="utf-8",
        )
        wrote_actions = True
        entries.append((twin_address, title, text))
    if wrote_actions:
        from papyrus_content.projection.standard.page_actions import SCRIPT_PATH
        from papyrus_content.projection.standard.projector import ASSET_DIRECTORY

        plugins = output_directory / "_plugins"
        plugins.mkdir(exist_ok=True)
        (output_directory / SCRIPT_PATH).write_bytes((ASSET_DIRECTORY / "papyrus-page-actions.js").read_bytes())
        (output_directory / PAGE_ACTIONS_STYLESHEET).write_text(page_actions_stylesheet(), encoding="utf-8")
    entries.sort(key=lambda entry: (entry[0] != INDEX_PAGE_PATH, entry[0]))
    summary = config.tagline or f"Documentation for {config.site_name}."
    links = "\n".join(f"- [{title}]({site_url}{address})" for address, title, _ in entries)
    (output_directory / "llms.txt").write_text(
        f"# {config.site_name}\n\n> {summary}\n\n## Documentation\n\n{links}\n", encoding="utf-8"
    )
    if 0 < len(entries) <= LLMS_FULL_MAX_PAGES:
        full = "\n\n---\n\n".join(f"Source: {site_url}{address}\n\n{text.strip()}" for address, _, text in entries)
        encoded = f"# {config.site_name}\n\n> {summary}\n\n{full}\n".encode("utf-8")
        (output_directory / "llms-full.txt").write_bytes(encoded[:LLMS_FULL_MAX_BYTES])
    robots = output_directory / "robots.txt"
    if not robots.exists():
        robots.write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site_url}sitemap.xml\n", encoding="utf-8")


def is_redirect_stub(page: Path) -> bool:
    return 'http-equiv="refresh"' in page.read_text(encoding="utf-8")[:300]


def page_title(source_page: Path) -> str:
    for line in source_page.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return source_page.stem.replace("_", " ").replace("-", " ").title()


def automatic_navigation(config: DocsSiteConfig) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Sidebar groups from the documentation tree: top-level pages together, then one group per directory."""
    groups: dict[str, list[tuple[str, str]]] = {"Overview": [("index.html", "Overview")]}
    for source_page in source_documentation_pages(config):
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        if relative_path == INDEX_PAGE_PATH:
            continue
        directory = posixpath.dirname(relative_path)
        label = directory.replace("-", " ").replace("_", " ").title() if directory else "Guides"
        groups.setdefault(label, []).append((f"articles/{published_page_slug(relative_path)}.html", page_title(source_page)))
    return tuple((label, tuple(entries)) for label, entries in groups.items())


def render_navigation_groups(navigation_groups, page_context) -> str:
    groups = []
    for group_label, entries in navigation_groups:
        items = "".join(
            f'<li><a href="{page_context.prefix}{href}"'
            + (' aria-current="page"' if href == page_context.active_href else "")
            + f">{html.escape(label)}</a></li>"
            for href, label in entries
        )
        groups.append(
            f'<div class="site-nav-group"><p class="site-nav-label">{html.escape(group_label)}</p>'
            f'<ul class="site-nav-list">{items}</ul></div>'
        )
    return "".join(groups)


MERMAID_SCRIPT_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"

COLLAPSE_MENU_ON_NARROW_SCREENS_SCRIPT = (
    "<script>(function(){var menu=document.querySelector('.site-menu');if(!menu)return;"
    "var wide=window.matchMedia('(min-width: 1100px)');"
    "function sync(){if(wide.matches){menu.setAttribute('open','')}else if(!menu.dataset.touched){menu.removeAttribute('open')}}"
    "menu.addEventListener('toggle',function(){if(!wide.matches)menu.dataset.touched='1'});"
    "sync();wide.addEventListener('change',sync)})()</script>"
)

RENDER_MERMAID_DIAGRAMS_SCRIPT = (
    '<script type="module">'
    "const blocks=[...document.querySelectorAll('pre > code.language-mermaid')];"
    "if(blocks.length){try{"
    f"const {{default:mermaid}}=await import('{MERMAID_SCRIPT_URL}');"
    "const dark=!window.matchMedia('(prefers-color-scheme: light)').matches;"
    "mermaid.initialize({startOnLoad:false,theme:dark?'dark':'neutral'});"
    "const targets=blocks.map(function(code){const holder=document.createElement('pre');holder.className='mermaid';"
    "holder.textContent=code.textContent;code.parentElement.replaceWith(holder);return holder});"
    "await mermaid.run({nodes:targets})}catch(error){console.warn('Mermaid diagrams left as source',error)}}"
    "</script>"
)


def theme_selection_script(config: DocsSiteConfig) -> str:
    """Pick the dark theme or its light sibling from the reader's colour scheme, and follow changes."""
    light_theme = LIGHT_THEME_FOR_DARK_THEME.get(config.theme)
    if light_theme is None:
        return f"<script>document.documentElement.setAttribute('data-theme','{config.theme}')</script>"
    return (
        "<script>(function(){var light=window.matchMedia('(prefers-color-scheme: light)');"
        "function apply(){var theme=light.matches?"
        f"'{light_theme}':'{config.theme}';"
        "document.documentElement.setAttribute('data-theme',theme);"
        "document.querySelectorAll('[data-theme]').forEach(function(element){element.setAttribute('data-theme',theme)})}"
        "apply();document.addEventListener('DOMContentLoaded',apply);light.addEventListener('change',apply)})()</script>"
    )


def family_footer_stylesheet() -> str:
    """The family-footer rules of the standard front end's component stylesheet (they use the ``--papyrus-family-footer-*`` tokens)."""
    from papyrus_content.projection.standard.projector import ASSET_DIRECTORY

    lines = (ASSET_DIRECTORY / "markus-components.css").read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if "papyrus-family-footer" in line) + "\n"


def docs_site_family_footer(config: DocsSiteConfig) -> str:
    """The Anthus family footer for this docs site, rendered by the standard front end's one footer renderer."""
    from papyrus_content.projection.standard.config import FamilyFooter
    from papyrus_content.projection.standard.family import family_footer

    family = FamilyFooter(name=config.site_name, description=config.tagline, contact_url=config.contact_url)
    return family_footer(family, config.site_name, config.tagline, ())


def docs_site_chrome(config: DocsSiteConfig) -> SiteChrome:
    def render_site_banner(page_context) -> str:
        navigation_groups = config.navigation or automatic_navigation(config)
        if navigation_groups:
            return (
                '<header class="site-banner"><div class="site-topbar">'
                f'<a class="site-wordmark" href="{page_context.prefix}index.html">{config.site_name}</a>'
                f'<p class="site-tagline">{config.tagline}</p>'
                f'<nav class="site-links" aria-label="Project"><a href="{config.source_repository_url}">GitHub</a></nav>'
                '</div><details class="site-menu" open><summary>Contents</summary>'
                f'<nav class="site-sidebar" aria-label="Documentation">{render_navigation_groups(navigation_groups, page_context)}</nav>'
                "</details></header>"
            )
        navigation_links = "".join(
            f'<a href="{page_context.prefix}{item.href}"'
            + (' aria-current="page"' if item.href == page_context.active_href else "")
            + f">{item.label}</a>"
            for item in page_context.nav_items
        )
        return (
            '<header class="site-banner">'
            f'<a class="site-wordmark" href="{page_context.prefix}index.html">{config.site_name}</a>'
            f'<p class="site-tagline">{config.tagline}</p>'
            '<div class="site-nav-container">'
            f'<nav class="site-nav" aria-label="Documentation">{navigation_links}</nav></div>'
            "</header>"
        )

    return SiteChrome(
        site_name=config.site_name,
        head_html=theme_selection_script(config),
        render_masthead=render_site_banner,
        footer_html=(
            docs_site_family_footer(config)
            + (COOKIE_SETTINGS_LINK if config.ga_measurement_id else "")
            + COLLAPSE_MENU_ON_NARROW_SCREENS_SCRIPT
            + RENDER_MERMAID_DIAGRAMS_SCRIPT
        ),
        ga_measurement_id=config.ga_measurement_id or None,
        consent_mode=ConsentModeSettings(privacy_policy_url=config.privacy_policy_url) if config.ga_measurement_id else None,
    )


def write_redirects_from_former_urls(config: DocsSiteConfig, output_directory: Path) -> None:
    for source_page in source_documentation_pages(config):
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        if relative_path == INDEX_PAGE_PATH:
            continue
        published_target = f"articles/{published_page_slug(relative_path)}.html"
        former_stem = relative_path.removesuffix(".md")
        depth_prefix = "../" * (former_stem.count("/") + 1)
        former_directory = output_directory / former_stem
        former_directory.mkdir(parents=True, exist_ok=True)
        (former_directory / "index.html").write_text(
            '<!DOCTYPE html><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0; url={depth_prefix}{published_target}">'
            f'<link rel="canonical" href="{depth_prefix}{published_target}">'
            f'<a href="{depth_prefix}{published_target}">Moved to {published_target}</a>',
            encoding="utf-8",
        )


def source_last_modified(config: DocsSiteConfig) -> dict[str, str]:
    """Published page address to the date of the last commit that touched its source page."""
    dates: dict[str, str] = {}
    for source_page in source_documentation_pages(config):
        relative_path = source_page.relative_to(config.documentation_directory).as_posix()
        date = git_commit_date(config.documentation_directory, relative_path)
        if date is not None:
            dates[published_page_path(relative_path).removesuffix(".md") + ".html"] = date
    return dates


def build_docs_site(config: DocsSiteConfig, output_directory: Path) -> BuildResult:
    with tempfile.TemporaryDirectory(prefix="papyrus-docs-site-") as staging_name, tempfile.TemporaryDirectory(
        prefix="papyrus-docs-site-css-"
    ) as stylesheet_name:
        staging_directory = Path(staging_name)
        stage_docs_content(config, staging_directory)
        site_stylesheet = Path(stylesheet_name) / "site.css"
        site_stylesheet.write_text(
            (config.site_stylesheet or DEFAULT_SITE_STYLESHEET).read_text(encoding="utf-8") + family_footer_stylesheet(),
            encoding="utf-8",
        )
        result = build_markus_site(
            content_dir=staging_directory,
            out_dir=output_directory,
            theme=config.theme,
            site_css=site_stylesheet,
            chrome=docs_site_chrome(config),
        )
        if config.redirect_former_directory_urls:
            write_redirects_from_former_urls(config, output_directory)
        if config.published_site_url:
            write_sitemap_and_not_found_page(
                config,
                output_directory,
                content_directory=staging_directory,
                last_modified_by_address=source_last_modified(config),
            )
    return result


def https_address(value: str) -> str:
    """Argument type for an address a link points at: an ``https://`` URL with a host."""
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise argparse.ArgumentTypeError(f"{value!r} is not an https:// address")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a documentation site with Papyrus.")
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--tagline", default="")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--theme", default="catppuccin")
    parser.add_argument("--site-url", default="", help="Public address ending in a slash; enables sitemap.xml and 404.html.")
    parser.add_argument("--exclude", action="append", default=[], help="Glob of pages (relative to --docs) never to publish; repeatable.")
    parser.add_argument("--contact-url", default=None, type=https_address, help="Where the footer's Contact us link points (default: the Anthus registry's contact address).")
    parser.add_argument("--ga-measurement-id", default="", help="Google Analytics 4 measurement id (G-XXXXXXXXXX); omit to keep analytics off.")
    parser.add_argument("--privacy-url", default=DEFAULT_PRIVACY_POLICY_URL, type=https_address, help="Where the consent banner's privacy link points (default: the Anthus privacy policy).")
    parser.add_argument("--redirect-former-urls", action="store_true", help="Write redirects from former directory-style URLs.")
    arguments = parser.parse_args(argv)
    result = build_docs_site(
        DocsSiteConfig(
            site_name=arguments.name,
            tagline=arguments.tagline,
            documentation_directory=arguments.docs,
            source_repository_url=arguments.source_url,
            theme=arguments.theme,
            redirect_former_directory_urls=arguments.redirect_former_urls,
            published_site_url=arguments.site_url,
            contact_url=arguments.contact_url or "",
            ga_measurement_id=arguments.ga_measurement_id,
            privacy_policy_url=arguments.privacy_url,
            excluded_page_patterns=tuple(arguments.exclude),
        ),
        arguments.out,
    )
    print(f"Built {len(result.pages)} pages into {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
