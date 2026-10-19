"""Build a Quarto-authored book as a Papyrus documentation site.

A Quarto book project is a ``_quarto.yml`` listing chapters in parts, ``.qmd``
chapters that are almost plain Markdown, ``{file=... snippet=...}`` code fences
that pull code from the repository, and ``{{< meta KEY >}}`` shortcodes fed by
metadata files. This module turns that project into an ordinary Markdown
documentation directory in reading order, with a sidebar built from the parts,
and then renders it with :func:`build_docs_site`.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from .build import BuildResult
from .docs_site import (
    IMAGE_DIRECTORY_NAME,
    INDEX_PAGE_PATH,
    DocsSiteConfig,
    build_docs_site,
    page_title,
    published_page_slug,
)

QUARTO_PROJECT_FILE_NAME = "_quarto.yml"
CODE_INCLUDE_FENCE_PATTERN = re.compile(
    r"^(?P<fence>`{3,})[ \t]*(?P<language>[A-Za-z0-9_+-]*)[ \t]*\{(?P<attributes>[^}\n]*)\}[ \t]*\n"
    r"(?P<body>.*?)^(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
FENCE_ATTRIBUTE_PATTERN = re.compile(r'(?P<key>[A-Za-z_][A-Za-z0-9_-]*)\s*=\s*"(?P<value>[^"]*)"')
META_SHORTCODE_PATTERN = re.compile(r"\{\{<\s*meta\s+(?P<key>[A-Za-z0-9_.-]+)\s*>\}\}")
QUARTO_HEADING_CLASS_PATTERN = re.compile(r"^(#{1,6} .*?)[ \t]*\{(?:\.[A-Za-z0-9_-]+[ \t]*)+\}[ \t]*$", re.MULTILINE)
SNIPPET_MARKER_PATTERN = re.compile(r"^\s*--\s*snippet:\s*(start|end)\s+")
TRUTHY_ATTRIBUTE_VALUES = {"true", "1", "yes", "on"}
INCLUDE_PATH_ATTRIBUTE_NAMES = ("file", "include", "tac-file")
SNIPPET_ATTRIBUTE_NAMES = ("snippet", "tac-snippet")
SHOW_PATH_ATTRIBUTE_NAMES = ("show-path", "show_path", "show-file")


class BookSourceError(ValueError):
    """The book project cannot be turned into a site as written."""


@dataclass(frozen=True)
class BookChapter:
    source_path: str
    part_title: str | None


@dataclass(frozen=True)
class QuartoBook:
    title: str
    chapters: tuple[BookChapter, ...]
    metadata_file_names: tuple[str, ...]


def read_quarto_book(project_directory: Path) -> QuartoBook:
    """Read the book title, the chapters in reading order with their parts, and the metadata files."""
    project_file = project_directory / QUARTO_PROJECT_FILE_NAME
    if not project_file.is_file():
        raise BookSourceError(f"{project_file} not found")
    project = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
    book = project.get("book") or {}
    chapters: list[BookChapter] = []

    def collect(entries, part_title: str | None) -> None:
        for entry in entries:
            if isinstance(entry, str):
                chapters.append(BookChapter(entry, part_title))
            elif isinstance(entry, dict) and "chapters" in entry:
                collect(entry["chapters"], entry.get("part") or part_title)
            elif isinstance(entry, dict) and "file" in entry:
                chapters.append(BookChapter(entry["file"], part_title))
            else:
                raise BookSourceError(f"Unrecognized chapter entry in {project_file}: {entry!r}")

    collect(book.get("chapters") or [], None)
    if not chapters:
        raise BookSourceError(f"{project_file} lists no book chapters")
    return QuartoBook(
        title=str(book.get("title") or project_directory.name),
        chapters=tuple(chapters),
        metadata_file_names=tuple(project.get("metadata-files") or []),
    )


def read_book_metadata(project_directory: Path, book: QuartoBook) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for metadata_file_name in book.metadata_file_names:
        metadata_file = project_directory / metadata_file_name
        if metadata_file.is_file():
            metadata.update(yaml.safe_load(metadata_file.read_text(encoding="utf-8")) or {})
    return metadata


def substitute_meta_shortcodes(page_text: str, metadata: dict[str, object], page_name: str) -> str:
    """Replace ``{{< meta KEY >}}`` with the metadata value, failing on a key no metadata file defines."""

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        if key not in metadata:
            raise BookSourceError(f"{page_name}: metadata key '{key}' is not defined in the book's metadata files")
        return str(metadata[key])

    return META_SHORTCODE_PATTERN.sub(replace, page_text)


def first_attribute(attributes: dict[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in attributes:
            return attributes[name]
    return None


def snippet_lines(file_lines: list[str], snippet_name: str, include_path: str) -> list[str]:
    start_pattern = re.compile(rf"^\s*--\s*snippet:\s*start\s+{re.escape(snippet_name)}\s*$")
    end_pattern = re.compile(rf"^\s*--\s*snippet:\s*end\s+{re.escape(snippet_name)}\s*$")
    start_index = next((index for index, line in enumerate(file_lines) if start_pattern.match(line)), None)
    if start_index is None:
        raise BookSourceError(f"snippet:start '{snippet_name}' not found in {include_path}")
    collected: list[str] = []
    for line in file_lines[start_index + 1 :]:
        if end_pattern.match(line):
            return collected
        collected.append(line)
    raise BookSourceError(f"snippet:end '{snippet_name}' not found in {include_path}")


def line_range_bounds(attributes: dict[str, str]) -> tuple[int | None, int | None]:
    range_specification = first_attribute(attributes, ("lines", "line-range", "line_range"))
    start_attribute = first_attribute(attributes, ("start-line", "start_line"))
    end_attribute = first_attribute(attributes, ("end-line", "end_line"))
    if range_specification and (start_attribute or end_attribute):
        raise BookSourceError('use either lines="..." or start-line/end-line, not both')
    if range_specification:
        match = re.fullmatch(r"\s*(\d*)\s*(-?)\s*(\d*)\s*", range_specification)
        if not match or not (match.group(1) or match.group(3)):
            raise BookSourceError(f'invalid lines spec "{range_specification}"')
        if not match.group(2):
            return int(match.group(1)), int(match.group(1))
        return (int(match.group(1)) if match.group(1) else None, int(match.group(3)) if match.group(3) else None)
    return (
        int(start_attribute) if start_attribute else None,
        int(end_attribute) if end_attribute else None,
    )


def dedent_code_lines(lines: list[str]) -> list[str]:
    indents = [len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip()) for line in lines if line.strip()]
    minimum_indent = min(indents) if indents else 0
    if minimum_indent == 0:
        return lines
    return [line.expandtabs(4)[minimum_indent:] if line.strip() else line for line in lines]


def uncomment_if_all_comments(lines: list[str]) -> list[str]:
    nonblank_lines = [line for line in lines if line.strip()]
    if not nonblank_lines or not all(line.lstrip().startswith("--") for line in nonblank_lines):
        return lines
    return [re.sub(r"^(\s*)--[ ]?", r"\1", line, count=1) for line in lines]


def included_code_text(attributes: dict[str, str], include_path: str, project_directory: Path) -> str:
    code_file = project_directory / include_path
    if not code_file.is_file():
        raise BookSourceError(f"code include file not found: {include_path}")
    file_lines = code_file.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    snippet_name = first_attribute(attributes, SNIPPET_ATTRIBUTE_NAMES)
    lines = snippet_lines(file_lines, snippet_name, include_path) if snippet_name else file_lines
    start_line, end_line = line_range_bounds(attributes)
    if start_line is not None or end_line is not None:
        first = start_line or 1
        last = end_line or len(lines)
        if first < 1 or last < 1 or first > len(lines) or last > len(lines) or first > last:
            raise BookSourceError(f"{include_path}: requested line range {first}-{last} is out of bounds (1-{len(lines)})")
        lines = lines[first - 1 : last]
    lines = [line for line in lines if not SNIPPET_MARKER_PATTERN.match(line)]
    lines = uncomment_if_all_comments(lines)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(dedent_code_lines(lines))


def expand_code_includes(page_text: str, project_directory: Path) -> str:
    """Replace each ``{file=... snippet=...}`` fence with a plain fence holding the included code."""

    def expand(match: re.Match[str]) -> str:
        attributes = {found.group("key"): found.group("value") for found in FENCE_ATTRIBUTE_PATTERN.finditer(match.group("attributes"))}
        include_path = first_attribute(attributes, INCLUDE_PATH_ATTRIBUTE_NAMES)
        if include_path is None:
            return match.group(0)
        fence = match.group("fence")
        code = included_code_text(attributes, include_path, project_directory)
        longest_backtick_run = max((len(run) for run in re.findall(r"`+", code)), default=0)
        fence = "`" * max(len(fence), longest_backtick_run + 1)
        show_path = (first_attribute(attributes, SHOW_PATH_ATTRIBUTE_NAMES) or "").lower() in TRUTHY_ATTRIBUTE_VALUES
        path_label = f"Source: `{include_path}`\n\n" if show_path else ""
        return f"{path_label}{fence}{match.group('language')}\n{code}\n{fence}"

    return CODE_INCLUDE_FENCE_PATTERN.sub(expand, page_text)


def markdown_page_path(chapter_source_path: str) -> str:
    """The chapter's path as a Markdown page; the first chapter becomes the site's index page."""
    return posixpath.splitext(chapter_source_path)[0] + ".md"


def strip_quarto_heading_classes(page_text: str) -> str:
    """Drop Quarto-only heading classes such as ``{.unnumbered}``; ``{#id}`` anchors stay."""
    return QUARTO_HEADING_CLASS_PATTERN.sub(r"\1", page_text)


def materialize_book_as_documentation(project_directory: Path, documentation_directory: Path) -> tuple[QuartoBook, tuple]:
    """Write the book's chapters as Markdown pages in reading order and return the sidebar navigation."""
    book = read_quarto_book(project_directory)
    metadata = read_book_metadata(project_directory, book)
    navigation_groups: list[tuple[str, list[tuple[str, str]]]] = []
    for position, chapter in enumerate(book.chapters):
        source_file = project_directory / chapter.source_path
        if not source_file.is_file():
            raise BookSourceError(f"chapter listed in {QUARTO_PROJECT_FILE_NAME} not found: {chapter.source_path}")
        page_path = INDEX_PAGE_PATH if position == 0 else markdown_page_path(chapter.source_path)
        page_text = source_file.read_text(encoding="utf-8")
        page_text = substitute_meta_shortcodes(page_text, metadata, chapter.source_path)
        page_text = expand_code_includes(page_text, project_directory)
        page_text = strip_quarto_heading_classes(page_text)
        staged_file = documentation_directory / page_path
        staged_file.parent.mkdir(parents=True, exist_ok=True)
        staged_file.write_text(page_text, encoding="utf-8")
        href = "index.html" if position == 0 else f"articles/{published_page_slug(page_path)}.html"
        label = page_title(staged_file)
        group_label = chapter.part_title or book.title
        if not navigation_groups or navigation_groups[-1][0] != group_label:
            navigation_groups.append((group_label, []))
        navigation_groups[-1][1].append((href, label))
    image_directory = project_directory / IMAGE_DIRECTORY_NAME
    if image_directory.is_dir():
        shutil.copytree(image_directory, documentation_directory / IMAGE_DIRECTORY_NAME)
    navigation = tuple((label, tuple(entries)) for label, entries in navigation_groups)
    return book, navigation


def write_redirects_from_former_chapter_urls(book: QuartoBook, output_directory: Path) -> None:
    """Keep Quarto's ``chapters/NAME.html`` addresses working by redirecting each to the published page."""
    for position, chapter in enumerate(book.chapters):
        former_path = posixpath.splitext(chapter.source_path)[0] + ".html"
        target = "index.html" if position == 0 else f"articles/{published_page_slug(markdown_page_path(chapter.source_path))}.html"
        if former_path == target:
            continue
        depth_prefix = "../" * former_path.count("/")
        former_file = output_directory / former_path
        former_file.parent.mkdir(parents=True, exist_ok=True)
        former_file.write_text(
            '<!DOCTYPE html><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0; url={depth_prefix}{target}">'
            f'<link rel="canonical" href="{depth_prefix}{target}">'
            f'<a href="{depth_prefix}{target}">Moved to {target}</a>',
            encoding="utf-8",
        )


def build_book_site(
    project_directory: Path,
    output_directory: Path,
    *,
    site_name: str | None = None,
    tagline: str = "",
    source_repository_url: str,
    theme: str = "catppuccin",
    published_site_url: str = "",
) -> BuildResult:
    with tempfile.TemporaryDirectory(prefix="papyrus-book-site-") as work_name:
        documentation_directory = Path(work_name) / "docs"
        documentation_directory.mkdir()
        book, navigation = materialize_book_as_documentation(project_directory, documentation_directory)
        result = build_docs_site(
            DocsSiteConfig(
                site_name=site_name or book.title,
                tagline=tagline,
                documentation_directory=documentation_directory,
                source_repository_url=source_repository_url,
                theme=theme,
                navigation=navigation,
                published_site_url=published_site_url,
            ),
            output_directory,
        )
    write_redirects_from_former_chapter_urls(book, output_directory)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a Quarto-authored book as a Papyrus site.")
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=Path("_site"))
    parser.add_argument("--name")
    parser.add_argument("--tagline", default="")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--theme", default="catppuccin")
    parser.add_argument("--site-url", default="")
    arguments = parser.parse_args(argv)
    result = build_book_site(
        arguments.project,
        arguments.out,
        site_name=arguments.name,
        tagline=arguments.tagline,
        source_repository_url=arguments.source_url,
        theme=arguments.theme,
        published_site_url=arguments.site_url,
    )
    print(f"Built {len(result.pages)} pages into {result.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
