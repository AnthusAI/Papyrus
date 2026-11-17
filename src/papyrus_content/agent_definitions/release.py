"""Applying the agent definitions when a site deploys (``papyrus agents apply``; slice D2, PPY-df3e74).

Git is the source of truth: the core definitions are the files in the wheel and a site's own are in its folder of definitions
(``papyrus-site-agents`` at the checkout root, or the folder ``--dir`` names). A deploy makes the site's backend agree with them, in this order and
with no write until every check has passed:

1. ``load`` reads and validates the core and site definitions exactly as ``papyrus agents validate`` does, and refuses the whole set when any is invalid.
2. ``plan`` checks each definition against the site: its procedure is registered (a core kind or one the site lists), and the automation it lands on
   is the agent's own. It reads the site and writes nothing.
3. ``apply_release`` then writes, definition by definition, in a form that is safe to run again after a part-way failure.

Each definition is the registered copy on an Automation record named for the definition (``registered.register``: the same digest writes nothing, a
changed digest writes the next version). A definition with no record gets one, created disabled with the definition's procedure and nothing else a
person would set. A definition that is gone from Git is retired on its record: the record is disabled and marked ``definitionRetiredAt``, it names no
schedule (``registered_schedules``), and its registered copy and version stay as its history. A definition that comes back clears the mark.

What this module never does: write the agent policy document (it does not import it), so a deploy cannot set a rung, a pause or a budget and a new agent
arrives at the rung ``off``; adopt an automation onto a responsibility (adoption is an admin who is a person, ``papyrus automations adopt``); or switch an
automation on. Where adopting and applying meet, applying registers the definition on the record and adopting names the responsibility the record fills;
``register`` refuses a record adopted as another responsibility than the definition's own.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..graphql_authoring import AUTOMATION_FIELDS
from ..automations import AutomationError, build_record, read_record, stored_payload
from ..procedure_deploy import ProcedureDeployError, load_site_registry
from ..procedure_registry import registered_kinds
from . import definition as agent_definition
from .definition import Definition
from .registered import digest, register

SITE_FOLDER = "papyrus-site-agents"
ACTOR = "release"
STATUS_WORDS = {"new": "is missing", "changed": "differs from Git", "revived": "is retired but is in Git", "retired": "is gone from Git and not yet retired"}


class ReleaseError(ValueError):
    """A definition, or the site, is not in a state the deploy may apply. Raised before anything is written."""


class ReleaseDriftError(ReleaseError):
    pass


@dataclass(frozen=True)
class Entry:
    definition_id: str
    status: str                 # new | changed | unchanged | revived | retired
    version: int | None
    digest: str | None
    revive: bool = False        # a changed definition whose record was retired also clears the mark
    applied: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"definitionId": self.definition_id, "automationId": self.definition_id, "status": self.status, "version": self.version,
                "digest": self.digest, "applied": self.applied}


def load(site_directory: Path | None, core_directory: Path = agent_definition.CORE_DIRECTORY) -> list[Definition]:
    """The effective definitions, valid whole or refused whole; the same check as ``papyrus agents validate``."""
    loaded = agent_definition.load_sets(site_directory or core_directory, core_directory)
    if loaded.problems:
        raise ReleaseError("The agent definitions are refused; fix them first (papyrus agents validate). Nothing was written.\n"
                           + "\n".join(f"  {problem.definition} {problem.line}: {problem.message}" for problem in loaded.problems))
    return loaded.definitions


def known_procedures(site_registry: Path | None = None) -> set[str]:
    """The procedure kinds a definition may name: every core kind and each kind the site lists in its procedure registry."""
    kinds = set(registered_kinds())
    if site_registry is not None:
        try:
            kinds |= set(load_site_registry(site_registry)["procedures"])
        except ProcedureDeployError as error:
            raise ReleaseError(str(error)) from error
    return kinds


def _trigger(definition: Definition) -> dict[str, Any]:
    """The record's trigger kind says what wakes the agent; the registered definition holds the schedule and the changes."""
    return {"kind": "schedule" if "schedule" in definition.data["wakes"] else "event", "config": {}}


