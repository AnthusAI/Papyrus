/**
 * Related links on a Reference and on a concept: the rows an editor sees, read from SemanticRelation rows. Pure helpers only, so the
 * browser, the memory store and the tests share them.
 *
 * A concept link is related_to from a Reference to a concept (metadata kind reference.concept); a Reference link is related_to between
 * two References, one row with the lower lineage id as subject (metadata kind reference.link). Only current and suggested rows are
 * shown; a rejected row is a person's "no" and stays out of sight.
 *
 * The explanation a person wrote when they accepted or made a link is `metadata.note` on the row. It is first-class: it is shown on the link
 * (here), and it reaches the idea writer in a context pack (src/papyrus_content/ideas/context_packs.py). Only a link a person decided carries
 * one; the note on a rejected row is a reason to learn from and is never shown as an explanation.
 */

import { conceptHashtag, conceptNamePart } from "./wiki";

export type RelatedItemKind = "concept" | "reference";

export type RelatedItem = {
  kind: RelatedItemKind;
  lineageId: string;
  title: string;
  hashtag: string | null;
  nodeKey: string | null;
  nodeKind: string | null;
  host: string | null;
  sourceUri: string | null;
  sourcePublishedAt: string | null;
  addedAt: string | null;
};

export type RelatedLinkState = "current" | "suggested";

/** What a person wrote about why two things are linked, and when. The author is only ever "an editor": the row holds an account id, not a name. */
export type LinkExplanation = { text: string; by: "editor"; at: string | null; via?: "cli" | null };
export type SuggestionLabel = "likely" | "possible";

export type RelatedEntry = {
  relationId: string;
  state: RelatedLinkState;
  provenance: string;
  predicate: string;
  direction: "outgoing" | "incoming";
  item: RelatedItem;
  similarity: number | null;
  label: SuggestionLabel | null;
  /** The editor's words on this link; absent or null when none were written, and never set on a suggestion. */
  explanation?: LinkExplanation | null;
};

export type RelationRow = {
  id: string;
  relationState: string;
  predicate: string;
  subjectKind: string;
  subjectLineageId: string;
  objectKind: string;
  objectLineageId: string;
  score?: number | null;
  metadata?: unknown;
};

export const RELATED_PREDICATE_WORDS: Record<string, { outgoing: string; incoming: string }> = {
  related_to: { outgoing: "relates to", incoming: "relates to" },
  cites: { outgoing: "cites", incoming: "cited by" },
  supports: { outgoing: "supports", incoming: "supported by" },
  contradicts: { outgoing: "contradicts", incoming: "contradicted by" },
};

export const KNOWLEDGE_INDEX_MISSING_TEXT = "Suggestions need the knowledge index";

/** What "Suggest more" says when the site found nothing to suggest, keyed by the backend's skip reason. Never shown raw. */
export const SUGGEST_SKIPPED_TEXTS: ReadonlyArray<{ match: RegExp; text: string }> = [
  { match: /no reference_summary vector is indexed/i, text: "Suggestions appear once this Reference has a summary." },
];
export const SUGGEST_SKIPPED_FALLBACK_TEXT = "No suggestions could be made for this Reference yet.";
export const SUGGEST_FAILED_TEXT = "Suggestions could not be made right now. Try again in a moment.";

/** Plain wording for a backend skip reason; an unknown reason gets a generic plain sentence, never the internal string. */
export function suggestSkippedText(skipped: string | null | undefined): string {
  const reason = String(skipped ?? "");
  return SUGGEST_SKIPPED_TEXTS.find(known => known.match.test(reason))?.text ?? SUGGEST_SKIPPED_FALLBACK_TEXT;
}

/** Plain wording for a failed "Suggest more": the missing knowledge index has its own sentence; everything else is generic. */
export function suggestFailureText(failure: unknown): string {
  return isKnowledgeIndexMissing(failure) ? KNOWLEDGE_INDEX_MISSING_TEXT : SUGGEST_FAILED_TEXT;
}

