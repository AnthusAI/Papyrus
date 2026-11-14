import { loadAllPages } from "../lib/newsroom-all-pages";
import { semanticStateKey } from "../lib/semantic-graph";
import { lineagesOfSuggestionRows, suggestionsFromRows, type LinkSuggestionPage, type SuggestionRow } from "../lib/link-suggestions";
import {
  conceptItem, editorLinkedReferenceLineages, referenceItem, relatedEntriesFromRelations,
  type RelatedEntry, type RelatedItem, type RelationRow, type SuggestionLabel,
} from "../lib/reference-links";
import type { ReferenceRecord, SemanticNodeRecord, SemanticRelationRecord } from "../lib/category-repository";
import { conceptSlug, editorConceptItem, editorConceptLineageId } from "../lib/reference-links";
import { createLinkResolver } from "../lib/reference-links-resolve";
import { conceptKeysForHashtag } from "../lib/wiki";
import type { ReferenceLinksStore, SuggestOutcome } from "./reference-links-context";
import { REFERENCE_LINK_FEED_KEY, globalKey } from "../lib/tenant-knowledge-keys";
import {
  LIST_SEMANTIC_RELATIONS_BY_OBJECT_STATE_QUERY, LIST_SEMANTIC_RELATIONS_BY_SUBJECT_STATE_QUERY,
  loadNewsroomReferencePage, loadNewsroomSemanticNodePage, loadReferenceRecordByLineageId, loadSemanticNodeByLineageId, loadSemanticRelationsByState, runGraphql,
} from "./news-desk-taxonomy-client";

const CREATE_REFERENCE_LINK_MUTATION =
  "mutation CreateReferenceLink($subjectLineageId: ID!, $objectKind: String!, $objectLineageId: ID!, $predicate: String!, $note: String) { createReferenceLink(subjectLineageId: $subjectLineageId, objectKind: $objectKind, objectLineageId: $objectLineageId, predicate: $predicate, note: $note) { ok relationId relationState outcome } }";
const CREATE_CONCEPT_AND_LINK_MUTATION =
  "mutation CreateConceptAndLink($subjectLineageId: ID!, $objectKind: String!, $objectLineageId: ID!, $predicate: String!, $newConceptName: String) { createReferenceLink(subjectLineageId: $subjectLineageId, objectKind: $objectKind, objectLineageId: $objectLineageId, predicate: $predicate, newConceptName: $newConceptName) { ok relationId relationState outcome } }";
const CREATE_EDITOR_CONCEPT_MUTATION =
  "mutation CreateEditorConcept($name: String!) { createEditorConcept(name: $name) { ok lineageId nodeKey displayName nodeKind } }";
const DESCRIBE_CONCEPT_MUTATION =
  "mutation DescribeConcept($lineageId: ID!, $description: String) { describeConcept(lineageId: $lineageId, description: $description) { ok lineageId description } }";
const DECIDE_REFERENCE_LINK_MUTATION =
  "mutation DecideReferenceLink($relationId: ID!, $decision: String!, $reasonCode: String, $note: String) { decideReferenceLink(relationId: $relationId, decision: $decision, reasonCode: $reasonCode, note: $note) { ok relationId relationState decision } }";
const SUGGEST_REFERENCE_LINKS_MUTATION =
  "mutation SuggestReferenceLinks($input: AWSJSON!) { suggestReferenceLinks(input: $input) }";

const SUGGESTED_LINKS_QUERY = `
  query ListSuggestedReferenceLinks($newsroomFeedKey: String!, $sortDirection: ModelSortDirection, $limit: Int, $nextToken: String, $filter: ModelSemanticRelationFilterInput) {
    listSemanticRelationsByNewsroomFeedAndCreatedAt(newsroomFeedKey: $newsroomFeedKey, sortDirection: $sortDirection, limit: $limit, nextToken: $nextToken, filter: $filter) {
      items { id relationState predicate subjectKind subjectLineageId objectKind objectLineageId score createdAt importedAt metadata }
      nextToken
    }
  }
`;
/** The feed key every reference-link row is written under (amplify/functions/category-action/reference-links.ts). */
/** How many open suggestions one page of the queue aims for. The filter runs after DynamoDB reads a page, so a page reads on until it has this many or the feed ends. */
const SUGGESTION_PAGE_SIZE = 50;
const SUGGESTION_READ_LIMIT = 200;

