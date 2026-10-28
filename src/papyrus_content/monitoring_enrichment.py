"""Item-level enrichment: curate a collected item ONCE, before the lab decides and before an editor rates it.

Order: the collector discovers (title, URL); the router enriches the item here (capture, completeness signals, summary, GROBID for
papers); the decision is posted on that enriched text; delivery copies the item's curation onto each delivered Reference in the shape
the post-delivery procedure (`papyrus.reference.curate`) writes, so the newsroom panel shows exactly what was decided. Stage code is
the curation pipeline's (`reference_capture`, `reference_curation.openai_summarizer`, `reference_grobid`); only the storage differs:
an `ENRICH#` row in the monitoring table (status, signals, summary: small) and the big text in S3.

An enrichment is attempted once; a transient failure (a timeout, a busy model or GROBID) is retried on later runs a few times, then
the row is final with whatever exists (`ready`, `degraded`, `capture_failed`) and the decision proceeds. Nothing waits forever.
Everything is idempotent: a finished stage is not repeated, and the S3 keys derive from the item.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .link_exploration import explore
from .reference_capture import Capture, capture_source
from .reference_curation import SummaryFailed, Summarizer, _write_reference_summary
from .reference_curation_store import (
    GROBID_SORT_KEY,
    GROBID_TEI_SORT_KEY,
    PIPELINE_VERSION,
    TEXT_SORT_KEY,
    AttachmentStore,
    compute_status,
    iso,
    new_card,
    read_card,
    sha256_text,
    write_card,
)
from .reference_grobid import (
    SKIP_REASONS_RETRYABLE,
    GrobidUnavailable,
    parse_tei,
    process_fulltext,
    summarize_fields,
)

ENRICH_PREFIX = "ENRICH#"
ENRICHMENT_VERSION = "item-enrichment-v1"
MAX_ATTEMPTS = 3                   # one try plus two retries of transient failures, then the decision goes ahead
RETRY_BACKOFF_SECONDS = 300        # the next run, not a sleep inside this one: Lambda time is the real constraint
SUMMARY_TRANSIENT = frozenset({"model_failed", "empty_summary"})


def enrich_sk(disc: dict[str, Any]) -> str:
    return f"{ENRICH_PREFIX}{disc['sourceId']}#{int(disc['revision']):06d}"


# --- where the big text lives ------------------------------------------------------------------------------------------


class S3Texts:
    """Captured text, GROBID fields and TEI in a private bucket (DynamoDB items stop at 400 KB)."""

    def __init__(self, bucket: str, client: Any = None) -> None:
        if client is None:
            import boto3  # the Lambda runtime provides it

            client = boto3.client("s3")
        self.bucket, self.client = bucket, client

    def put(self, key: str, text: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=text.encode("utf-8"), ContentType="text/plain; charset=utf-8",
                               ServerSideEncryption="AES256")

    def get(self, key: str) -> str | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read().decode("utf-8")
        except Exception as error:  # noqa: BLE001 - a missing key is None; anything else is the caller's retry
            if getattr(error, "response", {}).get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise


class MemoryTexts:
    """The same interface in memory, for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def put(self, key: str, text: str) -> None:
        self.objects[key] = text

    def get(self, key: str) -> str | None:
        return self.objects.get(key)


@dataclass
class Enricher:
    """Everything enrichment reaches outside itself for. Tests replace each one; nothing here touches the network by itself."""

    texts: Any
    summarizer: Summarizer | None = None
    grobid_url: str | None = None
    grobid_post: Callable[..., Any] | None = None
    explorer: Callable[..., Any] = explore
    capture: Callable[..., Capture] = capture_source


