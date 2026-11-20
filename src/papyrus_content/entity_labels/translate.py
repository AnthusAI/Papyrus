"""Translating the name of one thing, and the short description that goes with it, into one language (docs/multilingual-labels.md).

The procedure is the Story translation's engine with different blocks. One run makes one label (a section's name, a concept's name) in one language:

1. **decide without a model**: a glossary entry for the whole name decides it (its first approved rendering, or the original for do-not-translate).
2. **translate**: the name, other names and the description, in one structured call to the house model, told what the thing is, the glossary, the names
   the language already has for its neighbours, and that it may answer "this language has no settled term" (``equivalence: none``).
3. **check** with code and the bilingual judge: the description against its source with the Humanus translation-faithfulness rules and judge; the name
   against every other name in the language (a name two things share is held, never published).
4. **gate**: a collision, an error-severity finding or ``equivalence: none`` holds the label for a person; anything else is current, which is what makes it
   publishable (labelled AI-translated on its page).

Nothing here writes a concept or a section; a pinned label (a person's wording) is never overwritten.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .keys import ALIAS, CURRENT, HELD, PREFERRED, entity_key, fold, label_id, name_key, sort_key, work_key
from .store import LabelStore

MACHINE, COPIED, GLOSSARY = "machine", "copied", "glossary"
EQUIVALENCES = ("exact", "near", "partial", "none")
PROMPT_VERSION = "label-prompts-1"

SYSTEM = """You write how a news site that publishes in {target_name} ({target}) names one thing, translating from {source_name} ({source}).

Input: JSON with the kind of thing ("section" of the site, or "concept" the site tracks), its name, its other names, a one or two sentence description, the
glossary entries that occur in them, the names the language already uses for neighbouring things, and the language's register notes.

Reply with:
- name: the name a {target_name} news site would use. A person, organisation or product keeps its name unless the glossary gives a local form. A term of art
  with no settled {target_name} equivalent stays in the original (keepOriginal true).
- aliases: other names readers use for it in {target_name}, only ones in real use (an empty list is fine). Never repeat the name.
- description: the description in {target_name}: same claims, same hedges, same numbers, natural wording, one or two sentences.
- equivalence: how closely the {target_name} name matches what the {source_name} name means: exact, near, partial, or none (no equivalent exists).
- keepOriginal: true when the name is kept in the original because {target_name} has no settled term.
- reason: one short sentence on the choice, in English.

Rules: never reuse a name that a neighbouring thing already has. Use the glossary's approved forms. Do not add or drop a claim in the description.
{register}"""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "aliases", "description", "equivalence", "keepOriginal", "reason"],
    "properties": {"name": {"type": "string"}, "aliases": {"type": "array", "items": {"type": "string"}}, "description": {"type": "string"},
                   "equivalence": {"type": "string", "enum": list(EQUIVALENCES)}, "keepOriginal": {"type": "boolean"}, "reason": {"type": "string"}},
}


@dataclass(frozen=True)
class LabelSource:
    """What is being named: the thing and the words it is named with in its own language."""

    kind: str
    entity_id: str
    language: str
    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    summary: str = ""   # one line on what it is, for the translator (a section's editorial mission)

    @property
    def key(self) -> str:
        return entity_key(self.kind, self.entity_id)

    @property
    def content_hash(self) -> str:
        text = {"name": self.name, "aliases": sorted(self.aliases), "description": self.description}
        return "sha256:" + hashlib.sha256(json.dumps(text, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass
class Draft:
    name: str
    aliases: list[str]
    description: str
    equivalence: str
    origin: str
    reason: str = ""
    keep_original: bool = False


@dataclass
class Outcome:
    state: str                      # current | held | pinned | unchanged
    reasons: list[str] = field(default_factory=list)
    draft: Draft | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    cost_usd: float = 0.0


def glossary_decision(glossary: Any, name: str) -> tuple[str, str] | None:
    """The glossary's answer for a whole name: ``("glossary", rendering)`` or ``("copied", original)`` for do-not-translate, else None."""
    for entry in getattr(glossary, "entries", ()):
        if fold(entry["term"]) == fold(name):
            if entry.get("doNotTranslate"):
                return COPIED, name
            return GLOSSARY, entry["translations"][0]
    return None


def draft_label(models: Any, source: LabelSource, target: str, *, glossary: Any, neighbours: list[str], register_notes: list[str], language_names: Mapping[str, str]) -> Draft:
    """One structured model call for the name, other names and description. The glossary decides the name before the model is asked about it."""
    decided = glossary_decision(glossary, source.name)
    entries = glossary.entries_in([source.name, source.description, *source.aliases], source.language) if hasattr(glossary, "entries_in") else []
    payload = {"kind": source.kind, "name": source.name, "aliases": list(source.aliases), "description": source.description, "summary": source.summary,
               "glossary": glossary.prompt_lines(entries) if hasattr(glossary, "prompt_lines") else [], "neighbours": neighbours[:40],
               "nameIsDecided": decided[1] if decided else None}
    system = SYSTEM.format(target=target, target_name=language_names[target], source=source.language, source_name=language_names[source.language],
                           register=("Register and conventions:\n" + "\n".join(f"- {note}" for note in register_notes)) if register_notes else "")
    answer = models._structured("translate", system, json.dumps(payload, ensure_ascii=False), SCHEMA, "label")
    name, origin = (decided[1], decided[0]) if decided else (answer["name"].strip(), COPIED if answer["keepOriginal"] else MACHINE)
    aliases = [alias.strip() for alias in answer["aliases"] if alias.strip() and fold(alias) != fold(name)]
    return Draft(name=name, aliases=list(dict.fromkeys(aliases)), description=answer["description"].strip() if source.description else "",
                 equivalence=answer["equivalence"], origin=origin, reason=answer["reason"].strip(), keep_original=bool(answer["keepOriginal"]) and not decided)


