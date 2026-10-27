/**
 * What the newsroom actually captured of a Reference, so an editor can tell whether there is anything to rate.
 *
 * Curation before review (docs/reference-curation-pipeline.md) stores ONE `ReferenceAttachment` per Reference with role `curation` and sort
 * key `003-curation`: a card with a status (`ready` / `degraded` / `capture_failed` / `running`), typed reasons, completeness signals, the
 * summary and GROBID counts; the bodies are `ModelAttachment` rows (`curation-text`, `curation-grobid`, `curation-edit-NNNN-*`). That card is
 * read first. Older captured text lives in `ReferenceAttachment` rows (the fallback): role `extracted_text` (the canonical text, possibly filtered to the article) and
 * `extracted_text_raw` (what extraction returned), each with a `storagePath` to the stored text and a metadata object that carries
 * `textLength` (characters), `title`, and any structured extraction (`grobid`, `structured`) written by `papyrus references
 * process-fetch-url-text` / `process-attach-extracted-text`. The summary is a `metadata` payload on the Reference. A Reference that
 * monitoring discovered has only its `source` attachment (the address): nothing captured.
 */
import type { ReferenceAttachmentRecord } from "./category-repository";

export type CaptureState = "none" | "thin" | "full" | "running";

export type CurationStatus = "ready" | "degraded" | "capture_failed" | "running";

export type CurationCard = {
  status: CurationStatus;
  capture: { status?: string; reason?: string; transient?: boolean; sourceKind?: string; wordCount?: number; textSortKey?: string };
  signals: Record<string, unknown>;
  editedSignals: Record<string, unknown> | null;
  summary: { status?: string; text?: string; stale?: boolean; reason?: string } | null;
  grobid: { status?: string; reason?: string; title?: string; authorCount?: number; hasAbstract?: boolean; sectionCount?: number; referenceCount?: number; fieldsSortKey?: string } | null;
  current: { textSortKey?: string; grobidSortKey?: string } | null;
  labels: Array<{ kind?: string; assessment?: string; labeledAt?: string }>;
};

export type CaptureStatus = {
  state: CaptureState;
  /** Words in the stored text; an estimate (`estimated`) until the text itself is loaded. */
  words: number | null;
  estimated: boolean;
  /** Where the status came from: the curation card, the older extracted-text attachment, or nothing. */
  source?: "curation" | "extracted" | "none";
  /** The curation card's own status, when there is a card. */
  curation?: CurationStatus | null;
  /** Why nothing was captured (the card's typed reason). */
  reason?: string | null;
  /** Plain-words signs the text may be cut off or paywalled (from the card's completeness signals). */
  flags?: string[];
  /** The editor's own verdict on the capture, when they gave one. */
  assessment?: string | null;
  summaryStale?: boolean;
  /** Why a thin capture is thin: too few words, or signs in the text that it is cut off or paywalled. */
  thinBy?: "length" | "signals";
};

export type CaptureAssessment = "complete" | "incomplete" | "incorrect";

export const CURATION_ROLE = "curation";
export const CURATION_SORT_KEY = "003-curation";

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

