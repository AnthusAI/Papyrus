"""Curation before review: capture, summarize and (for papers) structure a Reference before an editor is asked about it.

``curate_reference`` runs the stages in this order, for one Reference, and records every stage's outcome on the Reference's curation
card (``reference_curation_store``; shapes in ``docs/reference-curation-pipeline.md``):

1. **capture**: resolve the source address and read the whole article or PDF (``reference_capture``), then compute the completeness
   signals. Signals are stored as facts; no stage decides whether a capture is complete.
2. **summary**: one gpt-6-luna summary of the captured text, in source voice (the prompt mirrors ``reference_summarization.tac``).
3. **GROBID** (research papers only): title, authors, abstract, sections and references from a GROBID service
   (``reference_grobid``), or a typed skip when none is configured.

It is idempotent: a Reference whose card is ``ready`` is left alone, a stage that finished is not repeated, and a stage that failed for a
reason that may pass (a timeout, a busy GROBID) is retried by the next run. Two runs at once are kept apart by a lease on the card.
Text an editor has pasted is never recaptured over.

Entry points: the Tactus tool ``papyrus_curate_reference`` (started by the monitoring router after a delivery, through the procedure runner)
and ``papyrus references curate`` (a backfill over a corpus).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .ids import hash_short
from .knowledge_snapshot.parallel import DEFAULT_WORKERS, map_with_clients, worker_count
from .link_exploration import explore
from .options import normalize_string, parse_options, resolve_mutation_apply
from .publication_dates import normalize_html_date, publication_date_resolution_record
from .reference_capture import SHORT_BODY_CHARACTERS, Capture, capture_source
from .reference_curation_store import (
    GROBID_SORT_KEY,
    GROBID_TEI_SORT_KEY,
    LEASE_SECONDS,
    METADATA_SORT_KEY,
    PIPELINE_VERSION,
    STATUS_RUNNING,
    TEXT_SORT_KEY,
    AttachmentStore,
    compute_status,
    current_text,
    find_reference,
    has_text_edit,
    iso,
    new_card,
    read_card,
    sha256_text,
    utc_now,
    write_card,
)
from .reference_grobid import (
    SKIP_REASONS_RETRYABLE,
    GrobidUnavailable,
    parse_tei,
    process_fulltext,
    resolve_grobid_url,
    summarize_fields,
)

SUMMARY_MODEL = "gpt-6-luna"   # the only model curation uses (Ryan, 2026-10); not an option
SUMMARY_PROMPT_VERSION = "reference-summary-v3-source-voice"
SUMMARY_MAX_TOKENS = 500
SUMMARY_MAX_OUTPUT_TOKENS = 4000          # includes the model's reasoning, so it is much larger than the summary itself
SUMMARY_INPUT_CHARACTERS = 120_000        # the model's input window, not a policy: longer text keeps its head and its tail
SUMMARY_HEAD_CHARACTERS = 100_000

SUMMARY_INSTRUCTIONS = """You summarize reference source material for Papyrus editorial curation metadata.

Always write in source voice:
- State what the source says directly.
- Do not frame as commentary about the source.
- Avoid openings like "This paper/article/review/work/study..." or "In this paper...".
- Do not describe the document itself ("A systematic review examines...", "The study investigates...", "The paper argues...").
- You may mention substantive evidence/method terms (survey, poll, trial, study, experiment) when they are part of the finding itself.
- Write claims directly (example: "Intelligent assessment and generative AI can strengthen learner agency when used as support, but can weaken it when over-relied on.").

Grounding rules:
- Keep claims faithful to provided source text and metadata.
- Do not invent evidence, citations, findings, or recommendations.
- Be concise and useful for downstream newsroom context.
"""

SUMMARY_MESSAGE = """Write a concise summary in no more than {tokens} tokens.

