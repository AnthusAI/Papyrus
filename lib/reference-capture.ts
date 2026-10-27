/**
 * What the newsroom actually captured of a Reference, so an editor can tell whether there is anything to rate.
 *
 * Captured text lives in `ReferenceAttachment` rows: role `extracted_text` (the canonical text, possibly filtered to the article) and
 * `extracted_text_raw` (what extraction returned), each with a `storagePath` to the stored text and a metadata object that carries
 * `textLength` (characters), `title`, and any structured extraction (`grobid`, `structured`) written by `papyrus references
 * process-fetch-url-text` / `process-attach-extracted-text`. The summary is a `metadata` payload on the Reference. A Reference that
 * monitoring discovered has only its `source` attachment (the address): nothing captured.
 */
import type { ReferenceAttachmentRecord } from "./category-repository";

export type CaptureState = "none" | "thin" | "full";

export type CaptureStatus = {
  state: CaptureState;
  /** Words in the stored text; an estimate (`estimated`) until the text itself is loaded. */
  words: number | null;
  estimated: boolean;
};

/** Without enough captured texts to learn from, text shorter than this many words reads as a teaser. */
export const DEFAULT_TEASER_WORDS = 250;
/** With at least this many captured texts, the teaser line is learned: a quarter of the corpus' median length. */
export const MINIMUM_CAPTURES_TO_LEARN = 10;
const AVERAGE_CHARACTERS_PER_WORD = 6;

export const EXTRACTED_TEXT_ROLES = ["extracted_text", "extracted_text_raw"] as const;

function metadataOf(attachment: ReferenceAttachmentRecord): Record<string, unknown> {
  const raw = attachment.metadata;
  if (typeof raw === "string") {
    try { const parsed = JSON.parse(raw); return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {}; } catch { return {}; }
  }
  return raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
}

export function countWords(text: string): number {
  const matches = text.trim().match(/\S+/g);
  return matches ? matches.length : 0;
}

/** The characters an extracted-text attachment holds, from its own record (no download). */
function recordedCharacters(attachment: ReferenceAttachmentRecord): number | null {
  const length = metadataOf(attachment).textLength;
  if (typeof length === "number" && length >= 0) return length;
  return typeof attachment.byteSize === "number" && attachment.byteSize >= 0 ? attachment.byteSize : null;
}

export function extractedTextAttachments(attachments: readonly ReferenceAttachmentRecord[]): ReferenceAttachmentRecord[] {
  return attachments.filter((attachment) => (EXTRACTED_TEXT_ROLES as readonly string[]).includes(attachment.role) && Boolean(attachment.storagePath || attachment.sourceUri));
}

/** The attachment to read: the filtered canonical text first, then the raw extraction; the newest of each. */
export function primaryTextAttachment(attachments: readonly ReferenceAttachmentRecord[]): ReferenceAttachmentRecord | null {
  const newest = (rows: ReferenceAttachmentRecord[]) => [...rows].sort((left, right) => String(right.importedAt ?? "").localeCompare(String(left.importedAt ?? "")) || right.id.localeCompare(left.id))[0] ?? null;
  const rows = extractedTextAttachments(attachments);
  return newest(rows.filter((row) => row.role === "extracted_text")) ?? newest(rows.filter((row) => row.role === "extracted_text_raw"));
}

/** Estimated word count of one Reference's stored text, from its record alone. */
export function estimatedWords(attachments: readonly ReferenceAttachmentRecord[]): number | null {
  const primary = primaryTextAttachment(attachments);
  const characters = primary ? recordedCharacters(primary) : null;
  return characters === null ? null : Math.round(characters / AVERAGE_CHARACTERS_PER_WORD);
}

/** Where "thin" starts for this corpus: learned from its captured texts, else the default. */
export function teaserWords(capturedWordCounts: readonly number[]): number {
  if (capturedWordCounts.length < MINIMUM_CAPTURES_TO_LEARN) return DEFAULT_TEASER_WORDS;
  const sorted = [...capturedWordCounts].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return Math.max(50, Math.round(median * 0.25));
}

