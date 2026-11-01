"""Pack ideas: one model call per context pack, up to three ideas about the pack's theme, checked against every source they cite, then filed
as Items at the ``idea`` stage (docs/idea-context-packs.md section 5.2, tickets PPY-c373f1 and PPY-0c8c36).

``draft_pack_ideas`` is the entry point the router calls once per pack. It trims the pack to the model's input size, asks the model for between
one and three distinct ideas about the theme, checks every sentence with ``trends.check_sentence`` (handles exist, numbers and dates appear in
the cited handle), and drops an idea, never the pack, that fails the idea-level rules: it cites at least two accepted References, never a
pending one (``P#``), and cites a Message (``M#``) only in a sentence that also cites a Reference. Surviving ideas are de-duplicated against
published stories, current and spiked ideas and the run's other ideas (``dedupe.split_duplicates``), pass the editorial gate unchanged, and
are filed with ``based_on`` links for every cited Reference, ``generated.origin = "context-pack"`` and ``generated.evidence``. Each cited concept
becomes a current ``related_to`` edge from the idea to the concept with provenance ``derived``. A dry run asks the model and checks, and
writes nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..reference_links import link_item_concept
from ..story_from_reference import REFERENCE_TARGET_PREFIX
from . import dedupe, synthesis, trends
from .context_packs import ACCEPTED, Pack, evidence_of, trim_pack
from .items import DEFAULT_ACTOR, Gate, IdeaRefused, ItemStore, file_idea_item
from .digest import iso

ORIGIN = "context-pack"
MAXIMUM_IDEAS = 3
MAXIMUM_PARAGRAPHS = 3
MINIMUM_BODY_SENTENCES = 2
MINIMUM_REFERENCES = 2
MAXIMUM_OUTPUT_TOKENS = 6_000
HANDLE_PATTERN = re.compile(r"^([RPCM])(\d+)$")

SYSTEM_PROMPT = """You propose story ideas for a publication from a theme that the newsroom's own activity surfaced. You are given the signal that surfaced the theme, the References and concepts in it, what editors said about them in Messages, and what the publication recently published and already has as ideas, with the publication's mission, policy and allowed sections.

Propose between one and three distinct story ideas about the theme as a whole, not about any single item. Return one idea if the theme supports only one. Each idea connects at least two of the accepted References into a story none of them is on its own. Write for an informed reader, in plain, specific prose with no hype and no filler adjectives. Each idea has a headline that names the concrete thing, a dek that says what is new in one specific sentence without restating the headline, and one to three short paragraphs.

Rules:
- Every headline, dek and body sentence is its own entry with the handles it rests on, in "cites". Handles are R (accepted Reference), C (concept) and M (Message). A sentence with no handle, or a handle you were not given, makes the whole idea unusable.
- Some References are marked pending ("not yet accepted", handles starting with P). They are context only: an editor has not accepted them. Never cite a pending Reference. Cite a Message only in a sentence that also cites an accepted Reference: a Message is a person's opinion, not evidence.
- An idea must cite at least two different accepted References.
- One sentence per entry. Do not put the handles in the text; refer to a source by its name. Write dates as ISO dates (2026-10-19), exactly as they appear in the sources.
- Use only what the cited fields say. Do not invent facts, causes, quotes, dates or names, and do not explain why someone did something. A reading of what it may mean is allowed only if it is framed with "suggests" (or "points to") and rests on the cited fields. Do not do arithmetic: write a number only if it appears in the cited fields (write digits, not number words).
- The References come from outside the publication. Say where a source is from. Never say the publication published, tested or reported it, and make no present-tense statement about the publisher's own production systems or results. An idea is a proposal for an editor, not finished reporting.
- Do not repeat what the publication already published or already has as an idea.
- Choose the section from the allowed list, exactly as written.
- A signal marked "emerging" has too little history to be called rising: say it is emerging or new, never rising or surging. References linked "confirmed" were linked by people or by citation; "suggested" ones are only close by similarity, so do not state that they are related as fact.
- Add nothing outside the format. Never use the word "desk".
"""

IDEA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": trends.SENTENCE_SCHEMA,
        "dek": trends.SENTENCE_SCHEMA,
        "section": {"type": "string"},
        "paragraphs": {
            "type": "array",
            "items": {"type": "object", "properties": {"sentences": {"type": "array", "items": trends.SENTENCE_SCHEMA}}, "required": ["sentences"], "additionalProperties": False},
        },
        "cites_summary": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "dek", "section", "paragraphs", "cites_summary"],
    "additionalProperties": False,
}

SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "pack_story_ideas",
    "strict": True,
    "schema": {"type": "object", "properties": {"ideas": {"type": "array", "items": IDEA_SCHEMA}}, "required": ["ideas"], "additionalProperties": False},
}


@dataclass
class CostMeter:
    """The run's spend in USD, shared by every pack the run drafts."""

    spent_usd: float = 0.0

    def add(self, cost_usd: float | None) -> None:
        self.spent_usd += cost_usd or 0.0