function objectOf(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

/** The curation card of a Reference, from the attachments the newsroom already loads. Null when curation has not run. */
export function curationCardOf(attachments: readonly ReferenceAttachmentRecord[]): CurationCard | null {
  const row = attachments.find((attachment) => attachment.role === CURATION_ROLE && (attachment.sortKey === CURATION_SORT_KEY || !attachment.sortKey));
  if (!row) return null;
  const card = metadataOf(row);
  const status = card.status;
  if (status !== "ready" && status !== "degraded" && status !== "capture_failed" && status !== "running") return null;
  const grobid = card.grobid ? objectOf(card.grobid) : null;
  const summary = card.summary ? objectOf(card.summary) : null;
  const current = card.current ? objectOf(card.current) : null;
  return {
    status,
    capture: objectOf(card.capture) as CurationCard["capture"],
    signals: objectOf(card.signals),
    editedSignals: card.editedSignals ? objectOf(card.editedSignals) : null,
    summary: summary as CurationCard["summary"],
    grobid: grobid as CurationCard["grobid"],
    current: current as CurationCard["current"],
    labels: Array.isArray(card.labels) ? card.labels.map((label) => objectOf(label) as CurationCard["labels"][number]) : [],
  };
}

const REASON_WORDS: Record<string, string> = {
  blocked: "The site refused our request. It may be paywalled or protect itself from bots.",
  http_4xx: "The page is gone or refused the request.",
  http_5xx: "The site had an error when we asked.",
  timeout: "The site took too long to answer.",
  connection: "We could not connect to the site.",
  dns: "The site's address did not resolve.",
  tls: "The site's certificate could not be verified.",
  too_large: "The document is larger than we read.",
  unreadable: "The page has nothing we could read.",
  no_text: "The page held no readable text.",
  unsupported_media: "The address is not a page or a PDF.",
  no_source_uri: "The record has no web address.",
  not_public: "The address is not a public web page.",
  invalid_url: "The address is not valid.",
  loop: "The address redirects in a circle.",
  unsafe_destination: "The destination did not pass our safety check.",
};

export function captureReasonWords(reason: string | null | undefined): string | null {
  return reason ? REASON_WORDS[reason] ?? `Capture failed (${reason}).` : null;
}

/** Plain-words signs, from the card's completeness signals, that the text may be cut off or paywalled. Facts, never a verdict. */
export function completenessFlags(signals: Record<string, unknown>): string[] {
  const flags: string[] = [];
  const markers = Array.isArray(signals.paywallMarkers) ? signals.paywallMarkers.map((marker) => objectOf(marker)) : [];
  if (markers.some((marker) => marker.inTail === true)) flags.push("The text ends with a subscribe or sign-in phrase.");
  else if (markers.length) flags.push("The text mentions subscribing or signing in.");
  if (signals.endingPattern === "ellipsis" || signals.endingPattern === "truncation_marker") flags.push("The text stops with an ellipsis or a cut-off marker.");
  else if (signals.endingPattern === "no_terminal_punctuation") flags.push("The text stops mid-sentence.");
  if (signals.bodyNotLongerThanDescription === true) flags.push("The text is no longer than the page's own description.");
  if (signals.structuredAccessibleForFree === false) flags.push("The page declares the article is not free to read.");
  const ratio = signals.wordCountRatioToDeclared;
  if (typeof ratio === "number" && ratio < 0.6 && typeof signals.declaredWordCount === "number") flags.push(`The page declares ${signals.declaredWordCount} words; we hold about ${Math.round(ratio * 100)}% of that.`);
  if (signals.responseTruncated === true) flags.push("The page was larger than we read and was cut.");
  const empty = signals.pdfEmptyPageCount;
  if (typeof empty === "number" && empty > 0 && typeof signals.pdfPageCount === "number") flags.push(`${empty} of ${signals.pdfPageCount} PDF pages had no text (scanned).`);
  return flags;
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

/** Words in the card's current text: the editor's corrected count when there is one, else the capture's. */
function curationWords(card: CurationCard): number | null {
  const edited = card.editedSignals?.wordCount;
  if (typeof edited === "number") return edited;
  const captured = card.capture.wordCount ?? card.signals.wordCount;
  return typeof captured === "number" ? captured : null;
}

/** Estimated word count of one Reference's stored text, from its record alone. */
export function estimatedWords(attachments: readonly ReferenceAttachmentRecord[]): number | null {
  const card = curationCardOf(attachments);
  const cardWords = card ? curationWords(card) : null;
  if (cardWords !== null && cardWords > 0) return cardWords;
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
  const card = curationCardOf(attachments);
  const assessment = card?.labels.filter((label) => label.kind === "capture_completeness").at(-1)?.assessment ?? null;
  const summaryStale = Boolean(card?.summary?.stale);
  const cardWords = card ? curationWords(card) : null;
  const cardHasText = Boolean(card && (cardWords ?? 0) > 0 && (card.capture.status === "completed" || card.current?.textSortKey));
  if (card && cardHasText) {
    const words = loadedWords ?? cardWords;
    const flags = completenessFlags(card.editedSignals ?? card.signals);
    const thin = words !== null && words < teaserLine;
    const edited = Boolean(card.current?.textSortKey?.startsWith("curation-edit"));
    // A complete text an editor vouched for is not second-guessed by the signals.
    const doubtful = !edited && assessment !== "complete" && flags.length > 0 && !thin ? flags.some((flag) => /ends with|stops|no longer|not free|cut|declares/.test(flag)) : false;
    return { state: thin || doubtful ? "thin" : "full", words, estimated: false, source: "curation", curation: card.status, reason: null, flags, assessment, summaryStale, ...(thin ? { thinBy: "length" as const } : doubtful ? { thinBy: "signals" as const } : {}) };
  }
  if (primaryTextAttachment(attachments)) {
    const words = loadedWords ?? estimatedWords(attachments);
    if (words === null) return { state: "thin", words: null, estimated: true, source: "extracted", curation: card?.status ?? null, reason: null, flags: [], assessment, summaryStale };
    return { state: words === 0 ? "none" : words < teaserLine ? "thin" : "full", words, estimated: loadedWords === null, source: "extracted", curation: card?.status ?? null, reason: null, flags: [], assessment, summaryStale, ...(words > 0 && words < teaserLine ? { thinBy: "length" as const } : {}) };
  }
  if (card && card.status === "running") return { state: "running", words: null, estimated: false, source: "curation", curation: "running", reason: null, flags: [], assessment, summaryStale };
  return { state: "none", words: null, estimated: false, source: "none", curation: card?.status ?? null, reason: card?.capture.reason ?? null, flags: [], assessment, summaryStale };
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
  if (status.state === "running") return { state: "running", label: "Being captured now", detail: "Curation is reading this item. Check back in a moment." };
  if (status.state === "none") {
    const why = captureReasonWords(status.reason);
    return { state: "none", label: "No text captured", detail: why ?? (status.curation === "capture_failed" ? "Capture failed." : "Only the link is on record. There is nothing here to judge the content by.") };
  }
  if (status.state === "thin") {
    const byLength = status.thinBy !== "signals";
    return {
      state: "thin",
      label: status.words === null ? "Only a little text captured — may be a teaser or paywalled" : byLength ? `Only ${status.words.toLocaleString("en-US")} words — may be a teaser or paywalled` : "Captured, but it may be cut off or paywalled",
      detail: status.flags?.length ? status.flags.join(" ") : "Check the source before you rate it.",
    };
  }
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

/** Rows for the structured extraction from the card's GROBID fields body (`curation-grobid`), else from its counts. */
export function grobidRows(fields: unknown, card: CurationCard | null): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  const record = objectOf(fields);
  const add = (label: string, value: unknown) => { if (typeof value === "string" && value.trim()) rows.push({ label, value: value.length > 500 ? `${value.slice(0, 497)}…` : value }); };
  add("Title", record.title ?? card?.grobid?.title);
  if (Array.isArray(record.authors) && record.authors.length) {
    add("Authors", record.authors.map((author) => (typeof author === "string" ? author : String(objectOf(author).name ?? ""))).filter(Boolean).join(", "));
  } else if (typeof card?.grobid?.authorCount === "number") add("Authors", `${card.grobid.authorCount} authors`);
  add("Abstract", record.abstract);
  add("DOI", record.doi);
  if (Array.isArray(record.keywords) && record.keywords.length) add("Keywords", record.keywords.join(", "));
  const sections = Array.isArray(record.sections) ? record.sections.length : card?.grobid?.sectionCount;
  if (typeof sections === "number") add("Sections", `${sections} sections`);
  const references = Array.isArray(record.references) ? record.references.length : card?.grobid?.referenceCount;
  if (typeof references === "number") add("References", `${references} cited works`);
  return rows;
}