def lambda_enricher(environment: dict[str, str] | None = None, *, ssm: Any = None, s3: Any = None) -> Enricher | None:
    """The router Lambda's enricher from its environment, or None when no bucket is configured (enrichment is then off).

    ENRICHMENT_BUCKET names the private bucket; ENRICHMENT_OPENAI_KEY_PARAMETER the SSM SecureString holding the OpenAI key (without
    it the summary stage is the typed skip `openai_not_configured`); BIBLICUS_GROBID_URL a GROBID service (without it papers get the
    typed skip `grobid_not_configured`).
    """
    import os

    environment = os.environ if environment is None else environment
    bucket = (environment.get("ENRICHMENT_BUCKET") or "").strip()
    if not bucket:
        return None
    summarizer = None
    parameter = (environment.get("ENRICHMENT_OPENAI_KEY_PARAMETER") or "").strip()
    if parameter:
        try:
            if ssm is None:
                import boto3

                ssm = boto3.client("ssm")
            key = ssm.get_parameter(Name=parameter, WithDecryption=True)["Parameter"]["Value"]
            from .reference_curation import openai_summarizer

            summarizer = openai_summarizer(key.strip()) if key.strip() else None
        except Exception:  # noqa: BLE001 - an unreadable key is "not configured": the summary stage records the typed skip
            summarizer = None
    return Enricher(texts=S3Texts(bucket, s3), summarizer=summarizer,
                    grobid_url=(environment.get("BIBLICUS_GROBID_URL") or "").strip() or None)


# --- one item ------------------------------------------------------------------------------------------------------------


def text_key(disc: dict[str, Any], monitor_id: str, name: str) -> str:
    return f"enrichment/{monitor_id}/{disc['sourceId']}/{int(disc['revision']):06d}/{name}"


def new_row(monitor_id: str, disc: dict[str, Any]) -> dict[str, Any]:
    return {"pk": f"MONITOR#{monitor_id}", "sk": enrich_sk(disc), "kind": "item-enrichment", "version": ENRICHMENT_VERSION,
            "sourceId": disc["sourceId"], "revision": int(disc["revision"]), "sourceUri": str(disc.get("canonicalUrl") or ""),
            "status": "pending", "final": False, "attempts": 0,
            "curation": {"capture": {"status": "not_run"}, "signals": {}, "paper": {}, "page": {},
                         "summary": {"status": "not_run"}, "grobid": {"status": "not_run"}}}


def retryable(curation: dict[str, Any]) -> bool:
    """True while some stage failed for a reason that may pass on another attempt."""
    capture, summary, grobid = curation["capture"], curation["summary"], curation["grobid"]
    return bool((capture.get("status") == "failed" and capture.get("transient"))
                or (summary.get("status") == "failed" and summary.get("reason") in SUMMARY_TRANSIENT)
                or (grobid.get("status") == "failed" and grobid.get("reason") in SKIP_REASONS_RETRYABLE))


def curation_as_card(curation: dict[str, Any]) -> dict[str, Any]:
    card = {key: curation[key] for key in ("capture", "summary") if key in curation}
    card["current"] = {"textSortKey": TEXT_SORT_KEY} if curation["capture"].get("status") == "completed" else {}
    return card


