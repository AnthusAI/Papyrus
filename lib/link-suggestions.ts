/**
 * Suggested links as a queue: the pure helpers behind the "Link suggestion" items of the Needs me feed. A suggestion is a
 * `suggested` SemanticRelation row written by the vector index (a Reference to a Reference, or a Reference to a concept). The row
 * only stores the close match (`score`, a cosine similarity); that is what the queue is ranked by, most likely first. The order is the
 * server's: an open suggestion sits in a sparse index sorted by its score (docs/reference-link-suggestion-index.md), so a page arrives in
 * order and the pages follow each other, and nothing here sorts.
 */
import type { RelatedItem, RelationRow } from "./reference-links";

export type LinkSuggestion = {
  relationId: string;
  /** Always a Reference. */
  subject: RelatedItem;
  /** Another Reference, or a concept. */
  object: RelatedItem;
  /** The close match the vector index recorded, 0 to 1; null when the row has none. */
  similarity: number | null;
  createdAt: string | null;
};

/** One page of the queue. `cursor` is null at the end. */
export type LinkSuggestionPage = { suggestions: LinkSuggestion[]; cursor: string | null };

export type SuggestionRow = RelationRow & { createdAt?: string | null; importedAt?: string | null };

/** Whether a row is an open suggestion between a Reference and a Reference or concept. */
export function isOpenSuggestion(row: Pick<RelationRow, "relationState" | "predicate" | "subjectKind" | "objectKind">): boolean {
  return row.relationState === "suggested" && row.predicate === "related_to" && row.subjectKind === "reference" && (row.objectKind === "reference" || row.objectKind === "semanticNode");
}

/** Most likely first; a row without a close match last; ties go to the newest, then by id. The index orders the real queue itself; this is the same order for a store that holds all its suggestions in memory (the local preview and the tests). */
export function compareSuggestions(left: LinkSuggestion, right: LinkSuggestion): number {
  const leftScore = left.similarity ?? -1;
  const rightScore = right.similarity ?? -1;
  return rightScore - leftScore || (Date.parse(right.createdAt ?? "") || 0) - (Date.parse(left.createdAt ?? "") || 0) || left.relationId.localeCompare(right.relationId);
}

/** The suggestions in `rows`, in the order given, each end resolved to what is shown; a row with an end that cannot be resolved is left out rather than shown as an id. */
export function suggestionsFromRows(rows: readonly SuggestionRow[], resolve: (kind: "concept" | "reference", lineageId: string) => RelatedItem | null): LinkSuggestion[] {
  const seen = new Set<string>();
  const found: LinkSuggestion[] = [];
  for (const row of rows) {
    if (seen.has(row.id) || !isOpenSuggestion(row)) continue;
    const subject = resolve("reference", row.subjectLineageId);
    const object = resolve(row.objectKind === "semanticNode" ? "concept" : "reference", row.objectLineageId);
    if (!subject || !object) continue;
    seen.add(row.id);
    found.push({
      relationId: row.id, subject, object, similarity: typeof row.score === "number" && Number.isFinite(row.score) ? row.score : null,
      createdAt: row.createdAt ?? row.importedAt ?? null,
    });
  }
  return found;
}

/** The lineage ids a page of rows needs resolved. */
export function lineagesOfSuggestionRows(rows: readonly SuggestionRow[]): { concepts: string[]; references: string[] } {
  const concepts = new Set<string>();
  const references = new Set<string>();
  for (const row of rows) {
    if (!isOpenSuggestion(row)) continue;
    references.add(row.subjectLineageId);
    (row.objectKind === "semanticNode" ? concepts : references).add(row.objectLineageId);
  }
  return { concepts: [...concepts], references: [...references] };
}

/** The sparse index every open suggestion sits in, most likely first (docs/reference-link-suggestion-index.md). The partition value is the one src/papyrus_content/reference_links.py writes. */
export const OPEN_SUGGESTION_KEY = "reference-links#suggested";
/** How many open suggestions one page of the queue reads. The index returns exactly this many (fewer only at the end), already in order, so one request is one page. */
export const SUGGESTION_PAGE_SIZE = 50;

export const SUGGESTED_LINKS_QUERY = `
  query ListSuggestedReferenceLinks($openSuggestionKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String) {
    listSemanticRelationsByOpenSuggestionAndScore(openSuggestionKey: $openSuggestionKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken) {
      items { id relationState predicate subjectKind subjectLineageId objectKind objectLineageId score createdAt importedAt metadata }
      nextToken
    }
  }
`;

type SuggestionConnection = { listSemanticRelationsByOpenSuggestionAndScore?: { items?: Array<SuggestionRow | null>; nextToken?: string | null } };

/**
 * One page of the queue, from the cursor the last page returned (null for the first). The server orders the page and hands back the
 * cursor to the next, so this reads once, resolves both ends of each row, and keeps the order it was given.
 */
export async function readSuggestionPage(
  graphql: (query: string, variables: Record<string, unknown>) => Promise<SuggestionConnection>,
  cursor: string | null,
  resolveAll: (lineages: { concepts: string[]; references: string[] }) => Promise<(kind: "concept" | "reference", lineageId: string) => RelatedItem | null>,
): Promise<LinkSuggestionPage> {
  const data = await graphql(SUGGESTED_LINKS_QUERY, { openSuggestionKey: OPEN_SUGGESTION_KEY, sortDirection: "DESC", limit: SUGGESTION_PAGE_SIZE, nextToken: cursor });
  const connection = data.listSemanticRelationsByOpenSuggestionAndScore;
  const rows = (connection?.items ?? []).filter((row): row is SuggestionRow => Boolean(row));
  const resolve = await resolveAll(lineagesOfSuggestionRows(rows));
  return { suggestions: suggestionsFromRows(rows, resolve), cursor: connection?.nextToken ?? null };
}