const LINK_STATES = ["current", "suggested"] as const;

async function relationsAround(kind: string, lineageId: string, direction: "subject" | "object" | "both"): Promise<SemanticRelationRecord[]> {
  const lookups: Array<Promise<SemanticRelationRecord[]>> = [];
  for (const state of LINK_STATES) {
    const keyValue = semanticStateKey(kind, lineageId, state);
    if (direction !== "object") lookups.push(loadSemanticRelationsByState({ field: "listSemanticRelationsBySubjectState", keyName: "subjectStateKey", keyValue, query: LIST_SEMANTIC_RELATIONS_BY_SUBJECT_STATE_QUERY }));
    if (direction !== "subject") lookups.push(loadSemanticRelationsByState({ field: "listSemanticRelationsByObjectState", keyName: "objectStateKey", keyValue, query: LIST_SEMANTIC_RELATIONS_BY_OBJECT_STATE_QUERY }));
  }
  return (await Promise.all(lookups)).flat();
}

function parseSuggestions(raw: unknown): SuggestOutcome {
  const parsed = typeof raw === "string" ? JSON.parse(raw) : raw;
  if (!parsed || typeof parsed !== "object") throw new Error("Suggestions returned no data.");
  const body = parsed as { ok?: boolean; errors?: Array<{ message?: string }>; skipped?: string | null; references?: Array<{ lineageId: string; label?: SuggestionLabel }>; concepts?: Array<{ lineageId: string; label?: SuggestionLabel }> };
  if (body.ok !== true) throw new Error(body.errors?.map(error => error.message).filter(Boolean).join("; ") || "Suggestions could not be made.");
  const labels: Record<string, SuggestionLabel> = {};
  for (const neighbour of [...(body.references ?? []), ...(body.concepts ?? [])]) if (neighbour.label) labels[neighbour.lineageId] = neighbour.label;
  return { labels, skipped: body.skipped ?? null };
}