def plan(client, definitions: list[Definition], procedures: set[str]) -> tuple[list[Entry], list[dict[str, Any]]]:
    """What each definition needs on this site, and the records to retire. Reads only; raises one ``ReleaseError`` naming every problem."""
    # The site's automations through the Automation tenantId index (one Query, as Today reads them): the ones whose definition left Git are not named
    # by any file, so the index is the only way to find them. Never a whole-table read.
    rows = {row["id"]: row for row in client.list_tenant_rows("Automation", AUTOMATION_FIELDS)}
    entries: list[Entry] = []
    problems: list[str] = []
    for item in definitions:
        procedure = item.data["procedure"]
        if procedure not in procedures:
            problems.append(f"{item.id}: the procedure {procedure} is not registered. Register it first (a core procedure, or one the site lists in papyrus-site-procedures.json).")
            continue
        row = rows.get(item.id)
        if row is None:
            entries.append(Entry(item.id, "new", 1, digest(item.data)))
            continue
        existing = read_record(row)
        if existing.get("definitionId") is None and existing.get("procedureKey") != procedure:
            problems.append(f"{item.id}: the automation {item.id} runs the procedure {existing.get('procedureKey')}, not {procedure}; it is not an agent the deploy created. "
                            "Rename the definition or the automation.")
            continue
        try:
            result = register(client, item.id, item, actor=ACTOR, apply=False)
        except AutomationError as error:
            problems.append(f"{item.id}: {error}")
            continue
        revive = existing.get("definitionRetiredAt") is not None
        status = "changed" if result["action"] != "unchanged" else ("revived" if revive else "unchanged")
        entries.append(Entry(item.id, status, result["version"], result["digest"], revive=revive))
    current = {item.id for item in definitions}
    retiring = [row for row in rows.values() if row.get("definitionId") and row["definitionId"] not in current and not row.get("definitionRetiredAt")]
    if problems:
        raise ReleaseError("The agent definitions cannot be applied. Nothing was written.\n" + "\n".join(f"  {problem}" for problem in problems))
    entries += [Entry(row["id"], "retired", row.get("definitionVersion"), row.get("definitionDigest")) for row in retiring]
    return entries, retiring


def apply_release(client, definitions: list[Definition], procedures: set[str], *, apply: bool, now: str | None = None) -> list[dict[str, Any]]:
    """Make the site agree with the definitions. ``apply`` False reads and says what would change. Each step can be run again."""
    entries, retiring = plan(client, definitions, procedures)
    if not apply:
        return [entry.as_dict() for entry in entries]
    by_id = {item.id: item for item in definitions}
    results: list[Entry] = []
    for entry in entries:
        if entry.status == "retired":
            continue
        item = by_id[entry.definition_id]
        if entry.status == "new":
            record = build_record({"id": item.id, "title": item.id, "enabled": False, "trigger": _trigger(item), "procedureKey": item.data["procedure"]},
                                  actor=ACTOR, now=now)
            client.create_record("Automation", stored_payload(record))
        if entry.status in ("new", "changed"):
            register(client, item.id, item, actor=ACTOR, apply=True, now=now)
        if entry.revive:
            _mark(client, item.id, retired=False, now=now)
        results.append(replace(entry, applied=entry.status != "unchanged"))
    for row in retiring:
        _mark(client, row["id"], retired=True, now=now)
        results.append(Entry(row["id"], "retired", row.get("definitionVersion"), row.get("definitionDigest"), applied=True))
    return [entry.as_dict() for entry in results]


def _mark(client, automation_id: str, *, retired: bool, now: str | None) -> None:
    """Set or clear the retired mark. Retiring also disables the record; reviving does not switch it back on."""
    now = now or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    existing = read_record(client.get_record("Automation", automation_id))
    fields: dict[str, Any] = {"id": automation_id}
    if retired:
        fields.update(enabled=False, definitionRetiredAt=now)
    payload = stored_payload(build_record(fields, existing=existing, actor=ACTOR, now=now))
    if not retired:
        payload["definitionRetiredAt"] = None   # an explicit null clears the field; a missing one would leave it
    client.update_record("Automation", payload)


def check_drift(client, definitions: list[Definition], procedures: set[str]) -> list[dict[str, Any]]:
    entries, _ = plan(client, definitions, procedures)
    drifted = [entry for entry in entries if entry.status != "unchanged"]
    if drifted:
        raise ReleaseDriftError("The registered agent definitions differ from Git: "
                                + "; ".join(f"{entry.definition_id} {STATUS_WORDS[entry.status]}" for entry in drifted)
                                + ". The deploy applies them (papyrus agents apply).")
    return [entry.as_dict() for entry in entries]


def registered_schedules(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The schedule of each live registered definition, by automation id: what the schedule trigger (PPY-2a53cd) keeps an entry for.
    A retired definition names none, whatever its registered copy says."""
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        record = read_record(row)
        schedule = ((record.get("definition") or {}).get("wakes") or {}).get("schedule")
        if schedule and not record.get("definitionRetiredAt"):
            found[record["id"]] = schedule
    return found
