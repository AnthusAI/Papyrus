"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import {
  captureStatus, countWords, curationCardOf, grobidRows, primaryTextAttachment, structuredRows,
  type CaptureAssessment as Assessment, type CaptureStatus, type CurationCard,
} from "../lib/reference-capture";
import { loadModelPayloadsForOwner, loadStoragePathText } from "./news-desk-taxonomy-client";

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
};

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
export type CorrectCaptureAction = (input: { referenceId: string; text?: string; assessment: CaptureAssessment; note?: string }) => Promise<unknown>;

export function useReferenceCapture(reference: ReferenceRecord, attachments: readonly ReferenceAttachmentRecord[], teaserLine: number, correctAction?: CorrectCaptureAction): CaptureView {
  const card: CurationCard | null = useMemo(() => curationCardOf(attachments), [attachments]);
  const primary = useMemo(() => primaryTextAttachment(attachments), [attachments]);
  const textSortKey = card?.current?.textSortKey ?? card?.capture.textSortKey ?? null;
  const grobidSortKey = card?.current?.grobidSortKey ?? card?.grobid?.fieldsSortKey ?? null;
  const [payloads, setPayloads] = useState<Payloads>({ key: "", text: null, grobid: null, summary: null, loaded: false });
  const [fallback, setFallback] = useState<{ key: string; text: string | null; error: string | null; loading: boolean }>({ key: "", text: null, error: null, loading: false });
  const [corrected, setCorrected] = useState<{ key: string; text: string; assessment: CaptureAssessment } | null>(null);
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
    setCorrected({ key: reference.id, text: input.text ?? text ?? "", assessment: input.assessment });
  }, [reference.id, text, correctAction]);

  return { status, text, loading, error, summary, summaryStale: Boolean(mine) || status.summaryStale === true, rows, correct: correctAction || isLocalPreviewEnabled() ? correct : undefined };
}
