"""The agent definition file form (slice D1, PPY-68abaa), read and checked with no network and no model.

One agent is one file, ``<id>.yaml``, in a folder under Git::

    schemaVersion: 1
    id: illustrate-stories            # permanent; the file's name
    version: 1                        # the author's own version; the site's registered copy (registered.py) counts the changes the site has applied
    responsibility: illustrate        # a key of the engine's catalog (responsibilities.py)
    procedure: illustrate_story       # the procedure's key as the registry names it (the release stops when it is not registered)
    wakes:
      changes: [{kind: Item, change: step_changed, filter: {step: illustration, state: open}}]
      schedule: {cron: "0 6 * * *", timeZone: America/New_York}      # optional; either or both
    serialBy: subject                 # subject | agent | key:<name>
    paid: true
    safeToRepeat: false
    operations: {image_search: observe, image_apply: draft}          # each operation and the lowest rung that allows it
    tier: editorial                   # editorial | work | bulk | decision; never a model name
    executor: lambda                  # optional; container only where the catalog allows it
    template:                         # the 11 lines of docs/automated-processes.md
      trigger: ...   inputs: ...   decision: ...   mayWrite: [...]   mustNever: [...]   seenAndReversed: ...
      records: ...   fails: ...   costAndBound: ...   measured: ...   gherkin: [some-spec.feature]
    instructions: [...]               # optional, add-only

A definition never sets how far the agent may go: the rung, a pause, a budget and a model belong to the site's agent policy document, so a deploy cannot change
them. Core definitions ship in ``core/``. A site's folder holds its own complete definitions, and may extend a core definition with a file named for it::

    extends: illustrate-stories
    instructions: [Prefer photographs of real places]
    mustNever: [Use a stock image of a person's face]      # added to the core rules

A site can add instructions and must-never rules and can do nothing else to a core definition; it can never remove a must-never rule.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from papyrus_content.agent_policy.document import RUNGS, TIERS
from papyrus_content.images.operations import operation as operation_named

from ..change_vocabulary import describe as describe_changes, known as known_change
from ..responsibilities import BY_KEY
from .cron import CronError, scheduler_expression

SCHEMA_VERSION = 1
SUFFIX = ".yaml"
CORE_DIRECTORY = Path(__file__).parent / "core"

TEMPLATE_LINES = ("trigger", "inputs", "decision", "mayWrite", "mustNever", "seenAndReversed", "records", "fails", "costAndBound", "measured", "gherkin")
LIST_LINES = ("mayWrite", "mustNever", "gherkin")
REQUIRED = ("schemaVersion", "id", "version", "responsibility", "procedure", "wakes", "serialBy", "paid", "safeToRepeat", "operations", "tier", "template")
OPTIONAL = ("executor", "instructions")
FIELDS = (*REQUIRED, *OPTIONAL)
#: What a person changes on the site, never in a definition. Naming one is refused so that a deploy can never move a rung, a pause, a budget or a model.
POLICY_FIELDS = ("rung", "paused", "pausedReason", "budget", "quietWindow", "model", "loopLimit", "overrides")
OVERLAY_FIELDS = ("schemaVersion", "extends", "instructions", "mustNever", "removes")
EXECUTORS = ("lambda", "container")

_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_WORD = re.compile(r"^[a-z][a-z0-9_]*$")
_PROCEDURE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")   # a procedure kind as the registry names it (references.curate), the same form as an Automation's procedureKey
_KIND = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_SERIAL = re.compile(r"^(?:subject|agent|key:[a-z][a-z0-9_]*)$")
_CRON_FIELD = re.compile(r"^[0-9A-Za-z*/,\-?#]+$")
_FEATURE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]*\.feature$")


@dataclass(frozen=True)
class Problem:
    definition: str
    line: str
    message: str
    code: str = "invalid_value"

    def as_dict(self) -> dict[str, str]:
        return {"definition": self.definition, "line": self.line, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class Definition:
    id: str
    data: dict[str, Any]
    source: str                 # "core" or "site"
    extended: bool = False      # a core definition that a site's file added to

    @property
    def responsibility(self) -> str:
        return self.data["responsibility"]

    @property
    def must_never(self) -> list[str]:
        return self.data["template"]["mustNever"]

    @property
    def instructions(self) -> list[str]:
        return self.data.get("instructions", [])

    @property
    def executor(self) -> str:
        return self.data.get("executor", "lambda")


@dataclass
class Loaded:
    definitions: list[Definition] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    def get(self, definition_id: str) -> Definition:
        return next(item for item in self.definitions if item.id == definition_id)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _texts(value: Any) -> bool:
    return isinstance(value, list) and all(_text(item) for item in value)


def _wakes(wakes: Any, add) -> None:
    if not isinstance(wakes, dict) or not wakes:
        add("wakes", "must say what wakes the agent: changes it listens for, a schedule, or both", "missing_line")
        return
    for key in wakes:
        if key not in ("changes", "schedule"):
            add(f"wakes.{key}", "is not a way to wake an agent; use changes or schedule", "unknown_key")
    if "changes" in wakes and not (isinstance(wakes["changes"], list) and wakes["changes"]):
        add("wakes.changes", "must be a list of at least one change; leave it out for a schedule alone")
    for position, change in enumerate(wakes["changes"] if isinstance(wakes.get("changes"), list) else []):
        here = f"wakes.changes[{position}]"
        if not isinstance(change, dict) or not {"kind", "change"} <= set(change) or set(change) - {"kind", "change", "filter"}:
            add(here, "must be an object with kind, change and optionally filter")
            continue
        if not (isinstance(change["kind"], str) and _KIND.match(change["kind"])):
            add(f"{here}.kind", "must be a record kind such as Reference or Item")
        if not (isinstance(change["change"], str) and _WORD.match(change["change"])):
            add(f"{here}.change", "must be one lower-case word for the kind of change, such as created or accepted")
        elif isinstance(change["kind"], str) and not known_change(change["kind"], change["change"]):
            add(f"{here}", f"listens for {change['kind']}/{change['change']}, which no change feed produces; the changes are {describe_changes()}", "unknown_change")
        selector = change.get("filter", {})
        if not isinstance(selector, dict) or any(isinstance(value, (dict, list)) for value in selector.values()):
            add(f"{here}.filter", "must be a flat set of fields and values")
    if "schedule" in wakes:
        schedule = wakes["schedule"]
        if not isinstance(schedule, dict) or set(schedule) != {"cron", "timeZone"}:
            add("wakes.schedule", "must be an object with cron and timeZone")
            return
        cron = schedule["cron"]
        if not (isinstance(cron, str) and len(cron.split()) == 5 and all(_CRON_FIELD.match(part) for part in cron.split())):
            add("wakes.schedule", "cron must be five fields: minute, hour, day of month, month, day of week")
        else:
            try:
                scheduler_expression(cron)
            except CronError as error:
                add("wakes.schedule", f"cron cannot be run by the scheduler: {error}")
        try:
            ZoneInfo(str(schedule["timeZone"]))
        except (ZoneInfoNotFoundError, ValueError):
            add("wakes.schedule", "timeZone must be a time zone name such as America/New_York")


def _operations(operations: Any, add) -> None:
    if not isinstance(operations, dict):
        add("operations", "must be an object of operation names and the lowest rung that allows each")
        return
    for name, rung in operations.items():
        here = f"operations.{name}"
        found = operation_named(str(name))
        if found is None:
            add(here, "is not an operation in the operation table", "unknown_operation")
        elif not found.agent_allowed:
            add(here, "is for a person only; an agent may not call it", "person_only_operation")
        if rung not in RUNGS[1:]:
            add(here, f"needs the lowest rung that allows it, one of: {', '.join(RUNGS[1:])}")
        elif found is not None and found.agent_allowed and RUNGS.index(rung) < RUNGS.index(found.agent_rung):
            add(here, f"{name} needs the rung {found.agent_rung} or higher in the operation table; a definition may ask for more, never less", "rung_below_table")


def _template(template: Any, add) -> None:
    if not isinstance(template, dict):
        add("template", "must hold the 11 template lines", "missing_line")
        return
    for key in template:
        if key not in TEMPLATE_LINES:
            add(f"template.{key}", "is not a line of the template", "unknown_key")
    for line in TEMPLATE_LINES:
        here = f"template.{line}"
        if line not in template:
            add(here, "is missing; a definition that cannot fill a line says so in that line", "missing_line")
        elif line in LIST_LINES:
            value = template[line]
            if value in ([], None):
                add(here, "must not be empty; say what it is, or say in words that there is nothing", "empty_line")
            elif not _texts(value):
                add(here, "must be a list of non-empty text")
            elif line == "gherkin" and not all(_FEATURE.match(item) for item in value):
                add(here, "must name feature files, each ending in .feature")
            elif len(set(value)) != len(value):
                add(here, "repeats an entry")
        elif not _text(template[line]):
            add(here, "must be non-empty text; say so in words when there is nothing", "empty_line")


def validate_definition(name: str, data: Any) -> list[Problem]:
    """Every problem with one complete definition, by line. The same checks run on a laptop and in the release."""
    problems: list[Problem] = []

    def add(line: str, message: str, code: str = "invalid_value") -> None:
        problems.append(Problem(name, line, message, code))

    if not isinstance(data, dict):
        return [Problem(name, "", "must be an object of the definition's fields", "not_a_mapping")]
    for key in data:
        if key in POLICY_FIELDS:
            add(key, "belongs to the site's agent policy, not to a definition: how far an agent goes is a person's decision and a deploy never changes it", "policy_field")
        elif key not in FIELDS:
            add(key, "is not a field of a definition", "unknown_key")
    for key in REQUIRED:
        if key not in data:
            add(key, "is required", "missing_line")
    if data.get("schemaVersion", SCHEMA_VERSION) != SCHEMA_VERSION:
        add("schemaVersion", f"must be {SCHEMA_VERSION}")
    if "id" in data:
        if not (isinstance(data["id"], str) and _ID.match(data["id"])):
            add("id", "is lower-case words joined by hyphens")
        elif data["id"] != name:
            add("id", f"must be the file's name, {name}")
    if "version" in data and not (isinstance(data["version"], int) and not isinstance(data["version"], bool) and data["version"] >= 1):
        add("version", "must be a whole number from 1")
    if "responsibility" in data and data["responsibility"] not in BY_KEY:
        add("responsibility", f"is not in the catalog; the catalog has: {', '.join(BY_KEY)}", "unknown_responsibility")
    if "procedure" in data and not (isinstance(data["procedure"], str) and _PROCEDURE.match(data["procedure"])):
        add("procedure", "must be the procedure's key as the registry names it: lower-case letters, digits, dots, dashes or underscores")
    if "wakes" in data:
        _wakes(data["wakes"], add)
    if "serialBy" in data and not (isinstance(data["serialBy"], str) and _SERIAL.match(data["serialBy"])):
        add("serialBy", "must be subject, agent, or key:<name>")
    for flag in ("paid", "safeToRepeat"):
        if flag in data and not isinstance(data[flag], bool):
            add(flag, "must be true or false")
    if "operations" in data:
        _operations(data["operations"], add)
    if "tier" in data and data["tier"] not in TIERS:
        add("tier", f"must be one of {', '.join(TIERS)}; a tier, never a model name")
    if "executor" in data:
        responsibility = BY_KEY.get(data.get("responsibility"))
        if data["executor"] not in EXECUTORS or (data["executor"] == "container" and not (responsibility and responsibility.containers)):
            add("executor", "must be lambda; container is only for a responsibility the catalog lets run as one (knowledge)")
    if "instructions" in data and not _texts(data["instructions"]):
        add("instructions", "must be a list of non-empty text")
    if "template" in data:
        _template(data["template"], add)
    return problems


def validate_overlay(name: str, data: dict, base: dict) -> list[Problem]:
    """A site's file that extends a core definition: instructions and must-never rules added, nothing else, and nothing removed."""
    problems: list[Problem] = []

    def add(line: str, message: str, code: str = "invalid_value") -> None:
        problems.append(Problem(name, line, message, code))

    for key in data:
        if key not in OVERLAY_FIELDS:
            add(key, "cannot be changed by a site: a site adds instructions and must-never rules to a core definition and nothing else", "not_addable")
    if name != data.get("extends"):
        add("extends", f"must be the file's name, {name}")
    if data.get("schemaVersion", SCHEMA_VERSION) != SCHEMA_VERSION:
        add("schemaVersion", f"must be {SCHEMA_VERSION}")
    for key in ("instructions", "mustNever"):
        if key in data and not (_texts(data[key]) and data[key]):
            add(key, "must be a list of non-empty text")
    if "removes" in data:
        removed = data["removes"] if isinstance(data["removes"], list) else [data["removes"]]
        for rule in removed:
            what = "a must-never rule of the core definition" if rule in base["template"]["mustNever"] else "anything from it"
            add("removes", f"a site cannot remove {what}: {rule!r}", "base_rule_removed")
    return problems