State what the source says directly in source voice.
Do not use referential lead-ins such as:
- "This paper..."
- "This article..."
- "This review..."
- "This work..."
- "This study..."
- "In this paper..."
- "A systematic review examines..."
- "The study investigates..."
- "The paper argues..."
You may mention substantive evidence/method terms (survey, poll, trial, study, experiment) when they are part of the finding itself.

Preserve the central contribution, method, evidence type, and relevance.
Do not add claims that are not supported by the provided text.

Title: {title}
Source URI: {source_uri}

{text}
"""

Summarizer = Callable[[dict[str, Any]], dict[str, Any]]


class SummaryFailed(Exception):
    """The summary call failed. ``reason`` is typed; model-service failures are worth retrying."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def openai_summarizer(api_key: str, *, transport: Any = None) -> Summarizer:
    """The summary stage's model call: gpt-6-luna through the Responses API, with the source-voice prompt."""
    from .ideas import synthesis

    send = transport or synthesis.openai_transport(api_key)

    def summarize(request: dict[str, Any]) -> dict[str, Any]:
        text = str(request["text"])
        truncated = len(text) > SUMMARY_INPUT_CHARACTERS
        if truncated:
            text = text[:SUMMARY_HEAD_CHARACTERS] + "\n\n[...]\n\n" + text[-(SUMMARY_INPUT_CHARACTERS - SUMMARY_HEAD_CHARACTERS):]
        message = SUMMARY_MESSAGE.format(tokens=request.get("maxTokens") or SUMMARY_MAX_TOKENS, title=request.get("title") or "",
                                         source_uri=request.get("sourceUri") or "", text=text)
        payload = {"model": SUMMARY_MODEL, "instructions": SUMMARY_INSTRUCTIONS, "input": message,
                   "max_output_tokens": SUMMARY_MAX_OUTPUT_TOKENS, "store": False}
        try:
            body = send(synthesis.RESPONSES_URL, {"Content-Type": "application/json"}, payload)
        except synthesis.SynthesisError:
            raise SummaryFailed("model_failed") from None
        answer = synthesis.response_text(body)
        if body.get("status") == "incomplete" or not answer or not answer.strip():
            raise SummaryFailed("empty_summary")
        usage = synthesis.usage_of(body, SUMMARY_MODEL)
        return {"text": answer.strip(), "model": SUMMARY_MODEL, "promptVersion": SUMMARY_PROMPT_VERSION, "inputTruncated": truncated,
                "usage": {"inputTokens": usage.input_tokens, "cachedInputTokens": usage.cached_input_tokens, "outputTokens": usage.output_tokens}}

    return summarize


@dataclass
class Services:
    """Everything curation reaches outside itself for. Tests replace each one."""

    store: AttachmentStore
    summarizer: Summarizer | None = None
    grobid_url: str | None = None
    grobid_post: Callable[..., Any] | None = None
    explorer: Callable[..., Any] = explore
    capture: Callable[..., Capture] = capture_source
    now: Callable[[], datetime] = utc_now


def default_services(client: Any, *, start_grobid: bool = False, grobid_url: str | None = None) -> Services:
    from .papyrus_config import resolve_openai_api_key

    api_key = resolve_openai_api_key()
    try:
        resolved = resolve_grobid_url(explicit=grobid_url, start=start_grobid)
    except GrobidUnavailable:
        resolved = None
    return Services(store=AttachmentStore(client), summarizer=openai_summarizer(api_key) if api_key else None, grobid_url=resolved)


# --- planning --------------------------------------------------------------------------------------------------------


TRANSIENT_SUMMARY_REASONS = frozenset({"model_failed", "empty_summary", "openai_not_configured", "no_text"})