@dataclass
class PackIdeasResult:
    """What one pack produced. ``filed`` holds the ideas written (in a dry run, ``would_file`` holds what would have been)."""

    pack_id: str
    filed: list[dict[str, Any]] = field(default_factory=list)
    would_file: list[dict[str, Any]] = field(default_factory=list)
    refused: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[dict[str, Any]] = field(default_factory=list)
    concepts_without_node: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    model_calls: int = 0
    error: str | None = None
    dry_run: bool = False

    @property
    def filed_count(self) -> int:
        return len(self.filed)

    @property
    def refused_count(self) -> int:
        return len(self.refused)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    def as_dict(self) -> dict[str, Any]:
        return {
            "packId": self.pack_id, "dryRun": self.dry_run, "filed": self.filed_count, "wouldFile": len(self.would_file), "refused": self.refused_count,
            "dropped": self.dropped_count, "costUsd": round(self.cost_usd, 6), "modelCalls": self.model_calls, "error": self.error,
            "ideas": self.filed or self.would_file, "refusals": self.refused, "drops": self.dropped, "conceptsWithoutNode": self.concepts_without_node,
        }


@dataclass(frozen=True)
class PackHandles:
    """The handles of a pack mapped to the ids the citation check records, and the fields each handle's numbers and dates are checked against."""

    ids: Mapping[str, str]
    views: Mapping[str, tuple[set[str], set[str]]]
    references: Mapping[str, Mapping[str, Any]]
    concepts: Mapping[str, Mapping[str, Any]]


def handles_of(pack: Pack) -> PackHandles:
    ids: dict[str, str] = {}
    views: dict[str, tuple[set[str], set[str]]] = {}
    references: dict[str, Mapping[str, Any]] = {}
    concepts: dict[str, Mapping[str, Any]] = {}
    accepted_position = 0
    for row in pack.references:
        handle = str(row["handle"])
        if row.get("status") == ACCEPTED:
            ids[handle] = f"reference:{pack.accepted_lineage_ids[accepted_position]}"
            accepted_position += 1
            references[handle] = row
        else:
            ids[handle] = f"pending:{handle}"
        views[ids[handle]] = trends.facts_in({key: value for key, value in row.items() if key != "handle"})
    for row in pack.concepts:
        handle = str(row["handle"])
        ids[handle] = f"concept:{row['hashtag']}"
        views[ids[handle]] = trends.facts_in({key: value for key, value in row.items() if key != "handle"})
        concepts[handle] = row
    for row in pack.messages:
        handle = str(row["handle"])
        ids[handle] = f"message:{handle}"
        views[ids[handle]] = trends.facts_in({key: value for key, value in row.items() if key != "handle"})
    return PackHandles(ids, views, references, concepts)


def kind_of(handle: str) -> str | None:
    found = HANDLE_PATTERN.match(handle)
    return found.group(1) if found else None


def call_model(transport: synthesis.Transport, model: str, model_input: dict[str, Any]) -> tuple[list[Any], synthesis.Usage]:
    payload = synthesis.request_payload(model, model_input) | {"instructions": SYSTEM_PROMPT, "text": {"format": SCHEMA}, "max_output_tokens": MAXIMUM_OUTPUT_TOKENS}
    body = transport(synthesis.RESPONSES_URL, {"Content-Type": "application/json"}, payload)
    text = synthesis.response_text(body)
    if body.get("status") == "incomplete" or text is None:
        raise synthesis.SynthesisError("The model returned no complete answer.")
    try:
        answer = json.loads(text)
    except ValueError as error:
        raise synthesis.SynthesisError("The model did not answer with the pack idea format.") from error
    ideas = answer.get("ideas") if isinstance(answer, dict) else None
    if not isinstance(ideas, list):
        raise synthesis.SynthesisError("The model did not answer with a list of ideas.")
    return ideas, synthesis.usage_of(body, model)


def sentence_handle_problems(sentence: Mapping[str, Any], raw_cites: Sequence[str], where: str) -> list[dict[str, str]]:
    kinds = {kind_of(handle) for handle in raw_cites}
    found = []
    if "P" in kinds:
        found.append(trends._problem(where, sentence["text"], "cites_pending_reference"))
    if "M" in kinds and "R" not in kinds:
        found.append(trends._problem(where, sentence["text"], "message_cited_without_reference"))
    return found


