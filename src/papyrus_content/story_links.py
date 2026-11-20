"""Story-to-story links: one ``SemanticRelation`` between two stories (Items), for a story's Related block.

There is exactly one official relation name, ``STORY_LINK_RELATION`` (``see_also``). The writer here, the reader (``stories show``, the data-quality
check) and the tests all use that one constant, and no caller can pass a relation name: the CLI, the Tactus tool and the MCP tool have no field for it,
and ``link_stories`` refuses to write any other predicate. ``SemanticRelation.predicate`` is a free string in the schema, so this code path is the guard;
a story-to-story relation written by hand under another name is listed by ``unofficial_item_relations`` instead of being silently ignored.

``see_also`` is symmetric, so A to B and B to A are the same link: the id is built from the sorted pair, and a link that exists in either direction
is reported, never written again. A link is only ever created (a signed-in editor's token may create a SemanticRelation but never update one), which is
why a repeat writes nothing. See docs/story-reporting.md ("Linking stories to each other").
"""

from __future__ import annotations

import json
from typing import Any

from .content_item_lifecycle import SYSTEM_ITEM_TYPES
from .publishing import published_item_id_for
from .reference_links import ITEM_LINK_KIND, ITEM_REFERENCE_LINK_KIND, SEE_ALSO, link_item_reference_see_also, link_items, reference_link_relation_id
from .relation_types import load_relation_type_lookup
from .story_reporting import current_reference, current_story_version, story_versions

STORY_LINK_RELATION = SEE_ALSO   # the one name, from reference_links, where every reference and concept edge gets it
STORY_LINK_KIND = ITEM_LINK_KIND
STORY_REFERENCE_LINK_KIND = ITEM_REFERENCE_LINK_KIND
ACCEPTED = "accepted"


def check_official_relation(name: object) -> str:
    """The official relation name, or a plain error listing the only allowed value (for any caller that offers a relation name)."""
    if name is None or name is True or str(name).strip() == STORY_LINK_RELATION:
        return STORY_LINK_RELATION
    raise ValueError(f"The only relation between stories is {STORY_LINK_RELATION!r}; {str(name).strip()!r} is not allowed. Allowed values: {STORY_LINK_RELATION}.")


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    return json.loads(raw) if isinstance(raw, str) and raw else (raw or {})


def resolve_story(client, lineage_or_slug: str) -> dict[str, Any]:
    """The story's current record, found by lineage id or slug; a plain error when it is not an existing story."""
    versions = story_versions(client, lineage_or_slug)
    if not versions:
        by_slug = [row for row in client.list_by_index("itemBySlug", lineage_or_slug) if row.get("lineageId")]
        if by_slug:
            versions = story_versions(client, by_slug[0]["lineageId"])
    if not versions:
        raise ValueError(f"No story found for {lineage_or_slug!r} (give a lineage id or a slug).")
    current = current_story_version(client, versions[0]["lineageId"])
    if current.get("type") in SYSTEM_ITEM_TYPES:
        raise ValueError(f"{lineage_or_slug!r} is a {current.get('type')} item, not a story.")
    return current


def story_summary(client, story: dict[str, Any]) -> dict[str, Any]:
    lineage = story.get("lineageId") or story["id"]
    return {
        "lineageId": lineage,
        "title": story.get("headline") or story.get("title") or lineage,
        "type": story.get("type") or "",
        "stage": story.get("stage") or "",
        "published": client.get_record("PublishedItem", published_item_id_for(lineage)) is not None,
    }


def story_link_relation_id(lineage_id: str, other_lineage_id: str) -> str:
    """The deterministic id of the link between two stories (the same from either end), as every reference edge gets its id."""
    return reference_link_relation_id(STORY_LINK_RELATION, *sorted([lineage_id, other_lineage_id]))


def _item_relations(client, lineage_id: str) -> list[tuple[dict[str, Any], str, str]]:
    """Every item-to-item relation the story is on either end of, as ``(row, own lineage key, other lineage key)``, de-duplicated by id."""
    state = f"item#{lineage_id}#current"
    found: dict[str, tuple[dict[str, Any], str, str]] = {}
    for index, own, other in (("semanticRelationsBySubjectState", "subjectLineageId", "objectLineageId"),
                              ("semanticRelationsByObjectState", "objectLineageId", "subjectLineageId")):
        for row in client.list_by_index(index, state):
            if row.get("subjectKind") == "item" and row.get("objectKind") == "item" and row.get(own) == lineage_id and row.get(other):
                found[row["id"]] = (row, own, other)
    return list(found.values())