def plan_stages(card: dict[str, Any] | None, *, force: bool, grobid_configured: bool, now: datetime, summarizer_available: bool = True) -> dict[str, Any]:
    """Which stages a run would do for this card, and why not when none. Pure; the backfill's ``--dry-run`` prints it."""
    if card is None:
        return {"outcome": "planned", "capture": True, "summary": True, "grobid": True}
    if card.get("status") == STATUS_RUNNING:
        started = _parse(card.get("startedAt"))
        if started and now - started < timedelta(seconds=LEASE_SECONDS):
            return {"outcome": "in_progress", "capture": False, "summary": False, "grobid": False}
    edited = has_text_edit(card)
    capture = card.get("capture") or {}
    summary = card.get("summary") or {}
    grobid = card.get("grobid") or {}
    paper = bool((card.get("paper") or {}).get("isPaper"))
    capture_needed = not edited and (force or capture.get("status") != "completed" and not (
        capture.get("status") == "failed" and not capture.get("transient")))
    if force or summary.get("stale"):
        summary_needed = True
    elif summary.get("text"):
        summary_needed = False
    else:
        reason = summary.get("reason")
        summary_needed = summary.get("status") in {None, "not_run"} or (
            reason in TRANSIENT_SUMMARY_REASONS and (reason != "openai_not_configured" or summarizer_available))
    text_possible = capture.get("status") == "completed" or capture_needed or bool((card.get("current") or {}).get("textSortKey"))
    summary_needed = bool(summary_needed and text_possible)
    grobid_needed = paper and (force or grobid.get("status") in {None, "not_run"} or (
        grobid.get("status") in {"skipped", "failed"} and grobid.get("reason") in SKIP_REASONS_RETRYABLE
        and (grobid.get("reason") != "grobid_not_configured" or grobid_configured)))
    if grobid.get("editedByEditor") and not force:
        grobid_needed = False
    if not (capture_needed or summary_needed or grobid_needed):
        return {"outcome": "already_curated", "capture": False, "summary": False, "grobid": False}
    return {"outcome": "planned", "capture": capture_needed, "summary": summary_needed, "grobid": grobid_needed}


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# --- one Reference ---------------------------------------------------------------------------------------------------


def curate_reference(client: Any, reference: dict[str, Any], *, services: Services, force: bool = False, dry_run: bool = False) -> dict[str, Any]:
    """Run the stages this Reference still needs. Never raises for a bad source; a failure is a stage outcome on the card."""
    now = services.now()
    card = read_card(client, reference)
    plan = plan_stages(card, force=force, grobid_configured=bool(services.grobid_url), now=now,
                       summarizer_available=services.summarizer is not None)
    result: dict[str, Any] = {"referenceId": reference["id"], "outcome": plan["outcome"], "planned": {k: plan[k] for k in ("capture", "summary", "grobid")},
                              "status": (card or {}).get("status")}
    if dry_run or plan["outcome"] != "planned":
        return result
    source_uri = normalize_string(reference.get("sourceUri"))
    card = card or new_card(reference)
    card.update({"status": STATUS_RUNNING, "startedAt": iso(now), "sourceUri": source_uri or "", "pipelineVersion": PIPELINE_VERSION})
    write_card(client, reference, card, now)
    store = services.store
    captured: Capture | None = None
    try:
        if (plan["capture"] or plan["grobid"]) and not has_text_edit(card):
            captured = (services.capture(source_uri, title=str(reference.get("title") or ""), explorer=services.explorer)
                        if source_uri else Capture(False, "no_source_uri"))
        if plan["capture"] and captured is not None:
            _record_capture(card, captured, reference, store, services.now())
            _publication_date_stage(client, reference, card, captured, services.now())
        if plan["summary"]:
            _summary_stage(card, reference, store, services, captured, force)
        if plan["grobid"]:
            _grobid_stage(card, reference, store, services, captured)
    except Exception as error:  # noqa: BLE001 - an unexpected bug must leave the card retryable, not stuck in "running"
        card.setdefault("errors", []).append({"at": iso(services.now()), "type": type(error).__name__})
    card["status"] = compute_status(card)
    card["completedAt"] = iso(services.now())
    write_card(client, reference, card, services.now())
    result.update(outcome="curated", status=card["status"], bodyCharacters=(card.get("signals") or {}).get("characterCount"), stages={name: (card.get(name) or {}).get("status")
                                                                    for name in ("capture", "summary", "grobid")})
    return result