/** The newsroom's related-links store: reads SemanticRelation rows by state key and writes only through the link mutations. */
export function createNetworkReferenceLinksStore(): ReferenceLinksStore {
  let concepts: Promise<SemanticNodeRecord[]> | null = null;
  let references: Promise<ReferenceRecord[]> | null = null;
  const referencesByLineage = new Map<string, Promise<ReferenceRecord | null>>();
  const allConcepts = () => (concepts ??= loadAllPages(nextToken => loadNewsroomSemanticNodePage({ nextToken })));
  const allReferences = () => (references ??= loadAllPages(nextToken => loadNewsroomReferencePage({ nextToken })));
  const referenceByLineage = (lineageId: string) => {
    if (!referencesByLineage.has(lineageId)) referencesByLineage.set(lineageId, loadReferenceRecordByLineageId(lineageId).catch(() => null));
    return referencesByLineage.get(lineageId) as Promise<ReferenceRecord | null>;
  };
  const resolveAll = createLinkResolver({ referenceByLineage, conceptByLineage: loadSemanticNodeByLineageId });
  return {
    async listSuggested(cursor) {
      const rows: SuggestionRow[] = [];
      let next = cursor;
      do {
        const data = await runGraphql<{ listSemanticRelationsByNewsroomFeedAndCreatedAt?: { items?: Array<SuggestionRow | null>; nextToken?: string | null } }>(SUGGESTED_LINKS_QUERY, {
          newsroomFeedKey: globalKey(REFERENCE_LINK_FEED_KEY), sortDirection: "DESC", limit: SUGGESTION_READ_LIMIT, nextToken: next, filter: { relationState: { eq: "suggested" } },
        });
        const connection = data.listSemanticRelationsByNewsroomFeedAndCreatedAt;
        rows.push(...(connection?.items ?? []).filter((row): row is SuggestionRow => Boolean(row)));
        next = connection?.nextToken ?? null;
      } while (next && rows.length < SUGGESTION_PAGE_SIZE);
      const resolve = await resolveAll(lineagesOfSuggestionRows(rows));
      const page: LinkSuggestionPage = { suggestions: suggestionsFromRows(rows, resolve), cursor: next };
      return page;
    },
    async listForReference(referenceLineageId) {
      const relations = (await relationsAround("reference", referenceLineageId, "both")) as RelationRow[];
      const candidates = relations.filter(row => row.predicate === "related_to" || (row.predicate === "tagged_with" && row.objectKind === "semanticNode"));
      const conceptIds: string[] = [];
      const referenceIds: string[] = [];
      for (const row of candidates) {
        if (row.subjectLineageId === referenceLineageId && row.objectKind === "semanticNode") conceptIds.push(row.objectLineageId);
        else if (row.subjectLineageId === referenceLineageId) referenceIds.push(row.objectLineageId);
        else referenceIds.push(row.subjectLineageId);
      }
      const resolve = await resolveAll({ concepts: conceptIds, references: referenceIds });
      return relatedEntriesFromRelations({ referenceLineageId, relations: candidates, resolve });
    },
    async listLinkedByEditors(conceptLineageId) {
      const relations = (await relationsAround("semanticNode", conceptLineageId, "object")) as RelationRow[];
      const linked = editorLinkedReferenceLineages(conceptLineageId, relations);
      const resolve = await resolveAll({ concepts: [], references: linked.map(found => found.lineageId) });
      const entries: RelatedEntry[] = [];
      for (const found of linked) {
        const item = resolve("reference", found.lineageId);
        if (item) entries.push({ relationId: found.relationId, state: "current", provenance: "human", predicate: "tagged_with", direction: "incoming", item, similarity: null, label: null, explanation: found.explanation });
      }
      return entries;
    },
    async searchConcepts(text) {
      const nodes = await allConcepts();
      const keys = nodes.map(node => node.nodeKey);
      const typed = text.trim().replace(/^#+/, "").trim().toLowerCase();
      if (!typed) return [];
      const exact = new Set(conceptKeysForHashtag(text, keys));
      const byKey = new Map(nodes.map(node => [node.nodeKey, node]));
      const prefix = nodes.filter(node => !exact.has(node.nodeKey) && (conceptItem(node, keys).hashtag ?? "").replace(/^#/, "").toLowerCase().startsWith(typed));
      return [...[...exact].map(key => byKey.get(key)).filter((node): node is SemanticNodeRecord => Boolean(node)), ...prefix].map(node => conceptItem(node, keys));
    },
    async searchReferences(text) {
      const needle = text.trim().toLowerCase();
      if (!needle) return [];
      const all = await allReferences();
      const exactLink = /^https?:\/\//.test(needle);
      return all
        .filter(record => (exactLink ? (record.sourceUri ?? "").trim().toLowerCase() === needle : (record.title ?? "").toLowerCase().includes(needle)))
        .map(referenceItem);
    },
    async create(input) {
      const data = await runGraphql<{ createReferenceLink?: { ok: boolean; relationId: string } }>(CREATE_REFERENCE_LINK_MUTATION, input);
      if (!data.createReferenceLink?.ok) throw new Error("The link could not be saved.");
      return { relationId: data.createReferenceLink.relationId };
    },
    async decide(input) {
      const data = await runGraphql<{ decideReferenceLink?: { ok: boolean } }>(DECIDE_REFERENCE_LINK_MUTATION, input);
      if (!data.decideReferenceLink?.ok) throw new Error("The decision could not be saved.");
    },
    async createConceptAndTag(referenceLineageId, name) {
      const slug = conceptSlug(name);
      if (!slug) throw new Error("A concept needs a name.");
      const lineageId = editorConceptLineageId(slug);
      const data = await runGraphql<{ createReferenceLink?: { ok: boolean; relationId: string } }>(CREATE_CONCEPT_AND_LINK_MUTATION, {
        subjectLineageId: referenceLineageId, objectKind: "semanticNode", objectLineageId: lineageId, predicate: "tagged_with", newConceptName: slug,
      });
      if (!data.createReferenceLink?.ok) throw new Error("The concept could not be created.");
      return { relationId: data.createReferenceLink.relationId, item: editorConceptItem(slug) };
    },
    async describeConcept(conceptLineageId, description) {
      const data = await runGraphql<{ describeConcept?: { ok: boolean } }>(DESCRIBE_CONCEPT_MUTATION, { lineageId: conceptLineageId, description });
      if (!data.describeConcept?.ok) throw new Error("The description could not be saved.");
    },
    async suggest(referenceId) {
      const data = await runGraphql<{ suggestReferenceLinks?: unknown }>(SUGGEST_REFERENCE_LINKS_MUTATION, { input: JSON.stringify({ referenceId }) });
      return parseSuggestions(data.suggestReferenceLinks);
    },
  };
}