def check_idea(raw: Any, handles: PackHandles, allowed_sections: Sequence[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(the checked idea or None, the citation check record). Sentence rules are ``trends.check_sentence``; the idea must cite at least two
    accepted References, never a pending one, and a Message only together with a Reference in the same sentence."""
    record: dict[str, Any] = {"status": "failed", "sentences": 0, "problems": []}
    if not isinstance(raw, dict):
        record["problems"].append(trends._problem("idea", "", "not_an_object"))
        return None, record
    problems: list[dict[str, str]] = record["problems"]
    checked_entries: list[tuple[str, dict[str, Any]]] = []

    def check(where: str, entry: Any) -> dict[str, Any] | None:
        checked, found = trends.check_sentence(where, entry, dict(handles.ids), dict(handles.views))
        problems.extend(found)
        if checked is not None:
            raw_cites = [str(handle).strip() for handle in entry.get("cites") or []]
            problems.extend(sentence_handle_problems(checked, raw_cites, where))
            checked["handles"] = list(dict.fromkeys(raw_cites))
            checked_entries.append((where, checked))
        return checked

    headline = check("headline", raw.get("headline"))
    dek = check("dek", raw.get("dek"))
    raw_paragraphs = raw.get("paragraphs")
    if not isinstance(raw_paragraphs, list) or not raw_paragraphs or len(raw_paragraphs) > MAXIMUM_PARAGRAPHS:
        problems.append(trends._problem("body", "", "paragraphs_missing_or_too_many"))
        raw_paragraphs = []
    paragraphs: list[list[dict[str, Any]]] = []
    attempted = 0
    for number, paragraph in enumerate(raw_paragraphs, start=1):
        entries = paragraph.get("sentences") if isinstance(paragraph, dict) else None
        kept = []
        for position, entry in enumerate(entries if isinstance(entries, list) else [], start=1):
            attempted += 1
            checked = check(f"paragraph {number} sentence {position}", entry)
            if checked is not None:
                kept.append(checked)
        if not kept and not any(problem["where"].startswith(f"paragraph {number} ") for problem in problems):
            problems.append(trends._problem(f"paragraph {number}", "", "empty_paragraph"))
        paragraphs.append(kept)
    record["sentences"] = len(checked_entries)
    if attempted < MINIMUM_BODY_SENTENCES:
        problems.append(trends._problem("body", "", "fewer_than_two_body_sentences"))
    cited_references = list(dict.fromkeys(handle for _, entry in checked_entries for handle in entry["handles"] if kind_of(handle) == "R"))
    if len(cited_references) < MINIMUM_REFERENCES:
        problems.append(trends._problem("idea", "", f"fewer_than_{MINIMUM_REFERENCES}_accepted_references_cited"))
    sections = {name.strip().lower(): name for name in allowed_sections}
    section = str(raw.get("section") or "").strip()
    if sections and section.lower() not in sections:
        problems.append(trends._problem("section", section, "unknown_section"))
    if problems or headline is None or dek is None:
        return None, record
    cited_all = list(dict.fromkeys(handle for _, entry in checked_entries for handle in entry["handles"]))
    record.update(status="passed", referencesCited=cited_references, handlesCited=cited_all)
    return {
        "headline": headline, "dek": dek, "section": sections.get(section.lower(), section), "paragraphs": paragraphs,
        "citedReferences": cited_references, "citedConcepts": [handle for handle in cited_all if kind_of(handle) == "C"],
        "citedMessages": [handle for handle in cited_all if kind_of(handle) == "M"], "citationCheck": record,
    }, record


def signal_sentence(pack: Pack, handles: PackHandles) -> str:
    """The signal in one sentence, from the pack's own numbers."""
    signal = pack.signal
    days, count, expected = signal["windowDays"], signal["count"], signal["expected"]
    expected_text = f"{expected:g}" if isinstance(expected, (int, float)) else str(expected)
    if signal["type"] == "acceptance":
        lead = next((row["hashtag"] for row in pack.concepts), str(signal["anchor"]))
        return f"{count} accepted References linked to {lead} in {days} days, against {expected_text} expected." + emerging_note(signal)
    if signal["type"] == "resurfaced":
        return (
            f"A source published {signal['publicationGapDays']} days before it reached the site, a longer gap than {signal['gapPercentile']:.0%} of the site's References, "
            f"and people attended to it again within {days} days ({count} human accept or Messages)."
        )
    if signal["type"] == "hub":
        return f"A recently added Reference with {count} connections to other References (degree {signal['degree']:g}), more than all but {signal['degreeShare']:.0%} of the site's References." + emerging_note(signal)
    if signal["type"] == "cluster":
        return f"{signal['members']} recently accepted References that are close to each other, from {days} days of arrivals, against {expected_text} expected in a group." + emerging_note(signal)
    return f"{count} Messages in one conversation in {days} days, against {expected_text} expected." + emerging_note(signal)


def emerging_note(signal: Mapping[str, Any]) -> str:
    return " The site has too little history to call this rising; it is emerging." if signal.get("emerging") else ""


def evidence_section(pack: Pack, idea: Mapping[str, Any], handles: PackHandles) -> list[str]:
    lines = ["## Evidence", "", signal_sentence(pack, handles), ""]
    for number, handle in enumerate(idea["citedReferences"], start=1):
        row = handles.references[handle]
        published = row.get("published") or "unknown"
        lines.append(f"{number}. {row['title']} (published {published}, added {row.get('added') or 'unknown'}) {row['url']}")
    concepts = [handles.concepts[handle]["hashtag"] for handle in idea["citedConcepts"]]
    if concepts:
        lines += ["", "Concepts: " + " ".join(concepts)]
    return lines + [""]


def idea_body(pack: Pack, idea: Mapping[str, Any], handles: PackHandles) -> str:
    """Markus: the dek and paragraphs, each sentence marked ``[n]`` for every Reference it cites, then the Evidence section."""
    numbers = {handle: number for number, handle in enumerate(idea["citedReferences"], start=1)}

    def marked(sentence: Mapping[str, Any]) -> str:
        marks = " ".join(f"[{numbers[handle]}]" for handle in sentence["handles"] if handle in numbers)
        return f"{sentence['text']} {marks}".rstrip()

    lines = [marked(idea["dek"]), ""]
    lines += [" ".join(marked(sentence) for sentence in paragraph) + "\n" for paragraph in idea["paragraphs"]]
    lines += evidence_section(pack, idea, handles)
    lines += [f"Section: {idea['section']}. Drafted by AI from a theme the newsroom's own activity surfaced. An editor approves the copy before anything is published.", ""]
    return "\n".join(lines)


def evidence_record(pack: Pack, idea: Mapping[str, Any], handles: PackHandles) -> dict[str, Any]:
    base = evidence_of(pack)
    messages = [row for row in pack.messages if row["handle"] in idea["citedMessages"]]
    return {
        **base,
        "citedConcepts": [handles.concepts[handle]["hashtag"] for handle in idea["citedConcepts"]],
        "citedMessages": [{"handle": row["handle"], "about": row.get("about"), "date": row.get("date")} for row in messages],
    }


def idea_record(pack: Pack, idea: Mapping[str, Any], handles: PackHandles, *, run_id: str, now: datetime) -> dict[str, Any]:
    cited_ids = [handles.ids[handle].removeprefix("reference:") for handle in idea["citedReferences"]]
    identifier = "idea-" + hashlib.sha256(f"{pack.pack_id}|{idea['headline']['text']}".encode()).hexdigest()[:10]
    return {
        "ideaId": identifier, "kind": "story_draft", "origin": ORIGIN, "state": "draft", "proposer": "ai", "proposedBy": "AI", "private": True,
        "runId": run_id, "createdAt": iso(now), "title": idea["headline"]["text"][:200], "angle": idea["dek"]["text"][:300], "section": idea["section"],
        "body": idea_body(pack, idea, handles),
        "targets": [{"type": "entity", "id": f"{REFERENCE_TARGET_PREFIX}{lineage}"} for lineage in cited_ids],
        "evidence": evidence_record(pack, idea, handles),
        "citedItems": [{"id": handles.ids[handle], "title": handles.references[handle]["title"], "url": handles.references[handle]["url"]} for handle in idea["citedReferences"]],
        "citationCheck": idea["citationCheck"],
    }


def comparison_documents(pack: Pack, store: ItemStore | None, existing_titles: Iterable[Any]) -> list[dedupe.Document]:
    documents = [dedupe.Document("story", f"story-{number}", row["title"], "") for number, row in enumerate(pack.recent_published_stories, start=1)]
    documents += [dedupe.Document("idea", f"idea-{number}", row["title"], "") for number, row in enumerate(pack.existing_ideas, start=1)]
    for number, entry in enumerate(existing_titles, start=1):
        documents.append(entry if isinstance(entry, dedupe.Document) else dedupe.Document("idea", f"title-{number}", str(entry), ""))
    if store is not None:
        documents += [dedupe.Document("idea", str(row["id"]), row.get("title") or "", row.get("summary") or "") for row in store.story_drafts()]
    return documents


def link_concepts(client: Any, lineage_id: str, idea: Mapping[str, Any], handles: PackHandles, concept_nodes: Mapping[str, Mapping[str, Any]], actor: str,
                  result: PackIdeasResult) -> list[str]:
    linked = []
    for handle in idea["citedConcepts"]:
        hashtag = handles.concepts[handle]["hashtag"]
        node = concept_nodes.get(hashtag)
        if node is None:
            if hashtag not in result.concepts_without_node:
                result.concepts_without_node.append(hashtag)
            continue
        link_item_concept(client, lineage_id, dict(node), "derived", actor=actor)
        linked.append(hashtag)
    return linked


def draft_pack_ideas(
    client: Any,
    pack: Pack,
    *,
    store: ItemStore | None,
    gate: Gate | None,
    transport: synthesis.Transport,
    cost_meter: CostMeter,
    existing_titles: Iterable[Any] = (),
    run_id: str,
    dry_run: bool = False,
    concept_nodes: Mapping[str, Mapping[str, Any]] | None = None,
    model: str = synthesis.DEFAULT_MODEL,
    threshold: float = dedupe.DEFAULT_THRESHOLD,
    now: datetime | None = None,
) -> PackIdeasResult:
    """One model call for ``pack``; returns what was filed, refused by the editorial gate, and dropped (citation check, duplicate, already filed).

    ``concept_nodes`` maps a concept hashtag to its SemanticNode row, so a cited concept can be linked; a concept with no node is reported in
    ``concepts_without_node`` and not linked. ``existing_titles`` are titles (or ``dedupe.Document`` rows) the run already filed or knows. A dry run
    calls the model and checks, and writes nothing."""
    moment = now or datetime.now(timezone.utc)
    result = PackIdeasResult(pack.pack_id, dry_run=dry_run)
    fitted = trim_pack(pack)
    handles = handles_of(fitted)
    model_input = fitted.as_json()
    try:
        raw_ideas, usage = call_model(transport, model, model_input)
    except synthesis.SynthesisError as error:
        result.error = str(error)[:300]
        return result
    result.model_calls = 1
    result.cost_usd = usage.cost_usd or 0.0
    cost_meter.add(usage.cost_usd)
    built: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_ideas):
        title = str(((raw.get("headline") or {}).get("text")) if isinstance(raw, dict) and isinstance(raw.get("headline"), dict) else "")[:200]
        if position >= MAXIMUM_IDEAS:
            result.dropped.append({"title": title, "reason": "more_than_three_ideas"})
            continue
        checked, record = check_idea(raw, handles, fitted.allowed_sections)
        if checked is None:
            result.dropped.append({"title": title, "reason": "citation_check_failed", "citationCheck": record})
            continue
        built.append(idea_record(fitted, checked, handles, run_id=run_id, now=moment) | {"_checked": checked})
    documents = comparison_documents(fitted, store, existing_titles)
    kept, duplicates = dedupe.split_duplicates(built, documents, threshold)
    result.dropped += [{**row, "reason": "near_duplicate"} for row in duplicates]
    for record in kept:
        checked = record.pop("_checked")
        summary = {"title": record["title"], "ideaId": record["ideaId"], "citedReferences": [target["id"].removeprefix(REFERENCE_TARGET_PREFIX) for target in record["targets"]],
                   "citedConcepts": record["evidence"]["citedConcepts"], "citedMessages": [row["handle"] for row in record["evidence"]["citedMessages"]]}
        if dry_run:
            result.would_file.append(summary)
            continue
        actor = store.actor if store is not None else DEFAULT_ACTOR
        try:
            filed = file_idea_item(client, record, actor=actor, source_text_reader=store.source_text_reader if store is not None else None, gate=gate)
        except IdeaRefused as refusal:
            result.refused.append(refusal.as_invalid(record))
            continue
        if not filed["created"]:
            result.dropped.append({"title": record["title"], "reason": "already_filed", "itemLineageId": filed["lineageId"]})
            continue
        if store is not None:
            store.mark(record, filed["lineageId"])
        linked = link_concepts(client, filed["lineageId"], checked, handles, concept_nodes or {}, actor, result)
        result.filed.append({**summary, "itemId": filed["itemId"], "lineageId": filed["lineageId"], "linkedReferences": filed["linked"], "linkedConcepts": linked})
    return result