def merge(base: dict, overlay: dict) -> dict:
    merged = copy.deepcopy(base)
    instructions = base.get("instructions", [])
    merged["instructions"] = [*instructions, *(item for item in overlay.get("instructions", []) if item not in instructions)]
    rules = base["template"]["mustNever"]
    merged["template"]["mustNever"] = [*rules, *(item for item in overlay.get("mustNever", []) if item not in rules)]
    if not merged["instructions"]:
        del merged["instructions"]
    return merged


def read_folder(directory: Path) -> tuple[dict[str, Any], list[Problem]]:
    """Each ``<id>.yaml`` read as the data it holds, by its name, with whatever could not be read."""
    found: dict[str, Any] = {}
    problems: list[Problem] = []
    if not directory.is_dir():
        return found, [Problem(str(directory), "", "is not a folder", "not_a_folder")]
    for path in sorted(entry for entry in directory.iterdir() if entry.is_file() and not entry.name.startswith(".")):
        if path.suffix != SUFFIX:
            problems.append(Problem(path.name, "", f"is not a definition file; a definition is <id>{SUFFIX}", "not_a_definition"))
            continue
        try:
            found[path.stem] = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            problems.append(Problem(path.stem, "", f"could not be read: {error}", "unreadable"))
        except yaml.YAMLError:
            problems.append(Problem(path.stem, "", "is not valid YAML", "unreadable"))
    return found, problems


