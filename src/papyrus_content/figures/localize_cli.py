"""``papyrus figures localize`` and ``papyrus figures variant``: a language variant of a figure, optional and never required.

    papyrus figures localize FOLDER --story STORY --language LANGUAGE [--design-system DIR | --neutral-default] [--out DIR] [--check-only] [--json]
                             [--save --reason TEXT [--original STORED_PATH] [--author-label NAME] [--dry-run]]
    papyrus figures variant --story STORY --language LANGUAGE --original STORED_PATH --light FILE [--dark FILE] [--alt TEXT] [--caption TEXT]
                             --reason TEXT [--author-label NAME] [--dry-run]

``localize`` takes a figure's folder (``figure.svg`` and ``figure.json``, as ``figures render`` does), translates only its ``<text>`` content, its alt text and
its caption into the language (the Story's glossary, the language's register notes, the language's Humanus copy-edit pack and the bilingual judge, as the
Story's own translation runs), writes a figure folder for the language (``SLUG-LANGUAGE``, ``localizedFrom`` naming the original), and renders it to a light
and a dark picture with the same checks as any figure (a label that grows past its shape or collides with another fails there). The Humanus findings are
advice and are printed; nothing blocks. With ``--save`` the pictures are saved into the Story's translation as its variant of the original picture.
``variant`` is the manual path for any picture, a raster image included: the files you give become the language variant (``--dark`` is the dark-mode picture).
Both write to the translation (``STORY--LANGUAGE``) only, never to the original Story, and a translation without a variant simply keeps showing the original.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from .renderer import FigureResult, RendererUnavailable, load_figure, open_browser, render_figure
from .text import replace_segments, text_segments


def _flags(tokens: list[str], values: tuple[str, ...], switches: tuple[str, ...]):
    from .cli import _split

    return _split(tokens, values, switches)


def _source_slug(metadata: dict, folder: Path) -> str:
    return str(metadata.get("slug") or folder.name)


def write_language_folder(folder: Path, language: str, words: dict, out_root: Path) -> Path:
    """The figure folder for ``language``: the source with its text replaced, and a ``figure.json`` that names the original and carries the translated alt
    text and caption. The slug carries the language so the pictures and the sidecar never collide with the original's."""
    source, metadata = load_figure(folder)
    slug = f"{_source_slug(metadata, folder)}-{language.lower()}"
    target = out_root / slug
    target.mkdir(parents=True, exist_ok=True)
    (target / "figure.svg").write_text(replace_segments(source, words["labels"]), encoding="utf-8")
    localized = {**metadata, "slug": slug, "localizedFrom": _source_slug(metadata, folder), "language": language}
    if words.get("alt"):
        localized["alt"] = words["alt"]
    if words.get("caption"):
        localized["caption"] = words["caption"]
    (target / "figure.json").write_text(json.dumps(localized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def figures_localize(tokens: list[str]) -> int:
    from .cli import resolve_design_system
    from ..graphql_authoring import create_authoring_client
    from ..localize.figure_labels import translate_figure_words

    folders, options = _flags(tokens, ("--design-system", "--out", "--story", "--language", "--reason", "--original", "--author-label"),
                              ("--neutral-default", "--check-only", "--json", "--save", "--dry-run"))
    if len(folders) != 1:
        raise ValueError("figures localize takes one figure folder (holding figure.svg and figure.json).")
    story, language = options.get("--story"), options.get("--language")
    if not story or not language:
        raise ValueError("figures localize needs --story and --language: the Story's glossary and register notes translate the words, and the Story names the language's lineage.")
    if options.get("--save") and not options.get("--reason"):
        raise ValueError("--save needs --reason TEXT, the change reason of the version it saves.")
    folder = Path(folders[0])
    source, metadata = load_figure(folder)
    labels = text_segments(source)
    if not labels:
        print(f"{_source_slug(metadata, folder)}: nothing to localize: the figure holds no text, so every language reads the same picture.")
        return 0
    client, _ = create_authoring_client()
    words = translate_figure_words(client, story=str(story), language=str(language), labels=labels, alt=str(metadata.get("alt") or ""),
                                   caption=str(metadata.get("caption") or ""))
    language = words["language"]
    out_root = Path(str(options["--out"])) if options.get("--out") else folder.parent
    written = write_language_folder(folder, language, words, out_root)
    for label in labels:
        print(f"{written.name}: label: {label} -> {words['labels'][label]}")
    for finding in words["findings"]:
        print(f"{written.name}: note: {finding['policy']} ({finding['severity']}) on \"{finding['block']}\": {finding['message']}")
    try:
        design_system = resolve_design_system(options)
        with open_browser() as browser:
            result: FigureResult = render_figure(browser, written, design_system, written.parent / "pictures" if not options.get("--check-only") else None,
                                                 write_pictures=not options.get("--check-only"))
    except RendererUnavailable as error:
        raise ValueError(str(error)) from error
    for warning in result.warnings:
        print(f"{result.slug}: note: {warning}")
    for problem in result.problems:
        print(f"{result.slug}: PROBLEM: {problem}")
    print(f"{result.slug}: {'ok' if result.ok else 'FAILED'}")
    if options.get("--json"):
        print(json.dumps({"figure": result.as_dict(), "labels": words["labels"], "findings": words["findings"], "costUsd": words["costUsd"]}, indent=2, ensure_ascii=False))
    if not result.ok or options.get("--check-only"):
        return 0 if result.ok else 1
    pictures = Path(result.files[0]).parent
    light, dark = pictures / f"{result.slug}.png", pictures / f"{result.slug}.dark.png"
    original = options.get("--original") or _original_path(client, str(story), _source_slug(metadata, folder), language)
    if not options.get("--save"):
        print(f"{result.slug}: pictures are in {pictures}. Save them as the {language} variant with: papyrus figures variant --story {story} --language {language} "
              f"--original {original} --light {light} --dark {dark} --alt \"{words['alt']}\" --caption \"{words['caption']}\" --reason \"...\"")
        return 0
    return _save(client, options, story=str(story), language=language, original=str(original), light=light, dark=dark,
                 texts={"alt": words["alt"], "caption": words["caption"]})


def _original_path(client, story: str, figure_slug: str, language: str) -> str:
    """The stored path of the original figure: the picture of the Story's published body whose file name is the figure's slug."""
    from ..item_language import localization_lineage_id
    from ..markus_renderer.content_markup import _IMAGE_DIRECTIVE_RE, parse_attrs
    from ..story_reporting import current_story_version

    body = current_story_version(client, story).get("bodyMarkus") or ""
    for match in _IMAGE_DIRECTIVE_RE.finditer(body):
        src = parse_attrs(match.group("attrs")).get("src") or ""
        if re.fullmatch(rf"{re.escape(figure_slug)}(-\d+)?\.(png|jpe?g|webp|svg)", src.rsplit("/", 1)[-1], re.I):
            return src.lstrip("/")
    raise ValueError(f"the Story's body shows no picture named {figure_slug}; pass --original with the stored path of the picture this figure stands in for "
                     f"(the src of its ::image line, see `papyrus stories pull`). The translation is {localization_lineage_id(story, language)}.")


def _save(client, options: dict, *, story: str, language: str, original: str, light: Path, dark: Path | None, texts: dict[str, str]) -> int:
    from ..localize.image_save import save_variant
    from ..options import resolve_mutation_apply
    from ..story_commands import _version_author

    plain = {key.removeprefix("--"): value for key, value in options.items()}
    apply = resolve_mutation_apply(plain, "figures variant")
    author = _version_author(plain, apply, client)
    for line in save_variant(client, story=story, language=language, original=original, light=light, dark=dark, reason=str(options["--reason"]), author=author,
                             texts={key: value for key, value in texts.items() if value}, apply=apply):
        print(line)
    return 0


def figures_variant(tokens: list[str]) -> int:
    from ..graphql_authoring import create_authoring_client

    folders, options = _flags(tokens, ("--story", "--language", "--original", "--light", "--dark", "--alt", "--caption", "--reason", "--author-label"), ("--dry-run",))
    if folders:
        raise ValueError(f"figures variant takes flags, not {folders[0]}.")
    for flag in ("--story", "--language", "--original", "--light", "--reason"):
        if not options.get(flag):
            raise ValueError(f"figures variant needs {flag}.")
    light = Path(str(options["--light"]))
    dark = Path(str(options["--dark"])) if options.get("--dark") else None
    for path in (light, dark):
        if path is not None and not path.is_file():
            raise ValueError(f"{path} is not a file.")
    client, _ = create_authoring_client()
    return _save(client, options, story=str(options["--story"]), language=str(options["--language"]), original=str(options["--original"]), light=light, dark=dark,
                 texts={key: str(options[flag]) for key, flag in (("alt", "--alt"), ("caption", "--caption")) if options.get(flag)})
