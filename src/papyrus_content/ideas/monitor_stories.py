"""Monitor stories: the items a site's monitors find, written up as cited story drafts (docs/idea-pipeline.md#monitor-stories).

A monitor (docs/monitoring-cloud.md) delivers pending ``Reference`` rows into the site's canonical knowledge corpus, whatever its source:
Hacker News, the Hugging Face Hub, an email submission. Each Reference records its monitor (``discoveredByMonitorId``)
and may carry the source's structured ``discoveryDetails``; no Message is written (Messages come only from people). This module picks the few most worth
writing about and drafts one short story per item. Nothing in it names a source.

The flow is read, rank, fetch, one model call per item, a deterministic citation check, then a ``story_draft`` Proposal in state ``draft``.

* **Read.** Every *accepted* Reference (accepted by an editor or automatically; ``--status accepted,pending`` adds pending ones, a rejected one is never read; ``--since`` is an optional filter, with no default) that a monitor delivered, that no
  item carries yet (promoted) and that no earlier draft cites. Pending References left out are counted as ``notAccepted``. A Reference the relevance Cyclotron judged *not* relevant is left out.
* **Rank.** The Cyclotron's verdict is the source-agnostic signal: the ``relevance_decision_is`` relation of the Reference holds the label and
  the score (the probability of the positive label). Judged relevant comes before not judged, and a higher score before a lower one, the score
  times a freshness weight ``exp(-age / tau)`` where ``tau`` is learned from this site's own editors (``learn_freshness``): there is no cutoff, an old
  item is only ranked lower among equals. Without enough examples there is no weight. Only then do the source's own numbers (``SECONDARY_SIGNALS``: likes, downloads) break a tie, when the item has them, then the newest, then the id.
* **Fetch.** The linked page, as plain text, through the same public-address-only reader the digest uses. A page that cannot be read is only a
  missing text: the story then rests on the title and the stored details. An item with nothing but a title is skipped, without a model call.
* **Draft.** One call per item, shown the mission, the policy, the allowed sections, the source and the recent stories. Every sentence
  carries ``cites: ["I1"]``, the source, and the Cited Trends citation check (``trends.check_sentence``) holds: a sentence with no handle, an unknown handle,
  a number or an ISO date that is not in the source it cites, several sentences in one entry or a banned word fails the whole draft.
* **File.** The same operator path as a trend story (``ProposalStore.file_story_draft``, one soft review request per run). The Proposal's
  target is ``entity:reference:<Reference lineage id>``: that is how a later run knows the Reference is drafted (the operator can read targets,
  not bodies), declined drafts included, so a Reference is never drafted twice. The same address delivered as another Reference (a second
  monitor, a repost) counts as the same Reference: ``sameSource`` in the run record. Before each filing the targets are read again, so a second run
  that overlaps this one files nothing the first run just filed.

Nothing here publishes or transitions a Proposal. Approving the copy is an editor's decision.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Callable, Iterable
from typing import Any

from .. import link_exploration
from ..categories_steering import semantic_state_key
from ..link_exploration import Context, Exploration
from ..knowledge_snapshot.monitor_records import discovery_details, discovery_monitor_id
from ..monitor_promotion import promoted_reference_ids
from . import dedupe, synthesis, trends
from .digest import CORPUS_PREFIX, collect_references, iso, parse_time, parse_window, relations_of, relevance_of
from .excluded_hosts import is_excluded, normalize_hosts
from . import source_text
from .source_text import SourceFetcher, fetch_source
from .pipeline import DEFAULT_MAXIMUM_COST_USD, comparison_documents
from .review import request_human_review
from .items import IdeaRefused
from .store import JsonStore, ProposalStore
from ..story_from_reference import url_key

DEFAULT_LIMIT = 3
MINIMUM_FRESHNESS_EXAMPLES = 10  # fewer accepted examples than this and there is no freshness weight: nothing is guessed
ATTEMPT_FACTOR = 2  # a draft that fails the check may be replaced by the next ranked item, up to this many attempts per story wanted
DEFAULT_STATUSES = ["accepted"]  # only a Reference an editor accepted, or the automatic acceptance did (docs/idea-pipeline.md#monitor-stories); `--status accepted,pending` reads pending ones too
POSITIVE_LABEL = "include"  # used only when the decision does not name its positive label
#: The one place the ranking looks at a source's own numbers, and only to break a tie between items the Cyclotron scored the same.
SECONDARY_SIGNALS = ("likes", "downloads")
TARGET_TYPE = "entity"
TARGET_PREFIX = "reference:"
TEXT_LIMIT = 4000
MAXIMUM_FACTS = 20
FACT_LIMIT = 200
MINIMUM_BODY_SENTENCES = 2
MAXIMUM_PARAGRAPHS = 3
MAXIMUM_OUTPUT_TOKENS = 3_000
SOURCE_HANDLE = "I1"
SUMMARY_KEYS = ("summary", "description")

SYSTEM_PROMPT = """You draft one short news story for a publication from one item that a monitor found: a link to a page, with the page's text where it could be read and any facts the monitor stored. You are given the publication's mission and policy, its allowed sections, the source, and its recent and in-flight stories.