def links_of_story(client, lineage_id: str) -> list[dict[str, Any]]:
    """Every official story link the story is on either end of: ``otherLineageId``, ``note``, ``addedBy``, ``addedAt``, ``relationId``."""
    rows = []
    for row, _own, other in _item_relations(client, lineage_id):
        if row.get("predicate") == STORY_LINK_RELATION:
            metadata = _metadata(row)
            rows.append({"relationId": row["id"], "otherLineageId": row[other], "note": metadata.get("note"), "addedBy": metadata.get("addedBy"),
                         "addedAt": metadata.get("addedAt")})
    return sorted(rows, key=lambda link: (str(link["addedAt"] or ""), link["relationId"]))


def unofficial_item_relations(client, lineage_id: str) -> list[dict[str, Any]]:
    """Item-to-item relations on the story whose predicate is not the official one (written by hand, or by another feature): they are never shown as
    Related stories, so they are listed here. ``knownType`` says whether the name is a seeded relation type."""
    known = load_relation_type_lookup()
    return sorted(({"relationId": row["id"], "predicate": row.get("predicate") or "", "otherLineageId": row[other], "knownType": row.get("predicate") in known}
                   for row, _own, other in _item_relations(client, lineage_id) if row.get("predicate") != STORY_LINK_RELATION),
                  key=lambda entry: entry["relationId"])


def related_stories(client, lineage_id: str) -> list[dict[str, Any]]:
    """The story's links with the other story's title, type, stage and whether it is published (a story that cannot be read is listed by id)."""
    rows = []
    for link in links_of_story(client, lineage_id):
        try:
            summary = story_summary(client, current_story_version(client, link["otherLineageId"]))
        except ValueError:
            summary = {"lineageId": link["otherLineageId"], "title": link["otherLineageId"], "type": "", "stage": "", "published": False}
        rows.append({**link, **summary})
    return rows


def existing_link(client, lineage_id: str, other_lineage_id: str) -> dict[str, Any] | None:
    """The link between the two stories, in either direction, or None."""
    return next((link for link in links_of_story(client, lineage_id) if link["otherLineageId"] == other_lineage_id), None)


def link_stories(client, story: dict[str, Any], other: dict[str, Any], *, actor: str, provenance: str = "human", note: str | None = None,
                 now: str | None = None) -> dict[str, Any]:
    """Creates the official link (``reference_links.link_items``) and returns ``{"outcome", "relationId"}``: ``created``; ``exists`` (either direction, nothing
    written); or ``rejected`` (a person rejected this link: nothing is written, only a person's decision reinstates it)."""
    lineage_id, other_id = story.get("lineageId") or story["id"], other.get("lineageId") or other["id"]
    if lineage_id == other_id:
        raise ValueError("A story cannot be linked to itself.")
    found = existing_link(client, lineage_id, other_id)
    if found:
        return {"outcome": "exists", "relationId": found["relationId"]}
    done = link_items(client, story, other, provenance, actor=actor, note=note, now=now)
    return {"outcome": "rejected" if done["outcome"] == "rejected" else "created", "relationId": done["relationId"],
            **({"decidedBy": done.get("decidedBy"), "decidedAt": done.get("decidedAt")} if done["outcome"] == "rejected" else {})}