export function relationMetadata(row: Pick<RelationRow, "metadata">): Record<string, unknown> {
  const raw = row.metadata;
  if (raw && typeof raw === "object") return raw as Record<string, unknown>;
  if (typeof raw !== "string" || !raw.trim()) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

/**
 * The explanation on a link row: the words in `metadata.note` of a current link that a person decided (decision accepted, or made by hand), decided by a
 * person rather than an `auto:` rule. Anything else (a suggestion, a rejected row, a machine link, blank words) has none.
 */
export function linkExplanationOf(row: Pick<RelationRow, "metadata" | "relationState">): LinkExplanation | null {
  if (row.relationState !== "current") return null;
  const meta = relationMetadata(row);
  const text = typeof meta.note === "string" ? meta.note.trim() : "";
  const decidedBy = typeof meta.decidedBy === "string" ? meta.decidedBy : "";
  const byPerson = meta.decision === "accepted" || meta.provenance === "human";
  if (!text || !byPerson || decidedBy.startsWith("auto:")) return null;
  // `decidedVia` is stamped by the site from the token that made the decision (`edit-origin.ts`), so the words written through the CLI say so.
  return { text, by: "editor", at: isoDay(typeof meta.decidedAt === "string" ? meta.decidedAt : null), ...(meta.decidedVia === "cli" ? { via: "cli" as const } : {}) };
}

/** "Written by an editor on 2026-11-02": says who and when, in words; "through the CLI" when it was not written in the Newsroom. */
export function explanationByline(explanation: LinkExplanation): string {
  return `Written by an editor${explanation.at ? ` on ${explanation.at}` : ""}${explanation.via === "cli" ? " through the CLI" : ""}`;
}

export function relatedEdgeWords(predicate: string, direction: "outgoing" | "incoming"): string {
  const words = RELATED_PREDICATE_WORDS[predicate];
  return words ? words[direction] : predicate.replace(/_/g, " ");
}

function isoDay(value: string | null | undefined): string | null {
  const text = String(value ?? "").trim();
  if (!text || Number.isNaN(Date.parse(text))) return null;
  return text.slice(0, 10);
}

export type PublicationPrecision = "day" | "month" | "year";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function publishedAtPrecision(precision: string | null | undefined): PublicationPrecision {
  return precision === "month" || precision === "year" ? precision : "day";
}

function publishedDayText(sourcePublishedAt: string | null | undefined, precision: string | null | undefined): string | null {
  const day = isoDay(sourcePublishedAt);
  if (!day) return null;
  const kind = publishedAtPrecision(precision);
  if (kind === "year") return day.slice(0, 4);
  if (kind === "month") return `${MONTH_NAMES[Number(day.slice(5, 7)) - 1] ?? day.slice(5, 7)} ${day.slice(0, 4)}`;
  return day;
}

/** "published 2026-10-27 · added 2026-10-28"; "published Oct 2026" or "published 2026" at coarser precision; "published unknown" when the source has no date of its own. */
export function publishedAddedText(sourcePublishedAt: string | null | undefined, addedAt: string | null | undefined, precision?: string | null): string {
  const published = publishedDayText(sourcePublishedAt, precision);
  const added = isoDay(addedAt);
  return `published ${published ?? "unknown"} · added ${added ?? "unknown"}`;
}

/** The precision the publication-date resolver recorded in a Reference's metadata (object or JSON string); day when absent. */
export function publicationPrecisionOf(metadata: unknown): PublicationPrecision {
  let record: unknown = metadata;
  if (typeof record === "string") {
    try { record = JSON.parse(record); } catch { return "day"; }
  }
  const resolution = record && typeof record === "object" ? (record as Record<string, unknown>).publicationDateResolution : null;
  const precision = resolution && typeof resolution === "object" ? (resolution as Record<string, unknown>).precision : null;
  return publishedAtPrecision(typeof precision === "string" ? precision : null);
}

/** Both dates of a stored Reference. The added date is createdAt and is never shown as the publication date. */
export function referenceDatesText(reference: { sourcePublishedAt?: string | null; createdAt?: string | null; importedAt?: string | null; metadata?: unknown }): string {
  return publishedAddedText(reference.sourcePublishedAt, reference.createdAt ?? reference.importedAt, publicationPrecisionOf(reference.metadata));
}

export function hostOf(sourceUri: string | null | undefined): string | null {
  const text = String(sourceUri ?? "").trim();
  if (!/^https?:\/\//i.test(text)) return null;
  try {
    return new URL(text).host.replace(/^www\./, "") || null;
  } catch {
    return null;
  }
}

export function closeMatchText(similarity: number | null | undefined): string | null {
  return typeof similarity === "number" && Number.isFinite(similarity) ? `close match ${similarity.toFixed(2)}` : null;
}

export function conceptItem(node: { lineageId?: string | null; id: string; nodeKey: string; nodeKind: string; displayName?: string | null }, allNodeKeys: readonly string[] = []): RelatedItem {
  const name = conceptNamePart(node.nodeKey);
  const shared = allNodeKeys.some(key => key !== node.nodeKey && conceptNamePart(key) === name);
  const hashtag = conceptHashtag(node.nodeKey);
  return {
    kind: "concept",
    lineageId: node.lineageId ?? node.id,
    title: node.displayName?.trim() || name || node.nodeKey,
    hashtag: hashtag ? (shared ? `${hashtag} (${node.nodeKind})` : hashtag) : null,
    nodeKey: node.nodeKey,
    nodeKind: node.nodeKind,
    host: null,
    sourceUri: null,
    sourcePublishedAt: null,
    addedAt: null,
  };
}

export function referenceItem(reference: { lineageId?: string | null; id: string; title?: string | null; sourceUri?: string | null; sourcePublishedAt?: string | null; createdAt?: string | null; importedAt?: string | null }): RelatedItem {
  return {
    kind: "reference",
    lineageId: reference.lineageId ?? reference.id,
    title: reference.title?.trim() || reference.sourceUri?.trim() || "Untitled Reference",
    hashtag: null,
    nodeKey: null,
    nodeKind: null,
    host: hostOf(reference.sourceUri),
    sourceUri: reference.sourceUri?.trim() || null,
    sourcePublishedAt: reference.sourcePublishedAt ?? null,
    addedAt: reference.createdAt ?? reference.importedAt ?? null,
  };
}

/**
 * The entries a Reference shows: its current and suggested related_to-style links to concepts and to other References. `resolve`
 * turns the other end of a row into what is shown; a row it cannot resolve is left out rather than shown as an id.
 */
export function relatedEntriesFromRelations(input: {
  referenceLineageId: string;
  relations: readonly RelationRow[];
  resolve: (kind: RelatedItemKind, lineageId: string) => RelatedItem | null;
}): RelatedEntry[] {
  const seen = new Set<string>();
  const entries: RelatedEntry[] = [];
  for (const row of input.relations) {
    if (seen.has(row.id)) continue;
    if (row.relationState !== "current" && row.relationState !== "suggested") continue;
    const meta = relationMetadata(row);
    const subjectIsMe = row.subjectKind === "reference" && row.subjectLineageId === input.referenceLineageId;
    const objectIsMe = row.objectKind === "reference" && row.objectLineageId === input.referenceLineageId;
    if (!subjectIsMe && !objectIsMe) continue;
    let other: { kind: RelatedItemKind; lineageId: string } | null = null;
    if (subjectIsMe && row.objectKind === "semanticNode") other = { kind: "concept", lineageId: row.objectLineageId };
    else if (subjectIsMe && row.objectKind === "reference") other = { kind: "reference", lineageId: row.objectLineageId };
    else if (objectIsMe && row.subjectKind === "reference") other = { kind: "reference", lineageId: row.subjectLineageId };
    if (!other) continue;
    const item = input.resolve(other.kind, other.lineageId);
    if (!item) continue;
    seen.add(row.id);
    entries.push({
      relationId: row.id,
      state: row.relationState,
      provenance: String(meta.provenance ?? (row.relationState === "suggested" ? "suggested" : "human")),
      predicate: row.predicate,
      direction: subjectIsMe ? "outgoing" : "incoming",
      item,
      similarity: typeof row.score === "number" ? row.score : null,
      label: null,
      explanation: linkExplanationOf(row),
    });
  }
  return entries;
}

/** The predicates that tag a Reference with a concept: `tagged_with`, and `related_to`, its name before 2026-11-09 (rows are not migrated yet). The Python side is CONCEPT_TAG_PREDICATES in reference_links.py. */
export const CONCEPT_TAG_PREDICATES: readonly string[] = ["tagged_with", "related_to"];

/** References a person linked to a concept: current tag rows (tagged_with or the older related_to) from a Reference with provenance human. */
export function editorLinkedReferenceLineages(conceptLineageId: string, relations: readonly RelationRow[]): Array<{ relationId: string; lineageId: string; explanation: LinkExplanation | null }> {
  const found: Array<{ relationId: string; lineageId: string; explanation: LinkExplanation | null }> = [];
  const seen = new Set<string>();
  for (const row of relations) {
    if (seen.has(row.id)) continue;
    if (row.relationState !== "current" || !CONCEPT_TAG_PREDICATES.includes(row.predicate)) continue;
    if (row.subjectKind !== "reference" || row.objectKind !== "semanticNode" || row.objectLineageId !== conceptLineageId) continue;
    if (relationMetadata(row).provenance !== "human") continue;
    seen.add(row.id);
    found.push({ relationId: row.id, lineageId: row.subjectLineageId, explanation: linkExplanationOf(row) });
  }
  return found;
}

export type AddInput =
  | { mode: "none"; query: "" }
  | { mode: "concept"; query: string }
  | { mode: "link"; query: string }
  | { mode: "title"; query: string };

/** What the Add box is being asked: a concept by hashtag, a Reference by link, or a Reference by words of its title. */
export function classifyAddInput(text: string): AddInput {
  const trimmed = text.trim();
  if (!trimmed) return { mode: "none", query: "" };
  if (trimmed.startsWith("#")) return { mode: "concept", query: trimmed.replace(/^#+/, "").trim() };
  if (/^https?:\/\//i.test(trimmed)) return { mode: "link", query: trimmed };
  return { mode: "title", query: trimmed };
}

/** The lower lineage id is the subject of a symmetric Reference link. */
export function symmetricSubjectFirst(first: string, second: string): [string, string] {
  return first <= second ? [first, second] : [second, first];
}

export function isKnowledgeIndexMissing(failure: unknown): boolean {
  const text = failure instanceof Error ? failure.message : String(failure ?? "");
  return /knowledge[- ]index/i.test(text);
}

/** The kind of a concept an editor invents by typing its hashtag (amplify/functions/category-action/reference-links.ts). */
export const EDITOR_CONCEPT_KIND = "editor_concept";

/** `#Fake Website  Networks` -> `fake-website-networks`: the name part of the key that `conceptKeysForHashtag` matches (lower case, runs of other characters one hyphen). */
export function conceptSlug(text: string): string {
  return text.trim().replace(/^#+/, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 80);
}

/** The lineage id the backend gives the concept of that name: the same for anyone who types the same name. */
export function editorConceptLineageId(slug: string): string {
  return `semantic-node-${EDITOR_CONCEPT_KIND}--${slug}`;
}

/** The concept as the Related section lists it, before its node has been read back. */
export function editorConceptItem(slug: string): RelatedItem {
  return { kind: "concept", lineageId: editorConceptLineageId(slug), title: slug.replace(/-/g, " "), hashtag: `#${slug}`, nodeKey: `${EDITOR_CONCEPT_KIND}--${slug}`, nodeKind: EDITOR_CONCEPT_KIND, host: null, sourceUri: null, sourcePublishedAt: null, addedAt: null };
}

/** Whether typing `query` after a # should offer to create the concept: it has a name, and no concept already has exactly that name part (in any kind). */
export function offersCreate(query: string, found: readonly RelatedItem[]): string | null {
  const slug = conceptSlug(query);
  if (!slug) return null;
  return found.some(item => (item.hashtag ?? "").replace(/^#/, "").replace(/ \(.*\)$/, "").toLowerCase() === slug) ? null : slug;
}
