import type { RelatedEntry } from "./reference-links";
import type { ReferenceLinksStore } from "../components/reference-links-context";

/** How many suggestions of each kind a card shows: the few most likely, never the whole queue (the Related section has the rest). */
export const CARD_SUGGESTIONS_PER_KIND = 2;

/** The open suggestions of one Reference, most likely first (the close match the vector index recorded; no match last, then the stable id). */
export function openSuggestions(entries: readonly RelatedEntry[]): { concepts: RelatedEntry[]; references: RelatedEntry[] } {
  const open = entries
    .filter((entry) => entry.state === "suggested")
    .sort((left, right) => (right.similarity ?? -1) - (left.similarity ?? -1) || left.relationId.localeCompare(right.relationId));
  return {
    concepts: open.filter((entry) => entry.item.kind === "concept").slice(0, CARD_SUGGESTIONS_PER_KIND),
    references: open.filter((entry) => entry.item.kind === "reference").slice(0, CARD_SUGGESTIONS_PER_KIND),
  };
}

export type SuggestionLoader = {
  /** The Reference's entries: read once, shared by every card that asks, and read again only after `forget`. */
  load: (lineageId: string) => Promise<RelatedEntry[]>;
  forget: (lineageId: string) => void;
};

/**
 * Reads each Reference's links through the store, at most `concurrency` at a time, so a page of cards that all become visible at once never fires a read per
 * card in the same instant. Cards ask only when they are on screen (`use-card-suggestions`), so a page the editor never scrolls to costs nothing. There is no
 * batch read on the backend; this is the batching the feed can do without one.
 */
export function createSuggestionLoader(store: Pick<ReferenceLinksStore, "listForReference">, concurrency = 2): SuggestionLoader {
  const results = new Map<string, Promise<RelatedEntry[]>>();
  const waiting: Array<() => void> = [];
  let running = 0;
  const next = () => {
    while (running < concurrency && waiting.length) { running += 1; waiting.shift()!(); }
  };
  return {
    load(lineageId) {
      const known = results.get(lineageId);
      if (known) return known;
      const started = new Promise<RelatedEntry[]>((resolve, reject) => {
        waiting.push(() => {
          store.listForReference(lineageId).then(resolve, reject).finally(() => { running -= 1; next(); });
        });
        next();
      });
      results.set(lineageId, started);
      started.catch(() => results.delete(lineageId));   // a failed read is tried again on the next ask
      return started;
    },
    forget(lineageId) { results.delete(lineageId); },
  };
}

const loaders = new WeakMap<object, SuggestionLoader>();

/** One loader per store, so the feed's cards share their reads. */
export function suggestionLoaderFor(store: ReferenceLinksStore): SuggestionLoader {
  let loader = loaders.get(store);
  if (!loader) { loader = createSuggestionLoader(store); loaders.set(store, loader); }
  return loader;
}
