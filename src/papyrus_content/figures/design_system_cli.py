"""``papyrus design-system ...``: the site's design system as backend data.

    papyrus design-system show [--version N] [--json]
    papyrus design-system pull DIR [--version N] [--force]
    papyrus design-system push DIR --reason TEXT [--author-label NAME] [--dry-run]

``show`` and ``pull`` read what the signed-in site stores; ``push`` publishes a design system folder (the site repository's, at deploy) as the next version.
A folder is ``mapping.json``, its tokens file, the fonts it names, ``examples/NAME/figure.svg`` + ``figure.json``, and an optional ``settings.json``
(``{"requireDarkFigures": true}``). ``figures render`` uses the stored design system when it is given no ``--design-system`` folder.
"""
from __future__ import annotations

import json
from pathlib import Path

from papyrus_content.guidelines import GuidelineError
from papyrus_content.options import normalize_string, parse_options, resolve_mutation_apply

from . import records
from .design_system import DesignSystemError, DirectorySource

COMMANDS = ("show", "pull", "push")
NONE_SAYS = ("design-system\tshow\tnone\tThis site has no design system. Draw with `papyrus figures render FOLDER --neutral-default` and tell the person you did, or ask for one. "
             "A site repository publishes one with `papyrus design-system push DIR --reason TEXT`.")


def route_tree() -> dict:
    return {name: {} for name in COMMANDS}


def _folder_and_flags(tokens: list[str], command: str) -> tuple[str, dict]:
    if not tokens or tokens[0].startswith("--"):
        raise ValueError(f"design-system {command} needs the design system folder: papyrus design-system {command} DIR.")
    return tokens[0], parse_options(tokens[1:])


def _version(options: dict) -> int | None:
    value = options.get("version")
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError as error:
        raise ValueError("--version must be a version number.") from error


def _described(stored: "records.StoredDesignSystem") -> dict:
    mapping = json.loads(stored.document["files"][records.MAPPING_FILE])
    row = stored.row
    return {
        "publication": stored.document.get("publication"), "version": stored.version, "itemId": stored.reference["itemId"], "contentHash": stored.reference["contentHash"],
        "savedBy": row.get("versionCreatedBy"), "savedAt": row.get("versionCreatedAt"), "reason": row.get("changeReason"),
        "figureRoles": sorted(mapping.get("figure_roles", {})), "typeRoles": sorted(mapping.get("type_roles", {})), "canvas": mapping.get("canvas", {}),
        "files": sorted(stored.document["files"]), "fonts": stored.document.get("media") or {},
        "examples": stored.source.list_examples(), "settings": stored.settings,
    }


def design_system_show(tokens: list[str], opened=None) -> int:
    options = parse_options(tokens)
    records_ = opened or records.open_records()
    stored = _read(records_, _version(options))
    if stored is None:
        if options.get("json"):
            print(json.dumps({"designSystem": None}, indent=2))
        else:
            print(NONE_SAYS)
        return 0
    info = _described(stored)
    if options.get("json"):
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    print(f"design-system\tshow\t{info['publication'] or 'this site'}\tversion {info['version']}\t{info['itemId']}")
    print(f"design-system\tshow\tsaved\t{info['savedBy']}\t{info['savedAt']}\t{info['reason']}")
    print(f"design-system\tshow\tcontent hash\t{info['contentHash']}")
    print(f"design-system\tshow\tfigure roles\t{', '.join(info['figureRoles'])}")
    print(f"design-system\tshow\ttype roles\t{', '.join(info['typeRoles'])}")
    print(f"design-system\tshow\tfonts\t{', '.join(f'{name} ({entry['byteSize']} bytes)' for name, entry in info['fonts'].items()) or 'none (a generic font family)'}")
    print(f"design-system\tshow\texamples\t{', '.join(info['examples']) or 'none'}")
    settings = info["settings"]
    print(f"design-system\tshow\tsettings\t{', '.join(f'{key} = {str(value).lower()}' for key, value in settings.items()) or 'none set'}")
    print("design-system\tshow\tnext\t`papyrus design-system pull DIR` writes these files to a folder; `papyrus figures render FOLDER` draws with this design system.")
    return 0


def design_system_pull(tokens: list[str], opened=None) -> int:
    folder, options = _folder_and_flags(tokens, "pull")
    stored = _read(opened or records.open_records(), _version(options))
    if stored is None:
        print(NONE_SAYS.replace("\tshow\t", "\tpull\t", 1))
        return 1
    target = Path(folder)
    if target.exists() and any(target.iterdir()) and not options.get("force"):
        raise ValueError(f"{folder} is not empty. Pull into a new folder, or pass --force to write over files of the same name.")
    try:
        written = stored.write_to(target)
    except DesignSystemError as error:
        raise ValueError(str(error)) from error
    for name in written:
        print(f"design-system\tpull\twrote\t{name}")
    print(f"design-system\tpull\tversion {stored.version}\t{len(written)} file(s) into {folder}")
    return 0


def design_system_push(tokens: list[str], opened=None) -> int:
    folder, options = _folder_and_flags(tokens, "push")
    apply = resolve_mutation_apply(options, "design-system push")
    reason = normalize_string(options.get("reason"))
    if not reason:
        raise ValueError("--reason is required.")
    opened = opened or records.open_records()
    source = DirectorySource(folder)
    try:
        settings = records.read_settings_file(folder)
        document, assets, current = opened.plan_push(source, settings)
    except DesignSystemError as error:
        raise ValueError(str(error)) from error
    number = int(current.get("versionNumber") or 0) + 1 if current else 1
    unchanged = current is not None and current.get("contentHash") == records.digest_of(document)
    files = [*document["files"], *assets]
    summary = (f"unchanged at version {current['versionNumber']}" if unchanged else f"version {number}") + f"\t{len(files)} file(s), {len(assets)} font(s)"
    if not apply:
        print(f"design-system\tpush\tdry run\t{summary}")
        for name in files:
            print(f"design-system\tpush\tfile\t{name}")
        return 0
    from papyrus_content.story_commands import _version_author

    actor = _version_author(options, apply, opened.client)
    try:
        result = opened.push(source, actor=actor, reason=reason, settings=settings)
    except (DesignSystemError, GuidelineError) as error:
        raise ValueError(str(error)) from error
    reference = result["reference"]
    print(f"design-system\tpush\t{'saved' if result['changed'] else 'unchanged'}\tversion {reference['versionNumber']}\t{reference['itemId']}")
    return 0


def _read(opened, version: int | None):
    try:
        return opened.read(version)
    except (DesignSystemError, GuidelineError) as error:
        raise ValueError(str(error)) from error


def command(args: list[str]) -> int:
    name, rest = (args[0] if args else ""), args[1:]
    if name == "show":
        return design_system_show(rest)
    if name == "pull":
        return design_system_pull(rest)
    if name == "push":
        return design_system_push(rest)
    raise ValueError(f"Unsupported papyrus command: design-system {name}".rstrip() + f"; the commands are {', '.join(COMMANDS)}.")
