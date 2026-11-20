"""Registering every core and site procedure when a site deploys (`papyrus procedures seed-required`).

Git is the source of truth. The core procedures are the files in the wheel, listed with their title, category, description, parameter schema
and defaults in `papyrus-required-procedures.json` (`procedures` and `procedureMetadata`, checked by `procedure_registry`). A site's own
procedures are listed in the site's `papyrus-site-procedures.json` and live in the site's repository. Each becomes a ProcedureDefinition and
a published ProcedureVersion whose id carries a digest of the source and what it is registered with, so a deploy of unchanged files writes
nothing and a change publishes a new version and archives the old one (`site_procedures.register_site_procedure`).

Nothing falls back. An unknown kind, a missing file, a file that declares another kind, or a site kind that takes a core kind's name
(unless the site names it under `overrides`) raises `ProcedureDeployError` before anything is written.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .ids import safe_id
from .procedure_registry import (
    ProcedureRegistryError,
    declared_kind,
    procedure_metadata_for_kind,
    procedure_source_for_kind,
    registered_kinds,
    validate_procedure_registry,
)
from .site_procedures import plan_status, register_site_procedure, registration_plan, source_digest

SITE_REGISTRY_FILE = "papyrus-site-procedures.json"
SITE_REGISTRY_VERSION = 1


class ProcedureDeployError(ValueError):
    pass


class ProcedureDriftError(ProcedureDeployError):
    pass


def _default_tokens() -> dict[str, Callable[[], str]]:
    from .model_defaults import DEFAULT_LLM_MODEL
    from .steering import default_corpus_key

    return {"$defaultLlmModel": lambda: DEFAULT_LLM_MODEL, "$defaultCorpusKey": default_corpus_key}


def resolve_defaults(defaults: dict[str, Any]) -> dict[str, Any]:
    tokens = _default_tokens()
    return {name: tokens[value]() if isinstance(value, str) and value.startswith("$") else value for name, value in defaults.items()}


def core_plan(kind: str) -> dict[str, Any]:
    """The registration of one core kind, from the packaged source and the registry's metadata."""
    metadata = procedure_metadata_for_kind(kind)
    source = procedure_source_for_kind(kind)
    registered_with = {**metadata, "defaults": resolve_defaults(metadata["defaults"])}
    digest = source_digest(source, [("metadata.json", json.dumps(registered_with, sort_keys=True).encode("utf-8"))])
    slug = safe_id(kind)[:120]
    return {
        "procedureKey": kind,
        "procedureId": f"procedure-definition-{slug}",
        "versionId": f"procedure-version-{slug}-{digest}",
        "contentDigest": digest,
        "title": metadata["title"],
        "category": metadata["category"],
        "description": metadata["description"],
        "sourcePath": f"papyrus_content/data/procedures/{kind}",
        "source": source,
        "parameterSchema": metadata["parameterSchema"],
        "defaults": registered_with["defaults"],
        "skills": [],
        "origin": "core",
    }


def core_plans() -> list[dict[str, Any]]:
    try:
        validate_procedure_registry()
        return [core_plan(kind) for kind in registered_kinds()]
    except ProcedureRegistryError as error:
        raise ProcedureDeployError(str(error)) from error


def load_site_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ProcedureDeployError(f"The site procedure registry {path} is not there.")
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProcedureDeployError(f"The site procedure registry {path} is not JSON: {error}") from error
    if not isinstance(registry, dict) or registry.get("version") != SITE_REGISTRY_VERSION:
        raise ProcedureDeployError(f"The site procedure registry {path} must be an object with \"version\": {SITE_REGISTRY_VERSION}.")
    procedures = registry.get("procedures")
    if not isinstance(procedures, dict) or not all(isinstance(kind, str) and isinstance(file, str) for kind, file in procedures.items()):
        raise ProcedureDeployError(f"The site procedure registry {path} needs a \"procedures\" map from kind to file.")
    overrides = registry.get("overrides", [])
    if not isinstance(overrides, list) or not all(isinstance(kind, str) for kind in overrides):
        raise ProcedureDeployError(f"The \"overrides\" of {path} must be a list of core kinds the site replaces on purpose.")
    unlisted = [kind for kind in overrides if kind not in procedures]
    if unlisted:
        raise ProcedureDeployError(f"{path} names {', '.join(unlisted)} under overrides but does not list a file for it.")
    return registry


def site_plans(registry_path: Path, *, root: Path, core: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The registrations of a site's own procedures; a kind a core procedure already has is refused unless the site names it under `overrides`,
    and then its version goes on the core definition."""
    registry = load_site_registry(registry_path)
    core_by_kind = {plan["procedureKey"]: plan for plan in core}
    overrides = set(registry.get("overrides", []))
    plans: list[dict[str, Any]] = []
    for kind, relative in sorted(registry["procedures"].items()):
        if kind in core_by_kind and kind not in overrides:
            raise ProcedureDeployError(
                f"The site kind {kind} shadows a core kind. Rename it, or name it under \"overrides\" in {registry_path} to replace the core procedure on purpose.")
        if kind in overrides and kind not in core_by_kind:
            raise ProcedureDeployError(f"{registry_path} names {kind} under overrides, but no core procedure has that kind.")
        source_path = root / relative
        if not source_path.is_file():
            raise ProcedureDeployError(f"The site procedure file {relative} for the kind {kind} is not there (looked in {root}).")
        declared = declared_kind(source_path.read_text(encoding="utf-8"))
        if declared != kind:
            raise ProcedureDeployError(f"{relative} declares the kind {declared or 'nothing'}, not {kind} (its first line must be -- papyrus-procedure-kind: {kind}).")
        plan = registration_plan(source_path, root=root, procedure_key=kind)
        plan["origin"] = "site"
        if kind in overrides:
            core_plan_ = core_by_kind[kind]
            plan.update(procedureId=core_plan_["procedureId"], category=core_plan_["category"], origin="override")
            plan["versionId"] = f"procedure-version-{safe_id(kind)[:120]}-{plan['contentDigest']}"
        plans.append(plan)
    return plans


def plan_deploy(*, site_registry: Path | None = None, root: Path = Path(".")) -> list[dict[str, Any]]:
    """Every registration this deploy makes, core first; an overridden core kind appears once, from the site."""
    core = core_plans()
    site = site_plans(site_registry, root=root, core=core) if site_registry is not None else []
    replaced = {plan["procedureKey"] for plan in site if plan["origin"] == "override"}
    return [plan for plan in core if plan["procedureKey"] not in replaced] + site


def plan_statuses(client, plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """For each plan, `new`, `changed` or `unchanged` against the backend. Reads only."""
    return [{"procedureKey": plan["procedureKey"], "versionId": plan["versionId"], "origin": plan["origin"],
             "status": plan_status(client, plan)} for plan in plans]


def check_drift(client, plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    statuses = plan_statuses(client, plans)
    drifted = [entry for entry in statuses if entry["status"] != "unchanged"]
    if drifted:
        words = {"new": "missing", "changed": "changed"}
        raise ProcedureDriftError(
            "The published procedures differ from Git: "
            + "; ".join(f"{entry['procedureKey']} is {words[entry['status']]}" for entry in drifted)
            + ". The deploy registers them (papyrus procedures seed-required).")
    return statuses


def apply_deploy(client, plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**register_site_procedure(client, plan), "origin": plan["origin"]} for plan in plans]