export function captureStatus(attachments: readonly ReferenceAttachmentRecord[], teaserLine = DEFAULT_TEASER_WORDS, loadedWords: number | null = null): CaptureStatus {
  if (!primaryTextAttachment(attachments)) return { state: "none", words: null, estimated: false };
  const words = loadedWords ?? estimatedWords(attachments);
  if (words === null) return { state: "thin", words: null, estimated: true };
  return { state: words === 0 ? "none" : words < teaserLine ? "thin" : "full", words, estimated: loadedWords === null };
}

/** Capture status for every Reference lineage that has attachments, using one corpus-wide teaser line. */
export function captureStatusesByLineage(attachments: readonly ReferenceAttachmentRecord[], lineageIds: Iterable<string>): { statuses: Map<string, CaptureStatus>; teaserLine: number } {
  const byLineage = new Map<string, ReferenceAttachmentRecord[]>();
  for (const attachment of attachments) {
    const list = byLineage.get(attachment.referenceLineageId) ?? [];
    list.push(attachment);
    byLineage.set(attachment.referenceLineageId, list);
  }
  const counts = [...byLineage.values()].map(estimatedWords).filter((words): words is number => words !== null && words > 0);
  const teaserLine = teaserWords(counts);
  const statuses = new Map<string, CaptureStatus>();
  for (const lineageId of lineageIds) statuses.set(lineageId, captureStatus(byLineage.get(lineageId) ?? [], teaserLine));
  return { statuses, teaserLine };
}

export type CaptureLine = { state: CaptureState; label: string; detail: string };

/** The plain-words status line. */
export function captureLine(status: CaptureStatus): CaptureLine {
  const count = status.words === null ? null : `${status.estimated ? "about " : ""}${status.words.toLocaleString("en-US")} words`;
  if (status.state === "none") return { state: "none", label: "No text captured", detail: "Only the link is on record. There is nothing here to judge the content by." };
  if (status.state === "thin") return { state: "thin", label: status.words === null ? "Only a little text captured — may be a teaser or paywalled" : `Only ${status.words.toLocaleString("en-US")} words — may be a teaser or paywalled`, detail: "Check the source before you rate it." };
  return { state: "full", label: "Full text captured", detail: count ?? "" };
}

/** Structured extraction (GROBID for papers, or the structured summary) as plain label and value rows. */
export function structuredRows(attachments: readonly ReferenceAttachmentRecord[]): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  const raw = attachments.find((attachment) => attachment.role === "extracted_text_raw") ?? primaryTextAttachment(attachments);
  if (!raw) return rows;
  const metadata = metadataOf(raw);
  const add = (label: string, value: unknown) => {
    if (value === null || value === undefined || value === "") return;
    const text = Array.isArray(value) ? value.map((entry) => (typeof entry === "string" ? entry : (entry as { name?: string })?.name ?? "")).filter(Boolean).join(", ")
      : typeof value === "object" ? "" : String(value);
    if (text.trim()) rows.push({ label, value: text.length > 400 ? `${text.slice(0, 397)}…` : text });
  };
  for (const source of [metadata.grobid, metadata.structured]) {
    if (!source || typeof source !== "object" || Array.isArray(source)) continue;
    const record = source as Record<string, unknown>;
    add("Title", record.title);
    add("Authors", record.authors);
    add("Abstract", record.abstract);
    add("DOI", record.doi);
    add("Published", record.published ?? record.date ?? record.year);
    add("Venue", record.venue ?? record.journal);
    if (Array.isArray(record.citations)) add("Citations", `${record.citations.length} cited works`);
    if (Array.isArray(record.references)) add("References", `${record.references.length} cited works`);
    add("Keywords", record.keywords);
  }
  return rows;
}
