import type { ReferenceRecord, SemanticNodeRecord } from "./category-repository";
import { conceptItem, referenceItem, type RelatedItem } from "./reference-links";

/** What the resolver needs from the network: one Reference or one concept by lineage id. Nothing here lists a whole table. */
export type ResolverLoaders = {
  referenceByLineage: (lineageId: string) => Promise<ReferenceRecord | null>;
  conceptByLineage: (lineageId: string) => Promise<SemanticNodeRecord | null>;
};

/**
 * Labels the few References and concepts a page shows, each fetched by id and all at once (one request per distinct id, never a scan of
 * every concept or Reference). A concept is labelled by its own key, so a name that two kinds share is not told apart here (the add box,
 * which does read every key, still does); this keeps opening a Reference with links, and "Suggest more", independent of how many nodes the site has.
 */
export function createLinkResolver(loaders: ResolverLoaders) {
  const concepts = new Map<string, Promise<SemanticNodeRecord | null>>();
  const conceptById = (lineageId: string) => {
    if (!concepts.has(lineageId)) concepts.set(lineageId, loaders.conceptByLineage(lineageId).catch(() => null));
    return concepts.get(lineageId) as Promise<SemanticNodeRecord | null>;
  };
  return async (lineages: { concepts: string[]; references: string[] }) => {
    const conceptMap = new Map<string, RelatedItem>();
    const referenceMap = new Map<string, RelatedItem>();
    await Promise.all([
      ...[...new Set(lineages.concepts)].map(async lineageId => {
        const node = await conceptById(lineageId);
        if (node) conceptMap.set(lineageId, conceptItem(node));
      }),
      ...[...new Set(lineages.references)].map(async lineageId => {
        const record = await loaders.referenceByLineage(lineageId).catch(() => null);
        if (record) referenceMap.set(lineageId, referenceItem(record));
      }),
    ]);
    return (kind: "concept" | "reference", lineageId: string) => (kind === "concept" ? conceptMap.get(lineageId) : referenceMap.get(lineageId)) ?? null;
  };
}
