/**
 * Related links on a Reference and on a concept: the rows an editor sees, read from SemanticRelation rows. Pure helpers only, so the
 * browser, the memory store and the tests share them.
 *
 * A concept link is related_to from a Reference to a concept (metadata kind reference.concept); a Reference link is related_to between
 * two References, one row with the lower lineage id as subject (metadata kind reference.link). Only current and suggested rows are
 * shown; a rejected row is a person's "no" and stays out of sight.
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

export function relatedEdgeWords(predicate: string, direction: "outgoing" | "incoming"): string {
  const words = RELATED_PREDICATE_WORDS[predicate];
  return words ? words[direction] : predicate.replace(/_/g, " ");
}

function isoDay(value: string | null | undefined): string | null {
  const text = String(value ?? "").trim();
  if (!text || Number.isNaN(Date.parse(text))) return null;
  return text.slice(0, 10);
}

/** "published 2026-10-27 · added 2026-10-28"; "published unknown" when the source has no date of its own. */
export function publishedAddedText(sourcePublishedAt: string | null | undefined, addedAt: string | null | undefined): string {
  const published = isoDay(sourcePublishedAt);
  const added = isoDay(addedAt);
  return `published ${published ?? "unknown"} · added ${added ?? "unknown"}`;
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
    });
  }
  return entries;
}

/** References a person linked to a concept: current related_to rows from a Reference with provenance human. */
export function editorLinkedReferenceLineages(conceptLineageId: string, relations: readonly RelationRow[]): Array<{ relationId: string; lineageId: string }> {
  const found: Array<{ relationId: string; lineageId: string }> = [];
  const seen = new Set<string>();
  for (const row of relations) {
    if (seen.has(row.id)) continue;
    if (row.relationState !== "current" || row.predicate !== "related_to") continue;
    if (row.subjectKind !== "reference" || row.objectKind !== "semanticNode" || row.objectLineageId !== conceptLineageId) continue;
    if (relationMetadata(row).provenance !== "human") continue;
    seen.add(row.id);
    found.push({ relationId: row.id, lineageId: row.subjectLineageId });
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
