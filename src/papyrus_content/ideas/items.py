"""Generated story ideas as content Items at the ``idea`` stage (docs/idea-pipeline.md, docs/content-item-lifecycle.md).

A story the pipeline generates (a monitor story, a trend story, a synthesized idea) is an ``Item`` at the ``idea`` stage, the same stage
people use. It records that a machine made it in its front matter (``generated``: origin, run, monitor, evidence, the subjects it cites).
When it cites References, each is linked ``based_on``, so the Reference counts as covered whatever happens to the idea next. An editor
accepts it by moving it forward and declines it by moving it to ``spiked`` with a reason (``story_reporting.move_story_stage``).

``ItemStore`` has the interface the pipeline already uses for ``ProposalStore`` (``file_story_draft``, ``file_idea``, ``story_drafts``), so
the runs, their dedupe and their ledgers work the same with either. The ``Proposal`` model stays for reader steering.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import yaml

from ..ids import hash_short
from ..publishing import ItemFields, item_id_for, save_item, utc_now_iso
from ..record_helpers import slugify
from ..story_from_reference import REFERENCE_TARGET_PREFIX, SourceTextReader, _current_versions, check_body_against_references, reference_lineages_of_targets
from ..story_reporting import BASED_ON, current_reference, link_reference_to_story

GENERATED_KEY = "generated"
IDEA_STAGE = "idea"
SPIKED_STAGE = "spiked"
DEFAULT_ACTOR = "AI"
KIND = "items"


def front_matter_of(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata")
    metadata = json.loads(metadata) if isinstance(metadata, str) and metadata else (metadata or {})
    try:
        front = yaml.safe_load(metadata.get("frontMatterYaml") or "") or {}
    except yaml.YAMLError:
        return {}
    return front if isinstance(front, dict) else {}


def generated_of(item: dict[str, Any]) -> dict[str, Any] | None:
    """What an Item records about its machine origin, or None for a story people made."""
    found = front_matter_of(item).get(GENERATED_KEY)
    return found if isinstance(found, dict) else None


def item_id_for_idea(draft: dict[str, Any]) -> str:
    """One id per idea: the Reference lineages it cites, else the idea's own id. Filing the same Reference twice is one Item."""
    lineages = sorted(reference_lineages_of_targets(draft.get("targets")))
    return "item-idea-" + hash_short(["idea", lineages or draft["ideaId"]])