Write for an informed reader. Say what the item is, who made or published it, what it says or does, and why it may matter to this publication's readers, using only what the source gives you. Plain, specific prose; no hype and no filler adjectives. Write one or two short paragraphs. The headline names the concrete thing. The dek says what is new about it in one specific sentence and does not restate the headline.

Rules:
- Every headline, dek and body sentence is its own entry with the handle it rests on, in "cites": the source handle (I1). A sentence with no handle, or a handle that is not one you were given, makes the whole draft unusable.
- One sentence per entry. Do not put the handle in the text; refer to the source by its name. Write dates as ISO dates (2026-10-19), exactly as they appear in the source.
- Use only what the source fields say. Do not invent facts, causes, quotes, dates or names, and do not explain why someone did something. A reading of what it may mean is allowed only if it is framed with "suggests" (or "points to") and rests on the source. Do not do arithmetic: write a number only if it appears in the source fields (write digits, not number words).
- The source is an item from outside the publication, found by a monitor. Say where it is from. Never say the publication published, tested or reported it, and make no present-tense statement about the publisher's own production systems or results. The story is a proposal for an editor, not finished reporting.
- If "page_text" is missing, the page could not be read: say only what the title, summary and facts say.
- Choose the section from the allowed list, exactly as written.
- Skip nothing and add nothing outside the format. Never use the word "desk".
"""

SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "name": "monitor_story_draft",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "headline": trends.SENTENCE_SCHEMA,
            "dek": trends.SENTENCE_SCHEMA,
            "section": {"type": "string"},
            "paragraphs": {
                "type": "array",
                "items": {"type": "object", "properties": {"sentences": {"type": "array", "items": trends.SENTENCE_SCHEMA}}, "required": ["sentences"], "additionalProperties": False},
            },
        },
        "required": ["headline", "dek", "section", "paragraphs"],
        "additionalProperties": False,
    },
}


# --- reading the monitored items -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class MonitoredItem:
    reference_id: str
    lineage_id: str
    title: str
    url: str
    arrived_at: str
    published_at: str | None
    monitor_id: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    verdict: dict[str, Any] | None = None  # the Cyclotron's: label, score, confidence, classifier, positiveLabel
    curated_at: str | None = None  # when an editor last set the curation status
    curated_by: str | None = None  # who: a person, or ``auto:cyclotron`` for an automatic acceptance

    @property
    def relevant(self) -> bool | None:
        """True when the Cyclotron judged it relevant, False when it judged it not, None when there is no verdict."""
        if self.verdict is None:
            return None
        return self.verdict.get("label") == (self.verdict.get("positiveLabel") or POSITIVE_LABEL)

    def as_dict(self) -> dict[str, Any]:
        return {
            "referenceId": self.reference_id, "referenceLineageId": self.lineage_id, "title": self.title, "url": self.url, "monitorId": self.monitor_id,
            "arrivedAt": self.arrived_at, "publishedAt": self.published_at, "status": self.status, "verdict": self.verdict,
        }


def has_based_on_story(relations: Iterable[dict[str, Any]]) -> bool:
    """True when a story (an item) is linked to the Reference with the ``uses_evidence`` relation in the role ``based_on``: someone or something already wrote it up."""
    for relation in relations:
        if relation.get("predicate") != "uses_evidence" or relation.get("subjectKind") != "item":
            continue
        metadata = relation.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                continue
        if isinstance(metadata, dict) and metadata.get("role") == "based_on":
            return True
    return False


def automated_monitor_ids(client: Any) -> tuple[set[str], str | None]:
    """(the monitors an enabled Automation of the site is triggered by, an error name or None). An Automation whose trigger is
    ``{"kind": "monitor", "config": {"monitorId": ...}}`` is meant to draft from that monitor's deliveries (docs/monitoring-cloud.md). Being configured is
    not handling: a Reference is left to it only once a story based on it exists or a procedure run for it is recorded (``automation_handled``). When the records cannot be read the set is empty and the error is returned, so the run still goes ahead and says so."""
    try:
        rows = client.list_records("Automation")
    except Exception as error:  # noqa: BLE001 - a role that cannot list Automations must not stop the step
        return set(), type(error).__name__
    monitors: set[str] = set()
    for row in rows or []:
        trigger = row.get("trigger")
        if isinstance(trigger, str):
            try:
                trigger = json.loads(trigger)
            except ValueError:
                continue
        if row.get("enabled") is False or not isinstance(trigger, dict) or trigger.get("kind") != "monitor":
            continue
        monitor = str((trigger.get("config") or {}).get("monitorId") or "").strip()
        if monitor:
            monitors.add(monitor)
    return monitors, None


def collect_monitored_items(
    client: Any, *, site: str, since: str | None = None, now: datetime, drafted: set[str] = frozenset(), excluded_hosts: Iterable[str] = (),
    automated_monitors: Iterable[str] = (), automation_handled: Iterable[str] = (), statuses: Iterable[str] = DEFAULT_STATUSES, workers: int = 1,
    out_of_time: Callable[[], bool] | None = None,
) -> tuple[list[MonitoredItem], dict[str, int]]:
    """Every monitored Reference of ``site`` (all of them, or only those that arrived inside ``since`` when it is given), each with the monitor,
    the stored details and the Cyclotron's verdict. One indexed query per Reference for its provenance and one more for its decision; the
    decision is not read for a Reference in ``drafted`` (it is never a candidate again). A Reference whose ``sourceUri`` host is one of
    ``excluded_hosts`` (or a subdomain) is never read further, never a candidate, and is counted as ``excludedHost``. A Reference an Automation has really taken on is never a candidate
    either, and is counted as ``handledByAutomation``: its id is in ``automation_handled`` (a procedure run for it is recorded or in progress), or a story is
    already ``based_on`` it and the monitor that delivered it is one in ``automated_monitors`` (an enabled Automation is configured for it). An Automation that is
    merely configured for the monitor handles nothing yet. A story ``based_on`` a Reference from a monitor no Automation is configured for is counted as ``hasStory``.

    With ``workers`` above 1 the References are read that many at a time, each worker on its own connection (a site with thousands of accepted
    References needs two queries each: read one after the other, a daily run would spend its whole time budget reading). If ``out_of_time()``
    turns true the rest are left unread and ``readStopped`` is set in the counts."""
    statuses = list(dict.fromkeys(statuses))
    window = now - parse_window(since) if since else None
    rows = collect_references(client, [f"{CORPUS_PREFIX}{site}"], statuses, window)
    not_accepted = 0 if "pending" in statuses else len(collect_references(client, [f"{CORPUS_PREFIX}{site}"], ["pending"], window))
    counts = {"inWindow": len(rows), "notAccepted": not_accepted, "notMonitored": 0, "judgedNotRelevant": 0, "excludedHost": 0, "handledByAutomation": 0, "hasStory": 0}
    automated = set(automated_monitors)
    handled = {str(identifier) for identifier in automation_handled}
    excluded_hosts = normalize_hosts(excluded_hosts)
    local = threading.local()

    def connection() -> Any:
        """The client for this worker thread: the given one when reading sequentially, otherwise a copy with a connection of its own."""
        if workers <= 1:
            return client
        if not hasattr(local, "client"):
            local.client = copy.copy(client)
            if hasattr(local.client, "_connection"):
                local.client._connection = None
        return local.client

    def read(row: dict[str, Any]) -> tuple[str, MonitoredItem | None]:
        if out_of_time is not None and workers > 1 and out_of_time():
            return "readStopped", None
        if is_excluded(row.get("sourceUri"), excluded_hosts):
            return "excludedHost", None
        reader = connection()
        lineage = row.get("lineageId") or row["id"]
        incoming = list(reader.list_semantic_relations_by_object_state(semantic_state_key("reference", lineage)))
        monitor = discovery_monitor_id(row)
        if monitor is None or not row.get("sourceUri"):
            return "notMonitored", None
        if handled & {str(row["id"]), str(lineage)}:
            return "handledByAutomation", None
        if has_based_on_story(incoming):
            return ("handledByAutomation" if monitor in automated else "hasStory"), None
        item = MonitoredItem(
            reference_id=row["id"], lineage_id=lineage, title=str(row.get("title") or row["sourceUri"]).strip(), url=str(row["sourceUri"]),
            arrived_at=str(row.get("createdAt") or ""), published_at=str(row.get("sourcePublishedAt") or "") or None, monitor_id=monitor,
            status=str(row.get("curationStatus") or "pending"), details=discovery_details(row),
            verdict=None if lineage in drafted else relevance_of(relations_of(reader, row)),
            curated_at=str(row.get("curationStatusUpdatedAt") or "") or None,
            curated_by=str(row.get("curationStatusUpdatedBy") or "") or None,
        )
        return ("judgedNotRelevant", None) if item.relevant is False else ("item", item)

    ordered = sorted(rows, key=lambda entry: str(entry["id"]))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(read, ordered))
    else:
        outcomes = [read(row) for row in ordered]
    items: list[MonitoredItem] = []
    for kind, item in outcomes:
        if kind == "item":
            items.append(item)
        elif kind == "readStopped":
            counts["readStopped"] = counts.get("readStopped", 0) + 1
        else:
            counts[kind] += 1
    return items, counts


# --- freshness -----------------------------------------------------------------------------------------------------------------


def age_days(start: str | None, end: str | None) -> float | None:
    first, last = parse_time(start), parse_time(end)
    return None if first is None or last is None else (last - first).total_seconds() / 86400


def learn_freshness(items: list[MonitoredItem]) -> dict[str, Any] | None:
    """How quickly this site's editors act on what monitors find, from their own decisions: the age at curation (``curationStatusUpdatedAt`` minus
    the arrival) of the monitored References they ACCEPTED. For an exponential ``exp(-age / tau)`` the median age is ``tau * ln 2``, so
    ``tau = median / ln 2``; the median keeps a few very late or instant decisions from moving it. None (no weight at all) when fewer than
    ``MINIMUM_FRESHNESS_EXAMPLES`` accepted items (an editor's, not an automatic acceptance) have a positive age: a constant is never guessed."""
    ages = sorted(age for item in items if item.status == "accepted" and not (item.curated_by or "").startswith("auto:") for age in [age_days(item.arrived_at, item.curated_at)] if age is not None and age > 0)
    if len(ages) < MINIMUM_FRESHNESS_EXAMPLES:
        return None
    middle = len(ages) // 2
    median = ages[middle] if len(ages) % 2 else (ages[middle - 1] + ages[middle]) / 2
    return {"tauDays": round(median / math.log(2), 4), "medianAgeDays": round(median, 4), "examples": len(ages)}


def freshness_weight(item: MonitoredItem, freshness: dict[str, Any] | None, now: datetime) -> float:
    """``exp(-age / tau)`` for the item's age at ``now``; 1 without a learned tau (no weight) or an unreadable arrival."""
    age = age_days(item.arrived_at, iso(now))
    if freshness is None or age is None:
        return 1.0
    return math.exp(-max(age, 0.0) / freshness["tauDays"])


# --- ranking -------------------------------------------------------------------------------------------------------------------


def secondary_interest(item: MonitoredItem) -> tuple[int, ...]:
    """The source's own numbers named in ``SECONDARY_SIGNALS``, in that order, 0 where the item has none."""
    return tuple(int(item.details[name]) if isinstance(item.details.get(name), (int, float)) and not isinstance(item.details.get(name), bool) else 0 for name in SECONDARY_SIGNALS)


def primary_key(item: MonitoredItem, weight: float = 1.0) -> tuple[Any, ...]:
    """Smaller sorts first: judged relevant, then not judged; a higher Cyclotron score times the freshness weight; then the source's own numbers."""
    score = (item.verdict or {}).get("score")
    return (0 if item.relevant else 1, 0 if score is not None else 1, -(score or 0.0) * weight, *(-number for number in secondary_interest(item)))


def rank(items: list[MonitoredItem], freshness: dict[str, Any] | None = None, now: datetime | None = None) -> list[MonitoredItem]:
    """Best first. Ties on everything above go to the newest arrival, then the lower id, so the same input always gives the same order.
    ``freshness`` (from ``learn_freshness``) weights the score by age at ``now``; without it the score alone ranks."""
    moment = now or datetime.now(timezone.utc)
    ordered = sorted(items, key=lambda item: item.reference_id)
    ordered.sort(key=lambda item: item.arrived_at, reverse=True)
    ordered.sort(key=lambda item: primary_key(item, freshness_weight(item, freshness, moment)))
    return ordered


def target_for(item: MonitoredItem) -> dict[str, str]:
    return {"type": TARGET_TYPE, "id": f"{TARGET_PREFIX}{item.lineage_id}"}


def source_keys(items: Iterable[MonitoredItem]) -> dict[str, str | None]:
    """Reference lineage id to the match key of its address (``url_key``), for the items whose address has one."""
    return {item.lineage_id: url_key(item.url) for item in items}


def drafted_lineage_ids(proposals: list[dict[str, Any]], stored: list[dict[str, Any]]) -> set[str]:
    """Reference lineage ids that an earlier draft cites: Proposals in any state (a declined draft counts) and monitor stories in the JSON store."""
    found: set[str] = set()
    for row in proposals:
        for kind, identifier in trends.target_key(row.get("targets")):
            if kind == TARGET_TYPE and identifier.startswith(TARGET_PREFIX):
                found.add(identifier.removeprefix(TARGET_PREFIX))
    found.update(str(idea["referenceLineageId"]) for idea in stored if idea.get("origin") == "monitor" and idea.get("referenceLineageId"))
    return found


# --- what the model sees -------------------------------------------------------------------------------------------------------


def facts_of(details: dict[str, Any]) -> dict[str, Any]:
    """The simple facts a monitor stored with an item (numbers, short text, short lists of text); the model may use them and the check grounds on them."""
    facts: dict[str, Any] = {}
    for key, value in details.items():
        if len(facts) >= MAXIMUM_FACTS:
            break
        if key in SUMMARY_KEYS or value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            facts[key] = value
        elif isinstance(value, str) and value.strip():
            facts[key] = value.strip()[:FACT_LIMIT]
        elif isinstance(value, list) and value and all(isinstance(entry, str) for entry in value):
            facts[key] = [entry.strip()[:FACT_LIMIT] for entry in value[:5] if entry.strip()]
    return facts


def stored_summary(details: dict[str, Any]) -> str | None:
    for key in SUMMARY_KEYS:
        if isinstance(details.get(key), str) and details[key].strip():
            return re.sub(r"\s+", " ", details[key]).strip()[:TEXT_LIMIT]
    return None


def read_source_text(url: str, fetch: SourceFetcher = fetch_source) -> str | None:
    """The plain text of the linked page or PDF (a few paragraphs, TEXT_LIMIT characters at most), or None when it cannot be read. Never raises."""
    return source_text.read_source_text(url, fetch, TEXT_LIMIT)


Explorer = Callable[[MonitoredItem], Exploration]


def explore_item(item: MonitoredItem) -> Exploration:
    """Follow the item's address through trackers and read it; when that fails, search the web for its title and read the best match.

    The context is the stored title and summary only. Nothing here raises.
    """
    return link_exploration.explore(item.url, Context(title=item.title, summary=stored_summary(item.details) or ""), want_text=True, text_limit=TEXT_LIMIT)


def source_view(item: MonitoredItem, page_text: str | None) -> dict[str, Any]:
    """What the model sees of the source, and the only numbers and dates a sentence citing it may use."""
    view = {
        "handle": SOURCE_HANDLE, "title": item.title, "url": item.url, "monitor": item.monitor_id,
        "published": (item.published_at or "")[:10] or None, "found": item.arrived_at[:10] or None,
        "summary": stored_summary(item.details), "facts": facts_of(item.details) or None, "page_text": page_text,
    }
    return {key: value for key, value in view.items() if value not in (None, [], {}, "")}


def has_material(view: dict[str, Any]) -> bool:
    """A story needs more than a title to stand on: page text, a stored summary or stored facts."""
    return any(key in view for key in ("page_text", "summary", "facts"))


def build_input(item: MonitoredItem, view: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return {
        "mission": context.get("mission"), "policy": context.get("policy"),
        "allowed_sections": [section["title"] for section in context.get("sections", [])],
        "source": view,
        "recent_and_in_flight_stories": [{key: story.get(key) for key in ("title", "section", "state", "date", "summary") if story.get(key)} for story in context.get("stories", [])],
        "earlier_drafts": [{key: draft.get(key) for key in ("title", "state", "angle") if draft.get(key)} for draft in context.get("drafts", [])],
    }


def call_model(transport: synthesis.Transport, model: str, model_input: dict[str, Any]) -> tuple[dict[str, Any], synthesis.Usage]:
    payload = synthesis.request_payload(model, model_input) | {"instructions": SYSTEM_PROMPT, "text": {"format": SCHEMA}, "max_output_tokens": MAXIMUM_OUTPUT_TOKENS}
    body = transport(synthesis.RESPONSES_URL, {"Content-Type": "application/json"}, payload)
    text = synthesis.response_text(body)
    if body.get("status") == "incomplete" or text is None:
        raise synthesis.SynthesisError("The model returned no complete answer.")
    try:
        draft = json.loads(text)
    except ValueError as error:
        raise synthesis.SynthesisError("The model did not answer with the monitor story format.") from error
    if not isinstance(draft, dict):
        raise synthesis.SynthesisError("The model did not answer with one draft.")
    return draft, synthesis.usage_of(body, model)


# --- the citation check --------------------------------------------------------------------------------------------------------


def check_story(raw: Any, item: MonitoredItem, view: dict[str, Any], allowed_sections: list[str]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(the checked draft or None, the citation check record). The sentence rules are the trend path's (``trends.check_sentence``): the only handle
    is the source, so every sentence cites it and every number and date in it is in the source."""
    source_id = f"item:{item.url}"
    handles = {SOURCE_HANDLE: source_id}
    views = {source_id: trends.facts_in({key: value for key, value in view.items() if key != "handle"})}
    record: dict[str, Any] = {"status": "failed", "sentences": 0, "problems": []}
    if not isinstance(raw, dict):
        record["problems"].append(trends._problem("draft", "", "not_an_object"))
        return None, record
    problems: list[dict[str, str]] = record["problems"]
    headline, found = trends.check_sentence("headline", raw.get("headline"), handles, views)
    problems += found
    dek, found = trends.check_sentence("dek", raw.get("dek"), handles, views)
    problems += found
    raw_paragraphs = raw.get("paragraphs")
    if not isinstance(raw_paragraphs, list) or not raw_paragraphs or len(raw_paragraphs) > MAXIMUM_PARAGRAPHS:
        problems.append(trends._problem("body", "", "paragraphs_missing_or_too_many"))
        raw_paragraphs = []
    paragraphs, sentences, attempted = [], [], 0
    for number, paragraph in enumerate(raw_paragraphs, start=1):
        entries = paragraph.get("sentences") if isinstance(paragraph, dict) else None
        checked_paragraph = []
        for position, entry in enumerate(entries if isinstance(entries, list) else [], start=1):
            attempted += 1
            checked, found = trends.check_sentence(f"paragraph {number} sentence {position}", entry, handles, views)
            problems += found
            if checked:
                checked_paragraph.append(checked)
                sentences.append(checked)
        if not checked_paragraph and not any(problem["where"].startswith(f"paragraph {number} ") for problem in problems):
            problems.append(trends._problem(f"paragraph {number}", "", "empty_paragraph"))
        paragraphs.append(checked_paragraph)
    record["sentences"] = len(sentences) + (headline is not None) + (dek is not None)
    if attempted < MINIMUM_BODY_SENTENCES:
        problems.append(trends._problem("body", "", "fewer_than_two_body_sentences"))
    sections = {name.strip().lower(): name for name in allowed_sections}
    section = str(raw.get("section") or "").strip()
    if sections and section.lower() not in sections:
        problems.append(trends._problem("section", section, "unknown_section"))
    if problems or headline is None or dek is None:
        return None, record
    record.update(status="passed", itemsCited=[source_id])
    return {"headline": headline, "dek": dek, "section": sections.get(section.lower(), section), "paragraphs": paragraphs, "citationCheck": record}, record


# --- the draft record ----------------------------------------------------------------------------------------------------------


def draft_body(draft: dict[str, Any], item: MonitoredItem) -> str:
    """Markus: the dek and paragraphs, each sentence marked ``[1]`` (the source), then the source with its address and who found it."""

    def marked(sentence: dict[str, Any]) -> str:
        return f"{sentence['text']} [1]"

    verdict = item.verdict or {}
    score = f" with a score of {verdict['score']}" if verdict.get("score") is not None else ""
    judged = f" The relevance check labelled it {verdict['label']}{score}." if verdict.get("label") else ""
    published = f" ({item.published_at[:10]})" if item.published_at else ""
    lines = [marked(draft["dek"]), ""]
    lines += [" ".join(marked(sentence) for sentence in paragraph) + "\n" for paragraph in draft["paragraphs"]]
    lines += ["## Source", "", f"1. {item.title}{published} {item.url}", ""]
    lines += [f"Section: {draft['section']}. Drafted by AI from an item the {item.monitor_id} monitor found.{judged} An editor approves the copy before anything is published.", ""]
    return "\n".join(lines)


def run_id_for(site: str, now: datetime) -> str:
    return f"monitor-stories-run-{now.strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256((site + iso(now)).encode()).hexdigest()[:6]}"


def draft_record(draft: dict[str, Any], item: MonitoredItem, view: dict[str, Any], *, run: dict[str, Any], now: datetime, exploration: Exploration | None = None) -> dict[str, Any]:
    found_by_search = exploration is not None and exploration.via == "search"
    record = {
        "ideaId": "idea-" + hashlib.sha256(f"{run['runId']}|{item.lineage_id}".encode()).hexdigest()[:10],
        "kind": "story_draft", "origin": "monitor", "state": "draft", "proposer": "ai", "proposedBy": "AI", "private": True,
        "publication": run["publication"], "runId": run["runId"], "createdAt": iso(now),
        "title": draft["headline"]["text"][:200], "angle": draft["dek"]["text"][:300], "section": draft["section"],
        "body": draft_body(draft, item),
        "targets": [target_for(item)],
        "evidence": {"signals": 1, "source": f"{item.monitor_id} monitor: {item.url}"[:200]},
        "monitorId": item.monitor_id, "referenceId": item.reference_id, "referenceLineageId": item.lineage_id, "relevance": item.verdict,
        "sourceText": ("page found by search" if found_by_search else "page") if "page_text" in view else "stored details",
        "citedItems": [{"id": f"item:{item.url}", "title": item.title, "date": (item.published_at or "")[:10] or None, "url": item.url}],
        "citationCheck": draft["citationCheck"],
        "sentences": [{"role": role, **sentence} for role, sentence in [("headline", draft["headline"]), ("dek", draft["dek"])]]
        + [{"role": "body", **sentence} for paragraph in draft["paragraphs"] for sentence in paragraph],
    }
    if found_by_search:
        # The original address could not be read, so the text came from a different page: say so, with the query and the match score.
        record["sourceExploration"] = exploration.as_record()
    return record


# --- the run -------------------------------------------------------------------------------------------------------------------


def draft_monitor_stories(
    *,
    client: Any,
    site: str,
    context: dict[str, Any],
    json_store: JsonStore | None,
    transport: synthesis.Transport,
    proposal_store: ProposalStore | None = None,
    review_client: Any = None,
    model: str = synthesis.DEFAULT_MODEL,
    limit: int | None = DEFAULT_LIMIT,
    since: str | None = None,
    threshold: float = dedupe.DEFAULT_THRESHOLD,
    maximum_cost_usd: float = DEFAULT_MAXIMUM_COST_USD,
    dry_run: bool = False,
    now: datetime | None = None,
    fetch: SourceFetcher = fetch_source,
    corpus_key: str | None = None,
    excluded_hosts: Iterable[str] = (),
    explorer: Explorer | None = None,
    statuses: Iterable[str] = DEFAULT_STATUSES,
    out_of_time: Callable[[], bool] | None = None,
    read_workers: int = 1,
    automation_handled: Iterable[str] = (),
) -> dict[str, Any]:
    """Drafts monitor stories and returns the run ledger. A dry run reads, asks the model and checks, but files, stores and requests nothing.

    ``limit=None`` drafts every candidate (the daily router task, docs/monitoring-cloud.md#monitor-stories): the run then stops only for a real
    constraint, and ``stoppedBy`` names it: ``time`` (``out_of_time()`` turned true between two items; the rest is picked up by the next run),
    ``cost`` (``maximum_cost_usd``) or ``file_error`` (a draft could not be filed: the run stops rather than spend on drafts that cannot be kept).
    Each draft is filed as soon as it is kept, so a run that stops early loses nothing it paid for."""
    moment = now or datetime.now(timezone.utc)
    run: dict[str, Any] = {
        "runId": run_id_for(site, moment), "kind": "monitor-stories-run", "publication": site, "startedAt": iso(moment), "model": model,
        "store": "dry-run" if dry_run else (proposal_store.kind if proposal_store else "json"), "dryRun": dry_run, "private": True,
        "window": {"since": since, "until": iso(moment)}, "limit": limit, "stoppedBy": None,
        "excludedSourceHosts": list(normalize_hosts(excluded_hosts)), "statuses": list(dict.fromkeys(statuses)),
    }
    stored = [idea for idea in (json_store.ideas() if json_store else []) if idea.get("origin") == "monitor"]
    proposals = proposal_store.story_drafts() if proposal_store else []
    already = drafted_lineage_ids(proposals, stored)
    automated, automation_error = automated_monitor_ids(client)
    items, counts = collect_monitored_items(
        client, site=corpus_key or site, since=since, now=moment, drafted=already, excluded_hosts=excluded_hosts, automated_monitors=automated, automation_handled=automation_handled, statuses=statuses,
        workers=read_workers, out_of_time=out_of_time,
    )
    if counts.get("readStopped"):
        run["stoppedBy"] = "time"   # the time ran out while reading: what was read is drafted if any time is left, the rest waits for the next run
    run["automatedMonitors"] = sorted(automated)
    if automation_error:
        run["automationLookupError"] = automation_error
    freshness = learn_freshness(items)
    run["freshness"] = freshness or {"tauDays": None, "examples": sum(item.status == "accepted" for item in items), "note": f"Fewer than {MINIMUM_FRESHNESS_EXAMPLES} accepted examples: no freshness weight, the score alone ranks."}
    promoted = promoted_reference_ids(client, items) if items else set()
    counts.update(alreadyDrafted=sum(item.lineage_id in already for item in items), promoted=sum(item.reference_id in promoted and item.lineage_id not in already for item in items))
    # One Reference is drafted once: not when its lineage, nor the address it came from, is already covered by a Proposal in any state, nor twice in this run.
    keys = source_keys(items)
    covered_addresses = {keys[lineage] for lineage in already if keys.get(lineage)}
    ranked = rank([item for item in items if item.lineage_id not in already and item.reference_id not in promoted], freshness, moment)
    candidates, seen_lineages, seen_addresses, same_source = [], set(), set(), 0
    for item in ranked:
        address = keys.get(item.lineage_id)
        if item.lineage_id in seen_lineages or (address and (address in covered_addresses or address in seen_addresses)):
            same_source += 1
            continue
        seen_lineages.add(item.lineage_id)
        if address:
            seen_addresses.add(address)
        candidates.append(item)
    counts["sameSource"] = same_source
    counts["candidates"] = len(candidates)
    run["inputs"] = counts
    attempt_cap = None if limit is None else limit * ATTEMPT_FACTOR
    run["ranking"] = [{"rank": number, **item.as_dict()} for number, item in enumerate(candidates[:attempt_cap], start=1)]
    run.update(attempted=0, invalid=[], skipped=[], duplicates=[], drafts=[], modelCalls=[], usage=None)
    documents = comparison_documents(context, [*stored], proposals, [])
    sections = [section["title"] for section in context.get("sections", [])]
    spent = 0.0
    kept: list[dict[str, Any]] = []
    for item in candidates:
        if limit is not None and (len(kept) >= limit or run["attempted"] >= attempt_cap):
            break
        if out_of_time is not None and out_of_time():
            run["stoppedBy"] = "time"
            break
        exploration = explorer(item) if explorer else None
        page_text = exploration.text if exploration else read_source_text(item.url, fetch)
        view = source_view(item, page_text)
        if not has_material(view):
            skipped = {"referenceId": item.reference_id, "title": item.title, "reason": "no_source_text"}
            if exploration:
                skipped.update(readFailure=exploration.failure or "unreadable", directFailure=exploration.direct_failure, searchFailure=exploration.search_failure)
            run["skipped"].append({key: value for key, value in skipped.items() if value})
            continue
        model_input = build_input(item, view, context)
        size = len(SYSTEM_PROMPT) + len(str(model_input))
        if size > synthesis.MAXIMUM_INPUT_CHARACTERS:
            run["skipped"].append({"referenceId": item.reference_id, "title": item.title, "reason": "input_too_large"})
            continue
        estimate = synthesis.estimate_cost_usd(model, size, MAXIMUM_OUTPUT_TOKENS)
        if estimate is not None and spent + estimate > maximum_cost_usd:
            run["stoppedForCost"] = f"The next call is estimated at ${estimate:.4f}; ${spent:.4f} is spent of --max-cost-usd ${maximum_cost_usd:.2f}."
            run["stoppedBy"] = "cost"
            break
        run["attempted"] += 1
        try:
            raw, usage = call_model(transport, model, model_input)
        except synthesis.SynthesisError as error:
            run["invalid"].append({"referenceId": item.reference_id, "title": item.title, "reason": "model_error", "message": str(error)[:300]})
            continue
        spent += usage.cost_usd or 0.0
        run["modelCalls"].append({"model": model, "promptTokens": usage.input_tokens, "completionTokens": usage.output_tokens, "cachedTokens": usage.cached_input_tokens})
        draft, record = check_story(raw, item, view, sections)
        if draft is None:
            title = str(((raw.get("headline") or {}).get("text")) if isinstance(raw, dict) and isinstance(raw.get("headline"), dict) else "")[:200]
            run["invalid"].append({"referenceId": item.reference_id, "title": title or item.title, "reason": "citation_check_failed", "citationCheck": record, "draft": raw})
            continue
        built = draft_record(draft, item, view, run=run, now=moment, exploration=exploration)
        similar, dropped = dedupe.split_duplicates([built], [*documents, *(dedupe.Document("draft", k["ideaId"], k["title"], k["angle"]) for k in kept)], threshold)
        run["duplicates"] += [{**row, "referenceId": item.reference_id} for row in dropped]
        kept += similar
        for record in similar:
            if not dry_run:
                try:
                    if proposal_store:
                        # Read the targets again: another run (an overlapping task, a laptop) may have filed this Reference since this run began.
                        if item.lineage_id in drafted_lineage_ids(proposal_store.story_drafts(), []):
                            run["skipped"].append({"referenceId": item.reference_id, "title": item.title, "reason": "already_drafted"})
                            continue
                        proposal_store.mark(record, proposal_store.file_story_draft(record))
                    if json_store:
                        json_store.save_idea(record)
                except IdeaRefused as refusal:   # the editorial check found an error-severity violation: not filed, the run goes on
                    run["invalid"].append({**refusal.as_invalid(record), "referenceId": item.reference_id})
                    continue
                except Exception as error:  # noqa: BLE001 - whatever is filed stays filed; stop before paying for drafts that cannot be kept
                    run["fileError"] = f"{type(error).__name__}: {error}"[:300]
                    run["stoppedBy"] = "file_error"
                    break
            run["drafts"].append(record)
        if run["stoppedBy"] == "file_error":
            break
    run["usage"] = _usage(model, run["modelCalls"])
    run["ideasCreated"] = 0 if dry_run else len(run["drafts"])
    if dry_run:
        run["review"] = {"status": "skipped", "requested": False, "ideas": len(run["drafts"]), "note": "Dry run: nothing was filed, so no review was requested."}
    else:
        request_human_review(review_client, run, run["drafts"], noun="monitor story draft")
    run["finishedAt"] = iso(datetime.now(timezone.utc))
    if json_store and not dry_run:
        json_store.save_run(run)
    return run


def _usage(model: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    total = synthesis.Usage(
        model=model, input_tokens=sum(call["promptTokens"] for call in calls), cached_input_tokens=sum(call["cachedTokens"] for call in calls),
        output_tokens=sum(call["completionTokens"] for call in calls),
    )
    return {**total.as_dict(), "calls": len(calls)}


def render_report(run: dict[str, Any]) -> str:
    """The markdown a person reads: the ranking, each draft with its body, then what failed the check or was skipped, and why."""
    usage = run.get("usage") or {}
    inputs = run["inputs"]
    lines = [
        f"# Monitor story drafts: {run['publication']}",
        "",
        f"Run `{run['runId']}`, " + (f"items that arrived in the last {run['window']['since']}" if run["window"]["since"] else "every undrafted monitored item") + f". Proposed by AI." + (" Dry run: nothing was filed." if run["dryRun"] else " Private drafts for review; nothing here is published."),
        "",
        "- Freshness: " + (f"tau {run['freshness']['tauDays']} days from {run['freshness']['examples']} accepted items" if run["freshness"]["tauDays"] else f"none ({run['freshness']['note']})"),
        f"- Monitored items read ({', '.join(run['statuses'])} only; pending not read: {inputs.get('notAccepted', 0)}): {inputs['inWindow'] - inputs['notMonitored'] - inputs.get('excludedHost', 0) - inputs.get('handledByAutomation', 0) - inputs.get('hasStory', 0)}; from excluded source hosts (never drafted): {inputs.get('excludedHost', 0)}; handled by an automation (a story based on it, or a procedure run recorded or in progress; never drafted here): {inputs.get('handledByAutomation', 0)}; already has a story based on it: {inputs.get('hasStory', 0)}; judged not relevant: {inputs['judgedNotRelevant']}; already drafted: {inputs['alreadyDrafted']}; the same address as a drafted or earlier candidate: {inputs.get('sameSource', 0)}; promoted: {inputs['promoted']}; candidates: {inputs['candidates']}",
        f"- Drafts attempted: {run['attempted']} ({'no limit' if run['limit'] is None else 'limit ' + str(run['limit'])}); kept: {len(run['drafts'])}; failed the check: {len(run['invalid'])}; skipped: {len(run['skipped'])}; duplicates dropped: {len(run['duplicates'])}",
        f"- Model {run['model']}: {usage.get('inputTokens', 0)} input and {usage.get('outputTokens', 0)} output tokens in {usage.get('calls', 0)} call(s), cost ${usage.get('costUsd') if usage.get('costUsd') is not None else 'unknown'}",
        "",
    ]
    for number, draft in enumerate(run["drafts"], start=1):
        lines += [f"## {number}. {draft['title']}", "", f"From the {draft['monitorId']} monitor, {draft['citedItems'][0]['url']} (source text: {draft['sourceText']}). Citation check: passed ({draft['citationCheck']['sentences']} sentences).", "", draft["body"].rstrip(), ""]
    for heading, rows, describe in (
        ("Failed the citation check or were invalid", run["invalid"], lambda r: f"{r['title'] or '(untitled)'}: {r['reason']}" + "".join(f"\n  - {p['where']}: {p['reason']}" + (f" ({p['text']})" if p["text"] else "") for p in (r.get("citationCheck") or {}).get("problems", []))),
        ("Skipped", run["skipped"], lambda r: f"{r['title']}: {r['reason']}" + (f" ({r['readFailure']})" if r.get("readFailure") else "")),
        ("Dropped as duplicates", run["duplicates"], lambda r: f"{r['title']}: {r['reason']}"),
    ):
        if rows:
            lines += [f"## {heading}", ""] + [f"- {describe(row)}" for row in rows] + [""]
    if run.get("stoppedForCost"):
        lines += [f"Stopped early: {run['stoppedForCost']}", ""]
    return "\n".join(lines)
