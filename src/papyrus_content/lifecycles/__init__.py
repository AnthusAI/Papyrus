"""The lifecycle of each record type, written down as data the agents read (docs/design/always-on-agents-architecture.md section 6).

One file per record type in this folder (``reference.yaml``, ``idea.yaml``, ``translation.yaml``, ``illustration.yaml``). A file lists the record's stages in order and, for
each stage, which responsibility moves it, whether a person is wanted by policy, and what happens when nobody acts. ``load`` reads and checks one file; a file that breaks a
rule is refused with every problem named, so a lifecycle is never half-valid.

The rules are the design's shared rules, held in code so no file can break them:

* **The mover is a responsibility in the catalog** (``responsibilities.py``), or ``engine`` for a move the code makes itself. A person is never a stage's mover: where a
  person is wanted the stage says so in ``person``, and the way to ask is a review request.
* **``person``** is ``never``, ``by_policy`` (asked at the rungs below ``rung``, which names a rung of the autonomy ladder) or ``always`` (a person decides whatever the
  rung, such as a five-star rating, and ``why`` says so).
* **``nobodyActs``** is what happens when nobody acts, one of: ``moves_on`` (nothing waits), ``stays`` (the record stays at the stage and is counted, never removed and never
  closed for its age), ``retries`` (one retry at a due time, then ``then``), ``flags`` (one flag, and the record waits). A record that stays is ``counted``.
* **No stage removes a record for its age.** ``nobodyActs`` has no kind that spikes, rejects or deletes by itself.

``waiting`` lists the stages where a record can wait for a person, which is what Today counts.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..agent_policy.document import RUNGS
from ..responsibilities import BY_KEY

FOLDER = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
ENGINE = "engine"
PERSON = ("never", "by_policy", "always")
NOBODY_ACTS = ("moves_on", "stays", "retries", "flags")
STAGE_KEYS = {"id", "title", "mover", "person", "rung", "why", "nobodyActs", "text"}
NOBODY_KEYS = {"kind", "counted", "then", "text"}
TOP_KEYS = {"schemaVersion", "record", "title", "summary", "stages"}


class LifecycleError(ValueError):
    """A lifecycle file that breaks a rule. The message names every problem."""


@dataclass(frozen=True)
class Stage:
    id: str
    title: str
    mover: str
    person: str
    rung: str | None
    why: str | None
    nobody_acts: str
    counted: bool
    then: str | None
    text: str | None
    nobody_text: str

    @property
    def waits_for_a_person(self) -> bool:
        """A record can wait here for a person: it is asked by policy or always, or when nobody acts it stays or is flagged (after its retry, for a stage that retries)."""
        outcome = self.then if self.nobody_acts == "retries" else self.nobody_acts
        return self.person != "never" or outcome in ("stays", "flags")


@dataclass(frozen=True)
class Lifecycle:
    record: str
    title: str
    summary: str
    stages: tuple[Stage, ...]

    def stage(self, stage_id: str) -> Stage:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        raise KeyError(f"{self.record} has no stage {stage_id!r}")

    @property
    def waiting(self) -> tuple[Stage, ...]:
        return tuple(stage for stage in self.stages if stage.waits_for_a_person)


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def problems_of(raw: Any) -> list[str]:
    """Every rule the file breaks, in words; an empty list is a valid lifecycle."""
    if not isinstance(raw, dict):
        return ["the file is not a mapping"]
    found = [f"unknown key {key!r}" for key in sorted(set(raw) - TOP_KEYS)]
    if raw.get("schemaVersion") != SCHEMA_VERSION:
        found.append(f"schemaVersion must be {SCHEMA_VERSION}")
    for key in ("record", "title", "summary"):
        if not _text(raw.get(key)):
            found.append(f"{key} is required")
    stages = raw.get("stages")
    if not isinstance(stages, list) or not stages:
        return found + ["stages must list at least one stage"]
    seen: set[str] = set()
    for number, stage in enumerate(stages, 1):
        if not isinstance(stage, dict):
            found.append(f"stage {number} is not a mapping")
            continue
        name = stage.get("id") if _text(stage.get("id")) else f"stage {number}"
        found += [f"{name}: unknown key {key!r}" for key in sorted(set(stage) - STAGE_KEYS)]
        if not _text(stage.get("id")) or not _text(stage.get("title")):
            found.append(f"{name}: id and title are required")
        elif stage["id"] in seen:
            found.append(f"{name}: the id is used twice")
        else:
            seen.add(stage["id"])
        mover = stage.get("mover")
        if mover != ENGINE and mover not in BY_KEY:
            found.append(f"{name}: mover {mover!r} is not a responsibility in the catalog (a person is never a stage's mover: say who is asked in `person`)")
        person = stage.get("person")
        if person not in PERSON:
            found.append(f"{name}: person must be one of {', '.join(PERSON)}")
        if person == "by_policy" and stage.get("rung") not in RUNGS:
            found.append(f"{name}: a stage asked by policy names the rung below which a person is asked, one of {', '.join(RUNGS)}")
        if person != "by_policy" and "rung" in stage:
            found.append(f"{name}: only a stage asked by policy names a rung")
        if person == "always" and not _text(stage.get("why")):
            found.append(f"{name}: a stage a person always decides says why")
        nobody = stage.get("nobodyActs")
        if not isinstance(nobody, dict):
            found.append(f"{name}: nobodyActs is required")
            continue
        found += [f"{name}: nobodyActs has unknown key {key!r}" for key in sorted(set(nobody) - NOBODY_KEYS)]
        kind = nobody.get("kind")
        if kind not in NOBODY_ACTS:
            found.append(f"{name}: nobodyActs.kind must be one of {', '.join(NOBODY_ACTS)} (no kind removes, spikes or rejects a record for its age)")
        if not _text(nobody.get("text")):
            found.append(f"{name}: nobodyActs.text says in words what happens")
        if kind == "stays" and nobody.get("counted") is not True:
            found.append(f"{name}: a record that stays is counted, so nobodyActs.counted must be true")
        if kind != "stays" and "counted" in nobody:
            found.append(f"{name}: only a record that stays is counted")
        if kind == "retries" and nobody.get("then") not in ("flags", "stays"):
            found.append(f"{name}: a retry says what follows its failure, `then`: flags or stays")
        if kind != "retries" and "then" in nobody:
            found.append(f"{name}: only a retry names what follows it")
    return found


def parse(raw: Any) -> Lifecycle:
    problems = problems_of(raw)
    if problems:
        name = raw.get("record") if isinstance(raw, dict) else None
        raise LifecycleError(f"The {name or 'unnamed'} lifecycle breaks {len(problems)} rule{'' if len(problems) == 1 else 's'}: " + "; ".join(problems))
    stages = tuple(
        Stage(id=stage["id"], title=stage["title"], mover=stage["mover"], person=stage["person"], rung=stage.get("rung"), why=stage.get("why"),
              nobody_acts=stage["nobodyActs"]["kind"], counted=bool(stage["nobodyActs"].get("counted")), then=stage["nobodyActs"].get("then"),
              text=stage.get("text"), nobody_text=stage["nobodyActs"]["text"])
        for stage in raw["stages"])
    return Lifecycle(record=raw["record"], title=raw["title"], summary=raw["summary"], stages=stages)


def load(record: str, folder: Path | None = None) -> Lifecycle:
    """The lifecycle of one record type (``Reference``, ``Idea``, ``Translation``, ``Illustration``), read from its file and checked."""
    path = (folder or FOLDER) / f"{record.lower()}.yaml"
    if not path.is_file():
        raise LifecycleError(f"There is no lifecycle for {record!r}: {path.name} is not in {path.parent}")
    lifecycle = parse(yaml.safe_load(path.read_text(encoding="utf-8")))
    if lifecycle.record != record:
        raise LifecycleError(f"{path.name} describes {lifecycle.record!r}, not {record!r}")
    return lifecycle


def names(folder: Path | None = None) -> list[str]:
    """The record types that have a lifecycle file, by the record name each file states."""
    return sorted(yaml.safe_load(path.read_text(encoding="utf-8"))["record"] for path in (folder or FOLDER).glob("*.yaml"))


def describe(record: str, folder: Path | None = None) -> str:
    """The lifecycle as plain words, for an agent's context or a person: one block per stage."""
    lifecycle = load(record, folder)
    lines = [f"{lifecycle.title} lifecycle. {lifecycle.summary.strip()}"]
    for number, stage in enumerate(lifecycle.stages, 1):
        mover = "the engine" if stage.mover == ENGINE else BY_KEY[stage.mover].title
        asked = {"never": "no person is asked", "always": f"a person always decides ({stage.why})",
                 "by_policy": f"a person is asked below the rung {stage.rung}"}[stage.person]
        lines.append(f"{number}. {stage.title}. Moved by {mover}; {asked}. If nobody acts: {stage.nobody_text.strip()}")
    return "\n".join(lines)