def file_idea_item(
    client: Any, draft: dict[str, Any], *, actor: str = DEFAULT_ACTOR, now: str | None = None, source_text_reader: SourceTextReader | None = None,
    extra_generated: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Saves a generated idea as an Item at the idea stage and links the References it cites ``based_on``. Returns ``itemId``, ``lineageId``,
    ``created`` and ``linked``. A body that copies a cited Reference's text raises ``StoryCopiedFromReference`` before anything is written.

    ``draft``: ``title``, ``angle``, ``body``, ``section``, ``targets``, ``ideaId``, ``origin`` and optional ``runId``, ``monitorId``, ``evidence``, ``citedItems``."""
    now = now or utc_now_iso()
    item_id = item_id_for_idea(draft)
    existing = client.get_record("Item", item_id)
    created = existing is None
    lineages = reference_lineages_of_targets(draft.get("targets"))
    references = []
    for lineage in lineages:
        row = current_reference(client, lineage)
        if row is None:
            raise ValueError(f"Reference {lineage} named by the idea was not found.")
        references.append(row)
    title = str(draft["title"]).strip()
    if existing is None:
        body = "\n".join(line for line in str(draft.get("body") or "").splitlines() if not line.startswith("Section: ")).strip() + "\n"
        if references:
            check_body_against_references(client, body, references, source_text_reader)
        section = slugify(str(draft.get("section") or "")) or None
        generated = {
            "origin": draft.get("origin") or "idea-pipeline", "proposedBy": draft.get("proposedBy") or "AI", "ideaId": draft["ideaId"],
            "runId": draft.get("runId"), "monitorId": draft.get("monitorId"), "targets": draft.get("targets"), "evidence": draft.get("evidence"),
            **(extra_generated or {}),
        }
        front = {"title": title, "deck": str(draft.get("angle") or ""), GENERATED_KEY: {key: value for key, value in generated.items() if value not in (None, "", [])}}
        sources = [{"title": cited.get("title"), "url": cited.get("url")} for cited in draft.get("citedItems") or [] if cited.get("url")]
        if sources:
            front["sources"] = sources
        save_item(
            client,
            ItemFields(type="article", slug=slugify(title)[:80].strip("-") or item_id, section=section, front_matter_yaml=yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1000),
                       body_markus=body, aliases=[], id=item_id, overrides={"stage": IDEA_STAGE}),
            actor=actor, now=now,
        )
        existing = client.get_record("Item", item_id)
    lineage_id = existing.get("lineageId") or item_id
    linked = [link_reference_to_story(client, lineage_id, row["id"], role=BASED_ON, actor=actor, now=now)["referenceLineageId"] for row in references]
    return {"itemId": item_id, "lineageId": lineage_id, "created": created, "linked": linked}


def idea_rows(client: Any) -> list[dict[str, Any]]:
    """Every generated story (current version of each Item lineage that records a ``generated`` origin), in the shape of a Proposal row: the
    pipeline's dedupe reads ``id``, ``title``, ``summary``, ``targets``, ``state`` (``declined`` for a spiked idea) and ``createdAt``."""
    rows = []
    for item in _current_versions(client.list_records("Item")):
        generated = generated_of(item)
        if generated is None:
            continue
        spiked = item.get("stage") == SPIKED_STAGE
        targets = generated.get("targets") or []
        rows.append({
            "id": item.get("lineageId") or item["id"], "kind": "story_draft", "title": item.get("title") or "", "summary": item.get("deck") or "",
            "targets": json.dumps(targets), "state": "declined" if spiked else "draft", "createdAt": item.get("versionCreatedAt") or "", "stage": item.get("stage"),
        })
    return rows


class ItemStore:
    """Files generated ideas as Items at the ``idea`` stage. The same interface as ``ProposalStore``."""

    kind = KIND

    def __init__(self, client: Any, *, actor: str = DEFAULT_ACTOR, source_text_reader: SourceTextReader | None = None, legacy: Callable[[], list[dict[str, Any]]] | None = None) -> None:
        self.client = client
        self.actor = actor
        self.source_text_reader = source_text_reader
        self.legacy = legacy

    def file_story_draft(self, draft: dict[str, Any]) -> str:
        return file_idea_item(self.client, draft, actor=self.actor, source_text_reader=self.source_text_reader)["lineageId"]

    def file_idea(self, idea: dict[str, Any], body: str, digest_id: str) -> str:
        lineages = list(dict.fromkeys(str(c.get("lineageId") or c["id"]) for c in idea.get("citations") or []))
        draft = {
            **idea, "body": body, "origin": "synthesis", "targets": [{"type": "entity", "id": f"{REFERENCE_TARGET_PREFIX}{lineage}"} for lineage in lineages],
            "evidence": {"signals": len(lineages), "source": f"ideas digest {digest_id}"},
        }
        return self.file_story_draft(draft)

    def story_drafts(self) -> list[dict[str, Any]]:
        """The generated ideas, plus the story draft Proposals filed before ideas became Items when they can be read (they still count as drafted)."""
        rows = idea_rows(self.client)
        if self.legacy is not None:
            try:
                rows += self.legacy()
            except Exception:  # noqa: BLE001 - a role that cannot read Proposals still dedupes against the Items
                pass
        return rows

    @staticmethod
    def mark(record: dict[str, Any], identifier: str) -> None:
        record["itemLineageId"] = identifier