def _publication_date_stage(client: Any, reference: dict[str, Any], card: dict[str, Any], captured: Capture, now: datetime) -> None:
    """Resolve the source's own publication date once, onto ``Reference.sourcePublishedAt``, with its provenance on the curation card
    (``card["publicationDate"]``, stored in the curation attachment's metadata; the Reference model has no metadata field). A date already on
    the Reference (a monitor supplied it) is kept, and an unknown date stays null: the ingestion date is never copied into it."""
    if card.get("publicationDate"):
        return
    existing = normalize_string(reference.get("sourcePublishedAt"))
    stamp = iso(now)
    if existing:
        kept = normalize_html_date(existing)
        card["publicationDate"] = publication_date_resolution_record(source="monitor", precision=(kept or {}).get("precision", "day"), resolved_at=stamp)
        return
    if not captured.publication_date:
        return
    found = captured.publication_date
    client.update_record("Reference", {"id": reference["id"], "sourcePublishedAt": found["value"]})
    reference["sourcePublishedAt"] = found["value"]
    card["publicationDate"] = publication_date_resolution_record(source=found["source"], precision=found["precision"], resolved_at=stamp)


def _record_capture(card: dict[str, Any], captured: Capture, reference: dict[str, Any], store: AttachmentStore, now: datetime) -> None:
    stamp = iso(now)
    capture: dict[str, Any] = {"status": "completed" if captured.ok else "failed", "capturedAt": stamp, "sourceKind": captured.source_kind,
                               "contentType": captured.content_type, "via": captured.via, "destinationUrl": captured.destination_url,
                               "fullTextUrl": captured.full_text_url, "textVia": captured.text_via, "textReason": captured.text_reason}
    if captured.ok:
        store.write(reference, TEXT_SORT_KEY, "curation-text.md", "text/markdown", captured.text, now)
        capture.update(textSortKey=TEXT_SORT_KEY, textSha256=sha256_text(captured.text), wordCount=captured.signals.get("wordCount"))
        card.setdefault("current", {})["textSortKey"] = TEXT_SORT_KEY
    else:
        capture.update(reason=captured.failure, transient=captured.transient)
    card["capture"] = {key: value for key, value in capture.items() if value is not None}
    card["signals"] = captured.signals
    card["paper"] = captured.paper
    card["page"] = captured.page


def _summary_stage(card: dict[str, Any], reference: dict[str, Any], store: AttachmentStore, services: Services, captured: Capture | None,
                   force: bool) -> None:
    previous = card.get("summary") or {}
    text = captured.text if captured is not None and captured.ok and not has_text_edit(card) else current_text(card, reference, store)
    if not text:
        card["summary"] = {"status": "skipped", "reason": "no_text"}
        return
    existing = _existing_summary(reference, store)
    if existing and not force and not previous.get("stale") and not previous.get("text"):
        card["summary"] = {"status": "skipped", "reason": "already_present", "text": existing}
        return
    if services.summarizer is None:
        card["summary"] = {**{k: v for k, v in previous.items() if k == "text"}, "status": "skipped", "reason": "openai_not_configured"}
        return
    stamp = iso(services.now())
    try:
        made = services.summarizer({"text": text, "title": reference.get("title") or "", "sourceUri": reference.get("sourceUri") or "",
                                    "maxTokens": SUMMARY_MAX_TOKENS})
    except SummaryFailed as failure:
        card["summary"] = {**{k: v for k, v in previous.items() if k == "text"}, "status": "failed", "reason": failure.reason, "attemptedAt": stamp}
        return
    card["summary"] = {"status": "completed", "text": made["text"], "model": made["model"], "promptVersion": made["promptVersion"],
                       "generatedAt": stamp, "inputTruncated": bool(made.get("inputTruncated")), "usage": made.get("usage") or {},
                       "basedOn": (card.get("current") or {}).get("textSortKey"), "textSha256": sha256_text(text)}
    _write_reference_summary(reference, store, made, stamp, services.now())


