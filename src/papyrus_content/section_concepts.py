"""The core concepts of a section: what an editor lists so every agent working in that section knows them (docs/newsroom-context-packs.md).

A section's ``coreConcepts`` is a list of ``{conceptLineageId, note, addedBy, addedAt}``. This module reads and writes it, finds the concept a name,
alias, ``#hashtag`` or node key means, and makes the concept an editor invents by typing a name. ``build_editor_concept_node`` writes the same node
``ensureEditorConcept`` writes in ``amplify/functions/category-action/reference-links.ts``; ``scripts/fixtures/editor-concept-vectors.json`` is read by
both, so the two cannot drift.

``papyrus sections concepts --section S`` lists; ``... add --section S --concept NAME [--note TEXT] [--create [--display-name TEXT]]`` and
``... remove --section S --concept NAME`` write unless ``--dry-run``. A concept made by ``--create`` is made by the site's ``createEditorConcept`` mutation
(``signed_in_concepts.py``), so it works on a signed-in session with no AWS login, and it keeps the capitals the person typed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .editorial_context import find_section
from .graphql_authoring import create_authoring_client
from .options import normalize_string, parse_options, resolve_mutation_apply
from .publishing import utc_now_iso
from .tenancy import tenant_id_from_options

CORE_CONCEPTS_FIELD = "coreConcepts"
EDITOR_CONCEPT_KIND = "editor_concept"
CONCEPT_KEY_SEPARATOR = "--"
EDITOR_CONCEPT_CHANGE_REASON = "Invented by an editor with a hashtag"
COMMAND_ACTOR = "papyrus-cli"
REJECTED = "rejected"


def concept_slug(text: str) -> str:
    """``#Fake Website  Networks`` is ``fake-website-networks``: lower case, each run of other characters one hyphen, at most 80 characters."""
    stripped = re.sub(r"^#+", "", text.strip()).lower()
    return re.sub(r"[^a-z0-9]+", "-", stripped).strip("-")[:80]


BARE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def display_name_for(typed: str, given: str | None = None) -> str:
    """The name a new concept shows. ``--display-name`` wins. Else the words as typed, capitals kept (``Information flow control``, ``Non-interference``),
    except that a ``#hashtag`` or a bare lower-case slug (``fake-website-networks``) reads with spaces, as a hashtag always has."""
    stripped = typed.strip()
    name = " ".join(stripped.lstrip("#").split())
    if given:
        name = " ".join(given.split())
    elif stripped.startswith("#") or BARE_SLUG.match(name):
        name = name.replace("-", " ")
    if not name:
        raise ValueError("A concept needs a name.")
    if concept_slug(name) != concept_slug(typed):
        raise ValueError(f"The name {name!r} is not the same words as {typed!r}, which makes the concept's key; give --display-name with the same words.")
    return name


def editor_concept_key(slug: str) -> str:
    return f"{EDITOR_CONCEPT_KIND}{CONCEPT_KEY_SEPARATOR}{slug}"


def editor_concept_lineage_id(slug: str) -> str:
    return f"semantic-node-{editor_concept_key(slug)}"


def build_editor_concept_node(name: str, actor: str, now: str, display_name: str | None = None) -> dict[str, Any]:
    slug = concept_slug(name)
    if not slug:
        raise ValueError("A concept needs a name.")
    lineage_id = editor_concept_lineage_id(slug)
    return {
        "id": f"{lineage_id}-v1", "lineageId": lineage_id, "versionNumber": 1, "versionState": "current", "versionCreatedAt": now,
        "versionCreatedBy": actor, "changeReason": EDITOR_CONCEPT_CHANGE_REASON, "nodeKey": editor_concept_key(slug),
        "nodeKind": EDITOR_CONCEPT_KIND, "displayName": display_name or slug.replace("-", " "), "status": "accepted", "aliases": [], "createdAt": now,
        "updatedAt": now, "newsroomFeedKey": "semanticNodes",
    }


