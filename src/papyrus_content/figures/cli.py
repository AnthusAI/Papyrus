"""``papyrus figures ...``: render, check and describe figures. ``render`` and ``rules`` read the signed-in site's design system and figure rules; nothing is written to a site.

    papyrus figures render FOLDER... [--design-system DIR | --neutral-default] [--out DIR] [--check-only] [--json]
    papyrus figures directive FOLDER
    papyrus figures rules [--packaged]
    papyrus figures primitives

With neither ``--design-system`` nor ``--neutral-default``, ``render`` uses the design system the signed-in site stores (``papyrus design-system show``); a folder
given with ``--design-system`` overrides it. With none stored there is no default: it stops and says to use the neutral default or ask.

Exit status: 0 when every figure passed, 1 when any had a problem. A usage error raises ``ValueError`` like the other commands.
"""
from __future__ import annotations

import json
import sys
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


def no_design_system(reason: str = "") -> str:
    return (
        "No design system" + (f": {reason}" if reason else ".") + " A figure is never drawn in an invented house style. If the site has one, sign in to it (`papyrus login`) "
        "and `figures render` uses it, or pass a folder with --design-system DIR (`papyrus design-system pull DIR` writes the site's). If the site has none, "
        "pass --neutral-default for the unbranded default and say so in your note to the person; never invent a brand."
    )


def stored_design_system() -> DesignSystem:
    """The design system the signed-in site stores. Raises ``ValueError`` saying what to do when it cannot be read or the site has none."""
    from . import records

    try:
        stored = records.open_records().read()
    except DesignSystemError as error:
        raise ValueError(str(error)) from error
    except Exception as error:  # noqa: BLE001 - not signed in, no endpoint, offline: the reason is shown, and nothing is guessed
        raise ValueError(no_design_system(f"reading the site's design system failed ({error}).")) from error
    if stored is None:
        raise ValueError(no_design_system("the site stores none."))
    print(f"figures: using the site's stored design system, {stored.document.get('publication') or 'this site'} version {stored.version}", file=sys.stderr)
    return load_design_system(stored.source)


def rules_text(*, packaged_only: bool = False) -> str:
    """The figure rules of the signed-in site (its own, when it saved them), or the packaged general rules. Where the site cannot be reached the packaged
    rules are printed and the reason goes to stderr, so a person or agent never takes them for the site's own."""
    packaged = packaged_text("rules.md")
    if packaged_only:
        return packaged
    from papyrus_content.guidelines.figure_rules import figure_rules

    try:
        from papyrus_content.graphql_authoring import create_authoring_client

        client, _ = create_authoring_client()
        found = figure_rules(client, packaged)
    except Exception as error:  # noqa: BLE001 - not signed in, no endpoint, offline
        print(f"figures: could not read the site's figure rules ({error}); these are the packaged general rules.", file=sys.stderr)
        return packaged
    whose = "the site's own" if found["source"] == "site" else "the packaged general"
    version = f", version {found['reference']['versionNumber']}" if found["reference"] else ""
    print(f"figures: using {whose} figure rules{version}", file=sys.stderr)
    return found["text"]


def resolve_design_system(options: dict[str, str | bool]) -> DesignSystem:
    """The design system the flags name; with neither, the one the signed-in site stores. Never an invented one."""
    directory, neutral = options.get("--design-system"), bool(options.get("--neutral-default"))
    if directory and neutral:
        raise ValueError("Pass --design-system DIR or --neutral-default, not both.")
    if directory:
        return load_design_system(DirectorySource(str(directory)))
    if neutral:
        return neutral_design_system()
    return stored_design_system()


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
    if name == "rules":
        _, options = _split(rest, (), ("--packaged",))
        print(rules_text(packaged_only=bool(options.get("--packaged"))), end="")
        return 0
    if name == "primitives":
        _split(rest, (), ())
        print(packaged_text("primitives.svg"), end="")
        return 0
    raise ValueError(f"Unsupported papyrus command: figures {name}".rstrip() + f"; the commands are {', '.join(COMMANDS)}.")