def _existing_summary(reference: dict[str, Any], store: AttachmentStore) -> str:
    metadata = store.read_json(reference, METADATA_SORT_KEY) or {}
    return str(metadata.get("summary") or "").strip()


def _write_reference_summary(reference: dict[str, Any], store: AttachmentStore, made: dict[str, Any], stamp: str, now: datetime) -> None:
    """Also put the summary where earlier summaries live (the Reference's ``metadata.json``), so every reader of it sees this one."""
    metadata = store.read_json(reference, METADATA_SORT_KEY) or {}
    metadata["summary"] = made["text"]
    metadata["summary_resolution"] = {"model": made["model"], "promptVersion": made["promptVersion"], "source": "llm_reference_summary",
                                      "run_id": f"reference-curation-{hash_short([reference['id'], stamp])}", "resolved_at": stamp,
                                      "rationale": "Generated by curation before review from the captured source text."}
    store.write(reference, METADATA_SORT_KEY, "metadata.json", "application/json", json.dumps(metadata, indent=2, sort_keys=True) + "\n", now)


def _grobid_stage(card: dict[str, Any], reference: dict[str, Any], store: AttachmentStore, services: Services, captured: Capture | None) -> None:
    paper = card.get("paper") or {}
    if not paper.get("isPaper"):
        card["grobid"] = {"status": "skipped", "reason": "not_a_paper"}
        return
    if captured is None or not captured.ok:
        card["grobid"] = {"status": "skipped", "reason": "capture_failed" if captured is not None else "pdf_unavailable"}
        return
    if captured.pdf_bytes is None:
        card["grobid"] = {"status": "skipped", "reason": "pdf_unavailable"}
        return
    if not services.grobid_url:
        card["grobid"] = {"status": "skipped", "reason": "grobid_not_configured"}
        return
    stamp = iso(services.now())
    try:
        tei = process_fulltext(captured.pdf_bytes, services.grobid_url, post=services.grobid_post)
        fields = parse_tei(tei)
    except GrobidUnavailable as failure:
        status = "skipped" if failure.reason in {"pdf_unavailable"} else "failed"
        card["grobid"] = {"status": status, "reason": failure.reason, "attemptedAt": stamp,
                          "transient": failure.reason in SKIP_REASONS_RETRYABLE}
        return
    if not (fields.get("title") or fields.get("sections") or fields.get("references")):
        card["grobid"] = {"status": "failed", "reason": "grobid_empty", "attemptedAt": stamp, "transient": False}
        return
    store.write(reference, GROBID_SORT_KEY, "curation-grobid.json", "application/json", json.dumps(fields, indent=2, sort_keys=True) + "\n", services.now())
    store.write(reference, GROBID_TEI_SORT_KEY, "curation-grobid.tei.xml", "text/plain", tei, services.now())
    card["grobid"] = {"status": "completed", "extractedAt": stamp, "fieldsSortKey": GROBID_SORT_KEY, "teiSortKey": GROBID_TEI_SORT_KEY,
                      **summarize_fields(fields)}
    if not (card.get("current") or {}).get("grobidSortKey"):
        card.setdefault("current", {})["grobidSortKey"] = GROBID_SORT_KEY


def curate_reference_by_id(reference_id: str, *, force: bool = False, client: Any = None, services: Services | None = None) -> dict[str, Any]:
    """The procedure tool's body: curate one Reference by id with the site's own API and the environment's keys."""
    if client is None:
        from .graphql_authoring import create_authoring_client

        client, _ = create_authoring_client()
    reference = find_reference(client, reference_id)
    return curate_reference(client, reference, services=services or default_services(client), force=force)


# --- a corpus (the backfill) -----------------------------------------------------------------------------------------