def core_concepts(section: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The section's core concepts in the order the editor added them. A site whose schema has no such field, or a row with nothing in it, gives none."""
    raw = (section or {}).get(CORE_CONCEPTS_FIELD)
    try:
        value = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw
    except ValueError:
        return []
    if not isinstance(value, list):
        return []
    found: dict[str, dict[str, Any]] = {}
    for entry in value:
        if isinstance(entry, dict) and str(entry.get("conceptLineageId") or "").strip():
            found.setdefault(str(entry["conceptLineageId"]), {
                "conceptLineageId": str(entry["conceptLineageId"]), "note": entry.get("note") or None,
                "addedBy": entry.get("addedBy") or None, "addedAt": entry.get("addedAt") or None,
            })
    return list(found.values())


def current_concept_nodes(store: Any) -> list[dict[str, Any]]:
    """The current version of every concept, rejected ones included (a caller decides what a rejected concept means)."""
    return [row for row in store.safe_list_records("SemanticNode") if row and row.get("versionState", "current") == "current"]


def nodes_by_lineage(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(node.get("lineageId") or node["id"]): node for node in nodes}


def name_part(node_key: str) -> str:
    separator_at = node_key.find(CONCEPT_KEY_SEPARATOR)
    return node_key[separator_at + len(CONCEPT_KEY_SEPARATOR):] if separator_at > 0 else ""


def _flat(text: Any) -> str:
    return " ".join(str(text or "").split()).lower()


def matching_nodes(nodes: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """The concepts a typed name, alias, ``#hashtag`` or node key can mean, from the surest reading to the loosest; the first reading that finds any wins.

    A ``#hashtag`` is read as the box in the Related section reads it (``lib/wiki.ts`` ``conceptKeysForHashtag``): an exact node key, else every key with
    that name part, narrowed by a trailing ``(kind)``."""
    typed = _flat(re.sub(r"^#+", "", text.strip()))
    kind_filter = None
    suffix = re.match(r"^(.*) \(([^()]*)\)$", typed)
    if suffix and text.strip().startswith("#"):
        typed, kind_filter = suffix.group(1).strip(), suffix.group(2).strip()
    if not typed:
        return []
    slug = concept_slug(typed)

    def key_of(node: dict[str, Any]) -> str:
        return str(node.get("nodeKey") or "").lower()

    def of_kind(node: dict[str, Any]) -> bool:
        return kind_filter is None or key_of(node).split(CONCEPT_KEY_SEPARATOR, 1)[0] == kind_filter

    readings = (
        [node for node in nodes if key_of(node) == typed],
        [node for node in nodes if name_part(key_of(node)) == typed and of_kind(node)],
        [node for node in nodes if _flat(node.get("displayName")) == typed],
        [node for node in nodes if typed in {_flat(alias) for alias in node.get("aliases") or []}],
        [node for node in nodes if slug and name_part(key_of(node)) == slug and of_kind(node)],
    )
    for found in readings:
        distinct = {str(node.get("lineageId") or node["id"]): node for node in found}
        if distinct:
            return sorted(distinct.values(), key=lambda node: str(node.get("nodeKey") or ""))
    return []


def concept_label(node: dict[str, Any]) -> str:
    return str(node.get("displayName") or node.get("nodeKey") or node.get("lineageId") or node["id"])


def resolve_concept(nodes: list[dict[str, Any]], text: str, *, allow_rejected: bool = False) -> dict[str, Any] | None:
    """The one current concept ``text`` means; None when none does. More than one is an error that lists their node keys."""
    usable = [node for node in nodes if allow_rejected or node.get("status") != REJECTED]
    found = matching_nodes(usable, text)
    if len(found) > 1:
        raise ValueError(f"{text!r} means more than one concept; use a node key: " + ", ".join(str(node.get("nodeKey")) for node in found))
    return found[0] if found else None


def _section_for(client: Any, value: str) -> dict[str, Any]:
    section = find_section(client, value)
    if section is None:
        raise ValueError(f"No newsroom section matches {value!r}.")
    return section


def _save(client: Any, section: dict[str, Any], entries: list[dict[str, Any]], now: str) -> None:
    client.update_record("NewsroomSection", {"id": section["id"], CORE_CONCEPTS_FIELD: json.dumps(entries, separators=(",", ":")), "updatedAt": now})


def _list(client: Any, section: dict[str, Any]) -> None:
    entries = core_concepts(section)
    if not entries:
        print(f"sections\tconcepts\t{section['id']}\tnone")
        return
    nodes = nodes_by_lineage(current_concept_nodes(client))
    for entry in entries:
        node = nodes.get(entry["conceptLineageId"])
        state = "no longer found" if node is None else ("rejected" if node.get("status") == REJECTED else "core")
        print("\t".join(["sections", "concepts", str(section["id"]), concept_label(node) if node else entry["conceptLineageId"], entry["conceptLineageId"], state, entry["note"] or ""]))


def _add(client: Any, section: dict[str, Any], options: dict[str, Any], apply: bool) -> None:
    text = normalize_string(options.get("concept"))
    if not text or text is True:
        raise ValueError("--concept is required.")
    note = normalize_string(options.get("note")) if options.get("note") is not True else None
    create = options.get("create") is True or str(options.get("create")).lower() in ("true", "yes", "1")
    now = utc_now_iso()
    nodes = current_concept_nodes(client)
    node = resolve_concept(nodes, text)
    made = False
    if node is None:
        invented = build_editor_concept_node(text, COMMAND_ACTOR, now, display_name_for(text, normalize_string(options.get("display-name")))) if concept_slug(text) else None
        existing = resolve_concept(nodes, text, allow_rejected=True) or (nodes_by_lineage(nodes).get(invented["lineageId"]) if invented else None)
        if existing is not None:
            raise ValueError(f"The concept {concept_label(existing)!r} was rejected, so a section cannot have it as a core concept.")
        if not create or invented is None:
            raise ValueError(f"No concept is named {text!r}. Name an existing concept, or add --create to make it.")
        node, made = invented, True
    lineage = str(node.get("lineageId") or node["id"])
    entries = core_concepts(section)
    held = next((entry for entry in entries if entry["conceptLineageId"] == lineage), None)
    mode = "write" if apply else "dry run"
    if held is not None and (note is None or note == held["note"]):
        print(f"sections\tconcepts\tunchanged\t{section['id']}\t{concept_label(node)}\t{lineage}")
        return
    action = "update note" if held is not None else ("create and add" if made else "add")
    print(f"sections\tconcepts\t{action}\t{section['id']}\t{concept_label(node)}\t{lineage}\t{mode}")
    if not apply:
        return
    if made:
        # An editor's token cannot write the graph directly; the site's own mutation makes the concept (and records that it was made from the CLI).
        from .signed_in_concepts import create_editor_concept

        create_editor_concept(client, text, normalize_string(options.get("display-name")))
    if held is not None:
        held["note"] = note
    else:
        entries.append({"conceptLineageId": lineage, "note": note, "addedBy": COMMAND_ACTOR, "addedAt": now})
    _save(client, section, entries, now)
    print(f"sections\tconcepts\tsaved\t{section['id']}\t{lineage}")


def _remove(client: Any, section: dict[str, Any], options: dict[str, Any], apply: bool) -> None:
    text = normalize_string(options.get("concept"))
    if not text or text is True:
        raise ValueError("--concept is required.")
    entries = core_concepts(section)
    core_ids = {entry["conceptLineageId"] for entry in entries}
    node = resolve_concept(current_concept_nodes(client), text, allow_rejected=True)
    lineage = str(node.get("lineageId") or node["id"]) if node else (text if text in core_ids else None)
    if lineage is None or lineage not in core_ids:
        raise ValueError(f"Section {section['id']} does not have the core concept {text!r}.")
    print(f"sections\tconcepts\tremove\t{section['id']}\t{concept_label(node) if node else lineage}\t{lineage}\t{'write' if apply else 'dry run'}")
    if not apply:
        return
    _save(client, section, [entry for entry in entries if entry["conceptLineageId"] != lineage], utc_now_iso())
    print(f"sections\tconcepts\tsaved\t{section['id']}\t{lineage}")


def sections_concepts(flags: list[str]) -> None:
    """papyrus sections concepts --section S | add --section S --concept NAME [--note TEXT] [--create] [--display-name TEXT] [--dry-run] | remove --section S --concept NAME [--dry-run]

    ``NAME`` is a name, an alias, a ``#hashtag`` or a node key. An unknown name fails unless ``--create``, which makes an ``editor_concept``
    concept as typing its hashtag in the console does, except that the name keeps the capitals typed (``--display-name`` gives other words with the same
    letters, for a lower-case slug such as ``non-interference``)."""
    if any(flag in ("--help", "-h") for flag in flags):
        print((sections_concepts.__doc__ or "").strip())
        return
    verb = flags[0] if flags and not flags[0].startswith("--") else "list"
    options = parse_options(flags[1:] if verb != "list" or (flags and not flags[0].startswith("--")) else flags)
    if verb not in ("list", "add", "remove"):
        raise ValueError("Usage: papyrus sections concepts [add|remove] --section S [--concept NAME] [--note TEXT] [--create] [--display-name TEXT] [--dry-run]")
    apply = resolve_mutation_apply(options, f"sections concepts {verb}") if verb != "list" else False
    value = normalize_string(options.get("section"))
    if not value or value is True:
        raise ValueError("--section is required.")
    client, _ = create_authoring_client(tenant_id_from_options(options))
    section = _section_for(client, value)
    {"list": lambda: _list(client, section), "add": lambda: _add(client, section, options, apply), "remove": lambda: _remove(client, section, options, apply)}[verb]()