def enrich_item(row: dict[str, Any], disc: dict[str, Any], monitor_id: str, enricher: Enricher, now: datetime) -> dict[str, Any]:
    """One attempt: run the stages that still need running, then mark the row final or schedule the retry. Never raises for a bad
    source; an unexpected bug is recorded as a typed error on the row and the decision proceeds with what exists."""
    curation = row["curation"]
    row["attempts"] = int(row.get("attempts", 0)) + 1
    row["lastAttemptAt"] = iso(now)
    key_text = text_key(disc, monitor_id, "text.md")
    title, source_uri = str(disc.get("title") or ""), str(disc.get("canonicalUrl") or "")
    try:
        text = enricher.texts.get(key_text) if curation["capture"].get("status") == "completed" else None
        capture_open = curation["capture"].get("status") != "completed" and not (
            curation["capture"].get("status") == "failed" and not curation["capture"].get("transient"))
        paper_open = bool(curation["paper"].get("isPaper")) and curation["grobid"].get("status") != "completed" and (
            curation["grobid"].get("status") in {None, "not_run"} or curation["grobid"].get("reason") in SKIP_REASONS_RETRYABLE)
        captured: Capture | None = None
        if capture_open or (paper_open and enricher.grobid_url):
            captured = (enricher.capture(source_uri, title=title, explorer=enricher.explorer) if source_uri
                        else Capture(False, "no_source_uri"))
        if capture_open and captured is not None:
            capture: dict[str, Any] = {"status": "completed" if captured.ok else "failed", "capturedAt": iso(now),
                                       "sourceKind": captured.source_kind, "contentType": captured.content_type, "via": captured.via,
                                       "destinationUrl": captured.destination_url, "fullTextUrl": captured.full_text_url,
                                       "textVia": captured.text_via, "textReason": captured.text_reason}
            if captured.ok:
                enricher.texts.put(key_text, captured.text)
                text = captured.text
                capture.update(textSortKey=TEXT_SORT_KEY, textSha256=sha256_text(captured.text),
                               wordCount=captured.signals.get("wordCount"))
                row["textKey"] = key_text
            else:
                capture.update(reason=captured.failure, transient=captured.transient)
            curation["capture"] = {k: v for k, v in capture.items() if v is not None}
            curation.update(signals=captured.signals, paper=captured.paper, page=captured.page)
        _summary_stage(curation, disc, enricher, text, now)
        _grobid_stage(curation, disc, monitor_id, enricher, captured, row, now)
    except Exception as error:  # noqa: BLE001 - never let one item's bug stop the decision; record it, typed
        row.setdefault("errors", []).append({"at": iso(now), "type": type(error).__name__})
        if curation["capture"].get("status") == "not_run":
            curation["capture"] = {"status": "failed", "reason": "enrichment_error", "transient": False}
    curation["status"] = compute_status(curation_as_card(curation))
    row["status"] = curation["status"]
    if retryable(curation) and row["attempts"] < MAX_ATTEMPTS:
        row["final"] = False
        row["nextAttemptAt"] = int(now.timestamp()) + RETRY_BACKOFF_SECONDS * 2 ** (row["attempts"] - 1)
    else:
        row["final"] = True
        row.pop("nextAttemptAt", None)
        row["completedAt"] = iso(now)
    return row


def _summary_stage(curation: dict[str, Any], disc: dict[str, Any], enricher: Enricher, text: str | None, now: datetime) -> None:
    if curation["summary"].get("text"):
        return
    if not text:
        curation["summary"] = {"status": "skipped", "reason": "no_text"}
        return
    if enricher.summarizer is None:
        curation["summary"] = {"status": "skipped", "reason": "openai_not_configured"}
        return
    stamp = iso(now)
    try:
        made = enricher.summarizer({"text": text, "title": disc.get("title") or "", "sourceUri": disc.get("canonicalUrl") or "",
                                    "maxTokens": 500})
    except SummaryFailed as failure:
        curation["summary"] = {"status": "failed", "reason": failure.reason, "attemptedAt": stamp}
        return
    curation["summary"] = {"status": "completed", "text": made["text"], "model": made["model"], "promptVersion": made["promptVersion"],
                           "generatedAt": stamp, "inputTruncated": bool(made.get("inputTruncated")), "usage": made.get("usage") or {},
                           "basedOn": TEXT_SORT_KEY, "textSha256": sha256_text(text)}


def _grobid_stage(curation: dict[str, Any], disc: dict[str, Any], monitor_id: str, enricher: Enricher, captured: Capture | None,
                  row: dict[str, Any], now: datetime) -> None:
    if curation["grobid"].get("status") == "completed":
        return
    if not curation["paper"].get("isPaper"):
        curation["grobid"] = {"status": "skipped", "reason": "not_a_paper"}
        return
    if curation["capture"].get("status") != "completed":
        curation["grobid"] = {"status": "skipped", "reason": "capture_failed"}
        return
    if not enricher.grobid_url:
        curation["grobid"] = {"status": "skipped", "reason": "grobid_not_configured"}
        return
    if captured is None or captured.pdf_bytes is None:
        curation["grobid"] = {"status": "skipped", "reason": "pdf_unavailable"}
        return
    stamp = iso(now)
    try:
        tei = process_fulltext(captured.pdf_bytes, enricher.grobid_url, post=enricher.grobid_post)
        fields = parse_tei(tei)
    except GrobidUnavailable as failure:
        curation["grobid"] = {"status": "skipped" if failure.reason == "pdf_unavailable" else "failed", "reason": failure.reason,
                              "attemptedAt": stamp, "transient": failure.reason in SKIP_REASONS_RETRYABLE}
        return
    if not (fields.get("title") or fields.get("sections") or fields.get("references")):
        curation["grobid"] = {"status": "failed", "reason": "grobid_empty", "attemptedAt": stamp, "transient": False}
        return
    row["grobidKey"], row["teiKey"] = text_key(disc, monitor_id, "grobid.json"), text_key(disc, monitor_id, "grobid.tei.xml")
    enricher.texts.put(row["grobidKey"], json.dumps(fields, indent=2, sort_keys=True) + "\n")
    enricher.texts.put(row["teiKey"], tei)
    curation["grobid"] = {"status": "completed", "extractedAt": stamp, "fieldsSortKey": GROBID_SORT_KEY, "teiSortKey": GROBID_TEI_SORT_KEY,
                          **summarize_fields(fields)}


