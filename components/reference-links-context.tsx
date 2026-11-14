"use client";

import { createContext, useContext, type ReactNode } from "react";
import { conceptSlug, editorConceptItem, editorConceptLineageId, symmetricSubjectFirst, type LinkExplanation, type RelatedEntry, type RelatedItem, type SuggestionLabel } from "../lib/reference-links";
import { compareSuggestions, type LinkSuggestion, type LinkSuggestionPage } from "../lib/link-suggestions";
import { conceptKeysForHashtag } from "../lib/wiki";

export type SuggestOutcome = { labels: Record<string, SuggestionLabel>; skipped: string | null };

/**
 * Where related links are read and written. The newsroom provides the network one; the demo and the tests provide the in-memory one.
 * A component that finds no store shows nothing.
 */
export type ReferenceLinksStore = {
  listForReference: (referenceLineageId: string) => Promise<RelatedEntry[]>;
  listLinkedByEditors: (conceptLineageId: string) => Promise<RelatedEntry[]>;
  searchConcepts: (text: string) => Promise<RelatedItem[]>;
  searchReferences: (text: string) => Promise<RelatedItem[]>;
  create: (input: { subjectLineageId: string; objectKind: "reference" | "semanticNode"; objectLineageId: string; predicate: string }) => Promise<{ relationId: string }>;
  /** Accept or reject a link. `note` is the person's words: the explanation of an accepted link (it replaces the earlier words; "" clears them), the reason for a rejection. */
  decide: (input: { relationId: string; decision: "accept" | "reject"; note?: string }) => Promise<void>;
  suggest: (referenceId: string) => Promise<SuggestOutcome>;
  /** Invents the concept named by a typed hashtag if it does not exist and tags the Reference with it, as one confirmed `tagged_with` link. Asking twice makes one concept and one link. */
  createConceptAndTag?: (referenceLineageId: string, name: string) => Promise<{ relationId: string; item: RelatedItem }>;
  /** Invents the concept named by a typed hashtag without tagging anything, for a section's list. Absent where the backend has no way to do it yet. */
  createConcept?: (name: string) => Promise<RelatedItem>;
  /** An editor's words about a concept they invented ("" clears them). */
  describeConcept?: (conceptLineageId: string, description: string) => Promise<void>;
  /** The Needs me queue: one page of open suggestions, from the cursor the last page returned (null for the first). Most likely first within the page. */
  listSuggested?: (cursor: string | null) => Promise<LinkSuggestionPage>;
};

const ReferenceLinksStoreContext = createContext<ReferenceLinksStore | null>(null);

export function ReferenceLinksStoreProvider({ store, children }: { store: ReferenceLinksStore; children: ReactNode }) {
  return <ReferenceLinksStoreContext.Provider value={store}>{children}</ReferenceLinksStoreContext.Provider>;
}

export function useReferenceLinksStore(): ReferenceLinksStore | null {
  return useContext(ReferenceLinksStoreContext);
}

export type MemoryLink = {
  id: string;
  subjectKind: "reference";
  subjectLineageId: string;
  objectKind: "reference" | "semanticNode";
  objectLineageId: string;
  state: "current" | "suggested" | "rejected";
  provenance: string;
  similarity?: number | null;
  /** The explanation an editor wrote when they accepted or made the link, and the ISO time they wrote it. */
  note?: string;
  noteAt?: string;
};

function explanationOfMemory(link: MemoryLink): LinkExplanation | null {
  const text = link.note?.trim();
  return link.state === "current" && text ? { text, by: "editor", at: link.noteAt ? link.noteAt.slice(0, 10) : null } : null;
}