def select_references(client: Any, *, corpus_id: str, status: str = "pending") -> list[dict[str, Any]]:
    """Current References of the corpus with the given curation status ("all" for every status), oldest first."""
    rows = [row for row in client.list_records("Reference")
            if row.get("corpusId") == corpus_id and row.get("versionState") in (None, "current")
            and (status == "all" or (row.get("curationStatus") or "pending") == status)
            and str(row.get("sourceUri") or "").lower().startswith(("http://", "https://"))]
    return sorted(rows, key=lambda row: (str(row.get("createdAt") or row.get("importedAt") or ""), str(row.get("id"))))


def curate_corpus(client: Any, *, corpus_id: str, status: str = "pending", limit: int | None = None, force: bool = False,
                  dry_run: bool = False, services: Services | None = None,
                  progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Curate every selected Reference that still needs it. A second run over an unchanged corpus does nothing."""
    references = select_references(client, corpus_id=corpus_id, status=status)
    cards = {}
    for row in client.list_records("ReferenceAttachment"):
        if row.get("role") == "curation":
            cards[row.get("referenceId")] = row
    services = services or (None if dry_run else default_services(client))
    counts = {"considered": len(references), "curated": 0, "alreadyCurated": 0, "inProgress": 0, "planned": 0, "ready": 0, "degraded": 0,
              "captureFailed": 0, "limited": 0, "shortBodies": 0}
    items = []
    attempted = 0
    for reference in references:
        if limit is not None and attempted >= limit:
            counts["limited"] += 1
            continue
        if dry_run:
            card = read_card_from_row(cards.get(reference["id"]))
            plan = plan_stages(card, force=force, grobid_configured=True, now=utc_now())
            outcome = {"referenceId": reference["id"], "outcome": plan["outcome"], "planned": {k: plan[k] for k in ("capture", "summary", "grobid")},
                       "status": (card or {}).get("status")}
            counts["planned" if plan["outcome"] == "planned" else {"already_curated": "alreadyCurated", "in_progress": "inProgress"}[plan["outcome"]]] += 1
            attempted += plan["outcome"] == "planned"
        else:
            outcome = curate_reference(client, reference, services=services, force=force)
            if outcome["outcome"] == "curated":
                counts["curated"] += 1
                attempted += 1
                counts[{"ready": "ready", "degraded": "degraded", "capture_failed": "captureFailed"}.get(outcome["status"], "degraded")] += 1
                characters = outcome.get("bodyCharacters")
                counts["shortBodies"] += characters is not None and 0 < characters < SHORT_BODY_CHARACTERS   # a statistic, not a gate
            else:
                counts["alreadyCurated" if outcome["outcome"] == "already_curated" else "inProgress"] += 1
        items.append(outcome)
        if progress:
            progress(outcome)
    return {"corpusId": corpus_id, "status": status, "dryRun": dry_run, "counts": counts, "items": items}


def read_card_from_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    try:
        card = json.loads(row.get("metadata") or "{}")
    except (TypeError, ValueError):
        return None
    return card if isinstance(card, dict) and card.get("kind") == "reference-curation" else None


def references_curate(flags: list[str]) -> None:
    """papyrus references curate --corpus <corpusId> [--status pending|accepted|rejected|all] [--limit N] [--force] [--dry-run]
    [--start-grobid] [--grobid-url URL] [--json]

    Capture, summarize and (for papers) GROBID-extract the Reference rows of one corpus that have not been curated yet, so an editor
    reviews them with their text and summary. Idempotent: run it again and only the Reference rows that still need a stage are touched.
    ``--dry-run`` reads the cards and prints what would run, without fetching anything or calling a model. ``--start-grobid`` lets
    Biblicus start a local GROBID container when a paper needs one (a developer machine with Docker); otherwise set
    ``BIBLICUS_GROBID_URL`` or ``--grobid-url``, or papers end with the typed skip ``grobid_not_configured``. The summary needs
    ``OPENAI_API_KEY``; without it summaries end with the typed skip ``openai_not_configured`` and a later run fills them in.
    """
    from .graphql_authoring import create_authoring_client

    options = parse_options(flags)
    for name in ("corpus", "status", "limit", "grobid-url"):
        if options.get(name) is True:
            raise ValueError(f"--{name} needs a value.")
    corpus = normalize_string(options.get("corpus"))
    if not corpus:
        raise ValueError("papyrus references curate needs --corpus <corpus id>.")
    corpus_id = corpus if corpus.startswith("knowledge-corpus-") else f"knowledge-corpus-{corpus}"
    status = normalize_string(options.get("status")) or "pending"
    if status not in {"pending", "accepted", "rejected", "archived", "all"}:
        raise ValueError("--status must be pending, accepted, rejected, archived or all.")
    apply = resolve_mutation_apply(options, "references curate")
    limit = int(options["limit"]) if options.get("limit") else None
    client, _ = create_authoring_client()
    services = default_services(client, start_grobid=bool(options.get("start-grobid")), grobid_url=normalize_string(options.get("grobid-url"))) if apply else None
    result = curate_corpus(client, corpus_id=corpus_id, status=status, limit=limit, force=bool(options.get("force")), dry_run=not apply,
                           services=services)
    if options.get("json"):
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    counts = result["counts"]
    print("references\tcurate\t" + "\t".join(f"{key}={value}" for key, value in counts.items()) + ("\tdry-run" if not apply else ""))


# --- publication dates only (the cheap backfill) ----------------------------------------------------------------------


class _RecordingClient:
    """Stands in for the client during ``--dry-run``: the date stage's update is kept, not sent."""

    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update_record(self, model: str, row: dict[str, Any]) -> None:
        self.updates.append(row)


def backfill_publication_date(client: Any, reference: dict[str, Any], *, capture: Callable[..., Capture] = capture_source,
                              explorer: Callable[..., Any] = explore, now: Callable[[], datetime] = utc_now, dry_run: bool = False) -> dict[str, Any]:
    """Resolve one Reference's publication date and nothing else (no summary, no GROBID). The date goes on ``Reference.sourcePublishedAt``
    and its provenance on the curation card (``card["publicationDate"]``); a Reference with no card gets a minimal one from ``new_card``.
    ``outcome`` is one of ``resolved`` (a date came from the page), ``monitor`` (the date the monitor supplied is recorded as such),
    ``unknown`` (the page declares none), ``fetch_failed``, ``skipped_pdf`` or ``already_resolved``. A page is fetched only when the
    Reference has no date at all."""
    result: dict[str, Any] = {"referenceId": reference["id"], "outcome": "already_resolved"}
    card = read_card(client, reference)
    if card and card.get("publicationDate"):
        return result
    source_uri = normalize_string(reference.get("sourceUri")) or ""
    if source_uri.lower().split("?")[0].split("#")[0].endswith(".pdf"):
        return {**result, "outcome": "skipped_pdf"}
    if normalize_string(reference.get("sourcePublishedAt")):
        captured = Capture(False, "not_needed")
    else:
        captured = capture(source_uri, title=str(reference.get("title") or ""), explorer=explorer)
        if captured.source_kind == "pdf":
            return {**result, "outcome": "skipped_pdf"}
        if not captured.ok:
            return {**result, "outcome": "fetch_failed", "failure": captured.failure}
    working = dict(reference)
    card = card or new_card(reference)
    stamp = now()
    _publication_date_stage(_RecordingClient() if dry_run else client, working, card, captured, stamp)
    resolution = card.get("publicationDate")
    if not resolution:
        return {**result, "outcome": "unknown"}
    if not dry_run:
        write_card(client, reference, card, stamp)
    return {**result, "outcome": "monitor" if resolution["source"] == "monitor" else "resolved", "date": working.get("sourcePublishedAt"),
            "source": resolution["source"], "precision": resolution["precision"]}


def backfill_publication_dates(client: Any, *, corpus_id: str, dry_run: bool = False, workers: int = DEFAULT_WORKERS,
                               client_factory: Callable[[], Any] | None = None, capture: Callable[..., Capture] = capture_source,
                               explorer: Callable[..., Any] = explore, now: Callable[[], datetime] = utc_now) -> dict[str, Any]:
    """Every current http(s) Reference of the corpus without a ``publicationDateResolution`` gets the date stage and no other."""
    references = select_references(client, corpus_id=corpus_id, status="all")
    items = map_with_clients(
        references, lambda worker, reference: backfill_publication_date(worker, reference, capture=capture, explorer=explorer, now=now, dry_run=dry_run),
        client=client, client_factory=client_factory, workers=workers)
    counts: dict[str, Any] = {"scanned": len(references), "alreadyResolved": 0, "resolved": 0, "resolvedBySource": {}, "keptMonitorDate": 0,
                              "unknown": 0, "fetchFailures": 0, "skippedPdf": 0}
    for item in items:
        outcome = item["outcome"]
        if outcome == "resolved":
            counts["resolved"] += 1
            counts["resolvedBySource"][item["source"]] = counts["resolvedBySource"].get(item["source"], 0) + 1
        else:
            counts[{"already_resolved": "alreadyResolved", "monitor": "keptMonitorDate", "unknown": "unknown", "fetch_failed": "fetchFailures",
                    "skipped_pdf": "skippedPdf"}[outcome]] += 1
    return {"corpusId": corpus_id, "dryRun": dry_run, "counts": counts, "items": items}


def references_backfill_publication_dates(flags: list[str]) -> None:
    """papyrus references backfill-publication-dates --corpus-id ID [--parallel N] [--dry-run] [--json]

    For every current Reference of the corpus with no ``metadata.publicationDateResolution``, capture the page the way curation does
    and run only the publication-date stage (no summary, no GROBID, no model cost). PDFs and non-http(s) sources are left alone. Writes
    unless ``--dry-run``, which prints what it would set (reference id, date, source, precision).
    """
    from .graphql_authoring import create_authoring_client

    options = parse_options(flags)
    for name in ("corpus-id", "corpus", "parallel"):
        if options.get(name) is True:
            raise ValueError(f"--{name} needs a value.")
    corpus = normalize_string(options.get("corpus-id")) or normalize_string(options.get("corpus"))
    if not corpus:
        raise ValueError("papyrus references backfill-publication-dates needs --corpus-id <corpus id>.")
    corpus_id = corpus if corpus.startswith("knowledge-corpus-") else f"knowledge-corpus-{corpus}"
    apply = resolve_mutation_apply(options, "references backfill-publication-dates")
    workers = worker_count(options.get("parallel"))
    client, _ = create_authoring_client()
    result = backfill_publication_dates(client, corpus_id=corpus_id, dry_run=not apply, workers=workers,
                                        client_factory=(lambda: create_authoring_client()[0]) if workers > 1 else None)
    if options.get("json"):
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if not apply:
        for item in result["items"]:
            if item["outcome"] in {"resolved", "monitor"}:
                print(f"would-set\t{item['referenceId']}\t{item['date']}\t{item['source']}\t{item['precision']}")
    counts = result["counts"]
    if not counts["scanned"]:
        print(f"No current http(s) References found in corpus {corpus_id}. Check the corpus id (it is knowledge-corpus-<publication key>; "
              "`papyrus references list` shows the corpusId of a Reference).")
        return
    by_source = ",".join(f"{source}={number}" for source, number in sorted(counts["resolvedBySource"].items())) or "none"
    print(f"scanned={counts['scanned']}\talreadyResolved={counts['alreadyResolved']}\tresolved={counts['resolved']} ({by_source})\t"
          f"keptMonitorDate={counts['keptMonitorDate']}\tunknown={counts['unknown']}\tfetchFailures={counts['fetchFailures']}\t"
          f"skippedPdf={counts['skippedPdf']}" + ("\tdry-run" if not apply else ""))
