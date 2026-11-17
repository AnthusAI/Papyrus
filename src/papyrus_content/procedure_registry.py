"""The procedure registry: which Tactus file runs for which procedure kind, and the check that keeps the two honest.

A procedure file declares its kind on its first line (`-- papyrus-procedure-kind: <kind>`). The registry
(`procedures` in `papyrus-required-procedures.json`) maps each kind to its file, and `requiredCliProcedures` maps each CLI alias to
a kind. `check_procedure_registry` compares all three and names every disagreement; `validate_procedure_registry` raises on any.
`python -m papyrus_content.procedure_registry` is the CI check.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .env import PAPYRUS_ROOT, resolve_corpora_file

REGISTRY_CONFIG_RELATIVE = "corpora/papyrus-required-procedures.json"
PROCEDURE_DIRECTORY = Path("procedures") / "newsroom"
_KIND_HEADER = re.compile(r"^--[ \t]*papyrus-procedure-kind:[ \t]*(\S+)[ \t]*$")


class ProcedureRegistryError(ValueError):
    pass


def declared_kind(source: str) -> str | None:
    """The kind a procedure source declares on its first line, or None."""
    first_line = source.split("\n", 1)[0].rstrip("\r")
    match = _KIND_HEADER.match(first_line)
    return match.group(1) if match else None


def load_registry_config() -> dict[str, Any]:
    path = resolve_corpora_file(REGISTRY_CONFIG_RELATIVE)
    return json.loads(path.read_text(encoding="utf-8"))


def discover_procedure_files(root: Path = PAPYRUS_ROOT) -> dict[str, str]:
    """Every procedure file under `<root>/procedures/newsroom`, as {path relative to root: source}."""
    directory = root / PROCEDURE_DIRECTORY
    return {path.relative_to(root).as_posix(): path.read_text(encoding="utf-8") for path in sorted(directory.glob("*.tac"))}


def check_procedure_registry(config: Mapping[str, Any], files: Mapping[str, str]) -> list[str]:
    """Every way the registry, the CLI aliases and the files' own headers disagree, as plain sentences; empty when they agree."""
    registry = config.get("procedures")
    aliases = config.get("requiredCliProcedures")
    if not isinstance(registry, dict) or not registry:
        return ["The registry has no `procedures` map from kind to file."]
    problems: list[str] = []
    kinds_by_path: dict[str, str] = {}
    for path, source in files.items():
        kind = declared_kind(source)
        if kind is None:
            problems.append(f"{path} does not declare its kind on its first line (-- papyrus-procedure-kind: <kind>).")
        elif kind in kinds_by_path.values():
            other = next(other_path for other_path, other_kind in kinds_by_path.items() if other_kind == kind)
            problems.append(f"{path} and {other} both declare the kind {kind}.")
        else:
            kinds_by_path[path] = kind
    for kind, path in registry.items():
        if path not in files:
            problems.append(f"The registry sends {kind} to {path}, which is not a procedure file.")
        elif declared_kind(files[path]) != kind:
            problems.append(f"The registry sends {kind} to {path}, which declares {declared_kind(files[path]) or 'no kind'}.")
    registered_paths = set(registry.values())
    for path in files:
        if path not in registered_paths:
            problems.append(f"{path} is a procedure file the registry does not list.")
    if not isinstance(aliases, dict):
        problems.append("The registry has no `requiredCliProcedures` map from CLI command to kind.")
    else:
        for alias, kind in aliases.items():
            if kind not in registry:
                problems.append(f"The CLI command {alias} needs the kind {kind}, which the registry does not list.")
    return problems


def validate_procedure_registry(root: Path = PAPYRUS_ROOT) -> None:
    problems = check_procedure_registry(load_registry_config(), discover_procedure_files(root))
    if problems:
        raise ProcedureRegistryError("The procedure registry does not match the procedure files:\n- " + "\n- ".join(problems))


def procedure_path_for_kind(kind: str, root: Path = PAPYRUS_ROOT) -> Path:
    """The file that runs for a kind, after checking that the file declares that kind."""
    registry = load_registry_config().get("procedures") or {}
    if kind not in registry:
        raise ProcedureRegistryError(f"No procedure is registered for the kind {kind}.")
    path = root / registry[kind]
    if declared_kind(path.read_text(encoding="utf-8")) != kind:
        raise ProcedureRegistryError(f"{registry[kind]} does not declare the kind {kind}.")
    return path


def main() -> int:
    try:
        validate_procedure_registry()
    except ProcedureRegistryError as error:
        print(error, file=sys.stderr)
        return 1
    print("The procedure registry matches the procedure files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
