"""Add an entity with its aliases in one step: ``papyrus knowledge entities add --kind K --name NAME --alias A [--alias B ...] --actor ai|human``.

The command an agent uses when it knows a thing by several names (``The NTSB`` and ``National Transportation Safety Board``): it creates the accepted node
or finds the one that is already there, adds every alias, and does what ``entities alias`` does for one (refuses an email address, a rejected node, a name that
another live entity of the kind holds). Before it creates a node it runs the duplicate check (``entity_duplicates.py``) on the name, so a second node for a
thing the map has is refused with the entity to use instead.

A name is **ambiguous** when another live entity of a different kind, or an editor concept, answers to the same name once case and punctuation are ignored
(``Mistral`` the model and ``Mistral`` the lab; a concept named ``Reasoning`` and an entity named ``Reasoning``). The extractor cannot resolve such a name
(``registry.py`` leaves it out of every entity that claims it), so the command tags the entity, and the entities it clashes with, with the standard
**Disambiguation** concept, in code: ``disambiguation_plan`` says which links to make and ``commands.py`` makes them with the concept link every editor
uses (``createConceptLink``), so no agent has to remember to.

Pure: rows in, a plan out.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..section_concepts import concept_slug, editor_concept_key, editor_concept_lineage_id
from .actors import Actor, decode_review
from .entity_duplicates import find_duplicate
from .entity_review import EntityReviewError, accept_patches, alias_patches
from .keys import contains_email, kind_key, name_identity
from .publish_run import STATUS_ACCEPTED, STATUS_GENERATED, STATUS_REJECTED, new_node_row, create_only_record
from .registry import alias_identity

DISAMBIGUATION_NAME = "Disambiguation"
DISAMBIGUATION_KEY = editor_concept_key(concept_slug(DISAMBIGUATION_NAME))
DISAMBIGUATION_LINEAGE = editor_concept_lineage_id(concept_slug(DISAMBIGUATION_NAME))
IMPORT_RUN_ID = "entities-add"


@dataclass(frozen=True)
class Ambiguity:
    """``name`` is also the name of ``others`` (live entities of other kinds, or concepts)."""

    name: str
    others: tuple[Mapping[str, Any], ...]


@dataclass
class AddPlan:
    node: dict
    created: bool
    records: list[dict] = field(default_factory=list)
    patches: list[dict] = field(default_factory=list)
    ambiguities: list[Ambiguity] = field(default_factory=list)


def _lineage(node: Mapping[str, Any]) -> str:
    return str(node.get("lineageId") or node.get("id"))


def _live(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("versionState", "current") == "current" and row.get("status") in (STATUS_ACCEPTED, STATUS_GENERATED)]


def clean_aliases(aliases: Iterable[str], name: str) -> list[str]:
    """The aliases as given, spaces folded, an alias that is the name or an earlier alias left out."""
    seen = {alias_identity(name)}
    kept: list[str] = []
    for alias in aliases:
        text = " ".join(str(alias).split())
        if not text:
            raise EntityReviewError("An alias is needed.")
        if contains_email(text):
            raise EntityReviewError("An alias must not hold an email address.")
        if alias_identity(text) not in seen:
            seen.add(alias_identity(text))
            kept.append(text)
    return kept


def _names(node: Mapping[str, Any]) -> list[str]:
    return [str(name) for name in [node.get("displayName"), *(node.get("aliases") or ())] if name]


def find_existing(kind: str, name: str, rows: Iterable[Mapping[str, Any]]) -> dict | None:
    """The live entity of ``kind`` that answers to ``name`` (a rejected one counts, so a rejection is not quietly undone), else ``None``."""
    wanted = alias_identity(name)
    found = [
        dict(row)
        for row in rows
        if row.get("versionState", "current") == "current"
        and row.get("status") in (STATUS_ACCEPTED, STATUS_GENERATED, STATUS_REJECTED)
        and kind_key(row.get("nodeKind") or "") == kind
        and (wanted in {alias_identity(n) for n in _names(row)} or name_identity(name) in {name_identity(n) for n in _names(row)})
    ]
    if len(found) > 1:
        raise EntityReviewError(f"{name!r} is the name of {len(found)} entities of kind {kind!r}: " + ", ".join(sorted(str(row["nodeKey"]) for row in found)) + "; merge them first.")
    return found[0] if found else None


def same_kind_holder(kind: str, names: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """A live entity of ``kind`` that already answers to one of ``names``."""
    wanted = {alias_identity(name) for name in names}
    return next((row for row in _live(rows) if kind_key(row.get("nodeKind") or "") == kind and wanted & {alias_identity(n) for n in _names(row)}), None)


def ambiguities_of(node: Mapping[str, Any], names: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> list[Ambiguity]:
    """Which of ``names`` another live entity of a different kind (an editor concept is one) also answers to."""
    kind = kind_key(node.get("nodeKind") or "")
    others = [row for row in _live(rows) if _lineage(row) != _lineage(node) and kind_key(row.get("nodeKind") or "") != kind and _lineage(row) != DISAMBIGUATION_LINEAGE]
    found = []
    for name in names:
        wanted = alias_identity(name)
        sharing = tuple(row for row in others if wanted in {alias_identity(n) for n in _names(row)})
        if sharing:
            found.append(Ambiguity(name, sharing))
    return found


def add_plan(
    kind: str,
    name: str,
    aliases: Iterable[str],
    node_rows: Iterable[Mapping[str, Any]],
    *,
    actor: Actor,
    now: str,
    corpus_id: str | None = None,
) -> AddPlan:
    rows = [dict(row) for row in node_rows]
    kind = kind_key(kind)
    display = " ".join(name.split())
    if not kind or not display:
        raise EntityReviewError("knowledge entities add requires --kind and --name.")
    if contains_email(display):
        raise EntityReviewError("An entity name must not hold an email address.")
    extra = clean_aliases(aliases, display)
    node = find_existing(kind, display, rows)
    if node is not None and node.get("status") == STATUS_REJECTED:
        raise EntityReviewError(f"{node['nodeKey']} was rejected, so it is not added again; accept it first if it was rejected by mistake.")
    plan_node: dict
    records: list[dict] = []
    patches: list[dict] = []
    if node is None:
        hit = find_duplicate(kind, display, rows)
        if hit is not None:
            raise EntityReviewError(f"{hit.sentence()} Add the name to it with `knowledge entities alias --key {hit.key} --add ...`, or give this entity one of its names.")
        marks = decode_review(None).replace(accepted_by=actor)
        plan_node = new_node_row(kind, display, STATUS_ACCEPTED, import_run_id=IMPORT_RUN_ID, corpus_id=corpus_id, now=now, reason=marks.encode())
        clash = same_kind_holder(kind, extra, rows)
        if clash is not None:
            raise EntityReviewError(f"{clash['id']} already has one of these names; merge the two with `knowledge entities merge`.")
        plan_node["aliases"] = list(extra)
        if extra:
            plan_node["changeReason"] = marks.replace(aliased_by=actor).encode()
        records.append(create_only_record(plan_node))
        created = True
    else:
        created = False
        current = dict(node)
        folded: dict[str, Any] = {}
        steps = []
        if current.get("status") != STATUS_ACCEPTED:
            steps = accept_patches(current, [], actor=actor, now=now, confirm_links=False)
        for patch in steps:
            folded.update(patch["expected"])
            current.update(patch["expected"])
        for alias in extra:
            for patch in alias_patches(current, alias, rows, actor=actor, now=now):
                folded.update(patch["expected"])
                current.update(patch["expected"])
        if folded:
            patches.append({"modelName": "SemanticNode", "expected": {**folded, "id": node["id"], "updatedAt": now}})
        plan_node = current
    ambiguities = ambiguities_of(plan_node, [display, *extra], rows)
    return AddPlan(node=plan_node, created=created, records=records, patches=patches, ambiguities=ambiguities)


def disambiguation_note(ambiguity: Ambiguity, node: Mapping[str, Any]) -> str:
    """The words on the link: what is ambiguous, and with what."""
    others = "; ".join(f"{row.get('displayName')} ({kind_key(row.get('nodeKind') or '')})" for row in ambiguity.others)
    return f"{ambiguity.name!r} names {node.get('displayName')} ({kind_key(node.get('nodeKind') or '')}) and also {others}: do not merge them."


def disambiguation_plan(plan: AddPlan) -> list[tuple[str, str, str]]:
    """The concept links that tag the ambiguity: ``(entity lineage, Disambiguation lineage, note)`` for the entity and for every entity it shares a name with.
    One link per entity: the note names every clash it is in."""
    notes: dict[str, list[str]] = {}
    for ambiguity in plan.ambiguities:
        for member in (plan.node, *ambiguity.others):
            notes.setdefault(_lineage(member), []).append(disambiguation_note(ambiguity, plan.node))
    return [(lineage, DISAMBIGUATION_LINEAGE, " ".join(dict.fromkeys(texts))) for lineage, texts in sorted(notes.items())]