# --- what the decision uses --------------------------------------------------------------------------------------------------


def decision_inputs(row: dict[str, Any] | None, texts: Any) -> dict[str, Any]:
    """`{summary, body, status}` for the decide payload: the summary and the full captured text, empty strings when absent."""
    if not row:
        return {"summary": "", "body": "", "status": None}
    summary = str(((row.get("curation") or {}).get("summary") or {}).get("text") or "")
    body = (texts.get(row["textKey"]) or "") if row.get("textKey") and texts is not None else ""
    return {"summary": summary, "body": body, "status": row.get("status")}


# --- delivery: copy the item's curation onto a Reference -----------------------------------------------------------------------


def copy_curation(client: Any, reference: dict[str, Any], row: dict[str, Any], texts: Any, now: datetime) -> str:
    """Write the item's curation onto `reference` in the shape `papyrus.reference.curate` uses (a `curation` ReferenceAttachment card
    plus `curation-*` ModelAttachment bodies), so the newsroom shows exactly what was decided and the post-delivery procedure only
    fills gaps. A Reference that already has a card keeps it. Returns `copied` or `kept`."""
    if read_card(client, reference) is not None:
        return "kept"
    curation = row["curation"]
    store = AttachmentStore(client)
    card = new_card(reference)
    card.update({key: curation[key] for key in ("capture", "signals", "paper", "page", "summary", "grobid")})
    card.update(pipelineVersion=PIPELINE_VERSION, sourceUri=row.get("sourceUri") or "", startedAt=row.get("lastAttemptAt"),
                completedAt=row.get("completedAt"),
                origin={"kind": "item-enrichment", "version": ENRICHMENT_VERSION, "sourceId": row["sourceId"],
                        "revision": row["revision"], "enrichedAt": row.get("completedAt")})
    text = texts.get(row["textKey"]) if row.get("textKey") else None
    if text:
        store.write(reference, TEXT_SORT_KEY, "curation-text.md", "text/markdown", text, now)
        card["current"]["textSortKey"] = TEXT_SORT_KEY
    if row.get("grobidKey") and curation["grobid"].get("status") == "completed":
        fields, tei = texts.get(row["grobidKey"]), texts.get(row.get("teiKey") or "")
        if fields:
            store.write(reference, GROBID_SORT_KEY, "curation-grobid.json", "application/json", fields, now)
            card["current"]["grobidSortKey"] = GROBID_SORT_KEY
        if tei:
            store.write(reference, GROBID_TEI_SORT_KEY, "curation-grobid.tei.xml", "text/plain", tei, now)
    summary = curation["summary"]
    if summary.get("text"):
        try:   # the Reference's metadata.json is where every earlier summary lives; the card holds it either way
            _write_reference_summary(reference, store, {"text": summary["text"], "model": summary.get("model"),
                                                        "promptVersion": summary.get("promptVersion")},
                                     summary.get("generatedAt") or iso(now), now)
        except Exception:  # noqa: BLE001 - the card is the record; a metadata write must not undo the copy
            card.setdefault("errors", []).append({"at": iso(now), "type": "metadata_summary_not_written"})
    card["status"] = compute_status(card)
    write_card(client, reference, card, now)
    return "copied"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
