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


class IdeaRefused(ValueError):
    """The editorial check found error-severity violations in an idea's text, so it is not filed. ``findings`` are the compact findings."""

    def __init__(self, findings: list[dict[str, Any]]) -> None:
        self.findings = findings
        super().__init__("The editorial check found " + "; ".join(f"{finding.get('policyId')}: {finding.get('message')}" for finding in findings[:3]) + (f" (and {len(findings) - 3} more)" if len(findings) > 3 else ""))

    def as_invalid(self, draft: dict[str, Any]) -> dict[str, Any]:
        return {"title": draft.get("title") or "", "referenceId": draft.get("referenceId"), "reason": "editorial_check_failed", "message": str(self)[:300], "findings": self.findings}


class Gate:
    """The Humanus check an idea passes before it is filed (``ideas/gate.py`` builds the real one). ``check(body, section)`` returns the Humanus
    result, or ``{"skipped": reason}`` when the site's checks are turned off; ``record(item, result)`` stores it as the Item's check run."""

    def check(self, body: str, section: str | None) -> dict[str, Any]: ...

    def record(self, item: dict[str, Any], result: dict[str, Any]) -> None: ...


SEVERITY_ORDER = ("error", "warn", "info")


def summarize_check(result: dict[str, Any]) -> dict[str, Any]:
    """What the Item keeps of a check, and what the batch review orders by: counts by severity, the non-error findings, and which lanes ran. A lane
    that did not run (no ``TYPESAFE_API_KEY`` for the judgment lane) is recorded as not run, with its reason, never as a pass."""
    if result.get("skipped"):
        return {"ran": False, "skipped": result["skipped"]}
    findings = [finding for finding in result.get("findings") or [] if finding.get("status") in ("violation", "review")]
    counts = {severity: sum(1 for finding in findings if finding.get("severity") == severity) for severity in SEVERITY_ORDER}
    lanes = {name: {key: lane.get(key) for key in ("status", "reason") if lane.get(key)} for name, lane in (result.get("lanes") or {}).items() if isinstance(lane, dict)}
    judgment = lanes.get("classifier") or {}
    return {
        "ran": True, "counts": counts, "findings": [{key: finding.get(key) for key in ("id", "policyId", "severity", "status", "message", "excerpt") if finding.get(key) is not None} for finding in findings],
        "lanes": lanes, "judgment": {"ran": judgment.get("status") == "ran", **judgment}, "packVersion": (result.get("pack") or {}).get("version") or result.get("packVersion"),
    }


