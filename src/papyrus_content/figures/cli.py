"""``papyrus figures ...``: render, check and describe figures. Everything here is local; nothing reaches a site.

    papyrus figures render FOLDER... (--design-system DIR | --neutral-default) [--out DIR] [--check-only] [--json]
    papyrus figures directive FOLDER
    papyrus figures rules
    papyrus figures primitives

Exit status: 0 when every figure passed, 1 when any had a problem. A usage error raises ``ValueError`` like the other commands.
"""
from __future__ import annotations

import json
from pathlib import Path

from .checks import image_directive
from .design_system import DesignSystem, DesignSystemError, DirectorySource, load_design_system
from .neutral import neutral_design_system
from .renderer import FigureResult, RendererUnavailable, load_metadata, open_browser, packaged_text, render_figure

COMMANDS = ("render", "directive", "rules", "primitives")


def route_tree() -> dict:
    return {name: {} for name in COMMANDS}


def _split(tokens: list[str], value_flags: tuple[str, ...], switch_flags: tuple[str, ...]) -> tuple[list[str], dict[str, str | bool]]:
    positional: list[str] = []
    options: dict[str, str | bool] = {}
    pending = list(tokens)
    while pending:
        token = pending.pop(0)
        flag, equals, inline = token.partition("=")
        if flag in value_flags:
            if equals:
                options[flag] = inline
            elif pending and not pending[0].startswith("--"):
                options[flag] = pending.pop(0)
            else:
                raise ValueError(f"{flag} needs a value.")
        elif flag in switch_flags and not equals:
            options[flag] = True
        elif token.startswith("--"):
            raise ValueError(f"Unknown flag {token}; `papyrus figures --help` lists the commands.")
        else:
            positional.append(token)
    return positional, options


def resolve_design_system(options: dict[str, str | bool]) -> DesignSystem:
    """The design system the flags name. With neither flag there is none: a figure is never drawn in an invented house style."""
    directory, neutral = options.get("--design-system"), bool(options.get("--neutral-default"))
    if directory and neutral:
        raise ValueError("Pass --design-system DIR or --neutral-default, not both.")
    if directory:
        return load_design_system(DirectorySource(str(directory)))
    if neutral:
        return neutral_design_system()
    raise ValueError(
        "No design system. Read the site's design system and pass its folder with --design-system DIR. If the site has none, "
        "pass --neutral-default for the unbranded default and say so in your note to the person; never invent a brand."
    )


def _print_result(result: FigureResult) -> None:
    for warning in result.warnings:
        print(f"{result.slug}: note: {warning}")
    for problem in result.problems:
        print(f"{result.slug}: PROBLEM: {problem}")
    print(f"{result.slug}: {'ok' if result.ok else 'FAILED'}")


def figures_render(tokens: list[str]) -> int:
    folders, options = _split(tokens, ("--design-system", "--out"), ("--neutral-default", "--check-only", "--json"))
    if not folders:
        raise ValueError("figures render needs at least one figure folder (a folder holding figure.svg and figure.json).")
    out_dir = Path(str(options["--out"])) if options.get("--out") else None
    if out_dir is not None and len(folders) > 1:
        raise ValueError("--out takes one figure folder; render several figures without --out and each writes next to its source.")
    try:
        design_system = resolve_design_system(options)
        results: list[FigureResult] = []
        with open_browser() as browser:
            for folder in folders:
                try:
                    results.append(render_figure(browser, Path(folder), design_system, out_dir, write_pictures=not options.get("--check-only")))
                except ValueError as error:
                    results.append(FigureResult(Path(folder).name, problems=[str(error)]))
    except (DesignSystemError, RendererUnavailable) as error:
        raise ValueError(str(error)) from error
    if options.get("--json"):
        print(json.dumps({"design_system": design_system.name, "figures": [result.as_dict() for result in results]}, indent=2))
    else:
        for result in results:
            _print_result(result)
    return 0 if all(result.ok for result in results) else 1


def figures_directive(tokens: list[str]) -> int:
    folders, _ = _split(tokens, (), ())
    if len(folders) != 1:
        raise ValueError("figures directive takes one figure folder.")
    metadata = load_metadata(Path(folders[0]))
    missing = [key for key in ("slug", "layout", "alt", "caption", "credit") if not metadata.get(key)]
    if missing:
        raise ValueError(f"figure.json is missing {', '.join(missing)}.")
    print(image_directive(metadata))
    return 0


def command(args: list[str]) -> int:
    name, rest = (args[0] if args else ""), args[1:]
    if name == "render":
        return figures_render(rest)
    if name == "directive":
        return figures_directive(rest)
    if name in ("rules", "primitives"):
        _split(rest, (), ())
        print(packaged_text("rules.md" if name == "rules" else "primitives.svg"), end="")
        return 0
    raise ValueError(f"Unsupported papyrus command: figures {name}".rstrip() + f"; the commands are {', '.join(COMMANDS)}.")
