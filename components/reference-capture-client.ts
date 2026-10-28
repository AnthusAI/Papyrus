"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import {
  captureStatus, countWords, curationCardOf, grobidRows, primaryTextAttachment, structuredRows,
  type CaptureAssessment as Assessment, type CaptureStatus, type CurationCard,
} from "../lib/reference-capture";
import { loadModelPayloadsForOwner, loadStoragePathText, uploadModelPayloadForOwner } from "./news-desk-taxonomy-client";

export type CaptureAssessment = Assessment;

export type CaptureView = {
  status: CaptureStatus;
  /** The stored text, once read. Null while loading, or when there is none. */
  text: string | null;
  loading: boolean;
  error: string | null;
  summary: string | null;
  /** True when an editor replaced the text and the summary awaits the next curation run. */
  summaryStale: boolean;
  rows: Array<{ label: string; value: string }>;
  /** Saves an editor's pasted or corrected text and their verdict on the capture (the `correctReferenceCapture` action). */
  correct?: (input: { text?: string; assessment: CaptureAssessment; note?: string }) => Promise<void>;
  /** True when the current text was read from a PDF the editor uploaded. */
  fromPdf: boolean;
  /** Stores a PDF the editor downloaded as an attachment of the Reference, then has the server read its text (`correctReferenceCapture` with `pdfAttachmentId`). */
  uploadPdf?: (input: { file: File; assessment: CaptureAssessment; note?: string }, onStep?: (step: "uploading" | "reading") => void) => Promise<void>;
};

/** The server reads PDFs up to this size (ideas.source_text.MAXIMUM_PDF_BYTES); say so before a slow upload that would be refused. */
export const MAXIMUM_PDF_UPLOAD_BYTES = 8_000_000;
export const PDF_UPLOAD_ROLE = "curation-upload-pdf";

function previewText(attachment: ReferenceAttachmentRecord): string | null {
  // Local preview only: a fixture can carry the captured text inline instead of in storage.
  if (!isLocalPreviewEnabled()) return null;
  const raw = attachment.metadata;
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
    const text = (parsed as { previewText?: unknown } | null)?.previewText;
    return typeof text === "string" ? text : null;
  } catch { return null; }
}

type Payloads = { key: string; text: string | null; grobid: unknown; summary: string | null; loaded: boolean };

/**
 * Reads what the newsroom stored for one Reference. The curation card comes first (status, word count, signals, summary, GROBID fields,
 * and the `curation-text` body its `current` points at); the older `extracted_text` attachment is the fallback.
 */
export type CorrectCaptureAction = (input: { referenceId: string; text?: string; pdfAttachmentId?: string; assessment: CaptureAssessment; note?: string }) => Promise<unknown>;