function matchesWords(item: RelatedItem, text: string): boolean {
  const needle = text.trim().toLowerCase();
  if (!needle) return false;
  if (item.sourceUri && item.sourceUri.toLowerCase() === needle) return true;
  if (/^https?:\/\//.test(needle)) return false;
  return item.title.toLowerCase().includes(needle);
}

/**
 * A store that keeps everything in memory: the demo newsroom and the tests. `suggestions` is what Suggest more files when the
 * knowledge index exists; `withoutIndex` makes it fail the way a site without one does.
 */
export function createMemoryReferenceLinksStore(options: {
  items: RelatedItem[];
  links?: MemoryLink[];
  suggestions?: Array<MemoryLink & { label?: SuggestionLabel }>;
  withoutIndex?: boolean;
  /** What Suggest more reports as skipped (the backend's raw reason), so the plain wording can be tested. */
  skipped?: string;
  onCall?: (call: Record<string, unknown>) => void;
  /** How many suggestions `listSuggested` returns at a time (all of them by default). */
  suggestedPageSize?: number;
}): ReferenceLinksStore {
  const items = new Map(options.items.map(item => [`${item.kind}#${item.lineageId}`, item]));
  const links = [...(options.links ?? [])];
  const pending = [...(options.suggestions ?? [])];
  const labels = new Map(pending.filter(entry => entry.label).map(entry => [entry.objectLineageId, entry.label as SuggestionLabel]));
  const note = (call: Record<string, unknown>) => options.onCall?.(call);
  const itemFor = (kind: "concept" | "reference", lineageId: string) => items.get(`${kind}#${lineageId}`) ?? null;
  const entryFor = (link: MemoryLink, referenceLineageId: string): RelatedEntry | null => {
    if (link.state === "rejected") return null;
    const mine = link.subjectLineageId === referenceLineageId;
    const otherKind = link.objectKind === "semanticNode" ? "concept" : "reference";
    const otherId = mine ? link.objectLineageId : link.subjectLineageId;
    if (!mine && !(link.objectKind === "reference" && link.objectLineageId === referenceLineageId)) return null;
    const item = itemFor(mine ? otherKind : "reference", otherId);
    if (!item) return null;
    return {
      relationId: link.id, state: link.state, provenance: link.provenance, predicate: link.objectKind === "semanticNode" ? "tagged_with" : "related_to",
      direction: mine ? "outgoing" : "incoming", item, similarity: link.similarity ?? null, label: labels.get(otherId) ?? null,
      explanation: explanationOfMemory(link),
    };
  };
  const suggestedPage = (cursor: string | null): LinkSuggestionPage => {
    const all = links
      .filter(link => link.state === "suggested")
      .flatMap((link): LinkSuggestion[] => {
        const subject = itemFor("reference", link.subjectLineageId);
        const object = itemFor(link.objectKind === "semanticNode" ? "concept" : "reference", link.objectLineageId);
        return subject && object ? [{ relationId: link.id, subject, object, similarity: link.similarity ?? null, createdAt: null }] : [];
      })
      .sort(compareSuggestions);
    const start = cursor ? Number(cursor) : 0;
    const size = options.suggestedPageSize ?? all.length;
    const end = start + size;
    return { suggestions: all.slice(start, end), cursor: end < all.length ? String(end) : null };
  };
  return {
    async listSuggested(cursor) {
      note({ type: "listSuggested", cursor });
      return suggestedPage(cursor);
    },
    async listForReference(referenceLineageId) {
      return links.map(link => entryFor(link, referenceLineageId)).filter((entry): entry is RelatedEntry => Boolean(entry));
    },
    async listLinkedByEditors(conceptLineageId) {
      return links
        .filter(link => link.objectKind === "semanticNode" && link.objectLineageId === conceptLineageId && link.state === "current" && link.provenance === "human")
        .map(link => ({ link, item: itemFor("reference", link.subjectLineageId) }))
        .filter((found): found is { link: MemoryLink; item: RelatedItem } => Boolean(found.item))
        .map(({ link, item }) => ({ relationId: link.id, state: "current" as const, provenance: link.provenance, predicate: "tagged_with", direction: "incoming" as const, item, similarity: null, label: null, explanation: explanationOfMemory(link) }));
    },
    async searchConcepts(text) {
      const concepts = [...items.values()].filter(item => item.kind === "concept" && item.nodeKey);
      const keys = concepts.map(item => item.nodeKey as string);
      const typed = text.trim().replace(/^#+/, "").trim().toLowerCase();
      if (!typed) return [];
      const exact = new Set(conceptKeysForHashtag(text, keys));
      const prefix = concepts.filter(item => (item.hashtag ?? "").replace(/^#/, "").toLowerCase().startsWith(typed));
      const ordered = [...concepts.filter(item => exact.has(item.nodeKey as string)), ...prefix.filter(item => !exact.has(item.nodeKey as string))];
      return ordered;
    },
    async searchReferences(text) {
      return [...items.values()].filter(item => item.kind === "reference" && matchesWords(item, text));
    },
    async create(input) {
      note({ type: "create", ...input });
      const reference = input.objectKind === "reference";
      const [subject, object] = reference ? symmetricSubjectFirst(input.subjectLineageId, input.objectLineageId) : [input.subjectLineageId, input.objectLineageId];
      const id = `memory-link-${links.length + 1}`;
      links.push({ id, subjectKind: "reference", subjectLineageId: subject, objectKind: input.objectKind, objectLineageId: object, state: "current", provenance: "human" });
      return { relationId: id };
    },
    async createConceptAndTag(referenceLineageId, name) {
      note({ type: "createConceptAndTag", referenceLineageId, name });
      const slug = conceptSlug(name);
      const item = items.get(`concept#${editorConceptLineageId(slug)}`) ?? editorConceptItem(slug);
      items.set(`concept#${item.lineageId}`, item);
      const existing = links.find(link => link.subjectLineageId === referenceLineageId && link.objectLineageId === item.lineageId);
      if (existing) { existing.state = "current"; return { relationId: existing.id, item }; }
      const id = `memory-link-${links.length + 1}`;
      links.push({ id, subjectKind: "reference", subjectLineageId: referenceLineageId, objectKind: "semanticNode", objectLineageId: item.lineageId, state: "current", provenance: "human" });
      return { relationId: id, item };
    },
    async createConcept(name) {
      note({ type: "createConcept", name });
      const slug = conceptSlug(name);
      const item = items.get(`concept#${editorConceptLineageId(slug)}`) ?? editorConceptItem(slug);
      items.set(`concept#${item.lineageId}`, item);
      return item;
    },
    async describeConcept(conceptLineageId, description) {
      note({ type: "describeConcept", conceptLineageId, description });
    },
    async decide(input) {
      note({ type: "decide", ...input });
      const link = links.find(candidate => candidate.id === input.relationId);
      if (!link) throw new Error("That link is not here.");
      const wasSuggested = link.state === "suggested";
      link.state = input.decision === "accept" ? "current" : "rejected";
      if (input.decision === "accept") {
        // Like the backend, an accept replaces the earlier words; a link that was already current keeps its provenance.
        if (wasSuggested) link.provenance = "suggested";
        const words = input.note?.trim();
        link.note = words || undefined;
        link.noteAt = words ? new Date().toISOString() : undefined;
      }
    },
    async suggest(referenceId) {
      note({ type: "suggest", referenceId });
      if (options.withoutIndex) throw new Error("Suggestions need the knowledge index.");
      if (options.skipped) return { labels: {}, skipped: options.skipped };
      for (const suggestion of pending.splice(0)) links.push({ ...suggestion, state: "suggested", provenance: "suggested" });
      return { labels: Object.fromEntries(labels), skipped: null };
    },
  };
}