def review_order(ideas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ideas for a batch review, clean ones first: fewest error, then warn, then info findings (an idea with no check keeps its place)."""
    def key(idea: dict[str, Any]) -> tuple[int, ...]:
        counts = (idea.get("editorialCheck") or {}).get("counts") or {}
        return tuple(int(counts.get(severity) or 0) for severity in SEVERITY_ORDER)

    return sorted(ideas, key=key)


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
    """One id per idea: the Reference lineages it cites, else the idea's own id. Filing the same Reference twice is one Item. A context-pack
    idea is a theme, and several distinct ideas from one pack may cite the same References, so it is keyed by its own id (pack and headline)."""
    if draft.get("origin") == "context-pack":
        return "item-idea-" + hash_short(["idea", draft["ideaId"]])
    lineages = sorted(reference_lineages_of_targets(draft.get("targets")))
    return "item-idea-" + hash_short(["idea", lineages or draft["ideaId"]])


def file_idea_item(
    client: Any, draft: dict[str, Any], *, actor: str = DEFAULT_ACTOR, now: str | None = None, source_text_reader: SourceTextReader | None = None,
    extra_generated: dict[str, Any] | None = None, gate: Gate | None = None,
) -> dict[str, Any]:
    """Saves a generated idea as an Item at the idea stage and links the References it cites ``based_on``. Returns ``itemId``, ``lineageId``,
    ``created`` and ``linked``. A body that copies a cited Reference's text raises ``StoryCopiedFromReference`` before anything is written.

    With a ``gate`` the text is checked first: error-severity violations raise ``IdeaRefused`` and nothing is written; any other finding is kept on the Item
    (``generated.check``) and as its check run. ``supersedes`` (a list of Item lineage ids the idea replaces) is kept in ``generated``.

    With a ``gate`` the text is checked first: error-severity violations raise ``IdeaRefused`` and nothing is written; any other finding is kept on the Item
    (``generated.check``) and as its check run. ``supersedes`` (Item lineage ids the idea replaces) is kept in ``generated``.

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
    check: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    if existing is None:
        body = "\n".join(line for line in str(draft.get("body") or "").splitlines() if not line.startswith("Section: ")).strip() + "\n"
        if references:
            check_body_against_references(client, body, references, source_text_reader)
        section = slugify(str(draft.get("section") or "")) or None
        for superseded in draft.get("supersedes") or []:
            if client.get_record("Item", f"{superseded}-v1") is None and not any((row.get("lineageId") or row["id"]) == superseded for row in client.list_records("Item")):
                raise ValueError(f"supersedes names {superseded}, which is not an Item lineage.")
        if gate is not None:
            result = gate.check(body, section)
            check = summarize_check(result)
            errors = [finding for finding in check.get("findings") or [] if finding.get("severity") == "error" and finding.get("status") == "violation"]
            if errors:
                raise IdeaRefused(errors)
        generated = {
            "origin": draft.get("origin") or "idea-pipeline", "proposedBy": draft.get("proposedBy") or "AI", "ideaId": draft["ideaId"],
            "runId": draft.get("runId"), "monitorId": draft.get("monitorId"), "targets": draft.get("targets"), "evidence": draft.get("evidence"),
            "supersedes": list(draft.get("supersedes") or []), "check": check, **(extra_generated or {}),
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
        if gate is not None and result is not None and not result.get("skipped"):
            gate.record(existing, result)
    lineage_id = existing.get("lineageId") or item_id
    linked = [link_reference_to_story(client, lineage_id, row["id"], role=BASED_ON, actor=actor, now=now)["referenceLineageId"] for row in references]
    return {"itemId": item_id, "lineageId": lineage_id, "created": created, "linked": linked, "check": check}


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
            "targets": json.dumps(targets), "evidence": json.dumps(generated.get("evidence") or {}), "state": "declined" if spiked else "draft", "createdAt": item.get("versionCreatedAt") or "", "stage": item.get("stage"),
        })
    return rows


class ItemStore:
    """Files generated ideas as Items at the ``idea`` stage. The same interface as ``ProposalStore``."""

    kind = KIND

    def __init__(self, client: Any, *, actor: str = DEFAULT_ACTOR, source_text_reader: SourceTextReader | None = None, legacy: Callable[[], list[dict[str, Any]]] | None = None,
                 gate: Gate | None = None) -> None:
        self.client = client
        self.gate = gate
        self.actor = actor
        self.source_text_reader = source_text_reader
        self.legacy = legacy

    def file_story_draft(self, draft: dict[str, Any]) -> str:
        result = file_idea_item(self.client, draft, actor=self.actor, source_text_reader=self.source_text_reader, gate=self.gate)
        if result["check"] is not None:
            draft["editorialCheck"] = result["check"]
        return result["lineageId"]

    def file_idea(self, idea: dict[str, Any], body: str, digest_id: str) -> str:
        lineages = list(dict.fromkeys(str(c.get("lineageId") or c["id"]) for c in idea.get("citations") or []))
        draft = {
            **idea, "body": body, "origin": "synthesis", "targets": [{"type": "entity", "id": f"{REFERENCE_TARGET_PREFIX}{lineage}"} for lineage in lineages],
            "evidence": {"signals": len(lineages), "source": f"ideas digest {digest_id}"},
        }
        lineage = self.file_story_draft(draft)
        if draft.get("editorialCheck") is not None:
            idea["editorialCheck"] = draft["editorialCheck"]
        return lineage

    def story_drafts(self) -> list[dict[str, Any]]:
        """The generated ideas, plus the story draft Proposals filed before ideas became Items when they can be read (they still count as drafted)."""
        rows = idea_rows(self.client)
        if self.legacy is not None:
            try:
                rows += self.legacy()
            except Exception:  # noqa: BLE001 - a role that cannot read Proposals still dedupes against the Items
                pass
        return rows

    def feedback(self) -> list[dict[str, Any]]:
        """Editors' decisions on earlier ideas (accepted, or spiked with a reason) as reviewer feedback for the next synthesis."""
        from .labels import feedback_entries

        return feedback_entries(self.client)

    @staticmethod
    def mark(record: dict[str, Any], identifier: str) -> None:
        record["itemLineageId"] = identifier