export function useReferenceCapture(reference: ReferenceRecord, attachments: readonly ReferenceAttachmentRecord[], teaserLine: number, correctAction?: CorrectCaptureAction): CaptureView {
  const card: CurationCard | null = useMemo(() => curationCardOf(attachments), [attachments]);
  const primary = useMemo(() => primaryTextAttachment(attachments), [attachments]);
  const textSortKey = card?.current?.textSortKey ?? card?.capture.textSortKey ?? null;
  const grobidSortKey = card?.current?.grobidSortKey ?? card?.grobid?.fieldsSortKey ?? null;
  const [payloads, setPayloads] = useState<Payloads>({ key: "", text: null, grobid: null, summary: null, loaded: false });
  const [fallback, setFallback] = useState<{ key: string; text: string | null; error: string | null; loading: boolean }>({ key: "", text: null, error: null, loading: false });
  const [corrected, setCorrected] = useState<{ key: string; text: string; assessment: CaptureAssessment; fromPdf?: boolean } | null>(null);
  const referenceKey = `${reference.id}:${textSortKey ?? ""}:${grobidSortKey ?? ""}`;

  // The card's bodies and the Reference's metadata.json, in one read of the Reference's ModelAttachments.
  useEffect(() => {
    if (isLocalPreviewEnabled()) { setPayloads({ key: referenceKey, text: null, grobid: null, summary: null, loaded: true }); return; }
    let active = true;
    void loadModelPayloadsForOwner("reference", reference.id, ["metadata"])
      .then((rows) => {
        if (!active) return;
        const bySortKey = (key: string | null) => (key ? rows.find((row) => row.attachment.sortKey === key) : undefined);
        const metadata = rows.find((row) => row.attachment.sortKey === "metadata")?.json as { summary?: unknown } | null | undefined;
        setPayloads({
          key: referenceKey,
          text: bySortKey(textSortKey)?.text ?? null,
          grobid: bySortKey(grobidSortKey)?.json ?? null,
          summary: typeof metadata?.summary === "string" && metadata.summary.trim() ? metadata.summary.trim() : null,
          loaded: true,
        });
      })
      .catch(() => { if (active) setPayloads({ key: referenceKey, text: null, grobid: null, summary: null, loaded: true }); });
    return () => { active = false; };
  }, [reference.id, referenceKey, textSortKey, grobidSortKey]);

  // Fallback: the older extracted_text attachment, when the card has no text of its own.
  const fallbackKey = primary ? `${primary.id}:${primary.storagePath ?? ""}` : "";
  const useFallback = Boolean(primary) && !textSortKey;
  useEffect(() => {
    if (!useFallback || !primary) { setFallback({ key: "", text: null, error: null, loading: false }); return; }
    const inline = previewText(primary);
    if (inline !== null) { setFallback({ key: fallbackKey, text: inline, error: null, loading: false }); return; }
    let active = true;
    setFallback({ key: fallbackKey, text: null, error: null, loading: true });
    void loadStoragePathText(primary.storagePath)
      .then((result) => { if (active) setFallback({ key: fallbackKey, text: result.text, error: result.error, loading: false }); })
      .catch((error) => { if (active) setFallback({ key: fallbackKey, text: null, error: error instanceof Error ? error.message : "Could not read the stored text.", loading: false }); });
    return () => { active = false; };
  }, [primary, fallbackKey, useFallback]);

  const current = payloads.key === referenceKey ? payloads : null;
  const mine = corrected && corrected.key === reference.id ? corrected : null;
  const fromPdf = mine ? mine.fromPdf === true : card?.current?.textVia === "editor_pdf";
  const text = mine?.text ?? (textSortKey ? current?.text ?? null : fallback.key === fallbackKey ? fallback.text : null);
  const loading = mine ? false : textSortKey ? !(current?.loaded) : useFallback && fallback.key === fallbackKey ? fallback.loading : useFallback;
  const error = textSortKey || mine ? null : fallback.key === fallbackKey ? fallback.error : null;
  const loadedWords = text !== null ? countWords(text) : null;
  const base = captureStatus(attachments, teaserLine, loadedWords);
  const status: CaptureStatus = mine ? { ...base, state: base.state === "none" || base.state === "running" ? (loadedWords !== null && loadedWords < teaserLine ? "thin" : "full") : base.state, words: loadedWords, estimated: false, assessment: mine.assessment, summaryStale: true, ...(loadedWords !== null && loadedWords < teaserLine ? { thinBy: "length" as const } : {}) } : base;
  const summary = card?.summary?.status === "completed" && card.summary.text ? card.summary.text : current?.summary ?? null;
  const rows = card ? grobidRows(current?.grobid, card) : structuredRows(attachments);

  const correct = useCallback(async (input: { text?: string; assessment: CaptureAssessment; note?: string }) => {
    if (correctAction) await correctAction({ referenceId: reference.id, ...(input.text !== undefined ? { text: input.text } : {}), assessment: input.assessment, ...(input.note ? { note: input.note } : {}) });
    setCorrected({ key: reference.id, text: input.text ?? text ?? "", assessment: input.assessment, fromPdf: input.text === undefined && fromPdf });
  }, [reference.id, text, fromPdf, correctAction]);

  const uploadPdf = useCallback(async (input: { file: File; assessment: CaptureAssessment; note?: string }, onStep?: (step: "uploading" | "reading") => void) => {
    if (!correctAction) throw new Error("Uploading is not available here.");
    if (input.file.size > MAXIMUM_PDF_UPLOAD_BYTES) throw new Error(`That PDF is larger than we read (${MAXIMUM_PDF_UPLOAD_BYTES / 1_000_000} MB). Paste the text instead.`);
    onStep?.("uploading");
    const attachment = await uploadModelPayloadForOwner({
      ownerKind: "reference", ownerId: reference.id, ownerLineageId: reference.lineageId ?? reference.id, ownerVersionNumber: reference.versionNumber ?? null,
      ownerVersionKey: `reference#${reference.id}`, role: PDF_UPLOAD_ROLE, sortKey: `${PDF_UPLOAD_ROLE}-${Date.now().toString(36)}`,
      filename: input.file.name || "upload.pdf", mediaType: "application/pdf", content: input.file,
    });
    onStep?.("reading");
    const result = await correctAction({ referenceId: reference.id, pdfAttachmentId: attachment.id, assessment: input.assessment, ...(input.note ? { note: input.note } : {}) });
    // The server read the text; fetch the new body it stored so the panel shows it.
    const sortKey = (result as { edits?: Array<{ sortKey?: string; kind?: string }> } | null | undefined)?.edits?.find((edit) => edit.kind === "text")?.sortKey;
    const rows = sortKey ? await loadModelPayloadsForOwner("reference", reference.id, ["metadata"]) : [];
    const stored = rows.find((row) => row.attachment.sortKey === sortKey)?.text;
    if (typeof stored !== "string") throw new Error("The PDF was read, but its text could not be loaded. Reload to see it.");
    setCorrected({ key: reference.id, text: stored, assessment: input.assessment, fromPdf: true });
  }, [reference.id, reference.lineageId, reference.versionNumber, correctAction]);

  return { status, text, loading, error, summary, summaryStale: Boolean(mine) || status.summaryStale === true, rows, fromPdf, correct: correctAction || isLocalPreviewEnabled() ? correct : undefined, uploadPdf: correctAction ? uploadPdf : undefined };
}