def load_sets(site_directory: Path, core_directory: Path = CORE_DIRECTORY) -> Loaded:
    """The effective definitions: the engine's core ones, each with what the site added, and the site's own. Valid whole or refused whole."""
    loaded = Loaded()
    core, problems = read_folder(core_directory)
    loaded.problems += problems
    core_only = site_directory.resolve() == core_directory.resolve()
    valid_core: dict[str, dict] = {}
    for name, data in core.items():
        found = validate_definition(name, data)
        loaded.problems += found
        if not found:
            valid_core[name] = data
    site, problems = ({}, []) if core_only else read_folder(site_directory)
    loaded.problems += problems
    extensions: dict[str, dict] = {}
    for name, data in site.items():
        if isinstance(data, dict) and "extends" in data:
            base = valid_core.get(data["extends"]) if isinstance(data["extends"], str) else None
            if base is None:
                loaded.problems.append(Problem(name, "extends", f"{data['extends']!r} is not a core definition", "unknown_base"))
                continue
            found = validate_overlay(name, data, base)
            loaded.problems += found
            if not found:
                extensions[name] = data
            continue
        found = validate_definition(name, data)
        loaded.problems += found
        if found:
            continue
        if name in valid_core:
            loaded.problems.append(Problem(name, "id", f"is already the id of a core definition; extend it with extends: {name}", "duplicate_id"))
            continue
        loaded.definitions.append(Definition(name, data, "site"))
    for name, data in valid_core.items():
        if name in extensions:
            loaded.definitions.append(Definition(name, merge(data, extensions[name]), "core", extended=True))
        else:
            loaded.definitions.append(Definition(name, data, "core"))
    loaded.definitions.sort(key=lambda item: item.id)
    return loaded


def resolve(loaded: Loaded) -> list[dict[str, Any]]:
    """The effective definitions as plain data, for the callers that register or print them."""
    return [{"source": item.source, "extended": item.extended, **copy.deepcopy(item.data)} for item in loaded.definitions]
