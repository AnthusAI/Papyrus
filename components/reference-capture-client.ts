"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import { captureStatus, countWords, primaryTextAttachment, structuredRows, type CaptureStatus } from "../lib/reference-capture";
import { loadModelPayloadsForOwner, loadStoragePathText } from "./news-desk-taxonomy-client";

export type CaptureView = {
  status: CaptureStatus;
  /** The stored text, once read. Null while loading, or when there is none. */
  text: string | null;
  loading: boolean;
  error: string | null;
  summary: string | null;
  rows: Array<{ label: string; value: string }>;
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

/** Reads what the newsroom stored for one Reference: the extracted text, its structured extraction, and the summary. */
export function useReferenceCapture(reference: ReferenceRecord, attachments: readonly ReferenceAttachmentRecord[], teaserLine: number): CaptureView {
  const primary = useMemo(() => primaryTextAttachment(attachments), [attachments]);
  const [state, setState] = useState<{ key: string; text: string | null; error: string | null; loading: boolean }>({ key: "", text: null, error: null, loading: false });
  const [summary, setSummary] = useState<{ key: string; value: string | null }>({ key: "", value: null });
  const textKey = primary ? `${primary.id}:${primary.storagePath ?? ""}` : "";
  useEffect(() => {
    if (!primary) { setState({ key: "", text: null, error: null, loading: false }); return; }
    const inline = previewText(primary);
    if (inline !== null) { setState({ key: textKey, text: inline, error: null, loading: false }); return; }
    let active = true;
    setState({ key: textKey, text: null, error: null, loading: true });
    void loadStoragePathText(primary.storagePath)
      .then((result) => { if (active) setState({ key: textKey, text: result.text, error: result.error, loading: false }); })
      .catch((error) => { if (active) setState({ key: textKey, text: null, error: error instanceof Error ? error.message : "Could not read the stored text.", loading: false }); });
    return () => { active = false; };
  }, [primary, textKey]);
  useEffect(() => {
    if (isLocalPreviewEnabled()) { setSummary({ key: reference.id, value: null }); return; }
    let active = true;
    void loadModelPayloadsForOwner("reference", reference.id, ["metadata"])
      .then((payloads) => {
        if (!active) return;
        const json = payloads.map((payload) => payload.json).find((value) => value && typeof value === "object") as { summary?: unknown } | undefined;
        setSummary({ key: reference.id, value: typeof json?.summary === "string" && json.summary.trim() ? json.summary.trim() : null });
      })
      .catch(() => { if (active) setSummary({ key: reference.id, value: null }); });
    return () => { active = false; };
  }, [reference.id]);
  const loaded = state.key === textKey && state.text !== null ? countWords(state.text) : null;
  return {
    status: captureStatus(attachments, teaserLine, loaded),
    text: state.key === textKey ? state.text : null,
    loading: state.key === textKey ? state.loading : Boolean(primary),
    error: state.key === textKey ? state.error : null,
    summary: summary.key === reference.id ? summary.value : null,
    rows: structuredRows(attachments),
  };
}
