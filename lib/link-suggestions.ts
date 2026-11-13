/**
 * Suggested links as a queue: the pure helpers behind the "Link suggestion" items of the Needs me feed. A suggestion is a
 * `suggested` SemanticRelation row written by the vector index (a Reference to a Reference, or a Reference to a concept). The row
 * only stores the close match (`score`, a cosine similarity); that is what the queue is ranked by, most likely first.
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
  return row.relationState === "suggested" && row.subjectKind === "reference"
    && ((row.predicate === "related_to" && (row.objectKind === "reference" || row.objectKind === "semanticNode")) || (row.predicate === "tagged_with" && row.objectKind === "semanticNode"));
}

/** Most likely first; a row without a close match last; ties go to the newest, then by id so the order never wobbles. */
export function compareSuggestions(left: LinkSuggestion, right: LinkSuggestion): number {
  const leftScore = left.similarity ?? -1;
  const rightScore = right.similarity ?? -1;
  return rightScore - leftScore || (Date.parse(right.createdAt ?? "") || 0) - (Date.parse(left.createdAt ?? "") || 0) || left.relationId.localeCompare(right.relationId);
}

/** The suggestions in `rows`, each end resolved to what is shown; a row with an end that cannot be resolved is left out rather than shown as an id. */
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
  return found.sort(compareSuggestions);
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