def collisions(store: LabelStore, source: LabelSource, target: str, draft: Draft) -> list[str]:
    """The other things of the same kind that already have this name in the language: a name two things share is held, never published."""
    clashes = []
    for text in [draft.name, *draft.aliases]:
        for row in store.named(target, text, source.kind):
            if row.get("entityKey") != source.key and f"{text!r} is also the name of {row.get('entityKey')}" not in clashes:
                clashes.append(f"{text!r} is already the {'name' if row.get('role') == PREFERRED else 'other name'} of {row.get('entityKey')}")
    return clashes


def check_label(source: LabelSource, draft: Draft, checker: Any | None) -> list[dict[str, Any]]:
    """The description against its source: the Humanus parity rules and the bilingual judge. Findings at error severity hold the label."""
    if not (source.description and draft.description and checker is not None):
        return []
    findings, _lanes = checker.faithfulness(source.description, draft.description)
    return [{"policy": f.policy, "severity": f.severity, "message": f.message} for f in findings]


def save_approved(client: Any, source: LabelSource, target: str, *, name: str, description: str, reviewed_by: str, now: str | None = None) -> Outcome:
    """Save wording a person has read and approved as the label: the machine's translation kept as it is (origin ``machine``, labelled AI-translated), pinned so no
    run overwrites it, current, with the reviewer recorded. A person's later correction through the console is origin ``human``."""
    store = LabelStore(client)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    draft = Draft(name=name, aliases=[], description=description, equivalence="near", origin=MACHINE)
    outcome = Outcome(CURRENT, draft=draft)
    clashes = collisions(store, source, target, draft)
    if clashes:
        raise ValueError("; ".join(clashes))
    _write(store, source, target, draft, outcome, {row["id"]: row for row in store.of_entity(source.key, target)}, stamp, pinned=True, reviewed_by=reviewed_by)
    return outcome


def localize_label(client: Any, models: Any, source: LabelSource, target: str, *, glossary: Any, checker: Any | None, register_notes: list[str],
                   language_names: Mapping[str, str], neighbour_keys: tuple[str, ...] = (), dry_run: bool = False, now: str | None = None) -> Outcome:
    """Make (or refuse to make) the label of ``source`` in ``target`` and write its rows. A pinned label and a current label made from these words are left alone."""
    store = LabelStore(client)
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = {row["id"]: row for row in store.of_entity(source.key, target)}
    preferred_id = label_id(source.key, target)
    have = existing.get(preferred_id)
    if have and have.get("pinned"):
        return Outcome("pinned", ["a person's wording is kept"])
    if have and have.get("sourceContentHash") == source.content_hash and have.get("syncState") == CURRENT:
        return Outcome("unchanged")
    neighbours = [row["text"] for key in neighbour_keys if key != source.key for row in store.of_entity(key, target) if row.get("role") == PREFERRED]
    before = models.spend.cost_usd
    draft = draft_label(models, source, target, glossary=glossary, neighbours=neighbours, register_notes=register_notes, language_names=language_names)
    findings = check_label(source, draft, checker)
    reasons = [f"{finding['policy']}: {finding['message']}" for finding in findings if finding["severity"] == "error"]
    reasons += collisions(store, source, target, draft)
    if draft.equivalence == "none":
        reasons.append(f"no equivalent term in {target}: {draft.reason}")
    outcome = Outcome(HELD if reasons else CURRENT, reasons, draft, findings, round(models.spend.cost_usd - before, 6))
    if not dry_run:
        _write(store, source, target, draft, outcome, existing, stamp)
    return outcome


def _write(store: LabelStore, source: LabelSource, target: str, draft: Draft, outcome: Outcome, existing: dict[str, dict[str, Any]], now: str, *, pinned: bool = False,
           reviewed_by: str | None = None) -> None:
    tenant = store.tenant_id
    preferred = {"id": label_id(source.key, target), "entityKind": source.kind, "entityId": source.entity_id, "entityKey": source.key, "language": target,
                 "role": PREFERRED, "text": draft.name, "nameKey": name_key(target, draft.name, tenant, source.kind), "sortKey": sort_key(target, PREFERRED, draft.name),
                 "description": draft.description or None, "equivalence": draft.equivalence, "origin": draft.origin, "pinned": pinned,
                 "reviewedBy": reviewed_by, "reviewedAt": now if reviewed_by else None,
                 "sourceContentHash": source.content_hash, "syncState": outcome.state, "workKey": work_key(target, outcome.state, tenant, source.kind), "updatedAt": now}
    wanted_aliases = {} if outcome.state == HELD else {label_id(source.key, target, ALIAS, alias): alias for alias in draft.aliases}
    have = existing.get(preferred["id"])
    if have is None:
        store.create({**preferred, "createdAt": now})
    else:
        store.update(preferred, removing=() if preferred["workKey"] else ("workKey",))
    for row_id, alias in wanted_aliases.items():
        row = {"id": row_id, "entityKind": source.kind, "entityId": source.entity_id, "entityKey": source.key, "language": target, "role": ALIAS, "text": alias,
               "nameKey": name_key(target, alias, tenant, source.kind), "sortKey": sort_key(target, ALIAS, alias), "origin": draft.origin, "updatedAt": now}
        if row_id in existing:
            store.update(row)
        else:
            store.create({**row, "createdAt": now})
    for row_id, row in existing.items():
        if row.get("role") == ALIAS and row_id not in wanted_aliases and not row.get("pinned"):
            store.delete(row_id)


__all__ = ["Draft", "LabelSource", "Outcome", "check_label", "collisions", "draft_label", "glossary_decision", "localize_label", "save_approved"]
