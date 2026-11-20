"""The procedure registry: which Tactus file runs for which procedure kind, and the check that keeps the two honest.

A procedure file declares its kind on its first line (`-- papyrus-procedure-kind: <kind>`). The registry
(`procedures` in `papyrus-required-procedures.json`) maps each kind to its file name in the wheel's `papyrus_content/data/procedures/`, and `requiredCliProcedures` maps each CLI alias to
a kind. `check_procedure_registry` compares all three and names every disagreement; `validate_procedure_registry` raises on any.
`procedureMetadata` holds, for each kind, the title, category, description, parameter schema and defaults the deploy registers it with (the one
source: nothing in code repeats them). `python -m papyrus_content.procedure_registry` is the CI check.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .env import packaged_procedures_directory, resolve_corpora_file, resolve_procedure_file

REGISTRY_CONFIG_RELATIVE = "corpora/papyrus-required-procedures.json"
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


def discover_procedure_files() -> dict[str, str]:
    """Every procedure file the wheel ships (papyrus_content/data/procedures), as {file name: source}, read with importlib.resources."""
    entries = [entry for entry in packaged_procedures_directory().iterdir() if entry.name.endswith(".tac")]
    return {entry.name: entry.read_text(encoding="utf-8") for entry in sorted(entries, key=lambda entry: entry.name)}


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
    problems.extend(_metadata_problems(config.get("procedureMetadata"), registry))
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


_METADATA_TEXT_FIELDS = ("title", "category", "description")
_METADATA_OBJECT_FIELDS = ("parameterSchema", "defaults")
DEFAULT_TOKENS = ("$defaultLlmModel", "$defaultCorpusKey")


def _metadata_problems(metadata: Any, registry: Mapping[str, str]) -> list[str]:
    if not isinstance(metadata, dict):
        return ["The registry has no `procedureMetadata` map from kind to title, category, description, parameter schema and defaults."]
    problems: list[str] = []
    for kind in registry:
        entry = metadata.get(kind)
        if not isinstance(entry, dict):
            problems.append(f"The registry has no metadata for the kind {kind}.")
            continue
        for field in _METADATA_TEXT_FIELDS:
            if not isinstance(entry.get(field), str) or not entry[field].strip():
                problems.append(f"The metadata for {kind} has no {field}.")
        for field in _METADATA_OBJECT_FIELDS:
            if not isinstance(entry.get(field), dict):
                problems.append(f"The metadata for {kind} has no {field} object.")
        for name, value in (entry.get("defaults") or {}).items() if isinstance(entry.get("defaults"), dict) else []:
            if isinstance(value, str) and value.startswith("$") and value not in DEFAULT_TOKENS:
                problems.append(f"The metadata for {kind} sets the default {name} to {value}, which is not one of {', '.join(DEFAULT_TOKENS)}.")
    for kind in metadata:
        if kind not in registry:
            problems.append(f"The registry has metadata for {kind}, which is not a registered kind.")
    return problems


def registered_kinds() -> list[str]:
    return sorted(load_registry_config().get("procedures") or {})


def procedure_metadata_for_kind(kind: str) -> dict[str, Any]:
    metadata = (load_registry_config().get("procedureMetadata") or {}).get(kind)
    if metadata is None:
        raise ProcedureRegistryError(f"The registry has no metadata for the kind {kind}.")
    return metadata


def validate_procedure_registry() -> None:
    problems = check_procedure_registry(load_registry_config(), discover_procedure_files())
    if problems:
        raise ProcedureRegistryError("The procedure registry does not match the procedure files:\n- " + "\n- ".join(problems))


def procedure_file_for_kind(kind: str) -> Path:
    """The file that runs for a kind: the checkout's copy when there is one, else the packaged copy; it must declare that kind."""
    registry = load_registry_config().get("procedures") or {}
    if kind not in registry:
        raise ProcedureRegistryError(f"No procedure is registered for the kind {kind}.")
    path = resolve_procedure_file(registry[kind])
    if not path.is_file():
        raise ProcedureRegistryError(f"The procedure file {registry[kind]} for the kind {kind} is not in this install.")
    if declared_kind(path.read_text(encoding="utf-8")) != kind:
        raise ProcedureRegistryError(f"{path} does not declare the kind {kind}.")
    return path


def procedure_source_for_kind(kind: str) -> str:
    return procedure_file_for_kind(kind).read_text(encoding="utf-8")


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