def resolve_link_targets(client, story_ref: str, target_refs: list[str]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """The story and its targets as current records. Every one must be an existing story and none the story itself, or nothing is written."""
    targets = list(dict.fromkeys(str(value).strip() for value in target_refs if str(value).strip()))
    if not targets:
        raise ValueError("At least one related story is required.")
    story = resolve_story(client, story_ref)
    lineage_id = story.get("lineageId") or story["id"]
    others = []
    for target in targets:
        other = resolve_story(client, target)
        if (other.get("lineageId") or other["id"]) == lineage_id:
            raise ValueError("A story cannot be linked to itself.")
        others.append(other)
    return story, others


def link_story_set(client, story: dict[str, Any], others: list[dict[str, Any]], *, actor: str | None, provenance: str = "human", note: str | None = None,
                   apply: bool = True, on_row: Any = None) -> list[dict[str, Any]]:
    """Links the story to each target (the one shared path for the CLI, the Tactus tool and the MCP tool). One row per target: the target's lineageId,
    title, type, stage, published, ``outcome`` (``write``, ``exists``, ``rejected`` or ``dry run``), ``relationId`` when known, and a ``warning`` when it is not published.
    ``on_row`` is called with each row as soon as it is settled (the CLI prints its ``write`` line there, after the save)."""
    if apply and not actor:
        raise ValueError("A link needs to record who added it.")
    lineage_id = story.get("lineageId") or story["id"]
    rows = []
    for other in others:
        summary = story_summary(client, other)
        row = {**summary, "relation": STORY_LINK_RELATION}
        existing = existing_link(client, lineage_id, summary["lineageId"])
        if existing:
            row["outcome"], row["relationId"] = "exists", existing["relationId"]
        elif not apply:
            row["outcome"] = "dry run"
        else:
            done = link_stories(client, story, other, actor=actor, provenance=provenance, note=note)
            row["outcome"], row["relationId"] = {"created": "write", "exists": "exists", "rejected": "rejected"}[done["outcome"]], done["relationId"]
        if row["outcome"] == "rejected":
            row["warning"] = f"A person rejected this link on {str(done.get('decidedAt') or 'an earlier date')[:10]}; nothing was written. Use the newsroom to reinstate it."
        elif not summary["published"]:
            row["warning"] = f"{summary['title']} is not published yet (stage {summary['stage']}); the public Related block shows published stories only."
        rows.append(row)
        if on_row:
            on_row(row)
    return rows


# ------------------------------------------------------------------ story -> Reference (the same `see_also`, directional)

def references_of_story(client, lineage_id: str) -> list[dict[str, Any]]:
    """The story's current see-also edges to References (one index read): ``referenceLineageId``, ``referenceId``, ``note``, ``addedBy``, ``addedAt``,
    ``relationId``; oldest first. A rejected or suggested edge is not listed (the state is in the index key)."""
    rows = []
    for row in client.list_by_index("semanticRelationsBySubjectState", f"item#{lineage_id}#current"):
        if row.get("predicate") == STORY_LINK_RELATION and row.get("objectKind") == "reference" and row.get("subjectLineageId") == lineage_id and row.get("objectLineageId"):
            metadata = _metadata(row)
            rows.append({"relationId": row["id"], "referenceLineageId": row["objectLineageId"], "referenceId": row.get("objectId"), "note": metadata.get("note"),
                         "addedBy": metadata.get("addedBy"), "addedAt": metadata.get("addedAt")})
    return sorted(rows, key=lambda link: (str(link["addedAt"] or ""), link["relationId"]))


def reference_summary(reference: dict[str, Any]) -> dict[str, Any]:
    from .home_page.export import host_of
    from .public_text import public_url

    address = public_url(reference.get("sourceUri"))
    return {"referenceId": reference["id"], "referenceLineageId": reference.get("lineageId") or reference["id"], "title": reference.get("title") or reference["id"],
            "host": host_of(address) or "", "status": reference.get("curationStatus") or ""}


def related_references(client, lineage_id: str) -> list[dict[str, Any]]:
    """The story's see-also References with each one's title, host and curation status (a Reference that cannot be read is listed by id)."""
    rows = []
    for link in references_of_story(client, lineage_id):
        found = current_reference(client, link["referenceLineageId"])
        summary = reference_summary(found) if found else {"referenceId": link["referenceId"], "referenceLineageId": link["referenceLineageId"], "title": link["referenceLineageId"], "host": "", "status": "missing"}
        rows.append({**link, **summary})
    return rows


def resolve_link_references(client, reference_ids: list[str]) -> list[dict[str, Any]]:
    """The Reference rows for the ids, each of which must exist and be accepted, or nothing is written (only accepted References are shown on the page)."""
    wanted = list(dict.fromkeys(str(value).strip() for value in reference_ids if str(value).strip()))
    found = []
    for value in wanted:
        reference = current_reference(client, value)
        if reference is None:
            raise ValueError(f"Reference not found: {value}")
        if reference.get("curationStatus") != ACCEPTED:
            raise ValueError(f"Reference {value} ({reference.get('title') or 'untitled'}) is {reference.get('curationStatus') or 'not accepted'}. Nothing was written: only accepted References are shown on the page, so only those can be linked.")
        found.append(reference)
    return found


def link_reference_set(client, story: dict[str, Any], references: list[dict[str, Any]], *, actor: str | None, provenance: str = "human", note: str | None = None,
                       apply: bool = True, on_row: Any = None) -> list[dict[str, Any]]:
    """Links the story to each accepted Reference (CLI, Tactus tool and MCP tool share this). One row per Reference: ``referenceId``, ``referenceLineageId``, title,
    host, status, ``outcome`` (``write``, ``exists``, ``rejected`` or ``dry run``) and ``relationId`` when known."""
    if apply and not actor:
        raise ValueError("A link needs to record who added it.")
    lineage_id = story.get("lineageId") or story["id"]
    existing = {link["referenceLineageId"]: link for link in references_of_story(client, lineage_id)}
    rows = []
    for reference in references:
        row = {**reference_summary(reference), "relation": STORY_LINK_RELATION}
        found = existing.get(row["referenceLineageId"])
        if found:
            row["outcome"], row["relationId"] = "exists", found["relationId"]
        elif not apply:
            row["outcome"] = "dry run"
        else:
            done = link_item_reference_see_also(client, lineage_id, reference["id"], provenance, actor=actor, note=note, story=story)
            row["outcome"], row["relationId"] = {"exists": "exists", "rejected": "rejected"}.get(done["outcome"], "write"), done["relationId"]
        if row["outcome"] == "rejected":
            row["warning"] = f"A person rejected this link; nothing was written. Use the newsroom to reinstate it."
        rows.append(row)
        if on_row:
            on_row(row)
    return rows
